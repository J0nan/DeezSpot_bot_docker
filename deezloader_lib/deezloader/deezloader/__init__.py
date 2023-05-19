#!/usr/bin/python3

from .dee_api import API
from ..easy_spoty import Spo
from .deegw_api import API_GW
from .deezer_settings import stock_quality

from ..models import (
	Track, Album, Playlist,
	Preferences, Smart
)

from .__download__ import (
	DW_TRACK, DW_ALBUM, DW_PLAYLIST
)

from ..exceptions import (
	InvalidLink, TrackNotFound,
	NoDataApi, AlbumNotFound
)

from ..libutils.utils import (
	create_zip, get_ids,
	link_is_valid, what_kind
)

from ..libutils.others_settings import (
	stock_output, stock_recursive_quality,
	stock_recursive_download, stock_not_interface,
	stock_zip, method_save
)

Spo()
API()

class DeeLogin:
	def __init__(
		self,
		arl = None,
		email = None,
		password = None
	) -> None:

		if arl:
			self.__gw_api = API_GW(arl = arl)
		else:
			self.__gw_api = API_GW(
				email = email,
				password = password
			)

	def download_trackdee(
		self, link_track,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		method_save = method_save
	) -> Track:

		link_is_valid(link_track)
		ids = get_ids(link_track)

		try:
			song_metadata = API.tracking(ids)
		except NoDataApi:
			infos = self.__gw_api.get_song_data(ids)

			if not "FALLBACK" in infos:
				raise TrackNotFound(link_track)

			ids = infos['FALLBACK']['SNG_ID']
			song_metadata = API.tracking(ids)

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

		track = DW_TRACK(preferences).dw()

		return track

	def download_albumdee(
		self, link_album,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		make_zip = stock_zip,
		method_save = method_save
	) -> Album:

		link_is_valid(link_album)
		ids = get_ids(link_album)

		try:
			album_json = API.get_album(ids)
		except NoDataApi:
			raise AlbumNotFound(link_album)

		song_metadata = API.tracking_album(album_json)

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

		album = DW_ALBUM(preferences).dw()

		return album

	def download_playlistdee(
		self, link_playlist,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		make_zip = stock_zip,
		method_save = method_save
	) -> Playlist:

		link_is_valid(link_playlist)
		ids = get_ids(link_playlist)

		song_metadata = []
		playlist_json = API.get_playlist(ids)

		for track in playlist_json['tracks']['data']:
			c_ids = track['id']

			try:
				c_song_metadata = API.tracking(c_ids)
			except NoDataApi:
				infos = self.__gw_api.get_song_data(c_ids)

				if not "FALLBACK" in infos:
					c_song_metadata = f"{track['title']} - {track['artist']['name']}"
				else:
					c_song_metadata = API.tracking(c_ids)

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

		playlist = DW_PLAYLIST(preferences).dw()

		return playlist

	def download_artisttopdee(
		self, link_artist,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface
	) -> list[Track]:

		link_is_valid(link_artist)
		ids = get_ids(link_artist)

		playlist_json = API.get_artist_top_tracks(ids)['data']

		names = [
			self.download_trackdee(
				track['link'], output_dir,
				quality_download, recursive_quality,
				recursive_download, not_interface
			)

			for track in playlist_json
		]

		return names

	def convert_spoty_to_dee_link_track(self, link_track):
		link_is_valid(link_track)
		ids = get_ids(link_track)

		track_json = Spo.get_track(ids)
		external_ids = track_json['external_ids']

		if not external_ids:
			msg = f"⚠ The track \"{track_json['name']}\" can't be converted to Deezer link :( ⚠"

			raise TrackNotFound(
				url = link_track,
				message = msg
			)

		isrc = f"isrc:{external_ids['isrc']}"

		track_json_dee = API.get_track(isrc)
		track_link_dee = track_json_dee['link']

		return track_link_dee

	def download_trackspo(
		self, link_track,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		method_save = method_save
	) -> Track:

		track_link_dee = self.convert_spoty_to_dee_link_track(link_track)

		track = self.download_trackdee(
			track_link_dee,
			output_dir = output_dir,
			quality_download = quality_download,
			recursive_quality = recursive_quality,
			recursive_download = recursive_download,
			not_interface = not_interface,
			method_save = method_save
		)

		return track

	def convert_spoty_to_dee_link_album(self, link_album):
		link_is_valid(link_album)
		ids = get_ids(link_album)
		link_dee = None

		tracks = Spo.get_album(ids)

		try:
			external_ids = tracks['external_ids']

			if not external_ids:
				raise AlbumNotFound

			upc = f"0{external_ids['upc']}"

			while upc[0] == "0":
				upc = upc[1:]

				try:
					upc = f"upc:{upc}"
					url = API.get_album(upc)
					link_dee = url['link']
					break
				except NoDataApi:
					if upc[0] != "0":
						raise AlbumNotFound
		except AlbumNotFound:
			tot = tracks['total_tracks']
			tracks = tracks['tracks']['items']
			tot2 = None

			for track in tracks:
				track_link = track['external_urls']['spotify']
				track_info = Spo.get_track(track_link)

				try:
					isrc = f"isrc:{track_info['external_ids']['isrc']}"
					track_data = API.get_track(isrc)

					if not "id" in track_data['album']:
						continue

					album_ids = track_data['album']['id']
					album_json = API.get_album(album_ids)
					tot2 = album_json['nb_tracks']

					if tot == tot2:
						link_dee = album_json['link']
						break
				except NoDataApi:
					pass

			if tot != tot2:
				raise AlbumNotFound(link_album)

		return link_dee

	def download_albumspo(
		self, link_album,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		make_zip = stock_zip,
		method_save = method_save
	) -> Album:

		link_dee = self.convert_spoty_to_dee_link_album(link_album)

		album = self.download_albumdee(
			link_dee, output_dir,
			quality_download, recursive_quality,
			recursive_download, not_interface,
			make_zip, method_save
		)

		return album

	def download_playlistspo(
		self, link_playlist,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		make_zip = stock_zip,
		method_save = method_save
	) -> Playlist:

		link_is_valid(link_playlist)
		ids = get_ids(link_playlist)

		playlist_json = Spo.get_playlist(ids)
		playlist_tracks = playlist_json['tracks']['items']
		playlist = Playlist()
		tracks = playlist.tracks

		for track in playlist_tracks:
			is_track = track['track']

			if not is_track:
				continue

			external_urls = is_track['external_urls']

			if not external_urls:
				print(f"The track \"{is_track['name']}\" is not avalaible on Spotify :(")
				continue

			link_track = external_urls['spotify']

			try:
				track = self.download_trackspo(
					link_track,
					output_dir = output_dir,
					quality_download = quality_download,
					recursive_quality = recursive_quality,
					recursive_download = recursive_download,
					not_interface = not_interface,
					method_save = method_save
				)
			except (TrackNotFound, NoDataApi):
				info = track['track']
				artist = info['artists'][0]['name']
				song = info['name']
				track = f"{song} - {artist}"

			tracks.append(track)

		if make_zip:
			playlist_name = playlist_json['name']
			zip_name = f"{output_dir}playlist {playlist_name}.zip"
			create_zip(tracks, zip_name = zip_name)
			playlist.zip_path = zip_name

		return playlist

	def download_name(
		self, artist, song,
		output_dir = stock_output,
		quality_download = stock_quality,
		recursive_quality = stock_recursive_quality,
		recursive_download = stock_recursive_download,
		not_interface = stock_not_interface,
		method_save = method_save
	) -> Track:

		query = f"track:{song} artist:{artist}"
		search = self.__spo.search(query)
		items = search['tracks']['items']

		if len(items) == 0:
			msg = f"No result for {query} :("
			raise TrackNotFound(message = msg)

		link_track = items[0]['external_urls']['spotify']

		track = self.download_trackspo(
			link_track,
			output_dir = output_dir,
			quality_download = quality_download,
			recursive_quality = recursive_quality,
			recursive_download = recursive_download,
			not_interface = not_interface,
			method_save = method_save
		)

		return track

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

		elif "deezer.com" in link:
			source = "https://deezer.com"

		smart.source = source

		if "track/" in link:
			if "spotify.com" in link:
				func = self.download_trackspo

			elif "deezer.com" in link:
				func = self.download_trackdee
				
			else:
				raise InvalidLink(link)

			track = func(
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
			if "spotify.com" in link:
				func = self.download_albumspo

			elif "deezer.com" in link:
				func = self.download_albumdee

			else:
				raise InvalidLink(link)

			album = func(
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
			if "spotify.com" in link:
				func = self.download_playlistspo

			elif "deezer.com" in link:
				func = self.download_playlistdee

			else:
				raise InvalidLink(link)

			playlist = func(
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