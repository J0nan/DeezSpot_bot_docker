#!/usr/bin/python3

"""YouTube link helpers.

Kept free of bot and telegram imports so the parsing and metadata rules stay
unit-testable (mutagen is imported only by the tag writer). The bot side lives
in helpers/youtube_help.py.

The video id is the only thing this module trusts out of a pasted URL: a
playlist parameter, a timestamp or a mobile/music host never changes what gets
downloaded.
"""

from os.path import isfile, join
from re import compile as re_compile, search as re_search
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {
	"youtube.com",
	"m.youtube.com",
	"music.youtube.com",
	"youtu.be",
}

# YouTube ids are exactly eleven URL-safe characters. Matched with fullmatch:
# `$` alone also matches before a trailing newline, which forged callback data
# could smuggle into the watch URL and the output filename.
VIDEO_ID_PATTERN = re_compile(r"[A-Za-z0-9_-]{11}")

# path prefixes that carry the id as their own next segment
YOUTUBE_ID_PATHS = {"shorts", "embed", "live", "v"}

# Bracket labels YouTube creators append to the real title. Only an EXACT
# match is dropped: "(Live at Wembley)", "(Remastered 2011)", "(feat. X)" and
# "(Extended Mix)" are real title information and stay untouched.
YOUTUBE_NOISE_LABELS = {
	"audio",
	"clip officiel",
	"hd",
	"hq",
	"lyric",
	"lyric video",
	"lyrics",
	"m/v",
	"music video",
	"mv",
	"official",
	"official audio",
	"official hd video",
	"official lyric video",
	"official music video",
	"official video",
	"official visualizer",
	"video",
	"video oficial",
	"videoclip",
	"visualizer",
	"with lyrics",
	"4k",
	"8k",
}

# the bracket worth stripping is always the LAST one: "Song (Live) (Official
# Video)" loses the label and keeps the live marker
__TRAILING_BRACKET = re_compile(r"^(?P<head>.*?)\s*[\(\[](?P<body>[^\(\)\[\]]*)[\)\]]\s*$")

# separators creators use between artist and song, in order of confidence
__ARTIST_SEPARATORS = (" - ", " – ", " — ")

# A left half longer than this is a sentence, not a performer name: only a
# short prefix is trusted as the artist when splitting "Artist - Song".
ARTIST_SPLIT_MAX = 60

# Telegram rejects a thumb above 200 KB; a 640-wide video miniature stays far
# below it while still looking sharp on a phone
THUMBNAIL_MAX_WIDTH = 640

# yt-dlp options shared by the metadata probe and the download, so a timeout
# or warning change can never land on one path only
YOUTUBE_BASE_OPTIONS = {
	"quiet": True,
	"no_warnings": True,
	"noprogress": True,
	# a pasted watch?v=...&list=... must never pull the whole playlist
	"noplaylist": True,
	"socket_timeout": 20,
}

def _cover_url(info):
	thumbnails = [
		thumbnail
		for thumbnail in (info.get("thumbnails") or [])
		if isinstance(thumbnail, dict) and thumbnail.get("url") and thumbnail.get("width")
	]
	fitting = [
		thumbnail
		for thumbnail in thumbnails
		if thumbnail["width"] <= THUMBNAIL_MAX_WIDTH
	]

	if fitting:
		return max(fitting, key = lambda thumbnail: thumbnail["width"])["url"]

	return info.get("thumbnail") or ""

def _host(link):
	netloc = urlparse(link).netloc.lower()

	if netloc.startswith("www."):
		netloc = netloc[len("www."):]

	return netloc

def is_youtube_link(link):
	if not isinstance(link, str):
		return False

	return _host(link) in YOUTUBE_HOSTS

def youtube_video_id(link):
	# Every supported shape reduces to one eleven character id; anything else
	# (a bare playlist, a channel page, a Shorts feed without an id) is not a
	# video this bot can download.
	if not is_youtube_link(link):
		return None

	parsed = urlparse(link)
	host = _host(link)
	segments = [
		segment
		for segment in parsed.path.split("/")
		if segment
	]
	query = parse_qs(parsed.query)
	candidate = None

	if host == "youtu.be":
		if segments:
			candidate = segments[0]

	elif segments:
		if segments[0] == "watch":
			candidate = (query.get("v") or [None])[0]

		elif segments[0] in YOUTUBE_ID_PATHS and len(segments) > 1:
			candidate = segments[1]

	if not candidate:
		candidate = (query.get("v") or [None])[0]

	if candidate and VIDEO_ID_PATTERN.fullmatch(candidate):
		return candidate

	return None

def video_url(video_id):
	return f"https://www.youtube.com/watch?v={video_id}"

def is_video_id(value):
	# validation for ids that arrive back from a callback payload
	return isinstance(value, str) and bool(VIDEO_ID_PATTERN.fullmatch(value))

def cache_key(video_id):
	# namespaced so a dwsongs row can never collide with a Deezer/Spotify path
	return f"youtube/{video_id}"

def _label(text):
	return " ".join(text.lower().split())

def clean_title(title):
	# Strip trailing bracket labels that carry no information about the song
	# itself, repeatedly so "Song (Live) (Official Video)" keeps "(Live)".
	if not title:
		return ""

	text = " ".join(title.split())

	while True:
		match = re_search(__TRAILING_BRACKET, text)

		if not match:
			break

		if _label(match.group("body")) not in YOUTUBE_NOISE_LABELS:
			break

		text = match.group("head").strip()

	return text.strip(" -–—")

def split_artist_title(title):
	# "Artist - Song" is the YouTube convention when the upload names no
	# artist. Exactly one separator or nothing: a longer title ("One - Two -
	# Three") is left whole instead of guessing which half is the artist.
	if not title:
		return "", ""

	for separator in __ARTIST_SEPARATORS:
		parts = title.split(separator)

		if len(parts) != 2:
			continue

		artist = parts[0].strip()
		song = parts[1].strip()

		if artist and song and len(artist) <= ARTIST_SPLIT_MAX:
			return artist, song

	return "", title

def normalize_date(raw):
	# yt-dlp reports upload_date/release_date as YYYYMMDD, Deezer as
	# YYYY-MM-DD; both normalize to the tagged form, and a zeroed date is
	# treated as unknown instead of "0000-00-00".
	if not raw:
		return ""

	digits = "".join(character for character in str(raw) if character.isdigit())

	if len(digits) < 8:
		return ""

	year = digits[:4]
	month = digits[4:6]
	day = digits[6:8]

	if int(month) < 1 or int(month) > 12:
		return ""

	if int(day) < 1 or int(day) > 31:
		return ""

	return f"{year}-{month}-{day}"

def _deezer_values(deezer_track):
	deezer_track = deezer_track or {}
	artist = (deezer_track.get("artist") or {}).get("name") or ""
	album = (deezer_track.get("album") or {}).get("title") or ""
	date = (deezer_track.get("album") or {}).get("release_date") or ""
	duration = deezer_track.get("duration") or 0

	return artist.strip(), album.strip(), normalize_date(date), duration

def build_yt_metadata(info, deezer_track = None):
	# yt-dlp is authoritative for WHAT was downloaded (a cover or a remix must
	# not inherit the metadata of the studio track it matched), so the Deezer
	# payload only fills the fields YouTube often lacks: album and date.
	info = info or {}
	dz_artist, dz_album, dz_date, dz_duration = _deezer_values(deezer_track)

	raw_title = (info.get("track") or info.get("title") or "").strip()
	artist = (info.get("artist") or info.get("creator") or "").strip()
	album = (info.get("album") or "").strip()
	title = clean_title(raw_title)

	if not artist:
		# explicit music metadata first, then the "Artist - Song" convention,
		# then the channel name: an uploader called "VEVO" or "Records" is the
		# least useful of the three, so it is only the last resort
		parsed_artist, parsed_title = split_artist_title(title)

		if parsed_artist:
			artist = parsed_artist
			title = parsed_title
		else:
			uploader = (info.get("uploader") or info.get("channel") or "").strip()

			if uploader.lower().endswith("- topic"):
				uploader = uploader[: -len("- topic")].strip()

			artist = uploader

	duration = info.get("duration") or dz_duration or 0

	return {
		"video_id": info.get("id") or "",
		"title": title or "",
		"artist": artist or dz_artist,
		"album": album or dz_album or "YouTube",
		"date": normalize_date(info.get("release_date") or info.get("upload_date")) or dz_date,
		"duration": int(duration),
		# always the video miniature: the user asked for the video art, not
		# the matched Deezer cover
		"cover_url": _cover_url(info),
	}

def search_query(meta):
	# "as a song on Deezer": the artist narrows the track search, the title
	# alone still finds it when the upload names no artist
	return " ".join(
		part
		for part in (meta.get("artist", ""), meta.get("title", ""))
		if part
	).strip()

def tag_payload(meta):
	# The keys set_path reads for every method_save scheme; a YouTube file has
	# no track number or ISRC, so those keep neutral values.
	return {
		"music": meta.get("title") or "Unknown title",
		"artist": meta.get("artist") or "Unknown artist",
		"album": meta.get("album") or "YouTube",
		"discnum": 1,
		"tracknum": 1,
		"isrc": "",
	}

def _date_parts(raw):
	normalized = normalize_date(raw)

	if not normalized:
		return "", "", ""

	year, month, day = normalized.split("-")

	return year, month, day

def _image_mime(data):
	if data[:2] == b"\xff\xd8":
		return "image/jpeg"

	if data[:4] == b"\x89PNG":
		return "image/png"

	if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
		return "image/webp"

	return "application/octet-stream"

def write_mp3_tags(path, meta, cover_bytes = None):
	# ID3v2.3 on purpose: the same version the bundled deezloader tagger writes,
	# which every Telegram client and car player reads.
	if not isfile(path):
		return False

	from mutagen.id3 import (
		APIC, ID3, ID3NoHeaderError,
		TALB, TDAT, TIT2, TPE1, TPE2, TYER
	)

	try:
		tags = ID3(path)
		# a re-downloaded file may still carry the frames of a previous run
		tags.delete()
	except ID3NoHeaderError:
		# delete() needs a file behind the tag; a fresh header has none to wipe
		tags = ID3()

	if meta.get("title"):
		tags.add(TIT2(encoding = 3, text = [meta["title"]]))

	if meta.get("artist"):
		tags.add(TPE1(encoding = 3, text = [meta["artist"]]))
		tags.add(TPE2(encoding = 3, text = [meta["artist"]]))

	if meta.get("album"):
		tags.add(TALB(encoding = 3, text = [meta["album"]]))

	year, month, day = _date_parts(meta.get("date"))

	if year:
		tags.add(TYER(encoding = 3, text = [year]))

	if month and day:
		# ID3v2.3 stores the date as DDMM
		tags.add(TDAT(encoding = 3, text = [f"{day}{month}"]))

	if cover_bytes:
		tags.add(
			APIC(
				encoding = 3,
				mime = _image_mime(cover_bytes),
				type = 3,
				desc = "Cover",
				data = cover_bytes
			)
		)

	tags.save(path, v2_version = 3)

	return True

def output_stem(video_id, suffix = None):
	# A per-download suffix is what keeps two users fetching the same video
	# from writing one file: yt-dlp overwrites its output and the tagger reads
	# it back. Leftovers stay under Songs/youtube and the periodic sweep
	# clears that folder.
	if suffix:
		return f"yt_{video_id}_{suffix}"

	return f"yt_{video_id}"

def download_options(video_id, output_dir, suffix = None):
	# bestaudio first: the source stream is never re-encoded downward, only
	# converted to the mp3 the user asked for, at the maximum MP3 bitrate.
	return {
		**YOUTUBE_BASE_OPTIONS,
		"format": "bestaudio/best",
		"outtmpl": join(output_dir, f"{output_stem(video_id, suffix)}.%(ext)s"),
		"overwrites": True,
		"postprocessors": [
			{
				"key": "FFmpegExtractAudio",
				"preferredcodec": "mp3",
				"preferredquality": "320",
			}
		],
	}

def mp3_path(video_id, output_dir, suffix = None):
	return join(output_dir, f"{output_stem(video_id, suffix)}.mp3")