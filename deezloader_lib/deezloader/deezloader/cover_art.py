#!/usr/bin/python3

"""Resilient cover-art pipeline for the download paths.

Deezer's CDN (cdn-images.dzcdn.net) intermittently answers 403 with an empty
body -- request-rate/content protection, not a dead host. The legacy
choose_img fired up to ten bare requests per track (no header, no timeout, no
backoff) and accepted any body that was not 13 bytes long, so refusals
silently became coverless files. This module owns fetching and validation for
every cover consumer:

- Deezer size ladder (asked size -> 1000x1000 -> 500x500), deduplicated, with
  no empty-md5 placeholder calls.
- Optional Spotify fallback URL (i.scdn.co), captured at link conversion.
- iTunes tertiary rung: keyless exact album lookup by the Deezer UPC
  (lookup?upc=...&entity=album), artworkUrl100 upscaled through the
  100x100bb -> 600x600bb URL rewrite. Lookups are paced at >= 3 s to respect
  the documented ~20 calls/min limit; no fuzzy term matching.
- Shared browser header, timeouts, bounded retries with exponential backoff
  and jitter on 403/429/5xx/network errors.
- Per-host minimum request interval and a per-key negative cache so a refused
  album is not re-hammered once per track.
- Magic-byte + minimum-size validation: HTML/JSON error bodies are never
  embedded as artwork.
"""

import random
import time
from urllib.parse import urlsplit

import requests

from ..libutils.others_settings import header

DEEZER = "deezer"
SPOTIFY = "spotify"
ITUNES = "itunes"

MIN_IMAGE_BYTES = 1024
NEGATIVE_TTL = 600.0
MIN_REQUEST_INTERVAL = 0.25
ITUNES_MIN_INTERVAL = 3.0
REQUEST_TIMEOUT = (5, 15)
MAX_RETRIES = 2
BACKOFF_BASE = 0.5
FALLBACK_SIZES = ("1000x1000", "500x500")
COVER_URL = "https://cdn-images.dzcdn.net/images/cover/%s/%s-000000-80-0-0.jpg"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup?upc=%s&entity=album"
ITUNES_ART_SMALL = "100x100bb"
ITUNES_ART_LARGE = "600x600bb"

# Clock seams so tests can drive time without waiting.
_now = time.time
_sleep = time.sleep

_negative_cache = {}
_last_request = {}

class CoverResult:
	def __init__(self, data = b"", source = "", reason = "", detail = ""):
		self.data = data
		self.source = source
		self.reason = reason
		self.detail = detail

	def __bool__(self):
		return bool(self.data)

def is_valid_image(data):
	if not data or len(data) < MIN_IMAGE_BYTES:
		return False

	if data[:3] == b"\xff\xd8\xff":
		return True

	if data[:8] == b"\x89PNG\r\n\x1a\n":
		return True

	if data[:6] in (b"GIF87a", b"GIF89a"):
		return True

	if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
		return True

	return False

def _throttle(url):
	host = urlsplit(url).netloc
	interval = (
		ITUNES_MIN_INTERVAL if host == "itunes.apple.com"
		else MIN_REQUEST_INTERVAL
	)
	last = _last_request.get(host)

	if last is not None:
		wait = interval - (_now() - last)

		if wait > 0:
			_sleep(wait)

	_last_request[host] = _now()

def _reason_for(status, body):
	if status == 403:
		return "cdn_403"

	if not body:
		return "cdn_empty"

	return "invalid_body"

def _get_image(url):
	last_status = 0
	last_body = b""

	for attempt in range(MAX_RETRIES + 1):
		_throttle(url)

		try:
			response = requests.get(
				url, headers = header, timeout = REQUEST_TIMEOUT
			)
		except requests.RequestException:
			last_status, last_body = 0, b""
		else:
			last_status, last_body = response.status_code, response.content

			if last_status == 200 and is_valid_image(last_body):
				return last_body, ""

		retryable = (
			last_status in (403, 429)
			or last_status >= 500
			or last_status == 0
		)

		if not retryable or attempt == MAX_RETRIES:
			break

		_sleep(BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.1))

	return b"", _reason_for(last_status, last_body)

def _deezer_urls(md5_image, size):
	sizes = list(dict.fromkeys((size, *FALLBACK_SIZES)))

	return [COVER_URL % (md5_image, c_size) for c_size in sizes]

def _itunes_cover(upc):
	lookup_url = ITUNES_LOOKUP % upc
	_throttle(lookup_url)

	try:
		response = requests.get(
			lookup_url, headers = header, timeout = REQUEST_TIMEOUT
		)
	except requests.RequestException:
		return b"", "cdn_empty"

	if response.status_code != 200:
		return b"", _reason_for(response.status_code, b"")

	try:
		results = response.json().get("results") or []
	except ValueError:
		return b"", "invalid_body"

	if not results:
		return b"", "no_match"

	artwork = results[0].get("artworkUrl100") or ""

	if not artwork:
		return b"", "no_match"

	return _get_image(artwork.replace(ITUNES_ART_SMALL, ITUNES_ART_LARGE))

def fetch_cover(
	md5_image = "", fallback_url = None, upc = None, size = "1200x1200"
):
	if not md5_image and not fallback_url and not upc:
		return CoverResult(reason = "no_md5")

	key = md5_image or fallback_url or upc
	cached = _negative_cache.get(key)

	if cached and cached[0] > _now():
		return CoverResult(reason = cached[1])

	detail = ""

	if md5_image:
		for url in _deezer_urls(md5_image, size):
			data, fail = _get_image(url)

			if data:
				return CoverResult(data, DEEZER)

			detail = fail or detail

	if fallback_url:
		data, fail = _get_image(fallback_url)

		if data:
			return CoverResult(data, SPOTIFY, "fallback_used")

		detail = fail or detail

	if upc:
		data, fail = _itunes_cover(upc)

		if data:
			return CoverResult(data, ITUNES, "fallback_used")

		detail = fail or detail

	_negative_cache[key] = (_now() + NEGATIVE_TTL, "all_sources_failed")

	return CoverResult(reason = "all_sources_failed", detail = detail)
