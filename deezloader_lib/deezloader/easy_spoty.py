#!/usr/bin/python3

from spotipy import Spotify
from .exceptions import InvalidLink
from spotapi import SyncCatalogue, SpotAPIError
from spotipy.exceptions import SpotifyException
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyClientCredentials

try:
    # Prefer project config when running inside the bot
    from configs.bot_settings import (
        spotify_client_id,
        spotify_client_secret,
        spotify_cache_file
    )
except Exception:
    # Fallback for package/CLI usage
    import os
    spotify_client_id = os.environ.get("SPOTIFY_CLIENT_ID", "c6b23f1e91f84b6a9361de16aba0ae17")
    spotify_client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "237e355acaa24636abc79f1a089e6204")
    spotify_cache_file = os.environ.get("SPOTIFY_CACHE_FILE", ".cache-spotipy")

class Spo:
	__error_codes = [404, 400]

	@classmethod
	def __init__(cls):
		cls.__api = Spotify(
			client_credentials_manager = cls.__generate_token()
		)

	@staticmethod
	def __generate_token():
		return SpotifyClientCredentials(
			client_id = spotify_client_id,
			client_secret = spotify_client_secret,
			cache_handler = CacheFileHandler(spotify_cache_file),
		)

	@classmethod
	def __lazy(cls, results):
		albums = results['items']

		while results['next']:
			results = cls.__api.next(results)
			albums.extend(results['items'])

		return results

	@staticmethod
	def __map_playlist_track(entry):
		item = entry.item
		uri = getattr(item, 'uri', None) or ''

		if not uri.startswith('spotify:track:'):
			# Episodes, local files and removed tracks cannot be
			# downloaded, so they map to None like spotipy does.
			return None

		ids = uri.split(':')[-1]
		artists = [
			{
				'name': artist.profile.name
			}

			for artist in (getattr(item.artists, 'items', None) or [])
			if getattr(getattr(artist, 'profile', None), 'name', None)
		]
		name = getattr(item, 'name', None) or 'Unknown'

		return {
			'added_at': getattr(entry, 'added_at', None),
			'track': {
				'name': name,
				'artists': artists or [{'name': 'Unknown'}],
				'external_urls': {
					'spotify': f"https://open.spotify.com/track/{ids}"
				}
			}
		}

	@staticmethod
	def __map_playlist_images(details):
		sources = []

		for image in (getattr(details.images, 'items', None) or []):
			c_sources = getattr(image, 'sources', None) or []

			if c_sources:
				big = max(
					c_sources,
					key = lambda source: getattr(source, 'width', 0) or 0
				)
				sources.append({'url': big.url})

		return sources

	@classmethod
	def get_playlist(cls, ids):
		# SpotAPI 2 serves the whole playlist (no 100-track cap) through
		# anonymous web-player queries. Its typed models are mapped back
		# to the spotipy shape the downloaders already consume.
		try:
			# One scoped client per call: the runner owns an event loop
			# in the calling thread, so it must not be shared between
			# the download worker threads. The item pages are consumed
			# inside the scope because the generator borrows it.
			with SyncCatalogue() as client:
				playlist = client.get_playlist(ids)
				items = [
					entry
					for page in client.get_playlist_items(ids)
					for entry in page
				]
		except (SpotAPIError, ValueError):
			raise InvalidLink(ids)

		mapped_tracks = [
			mapped for mapped in map(cls.__map_playlist_track, items)
			if mapped is not None
		]

		owner = getattr(getattr(playlist, 'owner_v2', None), 'data', None)
		content = getattr(playlist, 'content', None)
		total = getattr(content, 'total_count', None)

		if total is None:
			total = len(mapped_tracks)

		playlist_json = {
			'name': getattr(playlist, 'name', None) or 'Unknown',
			'owner': {
				'display_name': getattr(owner, 'name', None) or 'Unknown'
			},
			'followers': {
				'total': getattr(playlist, 'followers', None) or 0
			},
			'images': cls.__map_playlist_images(playlist),
			'tracks': {
				'items': mapped_tracks,
				'total': total,
				'next': None
			}
		}

		return playlist_json

	@classmethod
	def get_track(cls, ids):
		try:
			track_json = cls.__api.track(ids)
		except SpotifyException as error:
			if error.http_status in cls.__error_codes:
				raise InvalidLink(ids)

		return track_json

	@classmethod
	def get_album(cls, ids):
		try:
			album_json = cls.__api.album(ids)
		except SpotifyException as error:
			if error.http_status in cls.__error_codes:
				raise InvalidLink(ids)

		tracks = album_json['tracks']
		cls.__lazy(tracks)

		return album_json

	@classmethod
	def search(cls, query):
		search = cls.__api.search(query)

		return search
