#!/usr/bin/python3

"""Independent verification probes for the cover pipeline (S6, S7).

Returned by the independent verifier of commit 779a982 and adapted to the
repo's dual-runner style: negative-cache TTL boundaries measured from the
post-failure clock, thumb/cover cache-key independence in both directions,
no retry on invalid 200 bodies, and zero Deezer requests for an empty md5.

Run as: .venv\\Scripts\\python -m pytest tests/test_cover_thumb_independent.py -q
     or: .venv\\Scripts\\python tests/test_cover_thumb_independent.py
"""

import os
import random
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))

from deezloader.deezloader import cover_art as ca

JPEG = b"\xff\xd8\xff" + b"\x00" * 2000
MD5 = "a" * 32
SPOT = "https://i.scdn.co/image/ab67616d0000b273abcdef1234567890abcdef12"

class Resp:
	def __init__(self, status, body = b""):
		self.status_code = status
		self.content = body

class FakeRequests:
	RequestException = OSError

	def __init__(self, plan):
		self.plan = plan
		self.urls = []

	def get(self, url, headers = None, timeout = None):
		self.urls.append(url)

		return self.plan(url)

class chain:
	"""Fake clock + zero jitter + clean caches; bare-script friendly."""

	def __init__(self):
		self.clock = [0.0]
		self.saved = []

	def __enter__(self):
		self.saved = [
			(ca, "_now", ca._now),
			(ca, "_sleep", ca._sleep),
			(random, "uniform", random.uniform),
		]
		ca._now = lambda: self.clock[0]
		ca._sleep = lambda d: self.clock.__setitem__(0, self.clock[0] + d)
		random.uniform = lambda a, b: 0.0
		ca._negative_cache.clear()
		ca._last_request.clear()

		return self.clock

	def __exit__(self, *exc_info):
		for obj, name, value in reversed(self.saved):
			setattr(obj, name, value)

		ca._negative_cache.clear()
		ca._last_request.clear()

		return False

class transport:
	def __init__(self, fake):
		self.fake = fake
		self.saved = None

	def __enter__(self):
		self.saved = ca.requests
		ca.requests = self.fake

		return self.fake

	def __exit__(self, *exc_info):
		ca.requests = self.saved

		return False

def test_thumb_ttl_boundary():
	with chain() as clock:
		with transport(FakeRequests(lambda u: Resp(403))):
			assert ca.fetch_thumb(MD5).reason == "all_sources_failed"

		t = clock[0]
		clock[0] = t + 599.0
		probe = FakeRequests(lambda u: Resp(200, JPEG))

		with transport(probe):
			assert ca.fetch_thumb(MD5).reason == "all_sources_failed"
			assert probe.urls == []

		clock[0] = t + 601.0

		with transport(probe):
			assert ca.fetch_thumb(MD5).data == JPEG
			assert probe.urls == [ca.COVER_URL % (MD5, "90x90")]

def test_thumb_and_cover_keys_disjoint():
	with chain():
		with transport(FakeRequests(lambda u: Resp(403))):
			ca.fetch_thumb(MD5)
			ca.fetch_cover(MD5)

		assert set(ca._negative_cache) == {"thumb:90x90:" + MD5, MD5}

def test_thumb_fail_does_not_poison_cover():
	with chain():
		with transport(FakeRequests(lambda u: Resp(403))):
			assert ca.fetch_thumb(MD5).reason == "all_sources_failed"

		with transport(FakeRequests(lambda u: Resp(200, JPEG))):
			assert ca.fetch_cover(MD5).source == "deezer"

def test_cover_fail_does_not_poison_thumb():
	with chain():
		with transport(FakeRequests(lambda u: Resp(403))):
			assert ca.fetch_cover(MD5).reason == "all_sources_failed"

		with transport(FakeRequests(lambda u: Resp(200, JPEG))):
			assert ca.fetch_thumb(MD5).source == "deezer"

def test_invalid_bodies_get_no_retry():
	html = Resp(200, b"<html>err</html>" * 200)
	short = Resp(200, b"\xff\xd8\xff" + b"\x00" * 10)

	def plan(u):
		if "1200x1200" in u:
			return html

		if "1000x1000" in u:
			return short

		return Resp(200, JPEG)

	probe = FakeRequests(plan)

	with chain(), transport(probe):
		assert ca.fetch_cover(MD5).data == JPEG
		assert probe.urls == [
			ca.COVER_URL % (MD5, s)
			for s in ("1200x1200", "1000x1000", "500x500")
		]

def test_empty_md5_never_hits_deezer():
	probe = FakeRequests(
		lambda u: Resp(200, JPEG) if "i.scdn.co" in u else Resp(403)
	)

	with chain(), transport(probe):
		assert ca.fetch_cover("", fallback_url = SPOT).source == "spotify"
		assert probe.urls == [SPOT]

if __name__ == "__main__":
	tests = [
		(name, fn) for name, fn in sorted(globals().items())
		if name.startswith("test_") and callable(fn)
	]

	if not tests:
		print("no tests collected")
		sys.exit(1)

	failures = 0

	for name, fn in tests:
		try:
			fn()
			print(f"PASS {name}")
		except Exception as error:
			failures += 1
			print(f"FAIL {name}: {error}")

	print(f"{len(tests) - failures}/{len(tests)} passed")
	sys.exit(1 if failures else 0)
