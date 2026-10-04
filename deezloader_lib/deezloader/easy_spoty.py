#!/usr/bin/python3

from spotipy import Spotify
from .exceptions import InvalidLink
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
	def get_playlist(cls, ids):
		try:
			playlist_json = cls.__api.playlist(ids)
		except SpotifyException as error:
			if error.http_status in cls.__error_codes:
				raise InvalidLink(ids)

		if 'tracks' not in playlist_json:
			import requests
			import re
			import json
			url = f"https://open.spotify.com/embed/playlist/{ids}"
			try:
				headers = {'User-Agent': 'Mozilla/5.0'}
				html = requests.get(url, headers=headers, timeout=10).text
				match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
				items = []
				if match:
					embed_data = json.loads(match.group(1))
					trackList = embed_data['props']['pageProps']['state']['data']['entity']['trackList']
					for t in trackList:
						uri = t.get('uri', '')
						t_id = uri.split(':')[-1] if ':' in uri else uri
						name = t.get('title', 'Unknown')
						items.append({
							'added_at': 'Unknown',
							'track': {
								'name': name,
								'external_urls': {
									'spotify': f"https://open.spotify.com/track/{t_id}"
								}
							}
						})
				playlist_json['tracks'] = {'items': items, 'next': None}
			except Exception:
				playlist_json['tracks'] = {'items': [], 'next': None}

		tracks = playlist_json['tracks']
		cls.__lazy(tracks)

		return playlist_json

	@classmethod
	def search(cls, query):
		search = cls.__api.search(query)

		return search