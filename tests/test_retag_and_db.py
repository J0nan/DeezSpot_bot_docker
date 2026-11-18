#!/usr/bin/python3

"""T4 tests: cover-aware check_track, in-place re-tagging and the DB cover flag.

A track whose 18 vorbis comments are complete but whose picture block is
missing makes the legacy check_track answer True, so the downloader skips the
file forever and the cover never lands. check_track now also requires a real
picture block (format-aware), while has_complete_tags keeps the old >= 14 tag
answer so download_try can re-tag an existing file instead of pulling the audio
again. The DB gains an additive nullable cover_ok column: NULL keeps legacy
rows trusted, 1 records artwork, 0 marks a stored coverless file_id so the
caller falls through to a fresh download.

Real mutagen files are built in a temp directory (minimal FLAC/Ogg streams and
an ID3-only mp3), so the tag probes run against the real parsers. The DB tests
run on a throwaway sqlite file and never touch DB/deez_bot.db.

The last section pins the helpers.download_help cache seams: a cover_ok == 0
row is refreshed in place (its stored file_id stays servable until the
replacement upload succeeds), a NULL (legacy) or 1 row is served exactly as
before, a cooldown bounds retries for permanently coverless content, and every
upload records the presence of artwork in the delivered file itself.

Run as: .venv\\Scripts\\python -m pytest tests/test_retag_and_db.py -q
     or: .venv\\Scripts\\python tests/test_retag_and_db.py
"""

import base64
import builtins
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
import types
from contextlib import contextmanager
from types import SimpleNamespace

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))

from mutagen._vorbis import VCommentDict
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC, TXXX
from mutagen.oggvorbis import OggVorbis

from deezloader import __taggers__ as taggers
from deezloader.deezloader import __download__ as dee_dl
from deezloader.exceptions import TrackNotFound
from deezloader.spotloader import __download__ as spo_dl

# --- fixture builders (real files, real parsers) ---

def make_jpeg(width = 600, height = 600):
	sof = (
		b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" +
		struct.pack(">HH", height, width) +
		b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
	)

	return b"\xff\xd8" + sof + b"\xff\xd9"

def picture_block(image = None):
	block = Picture()
	block.type = 3
	block.mime = "image/jpeg"
	block.width = block.height = 600
	block.depth = 24
	block.data = image if image is not None else make_jpeg()

	return block

@contextmanager
def song_dir():
	directory = tempfile.mkdtemp(prefix = "t4-songs-")

	try:
		yield directory
	finally:
		shutil.rmtree(directory, ignore_errors = True)

def write_flac(song, comment_count, with_picture):
	# A header-only FLAC stream: mutagen parses and rewrites the metadata
	# blocks without needing audio frames.
	streaminfo_bits = (44100 << 44) | (1 << 41) | (15 << 36) | 1000
	streaminfo = (
		struct.pack(">HH", 4096, 4096) + b"\x00" * 6 +
		struct.pack(">Q", streaminfo_bits) + b"\x00" * 16
	)

	with open(song, "wb") as file:
		file.write(b"fLaC" + bytes([0x80, 0, 0, 34]) + streaminfo)

	tag = FLAC(song)

	for index in range(comment_count):
		tag[f"field{index}"] = f"value{index}"

	if with_picture:
		tag.add_picture(picture_block())

	tag.save()

def ogg_page(packets, flags, sequence, granule = 0):
	lacing = b""

	for packet in packets:
		quotient, remainder = divmod(len(packet), 255)
		lacing += b"\xff" * quotient + bytes([remainder])

	header = struct.pack(
		"<4sBBqIIiB", b"OggS", 0, flags, granule, 0x1234, sequence, 0, len(lacing)
	)

	return header + lacing + b"".join(packets)

def write_ogg(song, comment_count, with_picture):
	identification = (
		b"\x01vorbis" + struct.pack("<I", 0) +
		struct.pack("<BI3i", 2, 44100, 0, 0, 0) + b"\x11\x01"
	)
	comments = VCommentDict()

	for index in range(comment_count):
		comments[f"field{index}"] = f"value{index}"

	if with_picture:
		comments["metadata_block_picture"] = base64.b64encode(
			picture_block().write()
		).decode("ascii")

	with open(song, "wb") as file:
		file.write(ogg_page([identification], 2, 0))
		file.write(ogg_page([b"\x03vorbis" + comments.write()], 0, 1))
		file.write(ogg_page([b"\x05vorbis" + b"\x00" * 8], 4, 2))

def write_mp3(song, comment_count, with_picture, write_header = True):
	with open(song, "wb") as file:
		file.write(b"\x00" * 64)

	if not write_header:
		return

	tag = ID3()

	for index in range(comment_count):
		tag.add(TXXX(encoding = 3, desc = f"field{index}", text = [f"value{index}"]))

	if with_picture:
		tag.add(
			APIC(
				mime = "image/jpeg",
				type = 3,
				desc = "album front cover",
				data = make_jpeg()
			)
		)

	tag.save(song, v2_version = 3)

def track_stub(song_path, file_format):
	return SimpleNamespace(song_path = song_path, file_format = file_format)

# --- (a) the format-aware picture probe behind check_track ---

def test_flac_complete_tags_need_a_picture_block():
	with song_dir() as directory:
		covered = os.path.join(directory, "covered.flac")
		coverless = os.path.join(directory, "coverless.flac")
		short = os.path.join(directory, "short.flac")
		write_flac(covered, 15, True)
		write_flac(coverless, 15, False)
		write_flac(short, 3, True)

		assert len(FLAC(coverless).keys()) >= 14
		assert not FLAC(coverless).pictures
		assert taggers.check_track(track_stub(covered, ".flac")) is True
		assert taggers.has_complete_tags(track_stub(covered, ".flac")) is True
		assert taggers.check_track(track_stub(coverless, ".flac")) is False
		assert taggers.has_complete_tags(track_stub(coverless, ".flac")) is True
		assert taggers.check_track(track_stub(short, ".flac")) is False
		assert taggers.has_complete_tags(track_stub(short, ".flac")) is False

def test_ogg_complete_tags_need_a_picture_block():
	with song_dir() as directory:
		covered = os.path.join(directory, "covered.ogg")
		coverless = os.path.join(directory, "coverless.ogg")
		short = os.path.join(directory, "short.ogg")
		write_ogg(covered, 15, True)
		write_ogg(coverless, 15, False)
		write_ogg(short, 3, True)

		assert not OggVorbis(coverless).get("metadata_block_picture")
		assert taggers.check_track(track_stub(covered, ".ogg")) is True
		assert taggers.has_complete_tags(track_stub(covered, ".ogg")) is True
		assert taggers.check_track(track_stub(coverless, ".ogg")) is False
		assert taggers.has_complete_tags(track_stub(coverless, ".ogg")) is True
		assert taggers.check_track(track_stub(short, ".ogg")) is False
		assert taggers.has_complete_tags(track_stub(short, ".ogg")) is False

def test_mp3_complete_tags_need_an_apic_frame():
	with song_dir() as directory:
		covered = os.path.join(directory, "covered.mp3")
		coverless = os.path.join(directory, "coverless.mp3")
		short = os.path.join(directory, "short.mp3")
		write_mp3(covered, 14, True)
		write_mp3(coverless, 14, False)
		write_mp3(short, 3, True)

		assert not ID3(coverless).getall("APIC")
		assert taggers.check_track(track_stub(covered, ".mp3")) is True
		assert taggers.has_complete_tags(track_stub(covered, ".mp3")) is True
		assert taggers.check_track(track_stub(coverless, ".mp3")) is False
		assert taggers.has_complete_tags(track_stub(coverless, ".mp3")) is True
		assert taggers.check_track(track_stub(short, ".mp3")) is False
		assert taggers.has_complete_tags(track_stub(short, ".mp3")) is False

def test_mp3_without_an_id3_header_is_never_complete():
	with song_dir() as directory:
		bare = os.path.join(directory, "bare.mp3")
		write_mp3(bare, 0, False, write_header = False)

		assert taggers.check_track(track_stub(bare, ".mp3")) is False
		assert taggers.has_complete_tags(track_stub(bare, ".mp3")) is False

def test_has_picture_is_a_public_probe_and_min_complete_tags_is_fourteen():
	with song_dir() as directory:
		covered = os.path.join(directory, "covered.flac")
		coverless = os.path.join(directory, "coverless.flac")
		write_flac(covered, 15, True)
		write_flac(coverless, 15, False)

		assert taggers.MIN_COMPLETE_TAGS == 14
		# a Track-like object and a bare path both answer the same question
		assert taggers.has_picture(track_stub(covered, ".flac")) is True
		assert taggers.has_picture(covered) is True
		assert taggers.has_picture(track_stub(coverless, ".flac")) is False
		assert taggers.has_picture(coverless) is False
		# the private probe existing callers use keeps working unchanged
		assert taggers.__has_picture(FLAC(covered), ".flac") is True
		assert taggers.__has_picture(FLAC(coverless), ".flac") is False

def test_the_tag_threshold_shared_with_has_complete_tags_is_unchanged():
	with song_dir() as directory:
		for count in (3, 13, 14, 15):
			song = os.path.join(directory, f"count{count}.flac")
			write_flac(song, count, True)
			keys = len(FLAC(song).keys())

			# the answer still follows "at least MIN_COMPLETE_TAGS comments",
			# whatever the parser reports for this synthetic stream
			assert taggers.has_complete_tags(track_stub(song, ".flac")) == (
				keys >= taggers.MIN_COMPLETE_TAGS
			)

# --- (b) the re-tag-only seam in both downloaders ---

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

def no_download(*args, **kwargs):
	raise AssertionError("the audio must not be downloaded again")

def easy_dw_dee_stub(song_path, file_format):
	dw = object.__new__(dee_dl.EASY_DW)
	dw._EASY_DW__song_path = song_path
	dw._EASY_DW__file_format = file_format
	dw._EASY_DW__recursive_download = False
	dw._EASY_DW__song_metadata = {
		"music": "Probe Song", "artist": "Probe Artist", "image": b""
	}
	dw._EASY_DW__infos_dw = {
		"SNG_CONTRIBUTORS": {
			"author": ["Probe Author"],
			"composer": ["Probe Composer"],
			"lyricist": ["Probe Lyricist"],
		},
		"LYRICS_ID": 0,
		"media_url": {"media": [{"sources": [{"url": "https://probe.invalid"}]}]},
	}
	dw._EASY_DW__c_track = SimpleNamespace(
		song_path = song_path, file_format = file_format,
		tags = dw._EASY_DW__song_metadata
	)

	return dw

def test_dee_retags_a_coverless_file_without_downloading():
	with song_dir() as directory:
		song = os.path.join(directory, "coverless.flac")
		write_flac(song, 15, False)
		dw = easy_dw_dee_stub(song, ".flac")
		tagged = []

		with attr_patch(
			(dee_dl, "write_tags", lambda track: tagged.append(track)),
			(dee_dl.API_GW, "song_exist", staticmethod(no_download)),
			(dee_dl, "decryptfile", no_download),
			(builtins, "input", no_download),
		):
			result = dw.download_try()

		assert result is dw._EASY_DW__c_track
		assert tagged == [dw._EASY_DW__c_track]
		assert dw._EASY_DW__song_metadata["author"] == "Probe Author"
		assert dw._EASY_DW__song_metadata["lyric"] == ""

def test_dee_skips_a_covered_file_unchanged():
	with song_dir() as directory:
		song = os.path.join(directory, "covered.flac")
		write_flac(song, 15, True)
		dw = easy_dw_dee_stub(song, ".flac")
		dw._EASY_DW__recursive_download = True
		tagged = []

		with attr_patch(
			(dee_dl, "write_tags", lambda track: tagged.append(track)),
			(dee_dl.API_GW, "song_exist", staticmethod(no_download)),
			(dee_dl, "decryptfile", no_download),
			(builtins, "input", no_download),
		):
			result = dw.download_try()

		assert result is dw._EASY_DW__c_track
		assert tagged == []

def test_dee_prompts_before_redownloading_a_covered_file():
	with song_dir() as directory:
		song = os.path.join(directory, "covered.flac")
		write_flac(song, 15, True)
		dw = easy_dw_dee_stub(song, ".flac")
		dw._EASY_DW__recursive_download = False
		tagged = []
		visited = []

		class Reached(Exception):
			pass

		def reached(*args, **kwargs):
			visited.append(args)
			raise Reached()

		with attr_patch(
			(dee_dl, "write_tags", lambda track: tagged.append(track)),
			(dee_dl.API_GW, "song_exist", staticmethod(reached)),
			(builtins, "input", lambda prompt: "y"),
		):
			try:
				dw.download_try()
				raise AssertionError("expected the download path")
			except Reached:
				pass

		assert tagged == []
		assert visited == [("https://probe.invalid",)]

def test_dee_redownloads_a_file_with_incomplete_tags():
	with song_dir() as directory:
		song = os.path.join(directory, "short.flac")
		write_flac(song, 3, False)
		dw = easy_dw_dee_stub(song, ".flac")
		tagged = []
		visited = []

		class Reached(Exception):
			pass

		def reached(*args, **kwargs):
			visited.append(args)
			raise Reached()

		with attr_patch(
			(dee_dl, "write_tags", lambda track: tagged.append(track)),
			(dee_dl.API_GW, "song_exist", staticmethod(reached)),
			(builtins, "input", no_download),
		):
			try:
				dw.download_try()
				raise AssertionError("expected the download path")
			except Reached:
				pass

		assert tagged == []
		assert visited == [("https://probe.invalid",)]

def easy_dw_spo_stub(song_path, file_format):
	dw = object.__new__(spo_dl.EASY_DW)
	dw._EASY_DW__song_path = song_path
	dw._EASY_DW__file_format = file_format
	dw._EASY_DW__recursive_download = False
	dw._EASY_DW__ids = "probeids"
	dw._EASY_DW__dw_quality = "FLAC"
	dw._EASY_DW__song_metadata = {
		"music": "Probe Song", "artist": "Probe Artist", "image": b""
	}
	dw._EASY_DW__c_track = SimpleNamespace(
		song_path = song_path, file_format = file_format,
		tags = dw._EASY_DW__song_metadata
	)

	return dw

def test_spo_retags_a_coverless_file_without_streaming():
	with song_dir() as directory:
		song = os.path.join(directory, "coverless.ogg")
		write_ogg(song, 15, False)
		dw = easy_dw_spo_stub(song, ".ogg")
		tagged = []

		class NoStream:
			@staticmethod
			def from_base62(ids):
				no_download()

		with attr_patch(
			(spo_dl, "write_tags", lambda track: tagged.append(track)),
			(spo_dl, "TrackId", NoStream),
			(builtins, "input", no_download),
		):
			result = dw.download_try()

		assert result is dw._EASY_DW__c_track
		assert tagged == [dw._EASY_DW__c_track]

def test_spo_skips_a_covered_file_unchanged():
	with song_dir() as directory:
		song = os.path.join(directory, "covered.ogg")
		write_ogg(song, 15, True)
		dw = easy_dw_spo_stub(song, ".ogg")
		dw._EASY_DW__recursive_download = True
		tagged = []

		class NoStream:
			@staticmethod
			def from_base62(ids):
				no_download()

		with attr_patch(
			(spo_dl, "write_tags", lambda track: tagged.append(track)),
			(spo_dl, "TrackId", NoStream),
			(builtins, "input", no_download),
		):
			result = dw.download_try()

		assert result is dw._EASY_DW__c_track
		assert tagged == []

# --- (c) the additive DB cover flag ---

def db_module():
	# imported lazily so a missing or broken module reads as a test failure
	from utils import db

	return db

@contextmanager
def temp_db():
	directory = tempfile.mkdtemp(prefix = "t4-db-")
	db = db_module()
	previous = db.db_name
	db.db_name = os.path.join(directory, "deez_bot.db")

	try:
		yield db
	finally:
		db.db_name = previous
		shutil.rmtree(directory, ignore_errors = True)

def count_rows(db, link):
	connection = sqlite3.connect(db.db_name)

	try:
		return connection.execute(
			"SELECT COUNT(*) FROM dwsongs WHERE link = ?",
			(link, )
		).fetchone()[0]
	finally:
		connection.close()

def age_cover_attempt(db, link, quality, method_save, seconds):
	# Move a row's last refresh attempt into the past, so the cooldown is
	# already over when the helper reads it.
	connection = sqlite3.connect(db.db_name)

	try:
		connection.execute(
			"UPDATE dwsongs SET cover_attempted_at = ? \
			WHERE link = ? AND quality = ? AND method_save = ?",
			(time.time() - seconds, link, quality, method_save)
		)
		connection.commit()
	finally:
		connection.close()

def legacy_db(song_db):
	# A pre-flag database: the dwsongs table without the cover_ok column.
	# The connection is closed explicitly: sqlite3's context manager only
	# commits, and an open handle keeps Windows from deleting the temp dir.
	connection = sqlite3.connect(song_db)

	try:
		connection.execute(
			"CREATE TABLE dwsongs(\
			id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, \
			link VARCHAR(255) NOT NULL, \
			file_id VARCHAR(255) UNIQUE NOT NULL, \
			quality VARCHAR(5) NOT NULL, \
			date DATE DEFAULT (datetime('now', 'localtime')), \
			chat_id INT NOT NULL, \
			method_save INT NOT NULL, \
			UNIQUE(link, quality, method_save))"
		)
		connection.execute(
			"INSERT INTO dwsongs(link, file_id, quality, chat_id, method_save) VALUES (?, ?, ?, ?, ?)",
			("deezer.com/track/1", "legacy_file_id", "FLAC", 1, 3)
		)
		connection.commit()
	finally:
		connection.close()

def test_legacy_rows_stay_trusted_after_the_migration():
	with temp_db() as db:
		legacy_db(db.db_name)
		db.initialize_db()

		assert db.select_dwsongs("deezer.com/track/1", "FLAC", 3) == ("legacy_file_id", None, None)

def test_write_db_keeps_its_existing_signature():
	with temp_db() as db:
		db.initialize_db()
		db.write_db("deezer.com/track/2", "new_file_id", "FLAC", 1, 3)

		assert db.select_dwsongs("deezer.com/track/2", "FLAC", 3) == ("new_file_id", None, None)

def test_cover_flag_round_trips():
	with temp_db() as db:
		db.initialize_db()
		db.write_db("deezer.com/track/3", "covered", "FLAC", 1, 3, cover_ok = 1)
		db.write_db("deezer.com/album/4", "coverless", "FLAC", 1, 3, cover_ok = 0)

		assert db.select_dwsongs("deezer.com/track/3", "FLAC", 3) == ("covered", 1, None)

		coverless = db.select_dwsongs("deezer.com/album/4", "FLAC", 3)

		assert coverless[:2] == ("coverless", 0)
		# a coverless write stamps the attempt so the caller can cool down
		assert isinstance(coverless[2], float)

def test_a_deleted_coverless_row_is_not_served_again():
	with temp_db() as db:
		db.initialize_db()
		db.write_db("deezer.com/track/5", "coverless", "FLAC", 1, 3, cover_ok = 0)
		match = db.select_dwsongs("deezer.com/track/5", "FLAC", 3)

		assert match[0] == "coverless"
		assert match[1] == 0
		db.delete_dwsongs(match[0])
		assert db.select_dwsongs("deezer.com/track/5", "FLAC", 3) is None

def test_a_second_write_lands_the_newest_file_id():
	with temp_db() as db:
		db.initialize_db()
		db.write_db("deezer.com/track/6", "first_id", "FLAC", 1, 3)
		db.write_db("deezer.com/track/6", "second_id", "FLAC", 1, 3)

		# an atomic replace: the key owns exactly one row, the newest upload
		assert db.select_dwsongs("deezer.com/track/6", "FLAC", 3) == ("second_id", None, None)
		assert count_rows(db, "deezer.com/track/6") == 1

def test_a_failed_duplicate_write_keeps_the_servable_row():
	with temp_db() as db:
		db.initialize_db()
		db.write_db("deezer.com/track/8", "kept_id", "FLAC", 1, 3)

		# file_id is UNIQUE, so this insert fails: the transaction must roll
		# back instead of committing the second key's delete
		db.write_db("deezer.com/track/9", "kept_id", "FLAC", 1, 3)

		assert db.select_dwsongs("deezer.com/track/8", "FLAC", 3) == ("kept_id", None, None)
		assert db.select_dwsongs("deezer.com/track/9", "FLAC", 3) is None

def test_schema_init_is_idempotent():
	with temp_db() as db:
		db.initialize_db()
		db.write_db("deezer.com/track/7", "kept_id", "FLAC", 1, 3, cover_ok = 1)
		db.initialize_db()

		connection = sqlite3.connect(db.db_name)

		try:
			columns = [
				column[1]
				for column in connection.execute("PRAGMA table_info(dwsongs)")
			]
		finally:
			connection.close()

		assert columns[-2:] == ["cover_ok", "cover_attempted_at"]
		assert columns.count("cover_ok") == 1
		assert columns.count("cover_attempted_at") == 1
		assert db.select_dwsongs("deezer.com/track/7", "FLAC", 3) == ("kept_id", 1, None)

def test_both_cover_columns_migrate_idempotently_over_a_legacy_row():
	with temp_db() as db:
		legacy_db(db.db_name)
		db.initialize_db()
		db.initialize_db()

		connection = sqlite3.connect(db.db_name)

		try:
			columns = [
				column[1]
				for column in connection.execute("PRAGMA table_info(dwsongs)")
			]
			rows = connection.execute(
				"SELECT file_id, cover_ok, cover_attempted_at FROM dwsongs"
			).fetchall()
		finally:
			connection.close()

		assert columns[-2:] == ["cover_ok", "cover_attempted_at"]
		assert columns.count("cover_attempted_at") == 1
		# the migration never rewrites a stored row
		assert rows == [("legacy_file_id", None, None)]

# --- (d) the helpers.download_help cache seams ---
#
# helpers.download_help pulls python-telegram-bot 13.x, whose urllib3 shim no
# longer imports on Python 3.12, so the bot-stack modules are stubbed before
# the helper loads. The bot image runs 3.11 (S8 is the live proof); everything
# asserted here is the plain sqlite + dispatch behaviour.

def stub_module(name, **attributes):
	"""Register a stand-in module so the bot-stack imports resolve."""
	module = types.ModuleType(name)

	for attribute, value in attributes.items():
		setattr(module, attribute, value)

	# the bot's settings and copy tables carry dozens of names these tests
	# never read, so any unset one resolves to an empty string
	module.__getattr__ = lambda attribute: ""

	sys.modules[name] = module

	return module

class RecordingBot:
	"""Stands in for the two Telegram clients; records every call."""

	def __init__(self):
		self.calls = []

	def __getattr__(self, name):
		def recorder(*args, **kwargs):
			self.calls.append((name, args, kwargs))

			return SimpleNamespace(
				message_id = 1,
				audio = SimpleNamespace(file_id = "audio_id"),
				document = SimpleNamespace(file_id = "document_id")
			)

		return recorder

# logging_bot() builds a FileHandler per configured logger at import time; the
# null device keeps those four loggers (and these tests) out of the tree
_DH_LOGGER_NAMES = [
	(f"t4.{logger_name}", 20, os.devnull)
	for logger_name in ("telegram", "uploads", "downloads", "links")
]

stub_module(
	"telegram",
	ChatAction = SimpleNamespace(UPLOAD_AUDIO = "upload_audio", UPLOAD_DOCUMENT = "upload_document"),
	InlineKeyboardMarkup = object, InlineKeyboardButton = object
)
stub_module("telegram.error", BadRequest = type("BadRequest", (Exception, ), {}))
stub_module("configs").__path__ = []
stub_module(
	"configs.bot_settings",
	output_songs = "Songs/", supported_link = [], output_shazam = "Shazam/",
	logs_path = os.devnull,
	logger_names = _DH_LOGGER_NAMES,
	log_uploads = os.devnull,
	log_downloads = os.devnull,
	db_name = ":memory:", method_save = 3,
	bunker_channel = "bunker",
	seconds_limits_album = 1, seconds_limits_track = 1,
	max_song_per_playlist = 10,
	recursive_quality = True, recursive_download = True,
	upload_max_size_user = 1, user_errors = "errors",
	progress_status_rate = 1, is_thread = False, user_session = "session",
	# deezloader.easy_spoty reads these at import time; empty values make
	# spotipy refuse to build its credentials manager
	spotify_client_id = "probe_client", spotify_client_secret = "probe_secret",
	spotify_cache_file = os.devnull
)
stub_module(
	"configs.customs",
	send_image_track_query = "%s %s %s %s",
	send_image_album_query = "%s %s %s %s",
	send_image_artist_query = "%s %s %s",
	send_image_playlist_query = "%s %s %s %s",
	album_too_long = "album too long", track_too_long = "track too long",
	bot_settings_config = [], commands_queries = {},
	artist_commands_queries = {}, inline_textes = {}, empty_image_url = ""
)
stub_module(
	"configs.set_configs",
	SetConfigs = type(
		"SetConfigs", (), {
			"tg_bot_api": SimpleNamespace(bot = RecordingBot()),
			"tg_user_api": SimpleNamespace(),
			"deez_api": None, "spot_api": None, "create_zips": True,
			"queues_started": 0, "queues_finished": 0
		}
	)
)
# the real module renders whole keyboards from the customs tables; the cache
# seams only need the one factory download_help imports
stub_module("inlines.inline_keyboards", create_keyboard_artist = lambda link: None)

# utils.utils binds logger_names at its own import time: when another test file
# loaded it first, it still holds that file's empty list
if "utils.utils" in sys.modules:
	_utils_module = sys.modules["utils.utils"]
	_utils_module.logger_names = _DH_LOGGER_NAMES
	_utils_module.output_songs = "Songs/"

from helpers import download_help

def download_helper_stub(quality = "FLAC", method_save = 3, tracks = False, zips = False, source = 1):
	dw = object.__new__(download_help.DW)
	dw._DW__chat_id = 1
	dw._DW__source = source
	dw._DW__quality = quality
	dw._DW__n_quality = download_help.get_quality_dee_s_quality(quality)
	dw._DW__send_to_user_tracks = tracks
	dw._DW__send_to_user_zips = zips
	dw._DW__hash_link = 0
	dw._DW__c_download = {}
	dw._DW__method_save = method_save
	dw._DW__conv = False

	return dw

def check_track_seams(dw, link):
	"""Run __check_track with both branches replaced by recorders."""
	served = []
	downloaded = []

	with attr_patch(
		(download_help.DW, "_DW__upload_audio", lambda self, file_id: served.append(file_id)),
		(download_help.DW, "_DW__download_track", landed_recorder(downloaded)),
	):
		dw._DW__check_track(link)

	return served, downloaded

def landed_recorder(target):
	"""A download stub that reports a landed replacement (the delivery signal)."""

	def recorder(self, link, cover_fallback_url = None):
		target.append(link)

		return True

	return recorder

def test_check_track_serves_a_coverless_row_inside_the_cooldown():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/105", "recent_file_id", quality, 1, 3, cover_ok = 0)
		match = db.select_dwsongs("track/105", quality, 3)

		# write_db stamps the attempt, so a fresh coverless row cools down
		assert isinstance(match[2], float)

		served, downloaded = check_track_seams(
			download_helper_stub(), "https://www.deezer.com/track/105"
		)

		assert served == ["recent_file_id"]
		assert downloaded == []
		assert db.select_dwsongs("track/105", quality, 3) == match

def test_check_track_recovers_a_coverless_row_once_the_cooldown_expires():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/106", "stale_file_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "track/106", quality, 3, 7200)
		served, downloaded = check_track_seams(
			download_helper_stub(), "https://www.deezer.com/track/106"
		)

		assert downloaded == ["https://www.deezer.com/track/106"]
		assert served == []
		# soft invalidation: the cache row is not deleted before recovery
		assert db.select_dwsongs("track/106", quality, 3)[:2] == ("stale_file_id", 0)

def test_a_failed_track_recovery_serves_the_cached_file_id():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/107", "servable_file_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "track/107", quality, 3, 7200)
		dw = download_helper_stub()
		attempted = []
		served = []

		def refused(self, link, cover_fallback_url = None):
			attempted.append(link)
			raise RuntimeError("cover sources refused")

		with attr_patch(
			(download_help.DW, "_DW__upload_audio", lambda self, file_id: served.append(file_id)),
			(download_help.DW, "_DW__download_track", refused),
		):
			dw._DW__check_track("https://www.deezer.com/track/107")

		assert attempted == ["https://www.deezer.com/track/107"]
		assert served == ["servable_file_id"]
		assert db.select_dwsongs("track/107", quality, 3)[:2] == ("servable_file_id", 0)

def test_a_badrequest_after_a_failed_recovery_deletes_and_downloads():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/108", "dead_file_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "track/108", quality, 3, 7200)
		dw = download_helper_stub()
		downloads = []
		dead = []

		def download(self, link, cover_fallback_url = None):
			downloads.append(link)

			if len(downloads) == 1:
				raise RuntimeError("cover sources refused")

			db.write_db("track/108", "fresh_file_id", quality, 1, 3, cover_ok = 1)

			return True

		def gone(self, file_id):
			dead.append(file_id)
			raise download_help.BadRequest("file_id invalid")

		with attr_patch(
			(download_help.DW, "_DW__upload_audio", gone),
			(download_help.DW, "_DW__download_track", download),
		):
			dw._DW__check_track("https://www.deezer.com/track/108")

		# baseline semantics kept: a file_id dies only after Telegram proved it
		assert dead == ["dead_file_id"]
		assert downloads == [
			"https://www.deezer.com/track/108",
			"https://www.deezer.com/track/108"
		]
		assert db.select_dwsongs("track/108", quality, 3) == ("fresh_file_id", 1, None)

def test_a_successful_track_recovery_replaces_the_row():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/109", "stale_file_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "track/109", quality, 3, 7200)
		dw = download_helper_stub()
		served = []
		downloads = []

		def download(self, link, cover_fallback_url = None):
			downloads.append(link)
			db.write_db("track/109", "recovered_file_id", quality, 1, 3, cover_ok = 1)

			return True

		with attr_patch(
			(download_help.DW, "_DW__upload_audio", lambda self, file_id: served.append(file_id)),
			(download_help.DW, "_DW__download_track", download),
		):
			dw._DW__check_track("https://www.deezer.com/track/109")

		assert downloads == ["https://www.deezer.com/track/109"]
		# the recovery upload wrote the row itself: serve nothing extra
		assert served == []
		assert db.select_dwsongs("track/109", quality, 3) == ("recovered_file_id", 1, None)
		assert count_rows(db, "track/109") == 1

def test_check_track_serves_a_legacy_null_row_unchanged():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/102", "legacy_file_id", quality, 1, 3)
		served, downloaded = check_track_seams(
			download_helper_stub(), "https://www.deezer.com/track/102"
		)

		assert served == ["legacy_file_id"]
		assert downloaded == []
		assert db.select_dwsongs("track/102", quality, 3) == ("legacy_file_id", None, None)

def test_check_track_serves_a_covered_row_unchanged():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/103", "covered_file_id", quality, 1, 3, cover_ok = 1)
		served, downloaded = check_track_seams(
			download_helper_stub(), "https://www.deezer.com/track/103"
		)

		assert served == ["covered_file_id"]
		assert downloaded == []
		assert db.select_dwsongs("track/103", quality, 3) == ("covered_file_id", 1, None)

def test_check_track_keeps_the_stale_file_id_recovery():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/104", "gone_file_id", quality, 1, 3, cover_ok = 1)
		dw = download_helper_stub()
		attempted = []
		downloaded = []

		def gone(self, file_id):
			attempted.append(file_id)
			raise download_help.BadRequest("file_id invalid")

		with attr_patch(
			(download_help.DW, "_DW__upload_audio", gone),
			(
				download_help.DW, "_DW__download_track",
				lambda self, c_link, cover_fallback_url = None: downloaded.append(c_link)
			),
		):
			dw._DW__check_track("https://www.deezer.com/track/104")

		assert attempted == ["gone_file_id"]
		assert downloaded == ["https://www.deezer.com/track/104"]
		assert db.select_dwsongs("track/104", quality, 3) is None

def test_check_album_recovers_a_coverless_zip_once_the_cooldown_expires():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/201", "stale_zip_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "album/201", quality, 3, 7200)
		dw = download_helper_stub()
		served = []
		downloaded = []

		with attr_patch(
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: served.append(file_id)),
			(download_help.DW, "_DW__download_album", landed_recorder(downloaded)),
		):
			dw._DW__check_album("https://www.deezer.com/album/201", [])

		assert downloaded == ["https://www.deezer.com/album/201"]
		assert served == []
		assert db.select_dwsongs("album/201", quality, 3)[:2] == ("stale_zip_id", 0)

def test_check_album_serves_a_coverless_zip_inside_the_cooldown():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/205", "recent_zip_id", quality, 1, 3, cover_ok = 0)
		dw = download_helper_stub()
		served = []
		downloaded = []

		with attr_patch(
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: served.append(file_id)),
			(
				download_help.DW, "_DW__download_album",
				lambda self, link, cover_fallback_url = None: downloaded.append(link)
			),
		):
			dw._DW__check_album("https://www.deezer.com/album/205", [])

		assert served == ["recent_zip_id"]
		assert downloaded == []

def test_a_failed_album_recovery_serves_the_cached_zip():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/206", "servable_zip_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "album/206", quality, 3, 7200)
		dw = download_helper_stub()
		served = []
		attempted = []

		def refused(self, link, cover_fallback_url = None):
			attempted.append(link)
			raise RuntimeError("cover sources refused")

		with attr_patch(
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: served.append(file_id)),
			(download_help.DW, "_DW__download_album", refused),
		):
			dw._DW__check_album("https://www.deezer.com/album/206", [])

		assert attempted == ["https://www.deezer.com/album/206"]
		assert served == ["servable_zip_id"]
		assert db.select_dwsongs("album/206", quality, 3)[:2] == ("servable_zip_id", 0)

def test_check_album_serves_a_legacy_null_row_unchanged():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/202", "legacy_zip_id", quality, 1, 3)
		dw = download_helper_stub()
		served = []
		downloaded = []

		with attr_patch(
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: served.append(file_id)),
			(
				download_help.DW, "_DW__download_album",
				lambda self, link, cover_fallback_url = None: downloaded.append(link)
			),
		):
			dw._DW__check_album("https://www.deezer.com/album/202", [])

		assert served == ["legacy_zip_id"]
		assert downloaded == []
		assert db.select_dwsongs("album/202", quality, 3) == ("legacy_zip_id", None, None)

def test_check_album_recovers_a_coverless_track_once_the_cooldown_expires():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/303", "album_zip_id", quality, 1, 3, cover_ok = 1)
		db.write_db("track/306", "stale_track_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "track/306", quality, 3, 7200)
		dw = download_helper_stub(tracks = True)
		zips = []
		audio = []
		recovered = []

		with attr_patch(
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: zips.append(file_id)),
			(download_help.DW, "_DW__upload_audio", lambda self, file_id: audio.append(file_id)),
			(
				download_help.DW, "_DW__check_track",
				landed_recorder(recovered)
			),
		):
			dw._DW__check_album(
				"https://www.deezer.com/album/303",
				[{"link": "https://www.deezer.com/track/306"}]
			)

		assert zips == ["album_zip_id"]
		assert audio == []
		assert recovered == ["https://www.deezer.com/track/306"]
		# soft invalidation applies to the per-track row too: no delete first
		assert db.select_dwsongs("track/306", quality, 3)[:2] == ("stale_track_id", 0)

def test_check_album_serves_a_coverless_track_inside_the_cooldown():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/307", "album_zip_id", quality, 1, 3, cover_ok = 1)
		db.write_db("track/308", "recent_track_id", quality, 1, 3, cover_ok = 0)
		dw = download_helper_stub(tracks = True)
		audio = []
		recovered = []

		with attr_patch(
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: None),
			(download_help.DW, "_DW__upload_audio", lambda self, file_id: audio.append(file_id)),
			(
				download_help.DW, "_DW__check_track",
				lambda self, link, cover_fallback_url = None: recovered.append(link)
			),
		):
			dw._DW__check_album(
				"https://www.deezer.com/album/307",
				[{"link": "https://www.deezer.com/track/308"}]
			)

		assert audio == ["recent_track_id"]
		assert recovered == []

def test_an_album_zip_refresh_does_not_upload_the_tracks_again():
	# baseline downloaded the whole album for a coverless zip row and skipped
	# the per-track loop; the soft refresh keeps that exactly
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/309", "stale_zip_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "album/309", quality, 3, 7200)
		db.write_db("track/310", "cached_track_id", quality, 1, 3, cover_ok = 1)
		dw = download_helper_stub(tracks = True)
		audio = []
		recovered = []
		downloaded = []

		with attr_patch(
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: None),
			(download_help.DW, "_DW__upload_audio", lambda self, file_id: audio.append(file_id)),
			(
				download_help.DW, "_DW__download_album",
				landed_recorder(downloaded)
			),
			(
				download_help.DW, "_DW__check_track",
				lambda self, link, cover_fallback_url = None: recovered.append(link)
			),
		):
			dw._DW__check_album(
				"https://www.deezer.com/album/309",
				[{"link": "https://www.deezer.com/track/310"}]
			)

		assert downloaded == ["https://www.deezer.com/album/309"]
		assert audio == []
		assert recovered == []

def track_for_upload(directory, image, with_picture = True, readable = True):
	song_path = os.path.join(directory, "upload.flac")

	if readable:
		write_flac(song_path, 15, with_picture)
	else:
		with open(song_path, "wb") as song:
			song.write(b"\x00" * 64)

	tags = {
		"album": "Probe Album", "artist": "Probe Artist",
		"music": "Probe Song", "discnum": 1, "tracknum": 1,
		"image": image
	}

	return SimpleNamespace(
		song_path = song_path, track_md5 = "upload_md5", md5_image = "upload_img",
		duration = 1, artist = "Probe Artist", music = "Probe Song",
		file_format = ".flac", tags = tags, quality = "FLAC",
		link = "https://www.deezer.com/track/1", song_name = "Probe Song - Probe Artist"
	)

def upload_track(track, uploaded_id = "uploaded_audio_id", thumb_data = b"\xff\xd8\xff\xd9"):
	dw = download_helper_stub()
	tg_user_api = SimpleNamespace(
		send_audio = lambda **kwargs: SimpleNamespace(audio = SimpleNamespace(file_id = uploaded_id))
	)

	with attr_patch(
		(download_help, "fetch_thumb", lambda *args, **kwargs: SimpleNamespace(data = thumb_data)),
		(download_help, "bot", RecordingBot()),
		(download_help, "SetConfigs", SimpleNamespace(tg_user_api = tg_user_api, create_zips = True)),
		(download_help, "sleep", lambda seconds: None),
	):
		dw._DW__upload_audio_track(track)

def test_a_covered_file_records_cover_ok_one_even_when_the_fetch_fails():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with song_dir() as directory:
		with temp_db() as db:
			db.initialize_db()
			# the delivered file carries the picture; the CDN answered nothing
			upload_track(
				track_for_upload(directory, b"", with_picture = True),
				thumb_data = b""
			)

			assert db.select_dwsongs("upload_md5", quality, 3) == ("uploaded_audio_id", 1, None)

def test_a_coverless_file_records_cover_ok_zero_even_when_the_fetch_succeeds():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with song_dir() as directory:
		with temp_db() as db:
			db.initialize_db()
			# a fetched cover does not make the delivered file covered
			upload_track(
				track_for_upload(directory, make_jpeg(), with_picture = False),
				thumb_data = make_jpeg()
			)
			match = db.select_dwsongs("upload_md5", quality, 3)

			assert match[:2] == ("uploaded_audio_id", 0)
			assert isinstance(match[2], float)

def test_an_unreadable_file_records_cover_ok_zero():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with song_dir() as directory:
		with temp_db() as db:
			db.initialize_db()
			# the presence probe must not abort an upload it cannot read
			upload_track(
				track_for_upload(directory, make_jpeg(), readable = False)
			)

			assert db.select_dwsongs("upload_md5", quality, 3)[:2] == ("uploaded_audio_id", 0)

def album_for_upload(directory, image):
	zip_path = os.path.join(directory, "album.zip")

	with open(zip_path, "wb") as archive:
		archive.write(b"\x00" * 64)

	return SimpleNamespace(
		album_name = "Probe Album", md5_image = "album_img", upc = None,
		zip_path = zip_path, album_md5 = "upload_album_md5",
		tracks = [SimpleNamespace(quality = "FLAC")], image = image
	)

def upload_album(album, uploaded_id = "uploaded_zip_id", zip_size = None):
	dw = download_helper_stub()
	tg_user_api = SimpleNamespace(
		send_document = lambda **kwargs: SimpleNamespace(document = SimpleNamespace(file_id = uploaded_id))
	)
	patches = [
		(download_help, "fetch_thumb", lambda *args, **kwargs: SimpleNamespace(data = b"\xff\xd8\xff\xd9")),
		(download_help, "bot", RecordingBot()),
		(download_help, "SetConfigs", SimpleNamespace(tg_user_api = tg_user_api, create_zips = True)),
		(download_help, "sleep", lambda seconds: None),
	]

	if zip_size is not None:
		patches.append((download_help, "get_size", lambda path, size: zip_size))

	with attr_patch(*patches):
		return dw._DW__upload_zip_album(album)

def test_an_album_zip_with_artwork_records_cover_ok_one():
	with song_dir() as directory:
		with temp_db() as db:
			db.initialize_db()
			upload_album(album_for_upload(directory, make_jpeg()))

			assert db.select_dwsongs("upload_album_md5", "FLAC", 3) == ("uploaded_zip_id", 1, None)

def test_an_album_zip_without_artwork_records_cover_ok_zero():
	with song_dir() as directory:
		with temp_db() as db:
			db.initialize_db()
			upload_album(album_for_upload(directory, None))

			assert db.select_dwsongs("upload_album_md5", "FLAC", 3)[:2] == ("uploaded_zip_id", 0)

def test_a_too_big_album_stays_legacy_trusted():
	with song_dir() as directory:
		with temp_db() as db:
			db.initialize_db()
			upload_album(album_for_upload(directory, make_jpeg()), zip_size = 99.0)

			assert db.select_dwsongs("upload_album_md5", "FLAC", 3) == ("TOO BIG", None, None)

def test_db_help_startup_still_creates_every_table():
	# utils.utils starts the bot through helpers.db_help.initialize_db, which
	# now re-exports utils.db: the whole schema has to come along, whichever
	# module the dwsongs layer lives in
	from helpers import db_help

	with temp_db() as db, attr_patch((db_help, "db_name", db.db_name)):
		db_help.initialize_db()
		connection = sqlite3.connect(db.db_name)

		try:
			tables = {
				row[0]
				for row in connection.execute(
					"SELECT name FROM sqlite_master WHERE type = 'table'"
				)
			}
		finally:
			connection.close()

	assert {"dwsongs", "users_settings", "banned"} <= tables

def raw_row(db, link):
	# Every column, so a rolled-back write is proven byte-identical.
	connection = sqlite3.connect(db.db_name)

	try:
		return connection.execute(
			"SELECT id, link, file_id, quality, date, chat_id, method_save, cover_ok, cover_attempted_at \
			FROM dwsongs WHERE link = ?",
			(link, )
		).fetchone()
	finally:
		connection.close()

def test_a_swallowed_tracknotfound_recovery_still_serves_the_cached_file_id():
	# The blocker: a catalog-removed track makes __download_track swallow
	# TrackNotFound and deliver nothing. A recovery that delivers nothing is a
	# FAILED recovery, so the still-servable cached file_id must be served --
	# exactly what the pre-feature baseline did.
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("track/110", "servable_file_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "track/110", quality, 3, 7200)
		dw = download_helper_stub()
		served = []
		attempted = []

		def removed(url, **kwargs):
			attempted.append(url)
			raise TrackNotFound(url)

		deez_api = SimpleNamespace(download_trackdee = removed)

		with attr_patch(
			(download_help, "SetConfigs", SimpleNamespace(deez_api = deez_api)),
			(download_help.DW, "_DW__upload_audio", lambda self, file_id: served.append(file_id)),
		):
			dw._DW__check_track("https://www.deezer.com/track/110")

		assert attempted == ["https://www.deezer.com/track/110"]
		assert served == ["servable_file_id"]
		assert db.select_dwsongs("track/110", quality, 3)[:2] == ("servable_file_id", 0)

def test_a_failed_per_track_refresh_inside_an_album_serves_the_track_once():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()
		db.write_db("album/900", "zip_id", quality, 1, 3, cover_ok = 0)
		db.write_db("track/901", "track_id", quality, 1, 3, cover_ok = 0)
		age_cover_attempt(db, "album/900", quality, 3, 7200)
		age_cover_attempt(db, "track/901", quality, 3, 7200)
		dw = download_helper_stub(tracks = True)
		served = []

		def refused(self, link, cover_fallback_url = None):
			return False

		with attr_patch(
			(download_help.DW, "_DW__upload_audio", lambda self, file_id: served.append(file_id)),
			(download_help.DW, "_DW__upload_zip", lambda self, file_id: served.append(file_id)),
			(download_help.DW, "_DW__download_track", refused),
			(download_help.DW, "_DW__download_album", refused),
		):
			dw._DW__check_album(
				"https://www.deezer.com/album/900",
				[{"link": "https://www.deezer.com/track/901"}]
			)

		# the nested per-track guard must not re-serve what the inner
		# __check_track already delivered when its recovery failed
		assert served.count("track_id") == 1
		assert served.count("zip_id") == 1

def test_the_cooldown_boundary_is_exactly_one_hour():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with temp_db() as db:
		db.initialize_db()

		for age, refreshes in ((3599, False), (3600, True), (3601, True)):
			link_key = f"track/{1200 + age}"
			cached_id = f"cached_{age}"
			db.write_db(link_key, cached_id, quality, 1, 3, cover_ok = 0)
			age_cover_attempt(db, link_key, quality, 3, age)
			dw = download_helper_stub()
			served = []
			downloaded = []
			deezer_link = f"https://www.deezer.com/{link_key}"

			with attr_patch(
				(download_help.DW, "_DW__upload_audio", lambda self, file_id: served.append(file_id)),
				(download_help.DW, "_DW__download_track", landed_recorder(downloaded)),
			):
				dw._DW__check_track(deezer_link)

			if refreshes:
				# 3600 s and beyond: the cooldown is over, the refresh runs
				assert downloaded == [deezer_link]
				assert served == []
			else:
				# still inside the hour: the cached upload is served as-is
				assert downloaded == []
				assert served == [cached_id]

			assert db.select_dwsongs(link_key, quality, 3)[:2] == (cached_id, 0)

def test_a_failed_insert_rolls_back_an_executed_delete():
	# write_db's atomic replace deletes this key's row before inserting the
	# new one. When the INSERT then violates UNIQUE(file_id), the already
	# executed DELETE has to roll back with it.
	with temp_db() as db:
		db.initialize_db()
		db.write_db("deezer.com/track/12", "orig_id", "FLAC", 1, 3, cover_ok = 0)
		db.write_db("deezer.com/track/13", "dup_id", "FLAC", 1, 3, cover_ok = 1)
		before = raw_row(db, "deezer.com/track/12")
		other = raw_row(db, "deezer.com/track/13")

		assert before is not None
		assert before[2] == "orig_id"

		# same key (link, quality, method_save) -> the DELETE matches, then the
		# INSERT collides with the other row's file_id
		db.write_db("deezer.com/track/12", "dup_id", "FLAC", 9, 3, cover_ok = 0)

		assert raw_row(db, "deezer.com/track/12") == before
		assert raw_row(db, "deezer.com/track/13") == other

def test_a_zip_that_never_landed_keeps_the_cached_zip_servable():
	quality = download_help.get_quality_dee_s_quality("FLAC")

	with song_dir() as directory:
		with temp_db() as db:
			db.initialize_db()
			# a TOO BIG zip uploads nothing at all: no delivery signal
			assert upload_album(
				album_for_upload(directory, make_jpeg()), zip_size = 99.0
			) is False

			db.write_db("album/211", "servable_zip_id", quality, 1, 3, cover_ok = 0)
			age_cover_attempt(db, "album/211", quality, 3, 7200)
			dw = download_helper_stub()
			served = []
			attempted = []

			def no_delivery(self, link, cover_fallback_url = None):
				attempted.append(link)

				return False

			with attr_patch(
				(download_help.DW, "_DW__upload_zip", lambda self, file_id: served.append(file_id)),
				(download_help.DW, "_DW__download_album", no_delivery),
			):
				dw._DW__check_album("https://www.deezer.com/album/211", [])

			assert attempted == ["https://www.deezer.com/album/211"]
			assert served == ["servable_zip_id"]
			assert db.select_dwsongs("album/211", quality, 3)[:2] == ("servable_zip_id", 0)

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