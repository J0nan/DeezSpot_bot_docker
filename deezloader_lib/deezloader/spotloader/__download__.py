#!/usr/bin/python3

from tqdm import tqdm
from copy import deepcopy
from os.path import isfile
from librespot.core import Session
from ..exceptions import TrackNotFound
from librespot.metadata import TrackId
from .spotify_settings import qualities
from ..libutils.others_settings import answers
from ..__taggers__ import write_tags, check_track
from librespot.audio.decoders import VorbisOnlyAudioQuality

from os import (
	remove, system,
	replace as os_replace
)

from ..models import (
	Track, Album,
	Playlist, Preferences,
)

from ..libutils.utils import (
	set_path, create_zip, request
)

class Download_JOB:

	@classmethod
	def __init__(cls, session: Session) -> None:
		cls.session = session

class EASY_DW:
	def __init__(
		self,
		preferences: Preferences
	) -> None:

		self.__ids = preferences.ids
		self.__link = preferences.link
		self.__output_dir = preferences.output_dir
		self.__method_save = preferences.method_save
		self.__song_metadata = preferences.song_metadata
		self.__not_interface = preferences.not_interface
		self.__quality_download = preferences.quality_download
		self.__recursive_download = preferences.recursive_download

		self.__c_quality = qualities[self.__quality_download]
		self.__fallback_ids = self.__ids

		self.__set_quality()
		self.__write_track()

	def __set_quality(self) -> None:
		self.__dw_quality = self.__c_quality['n_quality']
		self.__file_format = self.__c_quality['f_format']
		self.__song_quality = self.__c_quality['s_quality']

	def __set_song_path(self) -> None:
		self.__song_path = set_path(
			self.__song_metadata,
			self.__output_dir,
			self.__song_quality,
			self.__file_format,
			self.__method_save
		)

	def __write_track(self) -> None:
		self.__set_song_path()

		self.__c_track = Track(
			self.__song_metadata, self.__song_path,
			self.__file_format, self.__song_quality,
			self.__link, self.__ids
		)

		self.__c_track.md5_image = self.__ids
		self.__c_track.set_fallback_ids(self.__fallback_ids)

	def __convert_audio(self) -> None:
		temp_filename = self.__song_path.replace(".ogg", ".tmp")
		os_replace(self.__song_path, temp_filename)
		ffmpeg_cmd = f"ffmpeg -y -hide_banner -loglevel error -i \"{temp_filename}\" -c:a copy \"{self.__song_path}\""
		system(ffmpeg_cmd)
		remove(temp_filename)

	def get_no_dw_track(self) -> Track:
		return self.__c_track

	def easy_dw(self) -> Track:
		pic = self.__song_metadata['image']
		image = request(pic).content
		self.__song_metadata['image'] = image
		song = f"{self.__song_metadata['music']} - {self.__song_metadata['artist']}"

		if not self.__not_interface:
			print(f"Downloading: {song}")

		self.download_try()

		return self.__c_track

	def download_try(self) -> Track:
		if isfile(self.__song_path) and check_track(self.__c_track):
			if self.__recursive_download:
				return self.__c_track

			ans = input(
				f"Track \"{self.__song_path}\" already exists, do you want to redownload it?(y or n):"
			)

			if not ans in answers:
				return self.__c_track

		track_id = TrackId.from_base62(self.__ids)

		try:
			stream = Download_JOB.session.content_feeder().load_track(
				track_id,
				VorbisOnlyAudioQuality(self.__dw_quality),
				False,
				None
			)
		except RuntimeError:
			raise TrackNotFound(self.__link)

		total_size = stream.input_stream.size

		with open(self.__song_path, "wb") as f:
			c_stream = stream.input_stream.stream()
			data = c_stream.read(total_size)
			c_stream.close()
			f.write(data)

		self.__convert_audio()
		write_tags(self.__c_track)

		return self.__c_track

def download_cli(preferences: Preferences) -> None:
	__link = preferences.link
	__output_dir = preferences.output_dir
	__method_save = preferences.method_save
	__not_interface = preferences.not_interface
	__quality_download = preferences.quality_download
	__recursive_download = preferences.recursive_download
	__recursive_quality = preferences.recursive_quality

	cmd = f"deez-dw.py -so spo -l \"{__link}\" "

	if __output_dir:
		cmd += f"-o {__output_dir} "
	if __method_save:
		cmd += f"-sa {__method_save} "
	if __not_interface:
		cmd += f"-g "
	if __quality_download:
		cmd += f"-q {__quality_download} "
	if __recursive_download:
		cmd += f"-rd "
	if __recursive_quality:
		cmd += f"-rq"

	system(cmd)

class DW_TRACK:
	def __init__(
		self,
		preferences: Preferences
	) -> None:

		self.__preferences = preferences

	def dw(self) -> Track:
		track = EASY_DW(self.__preferences).easy_dw()

		return track

	def dw2(self) -> Track:
		track = EASY_DW(self.__preferences).get_no_dw_track()
		download_cli(self.__preferences)

		return track

class DW_ALBUM:
	def __init__(
		self,
		preferences: Preferences
	) -> None:

		self.__preferences = preferences
		self.__ids = self.__preferences.ids
		self.__make_zip = self.__preferences.make_zip
		self.__output_dir = self.__preferences.output_dir
		self.__method_save = self.__preferences.method_save
		self.__song_metadata = self.__preferences.song_metadata
		self.__not_interface = self.__preferences.not_interface

		self.__song_metadata_items = self.__song_metadata.items()

	def dw(self) -> Album:
		pic = self.__song_metadata['image']
		image = request(pic).content
		self.__song_metadata['image'] = image

		album = Album(self.__ids)
		album.image = image
		album.nb_tracks = self.__song_metadata['nb_tracks']
		album.album_name = self.__song_metadata['album']
		album.upc = self.__song_metadata['upc']
		tracks = album.tracks
		album.md5_image = self.__ids
		album.tags = self.__song_metadata

		c_song_metadata = {}

		for key, item in self.__song_metadata_items:
			if type(item) is not list:
				c_song_metadata[key] = self.__song_metadata[key]

		t = tqdm(
			range(album.nb_tracks),
			desc = c_song_metadata['album'],
			disable = self.__not_interface
		)

		for a in t:
			for key, item in self.__song_metadata_items:
				if type(item) is list:
					c_song_metadata[key] = self.__song_metadata[key][a]

			song = f"{c_song_metadata['music']} - {c_song_metadata['artist']}"
			t.set_description_str(song)
			c_preferences = deepcopy(self.__preferences)
			c_preferences.song_metadata = c_song_metadata.copy()
			c_preferences.ids = c_song_metadata['ids']
			c_preferences.link = f"https://open.spotify.com/track/{c_preferences.ids}"
	
			try:
				track = EASY_DW(c_preferences).download_try()
			except TrackNotFound:
				track = Track(
					c_song_metadata,
					None, None,
					None, None, None,
				)

				track.success = False
				print(f"Track not found: {song} :(")

			tracks.append(track)

		if self.__make_zip:
			song_quality = tracks[0].quality

			zip_name = create_zip(
				tracks,
				output_dir = self.__output_dir,
				song_metadata = self.__song_metadata,
				song_quality = song_quality,
				method_save = self.__method_save
			)

			album.zip_path = zip_name

		return album

	def dw2(self) -> Album:
		pic = self.__song_metadata['image']
		image = request(pic).content
		self.__song_metadata['image'] = image

		album = Album(self.__ids)
		album.image = image
		album.nb_tracks = self.__song_metadata['nb_tracks']
		album.album_name = self.__song_metadata['album']
		album.upc = self.__song_metadata['upc']
		tracks = album.tracks
		album.md5_image = self.__ids
		album.tags = self.__song_metadata

		c_song_metadata = {}

		for key, item in self.__song_metadata_items:
			if type(item) is not list:
				c_song_metadata[key] = self.__song_metadata[key]

		t = tqdm(
			range(album.nb_tracks),
			desc = c_song_metadata['album'],
			disable = True
		)

		for a in t:
			for key, item in self.__song_metadata_items:
				if type(item) is list:
					c_song_metadata[key] = self.__song_metadata[key][a]

			song = f"{c_song_metadata['music']} - {c_song_metadata['artist']}"
			t.set_description_str(song)
			c_preferences = deepcopy(self.__preferences)
			c_preferences.song_metadata = c_song_metadata.copy()
			c_preferences.ids = c_song_metadata['ids']
			c_preferences.link = f"https://open.spotify.com/track/{c_preferences.ids}"
	
			track = EASY_DW(c_preferences).get_no_dw_track()

			tracks.append(track)

		download_cli(self.__preferences)

		if self.__make_zip:
			song_quality = tracks[0].quality

			zip_name = create_zip(
				tracks,
				output_dir = self.__output_dir,
				song_metadata = self.__song_metadata,
				song_quality = song_quality,
				method_save = self.__method_save
			)

			album.zip_path = zip_name

		return album

class DW_PLAYLIST:
	def __init__(
		self,
		preferences: Preferences
	) -> None:

		self.__preferences = preferences
		self.__ids = self.__preferences.ids
		self.__json_data = preferences.json_data
		self.__make_zip = self.__preferences.make_zip
		self.__output_dir = self.__preferences.output_dir
		self.__song_metadata = self.__preferences.song_metadata

	def dw(self) -> Playlist:
		playlist = Playlist()
		tracks = playlist.tracks

		for c_song_metadata in self.__song_metadata:
			if type(c_song_metadata) is str:
				print(f"Track not found {c_song_metadata} :(")
				continue

			c_preferences = deepcopy(self.__preferences)
			c_preferences.ids = c_song_metadata['ids']
			c_preferences.song_metadata = c_song_metadata

			track = EASY_DW(c_preferences).easy_dw()

			if not track.success:
				song = f"{c_song_metadata['music']} - {c_song_metadata['artist']}"
				print(f"Cannot download {song}")

			tracks.append(track)

		if self.__make_zip:
			playlist_title = self.__json_data['name']
			zip_name = f"{self.__output_dir}/{playlist_title} [playlist {self.__ids}]"
			create_zip(tracks, zip_name = zip_name)
			playlist.zip_path = zip_name

		return playlist

	def dw2(self) -> Playlist:
		playlist = Playlist()
		tracks = playlist.tracks

		for c_song_metadata in self.__song_metadata:
			if type(c_song_metadata) is str:
				print(f"Track not found {c_song_metadata} :(")
				continue

			c_preferences = deepcopy(self.__preferences)
			c_preferences.ids = c_song_metadata['ids']
			c_preferences.song_metadata = c_song_metadata

			track = EASY_DW(c_preferences).get_no_dw_track()

			if not track.success:
				song = f"{c_song_metadata['music']} - {c_song_metadata['artist']}"
				print(f"Cannot download {song}")

			tracks.append(track)

		download_cli(self.__preferences)

		if self.__make_zip:
			playlist_title = self.__json_data['name']
			zip_name = f"{self.__output_dir}/{playlist_title} [playlist {self.__ids}]"
			create_zip(tracks, zip_name = zip_name)
			playlist.zip_path = zip_name

		return playlist