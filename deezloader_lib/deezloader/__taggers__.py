#!/usr/bin/python3

from base64 import b64encode
from mutagen.flac import FLAC, Picture
from mutagen.oggvorbis import OggVorbis
from deezloader.models.track import Track

from mutagen.id3 import (
	ID3NoHeaderError,
	ID3, APIC, USLT, SYLT,
	COMM, TSRC, TRCK, TIT2,
	TLEN, TEXT, TCON, TALB, TBPM,
	TPE1, TYER, TDAT, TPOS, TPE2,
	TPUB, TCOP, TXXX, TCOM, IPLS
)

def __detect_mime(image):
	if image[:2] == b"\xff\xd8":
		return "image/jpeg"

	if image[:4] == b"\x89PNG":
		return "image/png"

	if image[:6] in (b"GIF87a", b"GIF89a"):
		return "image/gif"

	if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
		return "image/webp"

	return "application/octet-stream"

def __detect_depth(image):
	if image[:4] == b"\x89PNG":
		# PNG colour types: 0 grey, 2 RGB, 3 palette, 4 grey+alpha, 6 RGBA.
		colour_type = image[25] if len(image) > 25 else 0
		bit_depth = image[24] if len(image) > 24 else 8
		channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour_type, 0)

		return bit_depth * channels

	if image[:2] == b"\xff\xd8":
		return 24

	return 0

def __detect_size(image):
	if image[:4] == b"\x89PNG":
		width = int.from_bytes(image[16:20], "big")
		height = int.from_bytes(image[20:24], "big")

		return width, height

	return __detect_jpeg_size(image)

def __detect_jpeg_size(image):
	# Walk the JPEG segments until the frame header carries the size.
	index = 2

	while index + 1 < len(image):
		if image[index] != 0xFF:
			index += 1

			continue

		# Any number of 0xFF fill bytes may precede a marker.
		while index + 1 < len(image) and image[index + 1] == 0xFF:
			index += 1

		if index + 1 >= len(image):
			break

		marker = image[index + 1]
		index += 2

		# Standalone markers carry no length field.
		if marker in (
			0x01, 0xD0, 0xD1, 0xD2, 0xD3,
			0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9
		):
			continue

		if index + 2 > len(image):
			break

		segment = int.from_bytes(image[index:index + 2], "big")

		if segment < 2:
			break

		if marker in (
			0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6,
			0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF
		):
			if index + 7 > len(image):
				break

			height = int.from_bytes(image[index + 3:index + 5], "big")
			width = int.from_bytes(image[index + 5:index + 7], "big")

			return width, height

		index += segment

	return 0, 0

def __picture_block(image):
	# A FLAC picture block without a mime type and dimensions is invalid:
	# players drop the artwork even though the bytes are present, which is
	# why ogg and flac files looked coverless while mp3 worked. Formats
	# whose size cannot be read keep 0x0 (unknown) but still carry a mime.
	images = Picture()
	images.type = 3
	images.mime = __detect_mime(image)
	images.width, images.height = __detect_size(image)
	images.depth = __detect_depth(image)
	images.data = image

	return images

def __write_flac(song, data):
	tag = FLAC(song)
	tag.delete()
	tag.clear_pictures()
	tag.add_picture(__picture_block(data['image']))
	tag['lyrics'] = data['lyric']
	tag['artist'] = data['artist']
	tag['title'] = data['music']
	tag['date'] = f"{data['year'].year}/{data['year'].month}/{data['year'].day}"
	tag['album'] = data['album']
	tag['tracknumber'] = f"{data['tracknum']}"
	tag['discnumber'] = f"{data['discnum']}"
	tag['genre'] = data['genre']
	tag['albumartist'] = data['ar_album']
	tag['author'] = data['author']
	tag['composer'] = data['composer']
	tag['copyright'] = data['copyright']
	tag['bpm'] = f"{data['bpm']}"
	tag['length'] = f"{data['duration']}"
	tag['organization'] = data['label']
	tag['isrc'] = data['isrc']
	tag['lyricist'] = data['lyricist']
	tag['version'] = data['version']
	tag.save()

def __write_mp3(song, data):
	try:
		audio = ID3(song)
		audio.delete()
	except ID3NoHeaderError:
		audio = ID3()

	audio.add(
		APIC(
			mime = "image/jpeg",
			type = 3,
			desc = "album front cover",
			data = data['image']
		)
	)

	audio.add(
		COMM(
			lang = "eng",
			desc = "my comment",
			text = "DO NOT USE FOR YOUR OWN EARNING"
		)
	)

	audio.add(
		USLT(
			text = data['lyric']
		)
	)

	audio.add(
		SYLT(
			type = 1,
			format = 2,
			desc = "sync lyric song",
			text = data['lyric_sync']
		)
	)

	audio.add(
		TSRC(
			text = data['isrc']
		)
	)

	audio.add(
		TRCK(
			text = f"{data['tracknum']}/{data['nb_tracks']}"
		)
	)

	audio.add(
		TIT2(
			text = data['music']
		)
	)

	audio.add(
		TLEN(
			text = f"{data['duration']}"
		)
	)

	audio.add(
		TEXT(
			text = data['lyricist']
		)
	)

	audio.add(
		TCON(
			text = data['genre']
		)
	)

	audio.add(
		TALB(
			text = data['album']
		)
	)

	audio.add(
		TBPM(
			text = f"{data['bpm']}" 
		)
	)

	audio.add(
		TPE1(
			text = data['artist']
		)
	)

	audio.add(
		TYER(
			text = f"{data['year'].year}"
		)
	)

	audio.add(
		TDAT(
			text = f"{data['year'].day}{data['year'].month}"
		)
	)

	audio.add(
		TPOS(
			text = f"{data['discnum']}/{data['discnum']}"
		)
	)

	audio.add(
		TPE2(
			text = data['ar_album']
		)
	)

	audio.add(
		TPUB(
			text = data['label']
		)
	)

	audio.add(
		TCOP(
			text = data['copyright']
		)
	)

	audio.add(
		TXXX(
			desc = "REPLAYGAIN_TRACK_GAIN",
			text = f"{data['gain']}"
		)
	)

	audio.add(
		TCOM(
			text = data['composer']
		)
	)

	audio.add(
		IPLS(
			people = [
				data['author']
			]
		)
	)

	audio.save(song, v2_version = 3)

def __write_ogg(song, data):
	tag = OggVorbis(song)

	pic_data = b64encode(
		__picture_block(data['image']).write()
	).decode("ascii")

	tag['metadata_block_picture'] = pic_data
	#tag['lyrics'] = data['lyric']
	tag['artist'] = data['artist']
	tag['title'] = data['music']
	tag['year'] = f"{data['year'].year}"
	tag['date'] = f"{data['year'].year}/{data['year'].month}/{data['year'].day}"
	tag['album'] = data['album']
	tag['tracknumber'] = f"{data['tracknum']}"
	tag['discnumber'] = f"{data['discnum']}"
	tag['genre'] = data['genre']
	tag['albumartist'] = data['ar_album']
	#tag['author'] = data['author']
	#tag['composer'] = data['composer']
	#tag['copyright'] = data['copyright']
	tag['bpm'] = f"{data['bpm']}"
	tag['length'] = f"{data['duration']}"
	tag['organization'] = data['label']
	tag['isrc'] = data['isrc']
	#tag['lyricist'] = data['lyricist']
	#tag['version'] = data['version']
	tag.save()

def write_tags(track: Track):
	song = track.song_path
	song_metadata = track.tags
	f_format = track.file_format

	if f_format == ".flac":
		__write_flac(song, song_metadata)
	elif f_format == ".ogg":
		__write_ogg(song, song_metadata)
	else:
		__write_mp3(song, song_metadata)

def check_track(track: Track):
	song = track.song_path
	f_format = track.file_format
	is_ok = False

	if f_format == ".flac":
		tags = FLAC(song)
	elif f_format == ".ogg":
		tags = OggVorbis(song)
	else:
		try:
			tags = ID3(song)
		except ID3NoHeaderError:
			return is_ok

	l_tags = len(
		tags.keys()
	)

	if l_tags >= 14:
		is_ok = True

	return is_ok