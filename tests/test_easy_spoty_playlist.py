#!/usr/bin/python3

"""Contract tests for the SpotAPI 2 playlist mapping in deezloader.easy_spoty.

The tests never touch the network: the SpotAPI client is replaced by a fake
that yields SpotAPI 2 model objects, so the mapping from typed models to the
spotipy-shaped dictionary consumed by utils/utils_data.py and the spotloader
downloaders is pinned here.

Run as: python -m pytest tests/test_easy_spoty_playlist.py -q
     or: python tests/test_easy_spoty_playlist.py
"""

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

class FakeCatalogue:
	"""Stand-in for spotapi.SyncCatalogue with a scoped lifetime."""

	def __init__(self, details = None, pages = None, error = None):
		self.details = details
		self.pages = pages or []
		self.error = error
		self.closed = False

	def __enter__(self):
		return self

	def __exit__(self, *exc_info):
		self.closed = True

		return False

	def get_playlist(self, ids):
		if self.error is not None:
			raise self.error

		return self.details

	def get_playlist_items(self, ids):
		for page in self.pages:
			yield page

class PatchedCatalogue:
	"""Replace the SpotAPI client factory for the duration of a test."""

	def __init__(self, client):
		self.client = client

	def __enter__(self):
		self.original = easy_spoty.SyncCatalogue
		easy_spoty.SyncCatalogue = lambda: self.client

		return self.client

	def __exit__(self, *exc_info):
		easy_spoty.SyncCatalogue = self.original

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

def test_playlist_maps_to_spotipy_shape():
	details = make_details()
	pages = [
		[make_track_entry("Song One", "111", ["Artist A", "Artist B"])],
		[make_track_entry("Song Two", "222", ["Artist C"]), make_episode_entry(), PlaylistEntry(item = None)]
	]
	client = FakeCatalogue(details = details, pages = pages)

	with PatchedCatalogue(client) as fake:
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
	assert fake.closed is True

def test_all_items_are_collected_across_pages():
	first_page = [make_track_entry(f"First {index}", str(100 + index), ["Artist"]) for index in range(100)]
	second_page = [make_track_entry(f"Second {index}", str(200 + index), ["Artist"]) for index in range(100)]
	client = FakeCatalogue(details = make_details(total_count = 200), pages = [first_page, second_page])

	with PatchedCatalogue(client):
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
	client = FakeCatalogue(details = details, pages = [[make_track_entry("Song", "111", ["Artist"])]])

	with PatchedCatalogue(client):
		result = easy_spoty.Spo.get_playlist(PLAYLIST_ID)

	assert result["owner"] == {"display_name": "Unknown"}
	assert result["followers"] == {"total": 0}
	assert result["images"] == []
	assert result["tracks"]["total"] == 1

def test_spotapi_error_becomes_invalid_link():
	client = FakeCatalogue(error = SpotAPIError("fetchPlaylistMetadata: missing resource"))

	with PatchedCatalogue(client):
		with _pytest_raises(InvalidLink):
			easy_spoty.Spo.get_playlist("0000000000000000000000")

def test_value_error_becomes_invalid_link():
	client = FakeCatalogue(error = ValueError("not a Spotify playlist"))

	with PatchedCatalogue(client):
		with _pytest_raises(InvalidLink):
			easy_spoty.Spo.get_playlist("not-a-playlist")

def _run_standalone():
	failures = 0

	for name, test in sorted(globals().items()):
		if not name.startswith("test_") or not callable(test):
			continue

		try:
			test()
		except Exception as error:
			failures += 1
			print(f"FAIL {name}: {error!r}")
		else:
			print(f"PASS {name}")

	print(f"{failures} failure(s)")

	return 1 if failures else 0

if __name__ == "__main__":
	sys.exit(_run_standalone())
