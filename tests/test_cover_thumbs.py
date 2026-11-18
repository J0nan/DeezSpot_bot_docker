#!/usr/bin/python3

"""T3 tests: fetch_thumb, the small-variant cover service for Telegram thumbs.

Cards and audio/document thumbs used to call the legacy API.choose_img
directly -- up to ten bare requests per track, no body validation and no
shared negative cache. fetch_thumb routes them through the same pipeline as
embedded artwork with three differences: one Deezer request at the requested
size (a ladder would triple the thumb cost), the Spotify carrier URL rewritten
from the 640 px token to the 300 px one, and the iTunes rung asking for the
requested px variant instead of the 600x600bb default.

No network: scripted transport and clock seams from test_cover_art, carrier
helpers from test_cover_carrier.
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_cover_art import (
	HttpRecorder, FakeClock, patched, require_cover_art, thumb_utils,
	JPEG, PNG, HTML, MD5, SPOTIFY_URL,
)
from test_cover_carrier import (
	attr_patch, easy_dw_stub, LOOKUP_BODY, UPC,
)

import deezloader.deezloader as dz
from deezloader.deezloader import __download__ as dl
from deezloader.deezloader import cover_art

SPOTIFY_THUMB_URL = "https://i.scdn.co/image/ab67616d00001e02probe"
SPOTIFY_TOKENLESS_URL = "https://i.scdn.co/image/probe-without-token"

def deezer_thumb_url(md5, size):
	return f"https://cdn-images.dzcdn.net/images/cover/{md5}/{size}-000000-80-0-0.jpg"

def sizes_seen(urls, md5 = MD5):
	return list(dict.fromkeys(
		url.split(f"/cover/{md5}/")[1].split("-")[0]
		for url in urls if f"/cover/{md5}/" in url
	))

def host_sequence(urls):
	hosts = []

	for url in urls:
		host = url.split("/")[2]

		if not hosts or hosts[-1] != host:
			hosts.append(host)

	return hosts

# --- Deezer rung: one size, no ladder ---

def test_fetch_thumb_deezer_uses_the_requested_size_without_a_ladder():
	require_cover_art()
	http = HttpRecorder()

	with patched(http):
		result = cover_art.fetch_thumb(MD5, size = "320x320")

	assert result.data == b""
	assert result.reason == "all_sources_failed"
	# Persistent 403 on one single URL: MAX_RETRIES + 1 calls, never 1000x1000
	# or 500x500 (a ladder would triple the thumb cost on every card).
	assert sizes_seen(http.urls()) == ["320x320"]
	assert len(http.urls()) == cover_art.MAX_RETRIES + 1
	assert http.urls()[0] == deezer_thumb_url(MD5, "320x320")

def test_fetch_thumb_deezer_success_is_a_plain_cover_result():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG))

	with patched(http):
		result = cover_art.fetch_thumb(MD5)

	assert result.data == JPEG
	assert result.source == "deezer"
	assert result.reason == ""
	assert bool(result)
	assert http.urls() == [deezer_thumb_url(MD5, "90x90")]

# --- Spotify rung: 640 px token rewritten to 300 px ---

def test_fetch_thumb_rewrites_the_spotify_art_token_to_300px():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_thumb(fallback_url = SPOTIFY_URL)

	assert result.data == JPEG
	assert result.source == "spotify"
	assert result.reason == "fallback_used"
	assert http.urls() == [SPOTIFY_THUMB_URL]

def test_fetch_thumb_keeps_a_spotify_url_without_the_token():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_thumb(fallback_url = SPOTIFY_TOKENLESS_URL)

	assert result.data == JPEG
	assert http.urls() == [SPOTIFY_TOKENLESS_URL]

def test_fetch_thumb_spotify_rung_runs_after_deezer_refuses():
	require_cover_art()
	http = HttpRecorder().on(MD5, (403, b"")).on("i.scdn.co", (200, PNG))

	with patched(http):
		result = cover_art.fetch_thumb(MD5, fallback_url = SPOTIFY_URL)

	assert result.source == "spotify"
	assert result.reason == "fallback_used"
	assert SPOTIFY_THUMB_URL in http.urls()

# --- iTunes rung: requested px variant instead of the 600 px default ---

def test_fetch_thumb_requests_the_small_itunes_art_variant():
	require_cover_art()
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_thumb(upc = UPC, size = "90x90")

	assert result.data == JPEG
	assert result.source == "itunes"
	assert result.reason == "fallback_used"

	lookup_urls = [u for u in http.urls() if "itunes.apple.com/lookup" in u]
	assert lookup_urls and f"upc={UPC}" in lookup_urls[0]

	art_urls = [u for u in http.urls() if "mzstatic" in u]
	assert art_urls and "90x90bb" in art_urls[0]
	assert "600x600bb" not in art_urls[0]

def test_fetch_cover_keeps_the_600px_itunes_default():
	require_cover_art()
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_cover(upc = UPC)

	assert result.data == JPEG

	art_urls = [u for u in http.urls() if "mzstatic" in u]
	assert art_urls and "600x600bb" in art_urls[0]

def test_fetch_thumb_itunes_lookups_stay_paced_for_the_rate_limit():
	require_cover_art()
	http = HttpRecorder()
	http.on(f"upc={UPC}", (200, LOOKUP_BODY)).on("upc=999", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, JPEG))
	clock = FakeClock(advance_on_sleep = False)

	with patched(http, clock):
		assert cover_art.fetch_thumb(upc = UPC).data == JPEG
		assert cover_art.fetch_thumb(upc = "999").data == JPEG

	assert any(s >= 3.0 for s in clock.sleeps), clock.sleeps

# --- chain order and short-circuiting ---

def test_fetch_thumb_chain_order_is_deezer_spotify_itunes():
	require_cover_art()
	http = HttpRecorder()
	http.on("cdn-images", (403, b""))
	http.on("i.scdn.co", (403, b""))
	http.on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (403, b""))

	with patched(http):
		result = cover_art.fetch_thumb(MD5, fallback_url = SPOTIFY_URL, upc = UPC)

	assert result.data == b""
	assert result.reason == "all_sources_failed"
	assert host_sequence(http.urls()) == [
		"cdn-images.dzcdn.net", "i.scdn.co",
		"itunes.apple.com", "is1-ssl.mzstatic.com",
	], host_sequence(http.urls())

def test_fetch_thumb_stops_before_itunes_when_spotify_answers():
	require_cover_art()
	http = HttpRecorder().on(MD5, (403, b"")).on("i.scdn.co", (200, JPEG))
	http.on("itunes.apple.com/lookup", (200, LOOKUP_BODY))

	with patched(http):
		result = cover_art.fetch_thumb(MD5, fallback_url = SPOTIFY_URL, upc = UPC)

	assert result.source == "spotify"
	assert not any("itunes" in url for url in http.urls())

# --- validation ---

def test_fetch_thumb_validates_every_source_body():
	require_cover_art()
	http = HttpRecorder()
	http.default = (200, HTML)

	with patched(http):
		result = cover_art.fetch_thumb(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == b""
	assert result.reason == "all_sources_failed"

def test_fetch_thumb_rejects_a_short_itunes_artwork_body():
	require_cover_art()
	short = b"\xff\xd8\xff\xe0" + b"\x00" * 100
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, short))

	with patched(http):
		result = cover_art.fetch_thumb(upc = UPC)

	assert result.data == b""
	assert result.reason == "all_sources_failed"

# --- negative cache: own key space ---

def test_fetch_thumb_negative_cache_suppresses_the_refetch():
	require_cover_art()
	http = HttpRecorder()

	with patched(http):
		assert cover_art.fetch_thumb(MD5).data == b""
		first_round = len(http.calls)
		assert first_round > 0

		assert cover_art.fetch_thumb(MD5).data == b""
		assert len(http.calls) == first_round

		assert cover_art.fetch_thumb(MD5, size = "320x320").data == b""
		assert len(http.calls) > first_round, "thumb cache ignored the size"

def test_fetch_thumb_negative_cache_is_independent_from_the_embedded_cache():
	require_cover_art()
	http = HttpRecorder()

	with patched(http):
		assert cover_art.fetch_thumb(MD5).data == b""
		thumb_round = len(http.calls)

		# Same md5, different key space: the embedded-art fetch still runs.
		assert cover_art.fetch_cover(MD5).data == b""
		cover_round = len(http.calls)
		assert cover_round > thumb_round, "thumb failure poisoned the embedded cache"

		# And the embedded failure does not silence the thumb.
		assert cover_art.fetch_thumb(MD5).data == b""
		assert len(http.calls) == cover_round

def test_fetch_thumb_no_inputs_is_no_md5():
	require_cover_art()
	http = HttpRecorder()

	with patched(http):
		result = cover_art.fetch_thumb()

	assert result.data == b""
	assert result.reason == "no_md5"
	assert http.calls == []

# --- carrier attribute seams in the downloaders ---

def test_easy_dw_carries_the_spotify_fallback_on_the_track():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG))
	dw = easy_dw_stub(SPOTIFY_URL)

	with patched(http), attr_patch((dl.EASY_DW, "download_try", lambda self: None)):
		track = dw.easy_dw()

	assert track.md5_image == MD5
	assert track.cover_fallback_url == SPOTIFY_URL

def test_easy_dw_without_a_carrier_leaves_the_track_fallback_none():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG))
	dw = easy_dw_stub(None)

	with patched(http), attr_patch((dl.EASY_DW, "download_try", lambda self: None)):
		track = dw.easy_dw()

	assert track.cover_fallback_url is None

class AlbumProbe:
	"""Captures the Album built by DW_ALBUM.dw before the sentinel fires."""

	last = None

	def __init__(self, ids):
		self.ids = ids
		self.tracks = []
		AlbumProbe.last = self

class Sentinel(Exception):
	pass

def test_album_dw_carries_the_spotify_fallback_on_the_album():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG))
	album_dw = object.__new__(dl.DW_ALBUM)
	album_dw._DW_ALBUM__preferences = type(
		"Prefs", (), {"cover_fallback_url": SPOTIFY_URL}
	)()
	album_dw._DW_ALBUM__song_metadata = {
		"upc": UPC, "nb_tracks": 1, "album": "AL", "image": b"",
	}
	album_dw._DW_ALBUM__ids = "302127"
	album_dw._DW_ALBUM__quality_download = "FLAC"

	def boom(*args, **kwargs):
		raise Sentinel()

	with patched(http), attr_patch(
		(dl, "Album", AlbumProbe),
		(dl.API_GW, "get_album_data", staticmethod(
			lambda ids: {"data": [{"ALB_PICTURE": MD5}]}
		)),
		(dl.Download_JOB, "check_sources", staticmethod(boom)),
	):
		try:
			album_dw.dw()
			raise AssertionError("expected the sentinel after the cover fetch")
		except Sentinel:
			pass

	assert AlbumProbe.last is not None
	assert AlbumProbe.last.md5_image == MD5
	assert AlbumProbe.last.upc == UPC
	assert AlbumProbe.last.cover_fallback_url == SPOTIFY_URL

# --- existing behavior regressions ---

def test_thumb_bytes_feed_make_thumb_io_for_every_thumb_size():
	require_cover_art()

	for size in ("90x90", "320x320"):
		http = HttpRecorder().on(MD5, (200, JPEG))

		with patched(http):
			data = cover_art.fetch_thumb(MD5, size = size).data

		io_image = thumb_utils.make_thumb_io(data, MD5)
		assert io_image is not None, size
		assert io_image.name == MD5
		assert io_image.read() == JPEG

def test_choose_img_keeps_its_ladder_contract_after_the_thumb_addition():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG))

	with patched(http):
		assert dz.API.choose_img(MD5) == JPEG

	assert sizes_seen(http.urls()) == ["1200x1200"]
	assert http.urls() == [deezer_thumb_url(MD5, "1200x1200")]

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