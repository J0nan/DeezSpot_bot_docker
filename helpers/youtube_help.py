#!/usr/bin/python3

"""YouTube links: Deezer search with a YouTube download button, or the direct
download the user chose in /settings.

The worker mirrors helpers.download_help.DW: it runs in a magicThread that
start_download registered in c_downloads (so /kill_dw and MAX_DOWNLOAD_USER
cover it), uploads the audio to the bunker channel once and serves the file_id
from the dwsongs cache afterwards.
"""

from os import makedirs
from os.path import isfile, join
from telegram import ChatAction
from telegram.error import BadRequest
from configs.set_configs import SetConfigs
from deezloader.libutils.utils import request
from helpers.download_help import (
	l_downloads, l_links, log_error, start_download
)
from inlines.message_results import (
	create_keyboard_list, list_caption, send_list, send_not_found
)
from utils.db import delete_dwsongs, select_dwsongs, write_db
from utils.search_cache import attach_message, set_index, store
from utils.thumb_utils import make_thumb_io
from utils.utils import get_size, set_path
from utils.utils_data import execute_search, track_dee_data
from utils.youtube import (
	build_yt_metadata, cache_key, download_options,
	mp3_path, search_query, tag_payload, video_url, write_mp3_tags,
	youtube_video_id
)

from configs.customs import send_image_track_query, track_too_long

from configs.bot_settings import (
	bunker_channel, output_songs,
	seconds_limits_track, upload_max_size_user
)

bot = SetConfigs.tg_bot_api.bot

# The audio is always the same deliverable regardless of the Deezer quality
# setting: an mp3 at the maximum MP3 bitrate, so this is also its cache quality.
YOUTUBE_QUALITY = "MP3_320"

YOUTUBE_INFO_OPTIONS = {
	"quiet": True,
	"no_warnings": True,
	"noprogress": True,
	"skip_download": True,
	"noplaylist": True,
	"socket_timeout": 20,
}

def youtube_dir():
	# Nested under the download root on purpose: the bot's periodic sweep wipes
	# the SUBDIRECTORIES of output_songs, so a leftover mp3 from a crashed
	# worker is cleaned like an album folder instead of living forever.
	directory = join(output_songs, "youtube")
	makedirs(directory, exist_ok = True)

	return directory

def fetch_video_info(video_id):
	# Metadata only: the download runs later, in the worker thread.
	try:
		import yt_dlp

		with yt_dlp.YoutubeDL(YOUTUBE_INFO_OPTIONS) as ydl:
			info = ydl.extract_info(video_url(video_id), download = False)
	except Exception as error:
		# geo blocks, private/age gated videos, a missing yt-dlp install or a
		# network hiccup: the caller still has a video id to offer the download
		l_downloads.warning(f"youtube info failed for {video_id}: {error!r}")

		return None

	if not info or info.get("_type") == "playlist" or not info.get("id"):
		return None

	return info

def download_audio(video_id):
	# bestaudio -> mp3 320 through yt-dlp's ffmpeg postprocessor
	directory = youtube_dir()
	options = download_options(video_id, directory)

	try:
		import yt_dlp

		with yt_dlp.YoutubeDL(options) as ydl:
			ydl.download([video_url(video_id)])
	except Exception as error:
		l_downloads.warning(f"youtube download failed for {video_id}: {error!r}")

		return None

	path = mp3_path(video_id, directory)

	if not isfile(path):
		return None

	return path

def fetch_cover(meta):
	# The video miniature is the artwork of the mp3 and the upload thumb; a
	# dead image only costs the cover.
	url = meta.get("cover_url")

	if not url:
		return b""

	try:
		response = request(url)
	except Exception as error:
		l_downloads.warning(f"youtube cover failed for {meta.get('video_id')}: {error!r}")

		return b""

	if getattr(response, "status_code", 200) != 200:
		return b""

	return response.content or b""

def deezer_track(deezer_id):
	# Only used to fill album/release date YouTube rarely reports; the id comes
	# from the track the search matched, never from user input alone.
	if not deezer_id:
		return None

	try:
		image_url, name, artist, album, date, link_dee, duration = track_dee_data(
			f"https://www.deezer.com/track/{deezer_id}"
		)
	except Exception as error:
		l_downloads.info(f"deezer metadata unavailable for {deezer_id}: {error!r}")

		return None

	return {
		"artist": {"name": artist},
		"album": {"title": album, "release_date": date},
		"duration": duration
	}

def start_youtube_download(chat_id, video_id, user_data, deezer_id = None):
	return start_download(
		chat_id, user_data, video_url(video_id),
		YT, (video_id, deezer_id)
	)

def search_youtube(chat_id, video_id, user_data, user_message_id = None):
	# "search it as a song on Deezer": the video title is searched as a track
	# and the result view always keeps the YouTube download row.
	l_links.info(video_url(video_id))
	info = fetch_video_info(video_id)
	meta = build_yt_metadata(info) if info else None
	query = search_query(meta) if meta else ""
	display = ""

	if meta:
		display = " - ".join(
			part
			for part in (meta["artist"], meta["title"])
			if part
		)

	items = []

	if query:
		try:
			items = execute_search(f"trk: {query}", user_data) or []
		except Exception as error:
			# a Deezer hiccup must not cost the user the YouTube download
			log_error(error, exc_info = True)
			items = []

	deezer_id = None

	if items and items[0].get("type") == "track":
		deezer_id = str(items[0]["id"])

	token = store(
		chat_id, items, query, user_message_id, display,
		youtube_id = video_id, youtube_deezer_id = deezer_id
	)
	youtube = (video_id, deezer_id)

	if items:
		message = send_list(
			bot, chat_id, token, items,
			display, True, "all", 0, youtube
		)

	else:
		# S2: the row is offered even when Deezer found nothing
		if display:
			caption = (
				list_caption(display, items) +
				"\nNo Deezer match, you can still download it from YouTube"
			)
		else:
			caption = (
				"I could not read this video, "
				"you can still download it from YouTube"
			)

		message = send_not_found(
			bot, chat_id, caption,
			create_keyboard_list(token, [], False, "all", 0, youtube)
		)

	attach_message(chat_id, token, message.message_id)
	set_index(chat_id, token, 0)

	return token

def handle_youtube_link(chat_id, link, user_data, user_message_id = None):
	video_id = youtube_video_id(link)

	if not video_id:
		bot.send_message(
			chat_id = chat_id,
			text = "THIS LINK IS NOT SUPPORTED :("
		)

		return

	if user_data.get("youtube") == "Download":
		start_youtube_download(chat_id, video_id, user_data)

		return

	search_youtube(chat_id, video_id, user_data, user_message_id)

class YT:
	def __init__(self, chat_id, user_data, hash_link):
		self.__chat_id = chat_id
		self.__method_save = user_data["method_save"]
		self.__hash_link = hash_link
		self.__c_download = user_data["c_downloads"]

	def __finished(self):
		try:
			del self.__c_download[self.__hash_link]
		except KeyError:
			pass

	def __send_card(self, meta):
		# the same track card the Deezer flow paints before downloading, with
		# the video miniature as its picture
		caption = send_image_track_query % (
			meta["title"] or "Unknown",
			meta["artist"] or "Unknown",
			meta["album"] or "YouTube",
			meta["date"] or "Unknown"
		)

		try:
			bot.send_photo(
				chat_id = self.__chat_id,
				photo = meta["cover_url"] or None,
				caption = caption
			)
		except (BadRequest, ValueError):
			bot.send_message(
				chat_id = self.__chat_id,
				text = caption
			)

	def __serve_cached(self, key):
		match = select_dwsongs(key, YOUTUBE_QUALITY, self.__method_save)

		if not match:
			return False

		try:
			bot.send_audio(
				chat_id = self.__chat_id,
				audio = match[0]
			)

			return True

		except BadRequest:
			# the archived file is gone: drop the row and download again
			delete_dwsongs(match[0])

			return False

	def download(self, video_id, deezer_id = None):
		link = video_url(video_id)

		try:
			SetConfigs.queues_started += 1

			try:
				self.__download(video_id, deezer_id)
			except Exception as error:
				log_error(f"{link} {self.__chat_id}")
				log_error(error, exc_info = True)

				try:
					bot.send_message(
						chat_id = self.__chat_id,
						text = f"ERROR WITH THIS LINK {link}"
					)
				except Exception:
					pass

		finally:
			SetConfigs.queues_finished += 1
			self.__finished()

	def __download(self, video_id, deezer_id):
		link = video_url(video_id)
		l_links.info(link)
		info = fetch_video_info(video_id)

		if info is None:
			bot.send_message(
				chat_id = self.__chat_id,
				text = f"Cannot download {link} :("
			)

			return

		meta = build_yt_metadata(info, deezer_track(deezer_id))
		self.__send_card(meta)

		if meta["duration"] > seconds_limits_track:
			bot.send_message(
				chat_id = self.__chat_id,
				text = track_too_long
			)

			return

		key = cache_key(video_id)

		if self.__serve_cached(key):
			return

		progress_message_id = bot.send_message(
			chat_id = self.__chat_id,
			text = f"Starting uploading {meta['title']} ..."
		).message_id

		try:
			path = download_audio(video_id)

			if path is None:
				bot.send_message(
					chat_id = self.__chat_id,
					text = f"Cannot download {link} :("
				)

				return

			cover = fetch_cover(meta)

			# tags are written regardless of the cover: a coverless file is
			# still a correctly labelled song
			write_mp3_tags(path, meta, cover)

			track_size = get_size(path, "gb")

			if track_size > upload_max_size_user:
				bot.send_message(
					chat_id = self.__chat_id,
					text = f"THE SONG {meta['title']} IS TOO BIG TO BE UPLOADED\
						, MAX {upload_max_size_user} GB\
						, CURRENT {track_size} GB :("
				)

				return

			file_name = set_path(
				tag_payload(meta),
				YOUTUBE_QUALITY, ".mp3",
				self.__method_save
			)

			sent = SetConfigs.tg_user_api.send_audio(
				chat_id = bunker_channel,
				audio = path,
				thumb = make_thumb_io(cover, video_id),
				duration = meta["duration"],
				performer = meta["artist"],
				title = meta["title"],
				file_name = file_name
			)
		finally:
			try:
				bot.delete_message(
					chat_id = self.__chat_id,
					message_id = progress_message_id
				)
			except Exception:
				pass

		file_id = sent.audio.file_id if getattr(sent, "audio", None) else None

		if not file_id:
			bot.send_message(
				chat_id = self.__chat_id,
				text = f"Cannot upload {link} :("
			)

			return

		write_db(
			key, file_id,
			YOUTUBE_QUALITY, self.__chat_id, self.__method_save,
			1 if cover else 0
		)

		bot.send_chat_action(
			chat_id = self.__chat_id,
			action = ChatAction.UPLOAD_AUDIO
		)

		# the requested action is the audio itself, so it is sent even when the
		# user turned "Send tracks" off (that setting governs album deliveries)
		bot.send_audio(
			chat_id = self.__chat_id,
			audio = file_id
		)

		bot.send_message(
			chat_id = self.__chat_id,
			text = "FINISHED =)"
		)