#!/usr/bin/python3

"""Cover-art block tests for deezloader.__taggers__.

The ogg/flac writers build a FLAC picture block by hand. Without an explicit
mime type and dimensions the block is invalid, players ignore the artwork and
the file looks coverless even though the bytes are there. These tests pin the
block contents for the formats the bot actually produces.

Run as: python -m pytest tests/test_taggers_cover.py -q
     or: python tests/test_taggers_cover.py
"""

import base64
import datetime
import os
import struct
import sys

try:
	from pytest import raises as _pytest_raises
except ImportError:
	from contextlib import contextmanager

	@contextmanager
	def _pytest_raises(expected):
		try:
			yield
		except expected:
			return

		raise AssertionError(f"{expected.__name__} was not raised")

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))

from deezloader import __taggers__ as taggers
from mutagen.flac import Picture

def make_jpeg(width, height):
	# SOI, SOF0 with the given dimensions, EOI. Enough for the header probe.
	sof = (
		b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" +
		struct.pack(">HH", height, width) +
		b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
	)

	return b"\xff\xd8" + sof + b"\xff\xd9"

def make_png(width, height):
	ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"

	return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr

def picture_block(image):
	return getattr(taggers, "__picture_block")(image)

def track_stub(image, file_format):
	"""Minimal Track carrying every tag the writers touch."""

	metadata = {
		"image": image, "artist": "Probe Artist", "music": "Probe Song",
		"year": datetime.datetime(2024, 1, 2), "album": "Probe Album",
		"tracknum": 1, "discnum": 1, "genre": "Test", "ar_album": "Probe Artist",
		"bpm": 120, "duration": 60, "label": "Probe", "isrc": "ISRC00000000",
		"lyric": "", "lyric_sync": [], "author": "a", "composer": "c",
		"copyright": "", "lyricist": "", "version": "", "nb_tracks": 1,
		"gain": 0,
	}

	class Stub:
		pass

	track = Stub()
	track.song_path = "/tmp/does-not-matter"
	track.file_format = file_format
	track.tags = metadata

	for key, value in metadata.items():
		setattr(track, key, value)

	return track

def test_jpeg_block_carries_mime_and_dimensions():
	image = make_jpeg(640, 480)
	block = picture_block(image)
	picture = Picture(block.write())

	assert picture.mime == "image/jpeg"
	assert (picture.width, picture.height) == (640, 480)
	assert picture.type == 3
	assert picture.data == image

def test_png_block_is_recognised():
	image = make_png(300, 300)
	block = picture_block(image)
	picture = Picture(block.write())

	assert picture.mime == "image/png"
	assert (picture.width, picture.height) == (300, 300)
	assert picture.data == image

def test_unknown_image_still_produces_a_block():
	image = b"\x00\x01\x02\x03"
	block = picture_block(image)
	picture = Picture(block.write())

	assert picture.mime == "application/octet-stream"
	assert (picture.width, picture.height) == (0, 0)
	assert picture.data == image

def test_gif_and_webp_are_recognised_without_dimensions():
	gif = b"GIF89a" + b"\x00" * 20
	webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 20

	assert Picture(picture_block(gif).write()).mime == "image/gif"
	assert Picture(picture_block(webp).write()).mime == "image/webp"
	assert (Picture(picture_block(gif).write()).width, Picture(picture_block(gif).write()).height) == (0, 0)

def test_png_depth_follows_the_colour_type():
	# make_png writes colour type 6 (RGBA), so 4 channels at 8 bits.
	picture = Picture(picture_block(make_png(64, 64)).write())

	assert picture.depth == 32

def test_jpeg_depth_is_24():
	picture = Picture(picture_block(make_jpeg(64, 64)).write())

	assert picture.depth == 24

def test_unknown_image_depth_is_zero():
	picture = Picture(picture_block(b"\x00\x01").write())

	assert picture.depth == 0

def test_jpeg_fill_bytes_before_the_frame_header():
	app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
	sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", 720, 1280) + b"\x01\x01\x11\x00"
	image = b"\xff\xd8" + app0 + b"\xff\xff\xff" + sof + b"\xff\xd9"
	picture = Picture(picture_block(image).write())

	assert (picture.width, picture.height) == (1280, 720)

def test_jpeg_restart_marker_before_the_frame_header():
	# 0xD0 is a standalone marker with no length field.
	sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", 500, 500) + b"\x01\x01\x11\x00"
	image = b"\xff\xd8" + b"\xff\xd0" + sof + b"\xff\xd9"
	picture = Picture(picture_block(image).write())

	assert (picture.width, picture.height) == (500, 500)

def test_truncated_jpeg_does_not_raise():
	picture = Picture(picture_block(b"\xff\xd8\xff\xc0\x00").write())

	assert (picture.width, picture.height) == (0, 0)

def test_writer_hands_a_valid_picture_to_flac():
	image = make_jpeg(320, 240)
	calls = {}

	class FakeFlac:
		def __init__(self, song):
			self.values = {}

		def delete(self):
			pass

		def clear_pictures(self):
			calls["cleared"] = True

		def add_picture(self, picture):
			calls["picture"] = picture

		def __setitem__(self, key, value):
			self.values[key] = value

		def save(self):
			pass

	original = taggers.FLAC
	taggers.FLAC = FakeFlac

	try:
		taggers.write_tags(track_stub(image, ".flac"))
	finally:
		taggers.FLAC = original

	picture = calls["picture"]
	assert picture.mime == "image/jpeg"
	assert (picture.width, picture.height) == (320, 240)
	assert picture.data == image
	assert calls["cleared"] is True

def test_writer_hands_a_valid_picture_to_ogg():
	image = make_jpeg(320, 240)
	written = {}

	class FakeOgg:
		def __init__(self, song):
			self.values = {}

		def __setitem__(self, key, value):
			self.values[key] = value
			written[key] = value

		def save(self):
			pass

	original = taggers.OggVorbis
	taggers.OggVorbis = FakeOgg

	try:
		taggers.write_tags(track_stub(image, ".ogg"))
	finally:
		taggers.OggVorbis = original

	picture = Picture(base64.b64decode(written["metadata_block_picture"]))
	assert picture.mime == "image/jpeg"
	assert (picture.width, picture.height) == (320, 240)
	assert picture.data == image

def test_empty_image_does_not_raise():
	block = picture_block(b"")
	picture = Picture(block.write())

	assert picture.data == b""
	assert picture.mime == "application/octet-stream"

def test_jpeg_with_extra_segments_is_measured():
	# APP0 (JFIF) segment before the frame header, as real encoders emit.
	app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
	sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", 1080, 1920) + b"\x01\x01\x11\x00"
	image = b"\xff\xd8" + app0 + sof + b"\xff\xd9"

	picture = Picture(picture_block(image).write())

	assert (picture.width, picture.height) == (1920, 1080)

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