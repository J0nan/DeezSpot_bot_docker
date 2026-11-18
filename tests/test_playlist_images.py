#!/usr/bin/python3

"""Regression tests for the playlist card guards in utils.utils_data.

A SpotAPI 2 playlist can legitimately arrive without artwork (``images == []``)
or without a single playable item (``tracks['items'] == []``). playlist_spo_data
indexed both blindly, so either shape raised IndexError and the bot answered
"This playlist is unreadable :(" for a playlist that is merely empty. These
tests pin the two guards, the partial-image-entry shape, and the unchanged
6-tuple of a normal playlist.

The bot stack (python-telegram-bot 13.x, pyrogram) cannot be imported on the
local Python 3.12, and playlist_spo_data needs none of it, so the config package
is stubbed before utils_data is imported. The network is never touched: Spo is
replaced by a scripted fake.

Run as: python -m pytest tests/test_playlist_images.py -q
     or: python tests/test_playlist_images.py
"""

import os
import sys
import types

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))

def _stub_module(name, **attributes):
	"""Register a stand-in module so the bot-stack imports resolve."""
	module = types.ModuleType(name)

	for attribute, value in attributes.items():
		setattr(module, attribute, value)

	sys.modules[name] = module

	return module

# configs is a package: the empty __path__ keeps it from resolving the real
# submodules, whose imports pull the telegram stack.
_stub_module("configs").__path__ = []
_stub_module(
	"configs.set_configs",
	SetConfigs = type("SetConfigs", (), {"deez_api": None})
)
_stub_module(
	"configs.bot_settings",
	output_songs = "Songs/",
	supported_link = [],
	output_shazam = "Shazam/",
	logs_path = "logs/",
	logger_names = [],
	log_uploads = "logs/uploads.log",
	log_downloads = "logs/downloads.log",
	db_name = ":memory:",
	method_save = 1
)
# helpers.db_help reads the settings column table at import time
_stub_module("configs.customs", bot_settings_config = [])

from utils import utils_data

PLAYLIST_LINK = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"
IMAGE_URL = "https://i.scdn.co/image/big.jpg"

class FakeSpo:
	"""Stand-in for deezloader.easy_spoty.Spo; records the ids it was asked for."""

	def __init__(self, data):
		self.data = data
		self.ids_seen = []

	def get_playlist(self, ids):
		self.ids_seen.append(ids)

		return self.data

class PatchedSpo:
	"""Replace utils_data.Spo for the duration of a test."""

	def __init__(self, data):
		self.spo = FakeSpo(data)

	def __enter__(self):
		self.original = utils_data.Spo
		utils_data.Spo = self.spo

		return self.spo

	def __exit__(self, *exc_info):
		utils_data.Spo = self.original

		return False

def make_playlist():
	"""The spotipy-shaped playlist Spo.get_playlist returns for a healthy one."""
	return {
		"name": "My Playlist",
		"owner": {"display_name": "Playlist Owner"},
		"followers": {"total": 4321},
		"images": [{"url": IMAGE_URL}],
		"tracks": {
			"items": [
				{"added_at": "2024-01-01T00:00:00Z", "track": {"name": "Song One"}},
				{"added_at": "2024-01-02T00:00:00Z", "track": {"name": "Song Two"}}
			],
			"total": 2,
			"next": None
		}
	}

def read_playlist(data):
	with PatchedSpo(data) as spo:
		return utils_data.playlist_spo_data(PLAYLIST_LINK), spo

def test_normal_playlist_returns_the_unchanged_six_tuple():
	data = make_playlist()
	result, spo = read_playlist(data)

	assert result == (
		2, 4321,
		IMAGE_URL, "2024-01-01T00:00:00Z",
		"Playlist Owner", data["tracks"]["items"]
	)
	assert len(result) == 6
	assert spo.ids_seen == [PLAYLIST_ID]

def test_playlist_without_images_returns_none_image_url():
	data = make_playlist()
	data["images"] = []
	result, _ = read_playlist(data)

	assert result[2] is None
	# every other field is untouched by the guard
	assert result[0] == 2
	assert result[1] == 4321
	assert result[3] == "2024-01-01T00:00:00Z"
	assert result[4] == "Playlist Owner"
	assert result[5] == data["tracks"]["items"]

def test_playlist_without_images_key_returns_none_image_url():
	data = make_playlist()
	del data["images"]
	result, _ = read_playlist(data)

	assert result[2] is None
	assert result[0] == 2
	assert result[3] == "2024-01-01T00:00:00Z"

def test_image_entry_without_url_returns_none_image_url():
	data = make_playlist()
	data["images"] = [{"height": 640}]
	result, _ = read_playlist(data)

	assert result[2] is None
	assert result[1] == 4321

def test_playlist_without_items_returns_none_creation_date():
	data = make_playlist()
	data["tracks"] = {"items": [], "total": 0, "next": None}
	result, _ = read_playlist(data)

	assert result[3] is None
	# the reported count and the (empty) item list still reach the card
	assert result[0] == 0
	assert result[5] == []
	assert result[2] == IMAGE_URL

def test_empty_playlist_without_artwork_keeps_both_guards():
	data = make_playlist()
	data["images"] = []
	data["tracks"] = {"items": [], "total": 0, "next": None}
	result, _ = read_playlist(data)

	assert result == (0, 4321, None, None, "Playlist Owner", [])

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