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
- Shared browser header, timeouts, bounded retries with exponential backoff
  and jitter on 403/429/5xx/network errors.
- Per-host minimum request interval and a per-key negative cache so a refused
  album is not re-hammered once per track.
- Magic-byte + minimum-size validation: HTML/JSON error bodies are never
  embedded as artwork.

The iTunes rung (exact UPC lookup) joins fetch_cover additively in a later
work unit.
"""

import random
import time
from urllib.parse import urlsplit

import requests

from ..libutils.others_settings import header

DEEZER = "deezer"
SPOTIFY = "spotify"

MIN_IMAGE_BYTES = 1024
NEGATIVE_TTL = 600.0
MIN_REQUEST_INTERVAL = 0.25
REQUEST_TIMEOUT = (5, 15)
MAX_RETRIES = 2
BACKOFF_BASE = 0.5
FALLBACK_SIZES = ("1000x1000", "500x500")
COVER_URL = "https://cdn-images.dzcdn.net/images/cover/%s/%s-000000-80-0-0.jpg"

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
	last = _last_request.get(host)

	if last is not None:
		wait = MIN_REQUEST_INTERVAL - (_now() - last)

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

def fetch_cover(md5_image = "", fallback_url = None, size = "1200x1200"):
	if not md5_image and not fallback_url:
		return CoverResult(reason = "no_md5")

	key = md5_image or fallback_url
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

	_negative_cache[key] = (_now() + NEGATIVE_TTL, "all_sources_failed")

	return CoverResult(reason = "all_sources_failed", detail = detail)
