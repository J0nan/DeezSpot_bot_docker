#!/usr/bin/python3

"""T2 tests: the iTunes tertiary rung and the Spotify cover carrier.

The iTunes Search/lookup API is keyless and rate-limited to ~20 calls/min, so
the rung matches albums exactly by the Deezer UPC (lookup?upc=...&entity=album),
upscales artworkUrl100 via the 100x100bb -> 600x600bb URL rewrite, and paces
lookups at >= 3 s. The carrier captures the Spotify album image URL that the
link conversion already fetches (zero extra Spotify API calls) and threads it
as an optional cover_fallback_url through the download entry points into
EASY_DW / DW_ALBUM, where fetch_cover uses it when Deezer refuses.

No network: scripted transport and clock seams from test_cover_art; the
conversion/download entry points are driven with stubbed Spo/API/DW classes.

Run as: .venv\\Scripts\\python -m pytest tests/test_cover_carrier.py -q
     or: .venv\\Scripts\\python tests/test_cover_carrier.py
"""

import os
import sys
from types import SimpleNamespace

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_cover_art import (
	HttpRecorder, FakeClock, patched, require_cover_art,
	JPEG, HTML, MD5, SPOTIFY_URL,
)

import deezloader.deezloader as dz
from deezloader.deezloader import __download__ as dl
from deezloader.deezloader import cover_art

FAKE = object.__new__(dz.DeeLogin)

UPC = "602527644271"
SPO_TRACK_LINK = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
SPO_ALBUM_LINK = "https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3"
DEE_TRACK_LINK = "https://www.deezer.com/track/3135553"
DEE_ALBUM_LINK = "https://www.deezer.com/album/302127"
ART100 = "https://is1-ssl.mzstatic.com/image/thumb/probe/100x100bb.jpg"
LOOKUP_BODY = (
	b'{"resultCount":1,"results":[{"artworkUrl100":"' + ART100.encode() + b'"}]}'
)
NO_MATCH_BODY = b'{"resultCount":0,"results":[]}'

class attr_patch:
	"""Temporarily replace attributes on any object; bare-script friendly."""

	def __init__(self, *pairs):
		self.pairs = pairs
		self.saved = []

	def __enter__(self):
		for obj, name, value in self.pairs:
			self.saved.append((obj, name, getattr(obj, name)))
			setattr(obj, name, value)

		return self

	def __exit__(self, *exc_info):
		for obj, name, value in reversed(self.saved):
			setattr(obj, name, value)

		return False

def spo_track_payload(images = None):
	return {
		"name": "Probe Song",
		"external_ids": {"isrc": "GBUM71029605"},
		"album": {"images": images if images is not None else [{"url": SPOTIFY_URL}]},
	}

# --- iTunes rung ---

def test_itunes_rescues_when_deezer_and_spotify_refuse():
	require_cover_art()
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL, upc = UPC)

	assert result.data == JPEG
	assert result.source == "itunes"
	assert result.reason == "fallback_used"

	lookup_urls = [u for u in http.urls() if "itunes.apple.com/lookup" in u]
	assert lookup_urls and f"upc={UPC}" in lookup_urls[0]
	assert "entity=album" in lookup_urls[0]

	art_urls = [u for u in http.urls() if "mzstatic" in u]
	assert art_urls and "600x600bb" in art_urls[0]
	assert "100x100bb" not in art_urls[0]

def test_itunes_upc_only_source():
	require_cover_art()
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, JPEG))

	with patched(http):
		result = cover_art.fetch_cover(upc = UPC)

	assert result.data == JPEG
	assert result.source == "itunes"
	assert len(http.urls()) == 2

def test_itunes_no_match_fails_closed():
	require_cover_art()
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, NO_MATCH_BODY))

	with patched(http):
		result = cover_art.fetch_cover(upc = UPC)

	assert result.data == b""
	assert result.reason == "all_sources_failed"

def test_itunes_artwork_is_validated():
	require_cover_art()
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, HTML))

	with patched(http):
		result = cover_art.fetch_cover(upc = UPC)

	assert result.data == b""
	assert result.reason == "all_sources_failed"

def test_itunes_lookups_are_paced_for_the_rate_limit():
	require_cover_art()
	http = HttpRecorder()
	http.on(f"upc={UPC}", (200, LOOKUP_BODY)).on("upc=999", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, JPEG))
	clock = FakeClock(advance_on_sleep = False)

	with patched(http, clock):
		assert cover_art.fetch_cover(upc = UPC).data == JPEG
		assert cover_art.fetch_cover(upc = "999").data == JPEG

	assert any(s >= 3.0 for s in clock.sleeps), clock.sleeps

def test_itunes_lookup_connection_error_fails_closed():
	require_cover_art()
	import requests
	http = HttpRecorder().on(
		"itunes.apple.com/lookup", requests.exceptions.ConnectionError("probe")
	)

	with patched(http):
		result = cover_art.fetch_cover(upc = UPC)

	assert result.data == b""
	assert result.reason == "all_sources_failed"

def test_spotify_wins_before_itunes_is_touched():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))
	http.on("itunes.apple.com/lookup", (200, LOOKUP_BODY))

	with patched(http):
		result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL, upc = UPC)

	assert result.source == "spotify"
	assert not any("itunes" in url for url in http.urls())

# --- Spotify carrier at conversion ---

def test_convert_track_returns_link_and_spotify_image():
	with attr_patch(
		(dz.Spo, "get_track", staticmethod(lambda ids: spo_track_payload())),
		(dz.API, "get_track", staticmethod(lambda ids: {"link": DEE_TRACK_LINK})),
	):
		link, image = dz.DeeLogin.convert_spoty_to_dee_track(FAKE, SPO_TRACK_LINK)

	assert link == DEE_TRACK_LINK
	assert image == SPOTIFY_URL

def test_convert_track_legacy_method_keeps_link_only_contract():
	with attr_patch(
		(dz.Spo, "get_track", staticmethod(lambda ids: spo_track_payload())),
		(dz.API, "get_track", staticmethod(lambda ids: {"link": DEE_TRACK_LINK})),
	):
		assert dz.DeeLogin.convert_spoty_to_dee_link_track(FAKE, SPO_TRACK_LINK) == DEE_TRACK_LINK

def test_convert_track_without_images_yields_none_fallback():
	with attr_patch(
		(dz.Spo, "get_track", staticmethod(lambda ids: spo_track_payload(images = []))),
		(dz.API, "get_track", staticmethod(lambda ids: {"link": DEE_TRACK_LINK})),
	):
		link, image = dz.DeeLogin.convert_spoty_to_dee_track(FAKE, SPO_TRACK_LINK)

	assert link == DEE_TRACK_LINK
	assert image is None

def test_convert_album_returns_link_and_spotify_image():
	album_payload = {
		"external_ids": {"upc": UPC},
		"images": [{"url": SPOTIFY_URL}],
		"total_tracks": 1,
		"tracks": {"items": []},
	}

	with attr_patch(
		(dz.Spo, "get_album", staticmethod(lambda ids: album_payload)),
		(dz.API, "get_album", staticmethod(lambda ids: {"link": DEE_ALBUM_LINK})),
	):
		link, image = dz.DeeLogin.convert_spoty_to_dee_album(FAKE, SPO_ALBUM_LINK)
		legacy = dz.DeeLogin.convert_spoty_to_dee_link_album(FAKE, SPO_ALBUM_LINK)

	assert link == DEE_ALBUM_LINK
	assert image == SPOTIFY_URL
	assert legacy == DEE_ALBUM_LINK

# --- carrier threading through the download entry points ---

class CaptureDW:
	last = None

	def __init__(self, preferences):
		CaptureDW.last = preferences

	def dw(self):
		return SimpleNamespace(success = True)

def test_download_trackdee_threads_fallback_into_preferences():
	with attr_patch(
		(dz.API, "tracking", staticmethod(lambda ids: {"upc": UPC})),
		(dz, "DW_TRACK", CaptureDW),
	):
		dz.DeeLogin.download_trackdee(FAKE, DEE_TRACK_LINK, cover_fallback_url = SPOTIFY_URL)
		assert CaptureDW.last.cover_fallback_url == SPOTIFY_URL

		dz.DeeLogin.download_trackdee(FAKE, DEE_TRACK_LINK)
		assert CaptureDW.last.cover_fallback_url is None

def test_download_albumdee_threads_fallback_into_preferences():
	with attr_patch(
		(dz.API, "get_album", staticmethod(lambda ids: {"id": 302127})),
		(dz.API, "tracking_album", staticmethod(lambda album_json: {"upc": UPC})),
		(dz, "DW_ALBUM", CaptureDW),
	):
		dz.DeeLogin.download_albumdee(FAKE, DEE_ALBUM_LINK, cover_fallback_url = SPOTIFY_URL)
		assert CaptureDW.last.cover_fallback_url == SPOTIFY_URL

def test_download_trackspo_carries_the_conversion_image():
	with attr_patch(
		(dz.Spo, "get_track", staticmethod(lambda ids: spo_track_payload())),
		(dz.API, "get_track", staticmethod(lambda ids: {"link": DEE_TRACK_LINK})),
		(dz.API, "tracking", staticmethod(lambda ids: {"upc": UPC})),
		(dz, "DW_TRACK", CaptureDW),
	):
		dz.DeeLogin.download_trackspo(FAKE, SPO_TRACK_LINK)

	assert CaptureDW.last.link == DEE_TRACK_LINK
	assert CaptureDW.last.cover_fallback_url == SPOTIFY_URL

# --- cover seam inside the downloaders ---

def easy_dw_stub(fallback_url):
	dw = object.__new__(dl.EASY_DW)
	dw._EASY_DW__infos_dw = {"ALB_PICTURE": MD5}
	dw._EASY_DW__song_metadata = {"music": "M", "artist": "A", "upc": UPC}
	dw._EASY_DW__cover_fallback_url = fallback_url
	dw._EASY_DW__not_interface = True
	dw._EASY_DW__c_track = SimpleNamespace(success = True)
	return dw

def test_easy_dw_uses_spotify_fallback_when_deezer_refuses():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))
	dw = easy_dw_stub(SPOTIFY_URL)

	with patched(http), attr_patch((dl.EASY_DW, "download_try", lambda self: None)):
		track = dw.easy_dw()

	assert dw._EASY_DW__song_metadata["image"] == JPEG
	assert track.md5_image == MD5

def test_easy_dw_deezer_primary_wins():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG)).on("i.scdn.co", (200, HTML))
	dw = easy_dw_stub(SPOTIFY_URL)

	with patched(http), attr_patch((dl.EASY_DW, "download_try", lambda self: None)):
		dw.easy_dw()

	assert dw._EASY_DW__song_metadata["image"] == JPEG
	assert not any("i.scdn.co" in url for url in http.urls())

class Sentinel(Exception):
	pass

def test_album_dw_fetches_one_cover_with_fallback_and_upc():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))
	album_dw = object.__new__(dl.DW_ALBUM)
	album_dw._DW_ALBUM__preferences = SimpleNamespace(cover_fallback_url = SPOTIFY_URL)
	album_dw._DW_ALBUM__song_metadata = {"upc": UPC, "nb_tracks": 1, "album": "AL", "image": b""}
	album_dw._DW_ALBUM__ids = "302127"
	album_dw._DW_ALBUM__quality_download = "FLAC"

	def boom(*args, **kwargs):
		raise Sentinel()

	with patched(http), attr_patch(
		(dl.API_GW, "get_album_data", staticmethod(lambda ids: {"data": [{"ALB_PICTURE": MD5}]})),
		(dl.Download_JOB, "check_sources", staticmethod(boom)),
	):
		try:
			album_dw.dw()
			raise AssertionError("expected the sentinel after the cover fetch")
		except Sentinel:
			pass

	assert album_dw._DW_ALBUM__song_metadata["image"] == JPEG
	assert any("i.scdn.co" in url for url in http.urls())

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
