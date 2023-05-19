#!/usr/bin/python3

from os.path import isfile
from ..easy_spoty import Spo
from librespot.core import Session
from deezloader.exceptions import InvalidLink
from .__spo_api__ import tracking, tracking_album
from .spotify_settings import librespot_credentials, stock_quality

from ..libutils.utils import (
	get_ids, link_is_valid, what_kind
)

from ..models import (
	Track, Album,
	Playlist, Preferences, Smart
)

from .__download__ import (
	DW_TRACK, DW_ALBUM, DW_PLAYLIST,
	Download_JOB
)

from ..libutils.others_settings import (
	stock_output, stock_recursive_quality,
	stock_recursive_download, stock_not_interface,
	stock_zip, method_save, is_thread
)

Spo()

class SpoLogin:
	def __init__(
		self,
		email: str,
		pwd: str
	) -> None:

		__session = Session.Builder()
		__session.conf.stored_credentials_file = librespot_credentials

		if isfile(librespot_credentials):
			__session = __session.stored_file().create()
		else:
			__session = __session.user_pass(email, pwd).create()

		Download_JOB(__session)

	def download_track(
		self, link_track,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		method_save = method_save,
		is_thread = is_thread
	) -> Track:

		link_is_valid(link_track)
		ids = get_ids(link_track)
		song_metadata = tracking(ids)

		preferences = Preferences()

		preferences.link = link_track
		preferences.song_metadata = song_metadata
		preferences.quality_download = quality_download
		preferences.output_dir = output_dir
		preferences.ids = ids
		preferences.recursive_quality = recursive_quality
		preferences.recursive_download = recursive_download
		preferences.not_interface = not_interface
		preferences.method_save = method_save

		if not is_thread:
			track = DW_TRACK(preferences).dw()
		else:
			track = DW_TRACK(preferences).dw2()

		return track

	def download_album(
		self, link_album,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		make_zip = stock_zip,
		method_save = method_save,
		is_thread = is_thread
	) -> Album:

		link_is_valid(link_album)
		ids = get_ids(link_album)
		album_json = Spo.get_album(ids)
		song_metadata = tracking_album(album_json)

		preferences = Preferences()

		preferences.link = link_album
		preferences.song_metadata = song_metadata
		preferences.quality_download = quality_download
		preferences.output_dir = output_dir
		preferences.ids = ids
		preferences.json_data = album_json
		preferences.recursive_quality = recursive_quality
		preferences.recursive_download = recursive_download
		preferences.not_interface = not_interface
		preferences.method_save = method_save
		preferences.make_zip = make_zip

		if not is_thread:
			album = DW_ALBUM(preferences).dw()
		else:
			album = DW_ALBUM(preferences).dw2()

		return album

	def download_playlist(
		self, link_playlist,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		make_zip = stock_zip,
		method_save = method_save,
		is_thread = is_thread
	) -> Playlist:

		link_is_valid(link_playlist)
		ids = get_ids(link_playlist)

		song_metadata = []
		playlist_json = Spo.get_playlist(ids)

		for track in playlist_json['tracks']['items']:
			is_track = track['track']

			if not is_track:
				continue

			external_urls = is_track['external_urls']

			if not external_urls:
				c_song_metadata = f"The track \"{is_track['name']}\" is not avalaible on Spotify :("
			else:
				ids = get_ids(external_urls['spotify'])
				c_song_metadata = tracking(ids)

			song_metadata.append(c_song_metadata)

		preferences = Preferences()

		preferences.link = link_playlist
		preferences.song_metadata = song_metadata
		preferences.quality_download = quality_download
		preferences.output_dir = output_dir
		preferences.ids = ids
		preferences.json_data = playlist_json
		preferences.recursive_quality = recursive_quality
		preferences.recursive_download = recursive_download
		preferences.not_interface = not_interface
		preferences.method_save = method_save
		preferences.make_zip = make_zip

		if not is_thread:
			playlist = DW_PLAYLIST(preferences).dw()
		else:
			playlist = DW_PLAYLIST(preferences).dw2()

		return playlist

	def download_smart(
		self, link,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		make_zip = stock_zip,
		method_save = method_save
	) -> Smart:

		link_is_valid(link)
		link = what_kind(link)
		smart = Smart()

		if "spotify.com" in link:
			source = "https://spotify.com"

		smart.source = source

		if "track/" in link:
			if not "spotify.com" in link:
				raise InvalidLink(link)

			track = self.download_track(
				link,
				output_dir = output_dir,
				quality_download = quality_download,
				recursive_quality = recursive_quality,
				recursive_download = recursive_download,
				not_interface = not_interface,
				method_save = method_save
			)

			smart.type = "track"
			smart.track = track

		elif "album/" in link:
			if not "spotify.com" in link:
				raise InvalidLink(link)

			album = self.download_album(
				link,
				output_dir = output_dir,
				quality_download = quality_download,
				recursive_quality = recursive_quality,
				recursive_download = recursive_download,
				not_interface = not_interface,
				make_zip = make_zip,
				method_save = method_save
			)

			smart.type = "album"
			smart.album = album

		elif "playlist/" in link:
			if not "spotify.com" in link:
				raise InvalidLink(link)

			playlist = self.download_playlist(
				link,
				output_dir = output_dir,
				quality_download = quality_download,
				recursive_quality = recursive_quality,
				recursive_download = recursive_download,
				not_interface = not_interface,
				make_zip = make_zip,
				method_save = method_save
			)

			smart.type = "playlist"
			smart.playlist = playlist

		return smart