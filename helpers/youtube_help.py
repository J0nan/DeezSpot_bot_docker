#!/usr/bin/python3

"""YouTube links: Deezer search with a YouTube download button, or the direct
download the user chose in /settings.

The worker mirrors helpers.download_help.DW: it runs in a magicThread that
start_download registered in c_downloads (so /kill_dw and MAX_DOWNLOAD_USER
cover it), uploads the audio to the bunker channel once and serves the file_id
from the dwsongs cache afterwards.
"""

from hashlib import md5
from os import makedirs
from os.path import isfile, join
from threading import Lock
from time import time
from telegram import ChatAction
from telegram.error import BadRequest, TelegramError
from configs.set_configs import SetConfigs
from deezloader.libutils.utils import request
from helpers.download_help import (
	l_downloads, l_links, log_error, start_download
)
from inlines.inline_keyboards import create_youtube_confirm_keyboard
from inlines.message_results import (
	create_keyboard_list, list_caption, send_list, send_not_found
)
from utils.db import delete_dwsongs, select_dwsongs, write_db
from utils.search_cache import attach_message, set_index, store
from utils.thumb_utils import make_thumb_io
from utils.utils import get_size, set_path
from utils.utils_data import execute_search, track_dee_data
from utils.youtube import (
	YOUTUBE_BASE_OPTIONS,
	build_yt_metadata, cache_key, download_options,
	mp3_path, normalize_artists, search_query, tag_payload,
	video_url, write_mp3_tags, youtube_video_id
)

from configs.customs import (
	send_image_track_query, track_too_long,
	youtube_confirm_caption, youtube_download_mode,
	youtube_edit_invalid, youtube_edit_prompts,
	youtube_unbounded_msg
)

from configs.bot_settings import (
	bunker_channel, output_songs,
	seconds_limits_track, upload_max_size_user
)

bot = SetConfigs.tg_bot_api.bot

# The audio is always the same deliverable regardless of the Deezer quality
# setting: an mp3 at the maximum MP3 bitrate, so this is also its cache quality.
YOUTUBE_QUALITY = "MP3_320"

# A Telegram caption is 1024 characters: each editable field is capped well
# below that so the labels and the hint always fit, and a pasted essay is
# refused instead of overflowing the card.
YOUTUBE_FIELD_MAX = 200

# the fields the confirmation card lets the user fix, matching its buttons
YOUTUBE_EDIT_FIELDS = ("title", "artist", "album")

# an abandoned prompt stops holding the chat's messages after this long, so a
# forgotten edit can never divert searches forever
YOUTUBE_EDIT_TTL = 10 * 60

# One confirmation per chat, like the search cache. The card's buttons carry
# this id, so a tap on a stale card can never edit (or start) a newer
# confirmation of the same chat. PTB runs handlers concurrently, so the map is
# guarded the way search_cache guards its own entries.
_pending = {}
_pending_lock = Lock()

# token seed for the card ids: the counter keeps two confirmations of the same
# chat apart even when they land on the same clock tick
_id_counter = 0

def __new_pending_id(chat_id):
	global _id_counter

	with _pending_lock:
		_id_counter += 1
		seed = f"{chat_id}:{time()}:{_id_counter}"

	return md5(seed.encode()).hexdigest()[:8]

YOUTUBE_INFO_OPTIONS = {
	**YOUTUBE_BASE_OPTIONS,
	# metadata only: the download runs later, in the worker thread
	"skip_download": True,
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

def download_audio(video_id, suffix = None):
	# bestaudio -> mp3 320 through yt-dlp's ffmpeg postprocessor
	directory = youtube_dir()
	options = download_options(video_id, directory, suffix)

	try:
		import yt_dlp

		with yt_dlp.YoutubeDL(options) as ydl:
			ydl.download([video_url(video_id)])
	except Exception as error:
		l_downloads.warning(f"youtube download failed for {video_id}: {error!r}")

		return None

	path = mp3_path(video_id, directory, suffix)

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
	if not deezer_id or not str(deezer_id).isdigit():
		# callback data is client-forgeable: only digits may reach the URL
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

def confirm_caption(meta):
	# Plain text on purpose: a YouTube title may carry markdown characters
	return youtube_confirm_caption % (
		meta["title"] or "Unknown",
		meta["artist"] or "Unknown",
		meta["album"] or "YouTube",
		meta["date"] or "Unknown"
	)

def pending_download(chat_id):
	# a copy, its metadata included: a caller mutates the copy and saves it
	# back, so no handler ever reads a half-changed entry
	with _pending_lock:
		entry = _pending.get(chat_id)

		return __copy_pending(entry) if entry else None

def clear_pending(chat_id):
	with _pending_lock:
		_pending.pop(chat_id, None)

def __copy_pending(entry):
	copy = dict(entry)
	copy["meta"] = dict(entry["meta"])

	return copy

def __save_pending(chat_id, entry):
	with _pending_lock:
		_pending[chat_id] = __copy_pending(entry)

def __take_pending(chat_id, pending_id):
	# one atomic claim: two taps of the same card (or a tap racing another
	# callback) can only ever start one download
	with _pending_lock:
		entry = _pending.get(chat_id)

		if not entry or entry["id"] != pending_id:
			return None

		del _pending[chat_id]

		return __copy_pending(entry)

def __restore_pending(chat_id, entry):
	with _pending_lock:
		# setdefault: a newer confirmation created in the meantime wins
		_pending.setdefault(chat_id, __copy_pending(entry))

def __send_confirm_card(chat_id, entry):
	# the video miniature is the artwork the mp3 will carry; a dead image only
	# costs the picture, the card still arrives as text
	caption = confirm_caption(entry["meta"])
	markup = create_youtube_confirm_keyboard(entry["id"])

	try:
		message = bot.send_photo(
			chat_id = chat_id,
			photo = entry["meta"]["cover_url"] or None,
			caption = caption,
			reply_markup = markup
		)
		entry["has_photo"] = True
	except (TelegramError, ValueError) as error:
		l_downloads.warning(
			f"youtube confirm card failed for {entry['meta'].get('video_id')}: {error!r}"
		)

		message = bot.send_message(
			chat_id = chat_id,
			text = caption,
			reply_markup = markup
		)
		entry["has_photo"] = False

	entry["message_id"] = message.message_id

def __repaint_card(chat_id, entry):
	# The caption is replaced, not appended: the same buttons must ride along
	# or the edited card would lose its Edit/Download/Cancel row.
	caption = confirm_caption(entry["meta"])
	markup = create_youtube_confirm_keyboard(entry["id"])

	try:
		if entry["has_photo"]:
			bot.edit_message_caption(
				chat_id = chat_id,
				message_id = entry["message_id"],
				caption = caption,
				reply_markup = markup
			)
		else:
			bot.edit_message_text(
				chat_id = chat_id,
				message_id = entry["message_id"],
				text = caption,
				reply_markup = markup
			)
	except TelegramError:
		# identical caption (re-entering the same value) or a card the user
		# already removed: the stored metadata is what matters
		pass

def __drop_card(chat_id, entry, strip_only = False):
	# strip_only: the download is starting and the card becomes its track card
	message_id = entry.get("message_id")

	if message_id is None:
		return

	if not strip_only:
		try:
			bot.delete_message(
				chat_id = chat_id,
				message_id = message_id
			)

			return
		except TelegramError:
			pass

	try:
		# no delete right or the card must stay: only its buttons go away, so
		# a confirmed card can never start a second download
		bot.edit_message_reply_markup(
			chat_id = chat_id,
			message_id = message_id,
			reply_markup = None
		)
	except TelegramError:
		pass

def __delete_message(chat_id, message_id):
	if message_id is None:
		return

	try:
		bot.delete_message(
			chat_id = chat_id,
			message_id = message_id
		)
	except TelegramError:
		pass

def __delete_prompt(chat_id, entry):
	prompt_id = entry.get("prompt_id")

	if prompt_id is None:
		return

	__delete_message(chat_id, prompt_id)
	entry["prompt_id"] = None

def prepare_youtube_download(chat_id, video_id, deezer_id = None):
	# The download button's first stop: read the metadata the tags will carry,
	# refuse what the worker would refuse anyway, then let the user confirm or
	# fix it before any audio is fetched. A failure here must never escape the
	# callback unanswered: the tap ends in the same "cannot download" answer
	# the worker produces, and the button stays tappable.
	try:
		return __prepare_youtube_download(chat_id, video_id, deezer_id)
	except Exception as error:
		log_error(f"{video_url(video_id)} {chat_id}")
		log_error(error, exc_info = True)

		try:
			bot.send_message(
				chat_id = chat_id,
				text = f"Cannot download {video_url(video_id)} :("
			)
		except Exception:
			pass

		return False

def __prepare_youtube_download(chat_id, video_id, deezer_id):
	link = video_url(video_id)
	# every attempt is logged here too: a refusal before the worker starts must
	# leave the same operator signal the worker path always left
	l_links.info(link)
	# a card of this chat already waiting: a new confirmation supersedes it,
	# but only once the new one is actually sent
	previous = pending_download(chat_id)
	info = fetch_video_info(video_id)

	if info is None:
		bot.send_message(
			chat_id = chat_id,
			text = f"Cannot download {link} :("
		)

		return False

	meta = build_yt_metadata(info, deezer_track(deezer_id))

	# a live/upcoming stream reports no fixed duration, so the length limit
	# below cannot bound it: refuse instead of recording until it ends
	if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
		bot.send_message(
			chat_id = chat_id,
			text = youtube_unbounded_msg
		)

		return False

	if not meta["duration"]:
		bot.send_message(
			chat_id = chat_id,
			text = youtube_unbounded_msg
		)

		return False

	if meta["duration"] > seconds_limits_track:
		bot.send_message(
			chat_id = chat_id,
			text = track_too_long
		)

		return False

	entry = {
		"id": __new_pending_id(chat_id),
		"video_id": video_id,
		"deezer_id": deezer_id,
		"meta": meta,
		"edited": False,
		"stage": None,
		"message_id": None,
		"has_photo": False,
		"prompt_id": None
	}

	# the card is painted before the entry is stored: a failed send raises here
	# instead of leaving a confirmation nothing can repaint
	__send_confirm_card(chat_id, entry)
	__save_pending(chat_id, entry)

	if previous:
		# the old card is now inert, so it is removed instead of sitting there
		# with buttons that can only answer "too old"
		__drop_card(chat_id, previous)

	return True

def begin_youtube_edit(chat_id, pending_id, field):
	entry = pending_download(chat_id)

	if (
		not entry or entry["id"] != pending_id or
		field not in YOUTUBE_EDIT_FIELDS
	):
		return False

	try:
		# a prompt this card already asked for is replaced: its message must
		# not sit in the chat waiting for an answer that will never come
		__delete_prompt(chat_id, entry)

		prompt = bot.send_message(
			chat_id = chat_id,
			text = youtube_edit_prompts[field]
		)
	except TelegramError:
		# nothing was asked, so nothing may wait for an answer: the stage never
		# arms and the chat's next message is an ordinary search again
		return False

	entry["stage"] = field
	entry["stage_at"] = time()
	entry["prompt_id"] = prompt.message_id
	__save_pending(chat_id, entry)

	return True

def handle_youtube_edit_text(chat_id, text, message_id = None):
	# The card asked for exactly one value: the next message of this chat is
	# it. A command keeps reaching its own handler and never becomes a title.
	entry = pending_download(chat_id)

	if not entry or not entry["stage"]:
		return False

	if time() - entry.get("stage_at", 0) > YOUTUBE_EDIT_TTL:
		# an abandoned prompt must not swallow the chat's messages forever
		entry["stage"] = None
		__save_pending(chat_id, entry)

		return False

	if (text or "").lstrip().startswith("/"):
		return False

	# a caption is single line and the tags keep whatever goes in: control
	# characters are folded to spaces and runs collapsed before either, so a
	# pasted newline or a NUL can never reach a tag or the file name
	printable = "".join(
		character if character.isprintable() else " "
		for character in (text or "")
	)
	value = " ".join(printable.split())
	field = entry["stage"]

	if field == "artist":
		value = normalize_artists(value)

	if not value or len(value) > YOUTUBE_FIELD_MAX:
		bot.send_message(
			chat_id = chat_id,
			text = youtube_edit_invalid
		)

		# the stage stays armed: the user can just send a valid value
		return True

	changed = entry["meta"].get(field) != value

	if changed:
		# re-entering the value it already had is not an edit: the untouched
		# file keeps its plain cache key
		entry["meta"][field] = value
		entry["edited"] = True

	entry["stage"] = None
	__delete_prompt(chat_id, entry)
	# the typed value is consumed by the card: the chat keeps the prompt-free
	# card, not a stray line echoing what was sent
	__delete_message(chat_id, message_id)
	__save_pending(chat_id, entry)
	__repaint_card(chat_id, entry)

	return True

def confirm_youtube_download(chat_id, pending_id, user_data):
	entry = __take_pending(chat_id, pending_id)

	if entry is None:
		return None

	try:
		started = start_youtube_download(
			chat_id, entry["video_id"], user_data,
			entry["deezer_id"], entry["meta"], entry["edited"]
		)
	except Exception as error:
		# an enqueue failure must leave the card usable, not eat the entry
		log_error(f"{video_url(entry['video_id'])} {chat_id}")
		log_error(error, exc_info = True)
		__restore_pending(chat_id, entry)

		return False

	if not started:
		# the per-user cap refused it: the card and its buttons come back so
		# the user can confirm again once a slot frees up
		__restore_pending(chat_id, entry)

		return False

	__drop_card(chat_id, entry, strip_only = True)

	return True

def cancel_youtube_download(chat_id, pending_id):
	entry = __take_pending(chat_id, pending_id)

	if entry is None:
		return False

	__drop_card(chat_id, entry)

	return True

def drop_pending(chat_id):
	# a newer action supersedes the card: its buttons must never edit or start
	# what replaces it
	entry = pending_download(chat_id)

	if not entry:
		return

	clear_pending(chat_id)
	__drop_card(chat_id, entry)

def start_youtube_download(
	chat_id, video_id, user_data, deezer_id = None,
	meta = None, edited = False
):
	return start_download(
		chat_id, user_data, video_url(video_id),
		YT, (video_id, deezer_id, meta, edited)
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
			bot, chat_id, token, items, display,
			has_filters = True, scope = "all", page = 0,
			youtube = youtube
		)

	else:
		# the row is offered even when Deezer found nothing
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

	if user_data.get("youtube") == youtube_download_mode:
		# the new link supersedes a card still waiting for confirmation
		drop_pending(chat_id)
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

	def download(self, video_id, deezer_id = None, meta = None, edited = False):
		link = video_url(video_id)

		try:
			SetConfigs.queues_started += 1

			try:
				self.__download(video_id, deezer_id, meta, edited)
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

	def __download(self, video_id, deezer_id, meta, edited):
		link = video_url(video_id)
		l_links.info(link)

		if meta is None:
			# the "YouTube links: Download" setting never confirms first, so
			# this path still reads the video and paints its card here
			info = fetch_video_info(video_id)

			if info is None:
				bot.send_message(
					chat_id = self.__chat_id,
					text = f"Cannot download {link} :("
				)

				return

			meta = build_yt_metadata(info, deezer_track(deezer_id))
			self.__send_card(meta)

			# a live/upcoming stream reports no fixed duration, so the length
			# limit below cannot bound it: refuse instead of recording until
			# it ends
			if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
				bot.send_message(
					chat_id = self.__chat_id,
					text = youtube_unbounded_msg
				)

				return

		# the confirmation card already ran these guards; the unconfirmed path
		# must keep them too, since it is the one that reads the video itself
		if not meta["duration"]:
			bot.send_message(
				chat_id = self.__chat_id,
				text = youtube_unbounded_msg
			)

			return

		if meta["duration"] > seconds_limits_track:
			bot.send_message(
				chat_id = self.__chat_id,
				text = track_too_long
			)

			return

		# an edited tag set is its own deliverable: the plain key keeps serving
		# the untouched file to everyone else
		key = cache_key(video_id, meta if edited else None)

		if self.__serve_cached(key):
			# a cached delivery is a finished download too: the Deezer flow
			# closes every successful serve with the same note
			bot.send_message(
				chat_id = self.__chat_id,
				text = "FINISHED =)"
			)

			return

		progress_message_id = bot.send_message(
			chat_id = self.__chat_id,
			text = f"Starting uploading {meta['title']} ..."
		).message_id

		try:
			path = download_audio(video_id, self.__hash_link)

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