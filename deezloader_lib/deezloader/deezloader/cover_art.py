#!/usr/bin/python3

"""Cover-art fetching for every download path: a Deezer size ladder, an
optional Spotify URL, then an iTunes UPC lookup, all through one throttle,
retry loop and magic-byte validation. Reason codes go to the logger below.
"""

import logging
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

# The bot registers the `deezloader` parent logger (configs/bot_settings.py),
# so these reason-code lines reach logs/downloads.log.
logger = logging.getLogger("deezloader.cover_art")

# Clock seams so tests can drive time without waiting.
_now = time.time
_sleep = time.sleep

# Spotify serves every album image from one 640 px original; swapping the fixed
# hash token segment for the 300 px one yields the small variant with no API call.
SPOTIFY_ART_LARGE = "ab67616d0000b273"
SPOTIFY_ART_SMALL = "ab67616d00001e02"

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

def _itunes_cover(upc, art_size = ITUNES_ART_LARGE):
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

	return _get_image(artwork.replace(ITUNES_ART_SMALL, art_size))

def _fallback_result(key, data, source):
	"""Build the CoverResult a saved track gets and log the rescue line."""

	result = CoverResult(data, source, "fallback_used")
	logger.info(
		"cover fallback used key=%s source=%s reason=%s",
		key, result.source, result.reason
	)

	return result

def _run_chain(key, deezer_urls, fallback_url, upc, art_size):
	"""Walk Deezer -> Spotify -> iTunes, caching only a total failure so a
	rung that answered is never poisoned for the next caller.
	"""

	detail = ""

	for url in deezer_urls:
		data, fail = _get_image(url)

		if data:
			return CoverResult(data, DEEZER)

		detail = fail or detail

	if fallback_url:
		data, fail = _get_image(fallback_url)

		if data:
			return _fallback_result(key, data, SPOTIFY)

		detail = fail or detail

	if upc:
		data, fail = _itunes_cover(upc, art_size)

		if data:
			return _fallback_result(key, data, ITUNES)

		detail = fail or detail

	_negative_cache[key] = (_now() + NEGATIVE_TTL, "all_sources_failed")
	logger.warning(
		"cover failed key=%s reason=%s detail=%s",
		key, "all_sources_failed", detail
	)

	return CoverResult(reason = "all_sources_failed", detail = detail)

def fetch_cover(
	md5_image = "", fallback_url = None, upc = None, size = "1200x1200"
):
	if not md5_image and not fallback_url and not upc:
		return CoverResult(reason = "no_md5")

	key = md5_image or fallback_url or upc
	cached = _negative_cache.get(key)

	if cached and cached[0] > _now():
		return CoverResult(reason = cached[1])

	# an empty md5 would address the placeholder art: no Deezer URL is built
	deezer_urls = _deezer_urls(md5_image, size) if md5_image else []

	return _run_chain(key, deezer_urls, fallback_url, upc, ITUNES_ART_LARGE)

def _spotify_thumb_url(url):
	if SPOTIFY_ART_LARGE in url:
		return url.replace(SPOTIFY_ART_LARGE, SPOTIFY_ART_SMALL)

	return url

def fetch_thumb(
	md5_image = "", fallback_url = None, upc = None, size = "90x90"
):
	"""Fetch a small cover variant for Telegram cards and thumbs: same chain and
	validation as fetch_cover, one Deezer size, and a `thumb:` negative-cache key
	so a failed thumbnail never suppresses the track artwork.
	"""

	if not md5_image and not fallback_url and not upc:
		return CoverResult(reason = "no_md5")

	key = f"thumb:{size}:{md5_image or fallback_url or upc}"
	cached = _negative_cache.get(key)

	if cached and cached[0] > _now():
		return CoverResult(reason = cached[1])

	deezer_urls = [COVER_URL % (md5_image, size)] if md5_image else []
	thumb_fallback = _spotify_thumb_url(fallback_url) if fallback_url else None

	return _run_chain(
		key, deezer_urls, thumb_fallback, upc, f"{size}bb"
	)
