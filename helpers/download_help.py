#!/usr/bin/python3

from time import sleep, time
from hashlib import md5
from os.path import isfile
from telegram import ChatAction
from telegram.error import BadRequest
from deezloader.models.track import Track
from deezloader.models.album import Album
from configs.set_configs import SetConfigs
from deezloader.exceptions import TrackNotFound
from deezloader.libutils.utils import request, what_kind
from utils.special_thread import magicThread
from inlines.inline_keyboards import create_keyboard_artist
from deezloader.deezloader.cover_art import fetch_thumb
from deezloader.__taggers__ import has_picture

# One cache implementation for the bot: the dwsongs helpers live in utils.db,
# which helpers.db_help also re-exports.
from utils.db import (
	write_db, select_dwsongs, delete_dwsongs
)

from deezloader.exceptions import (
	NoDataApi, InvalidLink, AlbumNotFound
)

from utils.utils import (
	get_quality_dee_s_quality, get_quality_spo_s_quality,
	get_quality_spo, get_url_path, set_path, 
	get_size, logging_bot, get_netloc
)

from utils.thumb_utils import make_thumb_io

from configs.customs import (
	send_image_track_query, send_image_artist_query,
	send_image_playlist_query, send_image_album_query,
	album_too_long, track_too_long,
	max_download_user_msg
)

from utils.utils_data import (
	track_spo_data, track_dee_data,
	artist_dee_data, playlist_dee_data,
	playlist_spo_data, album_dee_data,
	album_spo_data, convert_spoty_to_dee_track
)

from configs.bot_settings import (
	bunker_channel, seconds_limits_album,
	seconds_limits_track, max_song_per_playlist,
	method_save, output_songs,
	recursive_quality, recursive_download,
	upload_max_size_user, user_errors,
	progress_status_rate, is_thread,
	max_download_user
)

bot = SetConfigs.tg_bot_api.bot
l_telegram, l_uploads, l_downloads, l_links = logging_bot()

# How long a cover_ok == 0 row is served before another refresh attempt, so
# permanently coverless content does not delete/download/upload on every request.
COVER_RETRY_COOLDOWN = 3600.0

def log_error(log, exc_info = False):
	l_downloads.error(log, exc_info = exc_info)

def start_download(chat_id, user_data, link, worker_class, args = ()):
	# One starter for every download kind (Deezer, Spotify and YouTube): the
	# per-user concurrency guard, the hash that /kill_dw sends back and the
	# c_downloads registration live here instead of being copied per flow.
	c_downloads = user_data['c_downloads']

	if len(c_downloads) == max_download_user:
		bot.send_message(
			chat_id = chat_id,
			text = max_download_user_msg
		)

		return False

	to_hash = f"{link}{user_data['quality']}{chat_id}{time()}".encode()
	hash_link = md5(to_hash).hexdigest()
	new_ins = worker_class(chat_id, user_data, hash_link)

	t = magicThread(
		target = new_ins.download,
		args = args
	)

	c_downloads[hash_link] = {
		"link": link,
		"thread": t,
		"dw": new_ins
	}

	t.start()

	return True

def delivered_has_cover(song_path, file_format):
	# The flag follows the delivered file, not the fetched bytes. A file the
	# parser cannot read reads as coverless instead of aborting the upload.
	try:
		return has_picture(song_path, file_format)
	except Exception:
		return False

class DW:
	def __init__(
		self,
		chat_id: int,
		user_data: dict,
		hash_link: int
	) -> None:

		self.__chat_id = chat_id
		self.__source = 1
		self.__quality = user_data['quality']
		self.__n_quality = get_quality_dee_s_quality(self.__quality)
		self.__send_to_user_tracks = user_data['tracks']
		self.__send_to_user_zips = user_data['zips']
		self.__hash_link = hash_link
		self.__c_download = user_data['c_downloads']
		self.__method_save = user_data['method_save']
		print (self.__method_save)

		if user_data['source'] == "SpoDee":
			conv = False
		else:
			conv = True

		self.__conv: bool = conv

	def __set_quality(self, link):
		netloc = get_netloc(link)

		if "spotify" in netloc:
			if self.__source == 2:
				return

			self.__source = 2
			self.__quality = get_quality_spo(self.__quality)
			self.__n_quality = get_quality_spo_s_quality(self.__quality)

	def __before_dw(self):
		SetConfigs.queues_started += 1

	def __after_dw(self):
		SetConfigs.queues_finished += 1

	def __finished(self):
		try:
			del self.__c_download[self.__hash_link]
		except KeyError:
			pass

	def __upload_audio(self, file_id):
		if self.__send_to_user_tracks:
			bot.send_chat_action(
				chat_id = self.__chat_id,
				action = ChatAction.UPLOAD_AUDIO
			)

			sleep(0.8)
			l_uploads.info(f"UPLOADING: {file_id}")

			bot.send_audio(
				chat_id = self.__chat_id,
				audio = file_id
			)

	def __upload_zip(self, file_id):
		if self.__send_to_user_zips:
			bot.send_chat_action(
				chat_id = self.__chat_id,
				action = ChatAction.UPLOAD_DOCUMENT
			)

			sleep(0.8)
			l_uploads.info(f"UPLOADING: {file_id}")

			bot.send_document(
				chat_id = self.__chat_id,
				document = file_id
			)

	def __upload_audio_track(self, track: Track):
		c_path = track.song_path
		track_md5 = track.track_md5
		md5_image = track.md5_image

		if self.__source == 1:
			image_bytes1 = fetch_thumb(
				md5_image,
				fallback_url = getattr(track, "cover_fallback_url", None),
				upc = track.tags.get("upc", "")
			).data
		elif self.__source == 2:
			image_bytes1 = request(track.tags['image3']).content

		thumb_io = make_thumb_io(image_bytes1, md5_image)
		duration = track.duration
		performer = track.artist
		title = track.music
		f_format = track.file_format
		tag = track.tags
		track_quality = track.quality

		file_name = set_path(tag, self.__n_quality, f_format, self.__method_save)

		if not isfile(c_path):
			bot.send_message(
				chat_id = self.__chat_id,
				text = f"Cannot download {track.link} :("
			)

			return False

		track_size = get_size(c_path, "gb")

		if track_size > upload_max_size_user:
			bot.send_message(
				chat_id = self.__chat_id,
				text = f"THE SONG {track.song_name} IS TOO BIG TO BE UPLOADED\
					, MAX {upload_max_size_user} GB\
					, CURRENT {track_size} GB :("
			)

			return False

		if track_quality != self.__n_quality:
			bot.send_message(
				chat_id = self.__chat_id,
				text = (
					f"⚠ The {title} - {performer} can't be downloaded in {self.__quality} quality :( ⚠\
					\nIT HAS BEEN DOWNLOADED IN {track_quality}"
				)
			)

		file_id = SetConfigs.tg_user_api.send_audio(
			chat_id = bunker_channel,
			audio = c_path,
			thumb = thumb_io,
			duration = duration,
			performer = performer,
			title = title,
			file_name = file_name
		)

		if file_id.audio:
			file_id = file_id.audio.file_id
		else:
			return False

		write_db(
			track_md5, file_id,
			track_quality, self.__chat_id, self.__method_save,
			1 if delivered_has_cover(c_path, f_format) else 0
		)

		self.__upload_audio(file_id)

		# Delivery signal: True only when the upload actually landed; the
		# cover-refresh guard serves the cached file_id when it did not.
		return True

	def __download_track(self, url, cover_fallback_url = None):
		try:
			if "deezer" in url:
				track = SetConfigs.deez_api.download_trackdee(
					url,
					output_dir = output_songs,
					quality_download = self.__quality,
					recursive_quality = recursive_quality,
					recursive_download = recursive_download,
					method_save = self.__method_save,
					cover_fallback_url = cover_fallback_url
				)

			elif "spotify" in url:
				track = SetConfigs.spot_api.download_track(
					url,
					output_dir = output_songs,
					quality_download = self.__quality,
					recursive_quality = recursive_quality,
					recursive_download = recursive_download,
					method_save = self.__method_save,
					is_thread = is_thread
				)
		except TrackNotFound as error:
			log_error(error, exc_info = True)

			bot.send_message(
				chat_id = self.__chat_id,
				text = f"Cannot download {url} :("
			)

			return False

		progress_message_id = bot.send_message(
			chat_id = self.__chat_id,
			text = f"Starting uploading {track.song_name} ..."
		).message_id

		delivered = self.__upload_audio_track(track)

		bot.delete_message(
			chat_id = self.__chat_id,
			message_id = progress_message_id
		)

		return delivered

	def __progress_status(self, current, total, times, album_name):
		c_time = times[0]

		if current == total:
			msg_id = times[1]

			bot.delete_message(
				chat_id = self.__chat_id,
				message_id = msg_id
			)

		if (c_time % progress_status_rate == 0):
			c_progress = f"{current * 100 / total:.1f}%"
			c_text = f"Uploading {album_name}: {c_progress}"
			l_uploads.info(c_text)

			if c_time == 0:
				msg_id = bot.send_message(
					chat_id = self.__chat_id,
					text = c_text
				).message_id

				times.append(msg_id)
			else:
				msg_id = times[1]

				try:
					bot.edit_message_text(
						chat_id = self.__chat_id,
						message_id = msg_id,
						text = c_text
					)
				except BadRequest:
					pass

		times[0] += 1

	def __upload_zip_album(self, album: Album):
		times = [0]
		album_name = album.album_name
		md5_image = album.md5_image

		if self.__source == 1:
			image_bytes2 = fetch_thumb(
				md5_image,
				fallback_url = getattr(album, "cover_fallback_url", None),
				upc = album.upc or "",
				size = "320x320"
			).data
		elif self.__source == 2:
			image_bytes2 = request(album.tags['image2']).content

		thumb_io = make_thumb_io(image_bytes2, md5_image)
		progress_args = (times, album_name)
		path_zip = album.zip_path
		album_md5 = album.album_md5
		zip_size = get_size(path_zip, "gb")
		album_quality = album.tracks[0].quality

		if zip_size > upload_max_size_user:
			bot.send_message(
				chat_id = self.__chat_id,
				text = f"THE ZIP IS TOO BIG TO BE UPLOADED\
					, MAX {upload_max_size_user} GB\
					, CURRENT {zip_size} GB :("
			)

			# TOO BIG rows keep cover_ok NULL: no upload happened
			write_db(
				album_md5, "TOO BIG",
				album_quality, self.__chat_id, self.__method_save
			)

			return False

		file_id = SetConfigs.tg_user_api.send_document(
			chat_id = bunker_channel,
			document = path_zip,
			thumb = thumb_io,
			progress = self.__progress_status,
			progress_args = progress_args
		).document.file_id

		write_db(
			album_md5, file_id,
			album_quality, self.__chat_id, self.__method_save,
			# the zip's artwork is the album image carried by the document
			1 if album.image else 0
		)

		self.__upload_zip(file_id)

		# Delivery signal: the zip really landed in the bunker channel.
		return True

	def __upload_audio_album(
		self,
		track: Track,
		image_bytes1,
		num_track, nb_tracks,
		progress_message_id
	):
		c_path = track.song_path
		track_md5 = track.track_md5
		thumb_io = make_thumb_io(image_bytes1, track_md5)
		duration = track.duration
		performer = track.artist
		title = track.music
		f_format = track.file_format
		tag = track.tags
		file_name = set_path(tag, self.__n_quality, f_format, self.__method_save)
		c_progress = f"Uploading ({num_track}/{nb_tracks}): {title}"
		c_progress += f" {num_track * 100 / nb_tracks:.1f}%"
		l_uploads.info(c_progress)

		bot.edit_message_text(
			chat_id = self.__chat_id,
			message_id = progress_message_id,
			text = c_progress
		)

		if track.success:
			if not isfile(c_path):
				bot.send_message(
					chat_id = self.__chat_id,
					text = f"Cannot download {track.link} :("
				)

				return
	
			track_size = get_size(c_path, "gb")

			if track_size > upload_max_size_user:
				bot.send_message(
					chat_id = self.__chat_id,
					text = f"THE SONG {track.song_name} IS TOO BIG TO BE UPLOADED\
						, MAX {upload_max_size_user} GB\
						, CURRENT {track_size} GB :("
				)

				return

			track_quality = track.quality

			if track_quality != self.__n_quality:
				bot.send_message(
					chat_id = self.__chat_id,
					text = (
						f"⚠ The {title} - {performer} can't be downloaded in {self.__quality} quality :( ⚠\
						\nIT HAS BEEN DOWNLOADED IN {track_quality}"
					)
				)

			file_id = SetConfigs.tg_user_api.send_audio(
				chat_id = bunker_channel,
				audio = c_path,
				thumb = thumb_io,
				duration = duration,
				performer = performer,
				title = title,
				file_name = file_name
			)

			if file_id.audio:
				file_id = file_id.audio.file_id
			else:
				return

			write_db(
				track_md5, file_id,
				track_quality, self.__chat_id, self.__method_save,
				1 if delivered_has_cover(c_path, f_format) else 0
			)

			self.__upload_audio(file_id)
		else:
			bot.send_message(
				chat_id = self.__chat_id,
				text = f"Cannot download {track.song_name} :("
			)

	def __download_album(self, url, cover_fallback_url = None):
		progress_message_id = bot.send_message(
			chat_id = self.__chat_id,
			text = "Downloading album, this may take a while..."
		).message_id

		try:
			if "deezer" in url:
				album = SetConfigs.deez_api.download_albumdee(
					url,
					output_dir = output_songs,
					quality_download = self.__quality,
					recursive_quality = recursive_quality,
					recursive_download = recursive_download,
					make_zip = SetConfigs.create_zips,
					method_save = self.__method_save,
					cover_fallback_url = cover_fallback_url
				)

			elif "spotify" in url:
				album = SetConfigs.spot_api.download_album(
					url,
					output_dir = output_songs,
					quality_download = self.__quality,
					recursive_quality = recursive_quality,
					recursive_download = recursive_download,
					make_zip = SetConfigs.create_zips,
					method_save = self.__method_save,
					is_thread = is_thread
				)
		except Exception:
			try:
				bot.delete_message(
					chat_id = self.__chat_id,
					message_id = progress_message_id
				)
			except BadRequest:
				pass

			raise

		md5_image = album.md5_image
		nb_tracks = album.nb_tracks

		if self.__source == 1:
			image_bytes1 = fetch_thumb(
				md5_image,
				fallback_url = getattr(album, "cover_fallback_url", None),
				upc = album.upc or ""
			).data
		elif self.__source == 2:
			image_bytes1 = request(album.tags['image3']).content

		num_track = 1

		try:
			bot.edit_message_text(
				chat_id = self.__chat_id,
				message_id = progress_message_id,
				text = "Starting uploading..."
			)
		except BadRequest:
			pass

		for track in album.tracks:
			self.__upload_audio_album(
				track, image_bytes1, num_track,
				nb_tracks, progress_message_id
			)

			num_track += 1

		bot.delete_message(
			chat_id = self.__chat_id,
			message_id = progress_message_id
		)

		if SetConfigs.create_zips:
			return self.__upload_zip_album(album)
		else:
			# no zip is uploaded here either: keep the row legacy-trusted
			write_db(
				album.album_md5, "TOO BIG",
				self.__quality, self.__chat_id, self.__method_save
			)

			return False

	def __send_for_debug(self, link, error):
		err_str = f"ERROR WITH THIS LINK {link} {self.__quality}"

		bot.send_message(
			chat_id = self.__chat_id,
			text = err_str
		)

		sleep(0.1)

		bot.send_message(
			chat_id = user_errors,
			text = err_str
		)

		log_error(error, exc_info = True)
		log_error(err_str)

	def __cover_cooldown_active(self, cover_attempted_at):
		if cover_attempted_at is None:
			return False

		return time() - cover_attempted_at < COVER_RETRY_COOLDOWN

	def __serve_or_refresh(self, link, match, recover, serve, retry):
		# One rule for all three cache sites: a NULL (legacy) or covered row is
		# served as before; a cover_ok == 0 row is refreshed in place, keeping
		# the cached file_id servable until the replacement lands.
		# Returns (delivered, refreshed).
		file_id, cover_ok, cover_attempted_at = match

		if cover_ok == 0:
			if self.__cover_cooldown_active(cover_attempted_at):
				l_downloads.info(
					f"cover refresh deferred for {link} (cooldown)"
				)
			else:
				l_downloads.info(f"cover refresh attempted for {link}")

				try:
					# the recovery upload writes the replacement row itself and reports True
					# only when it landed: a non-raising recovery is not success
					if recover():
						return True, True
				except Exception as error:
					l_downloads.warning(
						f"cover refresh failed for {link}: {error!r}, serving cached file_id"
					)

					# fall through: the old file_id is still servable

		try:
			serve(file_id)

			return True, False
		except BadRequest:
			delete_dwsongs(file_id)

			return bool(retry()), False

	def __check_track(self, link, cover_fallback_url = None):
		self.__set_quality(link)
		link_path = get_url_path(link)
		match = select_dwsongs(link_path, self.__n_quality, self.__method_save)

		if match:
			# True when the user got audio (landed replacement or cached file_id).
			return self.__serve_or_refresh(
				link, match,
				lambda: self.__download_track(link, cover_fallback_url = cover_fallback_url),
				lambda file_id: self.__upload_audio(file_id),
				lambda: self.__check_track(link, cover_fallback_url = cover_fallback_url)
			)[0]
		else:
			try:
				return self.__download_track(link, cover_fallback_url = cover_fallback_url)
			except Exception as error:
				self.__send_for_debug(link, error)

				return False

	def __check_album(self, link, tracks, cover_fallback_url = None):
		self.__set_quality(link)
		link_path = get_url_path(link)
		match = select_dwsongs(link_path, self.__n_quality, self.__method_save)

		if match:
			# TOO BIG marks a zip that was never uploaded: nothing to serve
			delivered = False
			refreshed = False

			if match[0] != "TOO BIG":
				delivered, refreshed = self.__serve_or_refresh(
					link, match,
					lambda: self.__download_album(link, cover_fallback_url = cover_fallback_url),
					lambda zip_id: self.__upload_zip(zip_id),
					lambda: self.__check_album(link, tracks, cover_fallback_url = cover_fallback_url)
				)

			# a refreshed album was downloaded whole, tracks included: the per-track
			# loop would upload every one of them a second time
			if self.__send_to_user_tracks and not refreshed:
				for track in tracks:
					if self.__source == 1:
						c_link = track['link']
					elif self.__source == 2:
						c_link = track['external_urls']['spotify']

					c_link_path = get_url_path(c_link)
					c_match = select_dwsongs(c_link_path, self.__n_quality, self.__method_save)

					if not c_match:
						bot.send_message(
							chat_id = self.__chat_id,
							text = f"The song {c_link} isn't avalaible :("
						)

						continue

					self.__serve_or_refresh(
						c_link, c_match,
						lambda: self.__check_track(c_link, cover_fallback_url = cover_fallback_url),
						lambda track_id: self.__upload_audio(track_id),
						lambda: self.__check_track(c_link, cover_fallback_url = cover_fallback_url)
					)

			return delivered
		else:
			try:
				return self.__download_album(link, cover_fallback_url = cover_fallback_url)
			except Exception as error:
				self.__send_for_debug(link, error)

				return False

	def __send_photo(
		self, chat_id,
		image_url, caption,
		reply_markup = None
	):
		# image_url may be None or dead: Telegram answers BadRequest, and a
		# malformed value raises ValueError. Fall back to a text Message so the
		# caller's .message_id keeps working.
		try:
			return bot.send_photo(
				chat_id = chat_id,
				photo = image_url,
				caption = caption,
				reply_markup = reply_markup
			)
		except (BadRequest, ValueError):
			return bot.send_message(
				chat_id = chat_id,
				text = caption,
				reply_markup = reply_markup
			)

	def download(self, link):
		try:
			l_links.info(link)
			stat = 1
			self.__before_dw()
			link = what_kind(link)

			if "track/" in link:
				if "spotify.com" in link:
					try:
						image_url, name,\
							artist, album,\
								date, link_dee, duration,\
									cover_fallback_url = track_spo_data(link, self.__conv)
					except TrackNotFound:
						bot.send_message(
							chat_id = self.__chat_id,
							text = f"Cannot download {link} :("
						)

						return

					# The Spotify carrier is a live CDN URL; the search card's image URL is a
					# dead-host template for the same album.
					image_url = cover_fallback_url or image_url

				elif "deezer.com" in link:
					image_url, name,\
						artist, album,\
							date, link_dee, duration = track_dee_data(link)

					cover_fallback_url = None

				if duration > seconds_limits_track:
					bot.send_message(
						chat_id = self.__chat_id,
						text = track_too_long
					)

					return

				caption = (
					send_image_track_query
					% (
						name,
						artist,
						album,
						date
					)
				)

				msg_id = self.__send_photo(
					self.__chat_id, image_url, caption
				).message_id

				self.__check_track(link_dee, cover_fallback_url = cover_fallback_url)

			elif "artist/" in link:
				stat = 0

				if "deezer.com" in link:
					name, image_url,\
						nb_album, nb_fan = artist_dee_data(link)
				else:
					return

				caption = (
					send_image_artist_query
					% (
						name,
						nb_album,
						nb_fan
					)
				)

				reply_markup = create_keyboard_artist(link)

				msg_id = self.__send_photo(
					self.__chat_id, image_url, caption,
					reply_markup = reply_markup
				).message_id

			elif "album/" in link:
				if "spotify.com" in link:
					image_url, album,\
						artist, date,\
						nb_tracks, tracks,\
						duration, link_dee,\
							cover_fallback_url = album_spo_data(link, self.__conv)

					# Same as the track card: prefer the live Spotify CDN URL.
					image_url = cover_fallback_url or image_url

				elif "deezer.com" in link:
					image_url, album,\
						artist, date,\
						nb_tracks, tracks,\
						duration, link_dee = album_dee_data(link)

					cover_fallback_url = None

				if duration > seconds_limits_album:
					bot.send_message(
						chat_id = self.__chat_id,
						text = album_too_long
					)

					return

				caption = (
					send_image_album_query
					% (
						album,
						artist,
						date,
						nb_tracks
					)
				)

				msg_id = self.__send_photo(
					self.__chat_id, image_url, caption
				).message_id

				self.__check_album(link_dee, tracks, cover_fallback_url = cover_fallback_url)

			elif "playlist/" in link:
				if "spotify.com" in link:
					mode = "spotify"

					try:
						nb_tracks, n_fans,\
							image_url, creation_data,\
								creator, tracks = playlist_spo_data(link)
					except IndexError:
						bot.send_message(
							chat_id = self.__chat_id,
							text = f"This playlist is unreadable :("
						)

						return

				elif "deezer.com" in link:
					mode = "deezer"

					nb_tracks, n_fans,\
						image_url, creation_data,\
							creator, tracks = playlist_dee_data(link)

				caption = (
					send_image_playlist_query
					% (
						creation_data,
						creator,
						nb_tracks,
						n_fans
					)
				)

				msg_id = self.__send_photo(
					self.__chat_id, image_url, caption
				).message_id

				if nb_tracks > max_song_per_playlist:
					bot.send_message(
						chat_id = self.__chat_id,
						text = f"This playlist contains {nb_tracks} tracks only the first {max_song_per_playlist} will be downloaded"
					)

				for track, index in zip(
					tracks, range(max_song_per_playlist)
				):
					c_cover = None

					if mode == "deezer":
						c_link = track['link']

					elif mode == "spotify":
						c_track = track['track']

						if not c_track:
							continue

						external_urls = c_track['external_urls']

						if not external_urls:
							bot.send_message(
								chat_id = self.__chat_id,
								text = f"The track \"{c_track['name']}\" is not avalaible on Spotify :("
							)

							continue

						c_link = external_urls['spotify']

						if self.__conv:
							try:
								c_link, c_cover = convert_spoty_to_dee_track(c_link)
							except (NoDataApi, TrackNotFound):
								bot.send_message(
									chat_id = self.__chat_id,
									text = f"Cannot download {c_link} :("
								)

								continue

					self.__check_track(c_link, cover_fallback_url = c_cover)

			else:
				bot.send_message(
					chat_id = self.__chat_id,
					text = "Can you just send normal links?, THANKS :)"
				)

				return

			if stat == 1:
				bot.send_message(
					chat_id = self.__chat_id,
					text = "FINISHED =)",
					reply_to_message_id = msg_id
				)
		except AlbumNotFound as error:
			bot.send_message(
				chat_id = self.__chat_id,
				text = error.msg
			)
		except (NoDataApi, InvalidLink) as error:
			if type(error) is NoDataApi:
				text = f"This {link} doesn't exist :("

			elif type(error) is InvalidLink:
				text = f"INVALID LINK {link} :("

			bot.send_message(
				chat_id = self.__chat_id,
				text = text
			)
		except Exception as error:
			try:
				self.__send_for_debug(link, error)
			except Exception as error:
				log_error(f"{link} {self.__quality} {self.__chat_id}")
				log_error(error, exc_info = True)
		finally:
			self.__after_dw()
			self.__finished()