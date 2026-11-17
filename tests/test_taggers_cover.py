#!/usr/bin/python3

"""Cover-art block tests for deezloader.__taggers__.

The ogg/flac writers build a FLAC picture block by hand. Without an explicit
mime type and dimensions the block is invalid, players ignore the artwork and
the file looks coverless even though the bytes are there. These tests pin the
block contents for the formats the bot actually produces.

Run as: python -m pytest tests/test_taggers_cover.py -q
     or: python tests/test_taggers_cover.py
"""

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