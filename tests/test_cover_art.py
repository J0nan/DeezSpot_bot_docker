#!/usr/bin/python3

"""Cover-art pipeline tests for deezloader.deezloader.cover_art and the
API.choose_img delegation.

The Deezer CDN intermittently answers 403 with an empty body (rate/content
protection). The old choose_img fired up to ten bare requests per track (no
header, no timeout, no backoff), accepted any body that was not 13 bytes long,
and silently returned b"" -- which the taggers report as "no cover art
available". These tests pin the replacement contract: browser header and
timeout on every request, a size ladder without empty-md5 placeholder calls,
bounded retries with backoff on 403/5xx, real image validation, a per-md5
negative cache, a per-host throttle, and a Spotify fallback rung.

No network is touched: requests.get and the legacy dee_api.req_get binding are
replaced by a scripted recorder, and the cover_art clock seams (_now/_sleep)
are replaced by a fake clock.

Run as: .venv\\Scripts\\python -m pytest tests/test_cover_art.py -q
     or: .venv\\Scripts\\python tests/test_cover_art.py
"""

import importlib.util
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))

import requests

from deezloader.deezloader import dee_api

try:
	from deezloader.deezloader import cover_art
except ImportError:
	cover_art = None

# thumb_utils is deliberately import-free; load it standalone so the bot's
# credential stack never enters these tests.
_spec = importlib.util.spec_from_file_location(
	"thumb_utils_probe", os.path.join(_root, "utils", "thumb_utils.py")
)
thumb_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(thumb_utils)

MD5 = "0123456789abcdef0123456789abcdef"
SPOTIFY_URL = "https://i.scdn.co/image/ab67616d0000b273probe"

# Validation only needs magic + length; structural parsing is pinned by
# tests/test_taggers_cover.py.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2048 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048
GIF = b"GIF89a" + b"\x00" * 2048
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 2048
HTML = b"<html><body>403 Forbidden</body></html>" * 64
JSON_BODY = b'{"error":{"message":"forbidden"}}' * 64
SHORT_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
THIRTEEN = b"0123456789abc"

def deezer_url(md5, size):
	return f"https://cdn-images.dzcdn.net/images/cover/{md5}/{size}-000000-80-0-0.jpg"

class FakeResponse:
	def __init__(self, status_code, content):
		self.status_code = status_code
		self.content = content

	def json(self):
		import json
		return json.loads(self.content)

class HttpRecorder:
	"""Scripted requests.get replacement; records url + kwargs per call."""

	def __init__(self):
		self.calls = []
		self.script = []
		self.default = (403, b"")

	def on(self, url_part, *steps):
		self.script.append((url_part, list(steps)))
		return self

	def get(self, url, **kwargs):
		self.calls.append((url, kwargs))

		for url_part, steps in self.script:
			if url_part in url:
				step = steps.pop(0) if len(steps) > 1 else steps[0]

				if isinstance(step, BaseException):
					raise step

				return FakeResponse(*step)

		return FakeResponse(*self.default)

	def urls(self):
		return [url for url, _ in self.calls]

class FakeClock:
	def __init__(self, advance_on_sleep = True):
		self.t = 1000.0
		self.sleeps = []
		self.advance = advance_on_sleep

	def now(self):
		return self.t

	def sleep(self, seconds):
		self.sleeps.append(seconds)

		if self.advance:
			self.t += seconds

class patched:
	"""Route both the legacy and the new transport bindings to one recorder,
	and give cover_art a fake clock. Works under pytest and as a bare script."""

	def __init__(self, recorder, clock = None):
		self.recorder = recorder
		self.clock = clock or FakeClock()
		self._saved = []

	def _set(self, obj, name, value):
		self._saved.append((obj, name, getattr(obj, name)))
		setattr(obj, name, value)

	def __enter__(self):
		self._set(dee_api, "req_get", self.recorder.get)
		self._set(requests, "get", self.recorder.get)

		if cover_art is not None:
			self._set(cover_art, "_now", self.clock.now)
			self._set(cover_art, "_sleep", self.clock.sleep)
			cover_art._negative_cache.clear()
			cover_art._last_request.clear()

		return self.recorder

	def __exit__(self, *exc_info):
		for obj, name, value in reversed(self._saved):
			setattr(obj, name, value)

		if cover_art is not None:
			cover_art._negative_cache.clear()
			cover_art._last_request.clear()

		return False

def require_cover_art():
	assert cover_art is not None, "deezloader.deezloader.cover_art module is missing"

# --- choose_img contract (RED against the legacy implementation) ---

def test_choose_img_sends_browser_header_and_timeout():
	http = HttpRecorder().on(MD5, (200, JPEG))

	with patched(http):
		image = dee_api.API.choose_img(MD5)

	assert image == JPEG
	assert http.calls, "expected at least one CDN request"

	for url, kwargs in http.calls:
		headers = kwargs.get("headers") or {}
		assert "User-Agent" in headers, f"no User-Agent sent for {url}"
		assert kwargs.get("timeout") is not None, f"no timeout for {url}"

def test_choose_img_rejects_html_and_json_error_bodies():
	for body in (HTML, JSON_BODY):
		http = HttpRecorder()
		http.default = (200, body)

		with patched(http):
			assert dee_api.API.choose_img(MD5) == b""

def test_choose_img_rejects_short_and_thirteen_byte_bodies():
	for body in (SHORT_JPEG, THIRTEEN, b""):
		http = HttpRecorder()
		http.default = (200, body)

		with patched(http):
			assert dee_api.API.choose_img(MD5) == b""

def test_choose_img_accepts_real_image_magics():
	for body in (JPEG, PNG, GIF, WEBP):
		http = HttpRecorder().on(MD5, (200, body))

		with patched(http):
			assert dee_api.API.choose_img(MD5) == body

def test_choose_img_retries_403_with_backoff_then_succeeds():
	http = HttpRecorder().on(
		"1200x1200", (403, b""), (403, b""), (200, JPEG)
	)
	clock = FakeClock()

	with patched(http, clock):
		image = dee_api.API.choose_img(MD5)

	assert image == JPEG
	assert len(http.urls()) >= 3
	# Backoff grows: at least one wait >= 0.5 s and a later one >= 1.0 s.
	assert any(s >= 0.5 for s in clock.sleeps), clock.sleeps
	assert any(s >= 1.0 for s in clock.sleeps), clock.sleeps

def test_choose_img_retries_connection_errors():
	http = HttpRecorder().on(
		"1200x1200", requests.exceptions.ConnectionError("probe"), (200, JPEG)
	)

	with patched(http):
		assert dee_api.API.choose_img(MD5) == JPEG

def test_choose_img_size_ladder_and_no_empty_md5_calls():
	http = HttpRecorder()

	with patched(http):
		assert dee_api.API.choose_img(MD5) == b""

	urls = http.urls()
	# Every call targets the real md5 (no empty-md5 placeholder attempts).
	assert all(f"/cover/{MD5}/" in url for url in urls)

	sizes_seen = list(dict.fromkeys(
		url.split(f"/cover/{MD5}/")[1].split("-")[0] for url in urls
	))
	assert sizes_seen == ["1200x1200", "1000x1000", "500x500"]
	# Persistent 403: each size is tried once plus MAX_RETRIES bounded retries.
	assert len(urls) == 3 * (cover_art.MAX_RETRIES + 1)

def test_choose_img_custom_size_leads_the_ladder():
	http = HttpRecorder()

	with patched(http):
		dee_api.API.choose_img(MD5, size = "500x500")

	urls = http.urls()
	sizes_seen = list(dict.fromkeys(
		url.split(f"/cover/{MD5}/")[1].split("-")[0] for url in urls
	))
	# The ladder deduplicates: 500x500 asked, 1000x1000 fallback, 500x500 skipped.
	assert sizes_seen == ["500x500", "1000x1000"]
	assert len(urls) == 2 * (cover_art.MAX_RETRIES + 1)

def test_choose_img_empty_md5_returns_empty_without_requests():
	http = HttpRecorder()

	with patched(http):
		assert dee_api.API.choose_img("") == b""

	assert http.calls == []

def test_negative_cache_skips_refetch_within_ttl():
	http = HttpRecorder()

	with patched(http):
		assert dee_api.API.choose_img(MD5) == b""
		first_round = len(http.calls)
		assert first_round > 0

		assert dee_api.API.choose_img(MD5) == b""
		assert len(http.calls) == first_round, "negative cache did not suppress the refetch"

def test_negative_cache_expires_after_ttl():
	require_cover_art()
	http = HttpRecorder()
	clock = FakeClock()

	with patched(http, clock):
		assert dee_api.API.choose_img(MD5) == b""
		first_round = len(http.calls)

		clock.t += cover_art.NEGATIVE_TTL + 1

		assert dee_api.API.choose_img(MD5) == b""
		assert len(http.calls) > first_round, "expired negative cache still suppressed the fetch"

def test_throttle_paces_requests_to_one_host():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG)).on("feedface", (200, JPEG))
	clock = FakeClock(advance_on_sleep = False)

	with patched(http, clock):
		assert dee_api.API.choose_img(MD5) == JPEG
		assert dee_api.API.choose_img("feedface" * 4) == JPEG

	assert any(
		abs(s - cover_art.MIN_REQUEST_INTERVAL) < 1e-9 for s in clock.sleeps
	), clock.sleeps

# --- fetch_cover source chain ---

def test_fetch_cover_deezer_primary_wins_and_spotify_untouched():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG)).on("i.scdn.co", (200, PNG))

	with patched(http):
		result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == JPEG
	assert result.source == "deezer"
	assert result.reason == ""
	assert not any("i.scdn.co" in url for url in http.urls())

def test_fetch_cover_spotify_fallback_when_deezer_refuses():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == JPEG
	assert result.source == "spotify"
	assert result.reason == "fallback_used"

def test_fetch_cover_spotify_only_without_md5():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_cover(fallback_url = SPOTIFY_URL)

	assert result.data == JPEG
	assert result.source == "spotify"
	assert http.urls() == [SPOTIFY_URL]

def test_fetch_cover_no_inputs_is_no_md5():
	require_cover_art()
	http = HttpRecorder()

	with patched(http):
		result = cover_art.fetch_cover()

	assert result.data == b""
	assert result.reason == "no_md5"
	assert http.calls == []

def test_fetch_cover_all_sources_failed_reason():
	require_cover_art()
	http = HttpRecorder()

	with patched(http):
		result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == b""
	assert result.reason == "all_sources_failed"
	assert not bool(result)

def test_fetch_cover_fallback_body_is_validated_too():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, HTML))

	with patched(http):
		result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == b""
	assert result.reason == "all_sources_failed"

# --- existing behavior regressions (must stay green) ---

def test_make_thumb_io_empty_bytes_returns_none():
	assert thumb_utils.make_thumb_io(b"", "cover.jpg") is None
	assert thumb_utils.make_thumb_io(None, "cover.jpg") is None

def test_make_thumb_io_valid_bytes_returns_named_stream():
	io_image = thumb_utils.make_thumb_io(JPEG, "cover.jpg")

	assert io_image is not None
	assert io_image.name == "cover.jpg"
	assert io_image.read() == JPEG

def test_get_img_url_keeps_template_contract():
	assert dee_api.API.get_img_url(MD5) == deezer_url(MD5, "1200x1200")
	assert dee_api.API.get_img_url(MD5, "500x500") == deezer_url(MD5, "500x500")

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
