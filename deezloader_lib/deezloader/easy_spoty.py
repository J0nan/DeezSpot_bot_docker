#!/usr/bin/python3

from threading import Lock

from spotipy import Spotify
from .exceptions import InvalidLink
from spotapi import PublicPlaylist
from spotipy.exceptions import SpotifyException
from spotapi.exceptions import PlaylistError
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

	# SpotAPI serves the whole playlist (no 100-track cap) through the
	# web player's GraphQL API, which only needs anonymous tokens.
	__playlist_client = None
	__playlist_lock = Lock()
	__playlist_page = 343

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

	@classmethod
	def __get_playlist_client(cls):
		# The anonymous session tokens and the persisted-query hashes
		# are expensive to fetch, so one client is shared and reused.
		if cls.__playlist_client is None:
			with cls.__playlist_lock:
				if cls.__playlist_client is None:
					cls.__playlist_client = PublicPlaylist("")

		return cls.__playlist_client

	@staticmethod
	def __map_playlist_track(item):
		data = (item.get('itemV2') or {}).get('data')
		uri = (data or {}).get('uri') or ''

		if not uri.startswith('spotify:track:'):
			# Episodes, local files and removed tracks cannot be
			# downloaded, so they map to None like spotipy does.
			return None

		ids = uri.split(':')[-1]
		artists = [
			{
				'name': artist['profile']['name']
			}

			for artist in data.get('artists', {}).get('items', [])
			if artist.get('profile', {}).get('name')
		]
		added_at = (item.get('addedAt') or {}).get('isoString')

		return {
			'added_at': added_at,
			'track': {
				'name': data.get('name', 'Unknown'),
				'artists': artists or [{'name': 'Unknown'}],
				'external_urls': {
					'spotify': f"https://open.spotify.com/track/{ids}"
				}
			}
		}

	@staticmethod
	def __map_playlist_images(playlist_v2):
		sources = []

		for image in playlist_v2.get('images', {}).get('items', []):
			c_sources = image.get('sources', [])

			if c_sources:
				big = max(
					c_sources,
					key = lambda source: source.get('width', 0)
				)
				sources.append({'url': big.get('url')})

		return sources

	@classmethod
	def get_playlist(cls, ids):
		client = cls.__get_playlist_client()
		items = []
		playlist_v2 = {}

		try:
			with cls.__playlist_lock:
				client.playlist_id = ids
				client.playlist_link = f"https://open.spotify.com/playlist/{ids}"

				response = client.get_playlist_info(limit = cls.__playlist_page)
				playlist_v2 = response['data']['playlistV2']
				content = playlist_v2['content']
				total = content.get('totalCount', 0)
				items.extend(content.get('items', []))

				# SpotAPI caps each GraphQL page at 343 tracks; keep
				# requesting until the whole playlist is fetched.
				offset = cls.__playlist_page

				while offset < total:
					response = client.get_playlist_info(
						limit = cls.__playlist_page,
						offset = offset
					)
					content = response['data']['playlistV2']['content']
					items.extend(content.get('items', []))
					offset += cls.__playlist_page
		except (PlaylistError, KeyError, TypeError):
			raise InvalidLink(ids)

		mapped_tracks = [
			mapped for mapped in map(cls.__map_playlist_track, items)
			if mapped is not None
		]

		owner = (playlist_v2.get('ownerV2') or {}).get('data') or {}

		playlist_json = {
			'name': playlist_v2.get('name', 'Unknown'),
			'owner': {
				'display_name': owner.get('name', 'Unknown')
			},
			'followers': {
				'total': playlist_v2.get('followers', 0)
			},
			'images': cls.__map_playlist_images(playlist_v2),
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
