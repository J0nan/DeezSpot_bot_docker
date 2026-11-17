#!/usr/bin/python3

"""Contract tests for the SpotAPI 2 playlist mapping in deezloader.easy_spoty.

The tests never touch the network: the SpotAPI client is replaced by a scripted
fake that yields SpotAPI 2 model objects, so the mapping from typed models to
the spotipy-shaped dictionary consumed by utils/utils_data.py and the spotloader
downloaders is pinned here, together with the retry, truncation and error
behavior of Spo.get_playlist.

Run as: python -m pytest tests/test_easy_spoty_playlist.py -q
     or: python tests/test_easy_spoty_playlist.py
"""

import logging
import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace

try:
	from pytest import raises as _pytest_raises
except ImportError:
	# The repo ships no test dependencies; keep this file runnable as a
	# plain script on a bare interpreter.
	@contextmanager
	def _pytest_raises(expected):
		try:
			yield
		except expected:
			return

		raise AssertionError(f"{expected.__name__} was not raised")

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))

from deezloader import easy_spoty
from deezloader.exceptions import InvalidLink
from spotapi import SpotAPIError
from spotapi.models import (
	PlaylistDetails,
	PlaylistEntry,
	PlaylistTrack
)

PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"
PLAYLIST_URI = f"spotify:playlist:{PLAYLIST_ID}"

class _Client:
	"""One fake SyncCatalogue instance; records its own lifetime."""

	def __init__(self, owner):
		self.owner = owner
		self.closed = False

	def __enter__(self):
		return self

	def __exit__(self, *exc_info):
		self.closed = True

		return False

	def get_playlist(self, ids):
		self.owner.attempts += 1
		self.owner.ids_seen.append(ids)

		step = self.owner.script[min(self.owner.attempts - 1, len(self.owner.script) - 1)]

		if isinstance(step, BaseException):
			raise step

		self.owner.pages = step[1]

		return step[0]

	def get_playlist_items(self, ids):
		for page in self.owner.pages:
			yield page

class ScriptedCatalogue:
	"""Factory standing in for spotapi.SyncCatalogue.

	Each call returns a fresh client, like the real scoped client per
	Spo.get_playlist call. ``script`` holds one step per attempt: either
	``(details, pages)`` or an exception instance to raise.
	"""

	def __init__(self, script):
		self.script = list(script)
		self.attempts = 0
		self.ids_seen = []
		self.pages = []
		self.clients = []

	def __call__(self):
		client = _Client(self)
		self.clients.append(client)

		return client

	@property
	def all_closed(self):
		return all(client.closed for client in self.clients)

class Patched:
	"""Replace module attributes for the duration of a test."""

	def __init__(self, **attributes):
		self.attributes = attributes
		self.originals = {}

	def __enter__(self):
		for name, value in self.attributes.items():
			self.originals[name] = getattr(easy_spoty, name)
			setattr(easy_spoty, name, value)

		return self

	def __exit__(self, *exc_info):
		for name, value in self.originals.items():
			setattr(easy_spoty, name, value)

		return False

class NoSleep:
	"""Stand-in for time.sleep inside easy_spoty; records the delays."""

	def __init__(self):
		self.delays = []

	def __call__(self, seconds):
		self.delays.append(seconds)

class PatchedSleep:
	"""Patch easy_spoty.time.sleep without replacing the whole time module."""

	def __enter__(self):
		self.sleeper = NoSleep()
		self.original = easy_spoty.time.sleep
		easy_spoty.time.sleep = self.sleeper

		return self.sleeper

	def __exit__(self, *exc_info):
		easy_spoty.time.sleep = self.original

		return False

def make_details(
	total_count = 4,
	followers = 4321,
	owner_name = "Playlist Owner",
	image_url = "https://i.scdn.co/image/big.jpg"
):
	details = PlaylistDetails(name = "My Playlist", uri = PLAYLIST_URI)
	details.followers = followers
	details.owner_v2 = SimpleNamespace(data = SimpleNamespace(name = owner_name))
	details.images = SimpleNamespace(
		items = [
			SimpleNamespace(
				sources = [
					SimpleNamespace(url = "https://i.scdn.co/image/small.jpg", width = 64),
					SimpleNamespace(url = image_url, width = 640)
				]
			)
		]
	)
	details.content = SimpleNamespace(total_count = total_count)

	return details

def make_track_entry(name, track_id, artist_names, added_at = "2024-01-01T00:00:00Z"):
	item = PlaylistTrack(name = name, uri = f"spotify:track:{track_id}")
	item.artists = SimpleNamespace(
		items = [
			SimpleNamespace(profile = SimpleNamespace(name = artist_name))
			for artist_name in artist_names
		]
	)

	return PlaylistEntry(item = item, uid = f"uid-{track_id}", added_at = added_at)

def make_episode_entry(name = "An episode"):
	item = SimpleNamespace(name = name, uri = "spotify:episode:0ofHAoxe9vBkTCp2UQIavz", artists = None)

	return PlaylistEntry(item = item, uid = "uid-episode", added_at = "2024-02-02T00:00:00Z")

def track_names(tracks):
	return [entry["track"]["name"] for entry in tracks]

def test_playlist_maps_to_spotipy_shape():
	details = make_details()
	pages = [
		[make_track_entry("Song One", "111", ["Artist A", "Artist B"])],
		[make_track_entry("Song Two", "222", ["Artist C"]), make_episode_entry(), PlaylistEntry(item = None)]
	]
	catalogue = ScriptedCatalogue([(details, pages)])

	with Patched(SyncCatalogue = catalogue):
		result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert result == {
		"name": "My Playlist",
		"owner": {"display_name": "Playlist Owner"},
		"followers": {"total": 4321},
		"images": [{"url": "https://i.scdn.co/image/big.jpg"}],
		"tracks": {
			"items": [
				{
					"added_at": "2024-01-01T00:00:00Z",
					"track": {
						"name": "Song One",
						"artists": [{"name": "Artist A"}, {"name": "Artist B"}],
						"external_urls": {"spotify": "https://open.spotify.com/track/111"}
					}
				},
				{
					"added_at": "2024-01-01T00:00:00Z",
					"track": {
						"name": "Song Two",
						"artists": [{"name": "Artist C"}],
						"external_urls": {"spotify": "https://open.spotify.com/track/222"}
					}
				}
			],
			"total": 4,
			"next": None
		}
	}
	assert catalogue.attempts == 1
	assert catalogue.all_closed is True

def test_all_items_are_collected_across_pages():
	first_page = [make_track_entry(f"First {index}", str(100 + index), ["Artist"]) for index in range(100)]
	second_page = [make_track_entry(f"Second {index}", str(200 + index), ["Artist"]) for index in range(100)]
	catalogue = ScriptedCatalogue([(make_details(total_count = 200), [first_page, second_page])])

	with Patched(SyncCatalogue = catalogue):
		result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert result["tracks"]["total"] == 200
	assert len(result["tracks"]["items"]) == 200
	assert result["tracks"]["items"][0]["track"]["name"] == "First 0"
	assert result["tracks"]["items"][-1]["track"]["name"] == "Second 99"

def test_missing_optional_metadata_falls_back():
	details = PlaylistDetails(name = "Bare", uri = PLAYLIST_URI)
	details.followers = None
	details.owner_v2 = None
	details.images = None
	details.content = None
	catalogue = ScriptedCatalogue([(details, [[make_track_entry("Song", "111", ["Artist"])]])])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep() as sleeper:
			result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert result["owner"] == {"display_name": "Unknown"}
	assert result["followers"] == {"total": 0}
	assert result["images"] == []
	assert result["tracks"]["total"] == 1
	assert catalogue.attempts == 1
	assert sleeper.delays == []

def test_track_without_artists_gets_unknown_artist():
	details = make_details(total_count = 1)
	catalogue = ScriptedCatalogue([(details, [[make_track_entry("Song", "111", [])]])])

	with Patched(SyncCatalogue = catalogue):
		result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert result["tracks"]["items"][0]["track"]["artists"] == [{"name": "Unknown"}]

def test_image_without_sources_is_skipped():
	details = make_details(total_count = 1)
	details.images = SimpleNamespace(
		items = [
			SimpleNamespace(sources = []),
			SimpleNamespace(sources = [SimpleNamespace(url = "https://i.scdn.co/image/only.jpg", width = 300)])
		]
	)
	catalogue = ScriptedCatalogue([(details, [[make_track_entry("Song", "111", ["Artist"])]])])

	with Patched(SyncCatalogue = catalogue):
		result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert result["images"] == [{"url": "https://i.scdn.co/image/only.jpg"}]

def test_image_source_without_url_is_skipped():
	details = make_details(total_count = 1)
	details.images = SimpleNamespace(
		items = [SimpleNamespace(sources = [SimpleNamespace(width = 640)])]
	)
	catalogue = ScriptedCatalogue([(details, [[make_track_entry("Song", "111", ["Artist"])]])])

	with Patched(SyncCatalogue = catalogue):
		result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert result["images"] == []

def test_entry_without_item_attribute_is_skipped():
	details = make_details(total_count = 1)
	entries = [
		SimpleNamespace(name = "no item here"),
		make_track_entry("Song", "111", ["Artist"])
	]
	catalogue = ScriptedCatalogue([(details, [entries])])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep() as sleeper:
			result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert track_names(result["tracks"]["items"]) == ["Song"]
	assert catalogue.attempts == 1
	assert sleeper.delays == []

def test_longest_attempt_wins_over_a_shorter_complete_one():
	# Deliberate: when the playlist shrinks between attempts, the largest
	# snapshot is returned and tracks.total keeps the reported total, so
	# the shortfall stays visible to the caller. See the plan record.
	details = make_details(total_count = 10)
	longer_truncated = [[make_track_entry(f"Track {index}", str(100 + index), ["Artist"]) for index in range(6)]]
	shorter_complete = [[make_track_entry(f"New {index}", str(200 + index), ["Artist"]) for index in range(4)]]
	catalogue = ScriptedCatalogue([
		(details, longer_truncated),
		(make_details(total_count = 4), shorter_complete)
	])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep():
			result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert catalogue.attempts == 2
	assert len(result["tracks"]["items"]) == 6
	assert result["tracks"]["total"] == 10

def test_spotapi_error_becomes_invalid_link():
	catalogue = ScriptedCatalogue([SpotAPIError("fetchPlaylistMetadata: missing resource")])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep() as sleeper:
			with _pytest_raises(InvalidLink):
				easy_spoty.Spo.get_playlist("0000000000000000000000")

	assert catalogue.attempts == 2
	assert sleeper.delays == [1]
	assert catalogue.all_closed is True

def test_value_error_is_not_retried():
	catalogue = ScriptedCatalogue([ValueError("not a Spotify playlist")])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep() as sleeper:
			with _pytest_raises(InvalidLink):
				easy_spoty.Spo.get_playlist("not-a-playlist")

	assert catalogue.attempts == 1
	assert sleeper.delays == []
	assert catalogue.all_closed is True

def test_transient_failure_is_retried():
	details = make_details(total_count = 1)
	track = make_track_entry("Song", "111", ["Artist"])
	catalogue = ScriptedCatalogue([
		SpotAPIError("HTTP 503 from the Spotify web player"),
		(details, [[track]])
	])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep() as sleeper:
			result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert catalogue.attempts == 2
	assert catalogue.all_closed is True
	assert result["tracks"]["items"][0]["track"]["name"] == "Song"
	assert sleeper.delays == [1]

def test_longest_attempt_survives_an_unknown_total():
	short_total = make_details(total_count = 10)
	many_items = [[make_track_entry(f"Track {index}", str(100 + index), ["Artist"]) for index in range(6)]]
	few_items = [[make_track_entry(f"Only {index}", str(200 + index), ["Artist"]) for index in range(4)]]
	unknown_total = make_details(total_count = None)
	catalogue = ScriptedCatalogue([(short_total, many_items), (unknown_total, few_items)])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep():
			result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert catalogue.attempts == 2
	assert len(result["tracks"]["items"]) == 6

def test_truncated_playlist_is_refetched():
	details = make_details(total_count = 3)
	short = [[make_track_entry("Only", "111", ["Artist"])]]
	full = [[
		make_track_entry("Only", "111", ["Artist"]),
		make_track_entry("Two", "222", ["Artist"]),
		make_track_entry("Three", "333", ["Artist"])
	]]
	catalogue = ScriptedCatalogue([(details, short), (details, full)])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep():
			result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert catalogue.attempts == 2
	assert track_names(result["tracks"]["items"]) == ["Only", "Two", "Three"]

def test_truncated_playlist_keeps_the_best_result_and_warns():
	details = make_details(total_count = 3)
	short = [[make_track_entry("Only", "111", ["Artist"])]]
	catalogue = ScriptedCatalogue([(details, short), (details, short)])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep():
			with LogCapture() as logs:
				result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert catalogue.attempts == 2
	assert track_names(result["tracks"]["items"]) == ["Only"]
	assert result["tracks"]["total"] == 3
	assert any("truncated" in message for message in logs.warnings)
	assert logs.errors == []

def test_partial_then_failed_attempt_keeps_the_partial_playlist():
	details = make_details(total_count = 3)
	short = [[make_track_entry("Only", "111", ["Artist"])]]
	catalogue = ScriptedCatalogue([
		(details, short),
		SpotAPIError("HTTP 429 Too Many Requests")
	])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep():
			result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert catalogue.attempts == 2
	assert track_names(result["tracks"]["items"]) == ["Only"]

class LogCapture:
	"""Capture the warnings and errors emitted by easy_spoty's logger."""

	def __enter__(self):
		self.warnings = []
		self.errors = []
		self.handler = logging.Handler()
		self.handler.emit = self._emit
		self.logger = easy_spoty.logger
		self.previous_level = self.logger.level
		self.logger.addHandler(self.handler)
		self.logger.setLevel(logging.DEBUG)

		return self

	def _emit(self, record):
		if record.levelno >= logging.ERROR:
			self.errors.append(record.getMessage())
		else:
			self.warnings.append(record.getMessage())

	def __exit__(self, *exc_info):
		self.logger.removeHandler(self.handler)
		self.logger.setLevel(self.previous_level)

		return False

def test_failure_after_retries_is_logged_as_an_error():
	catalogue = ScriptedCatalogue([SpotAPIError("HTTP 503 from the Spotify web player")])

	with Patched(SyncCatalogue = catalogue):
		with PatchedSleep():
			with LogCapture() as logs:
				with _pytest_raises(InvalidLink):
					easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert len(logs.errors) == 1
	assert PLAYLIST_ID in logs.errors[0]

def _run_standalone():
	failures = 0
	executed = 0

	for name, test in sorted(globals().items()):
		if not name.startswith("test_") or not callable(test):
			continue

		executed += 1

		try:
			test()
		except Exception as error:
			failures += 1
			print(f"FAIL {name}: {error!r}")
		else:
			print(f"PASS {name}")

	if not executed:
		print("FAIL: no tests were collected")
		return 1

	print(f"{failures} failure(s)")

	return 1 if failures else 0

if __name__ == "__main__":
	sys.exit(_run_standalone())