#!/usr/bin/python3

from deezloader.easy_spoty import Spo
from configs.set_configs import SetConfigs
from deezloader.exceptions import NoDataApi, QuotaExceeded
from deezloader.libutils.utils import get_ids
from utils.utils import my_round
from deezloader.deezloader.dee_api import API as deezer_api

def shazam_song(song):
	data = SetConfigs.acrcloud_api.recognize_audio(song)
	status = data['status']

	if status['msg'] != "Success":
		return

	song_tags = data['metadata']['music'][0]

	artists = [
		artist['name']
		for artist in song_tags['artists']
	]

	artist = " & ".join(artists)

	if "genres" in song_tags:
		genres = [
			genre['name']
			for genre in song_tags['genres']
		]

		genre = " & ".join(genres)
	else:
		genre = "Unknown"

	album = song_tags['album']['name']
	label = song_tags['label']
	external_ids = song_tags['external_ids']

	if "upc" in external_ids:
		upc = f"upc:{external_ids['upc']}"

	if "isrc" in external_ids:
		isrc = f"isrc:{external_ids['isrc']}"
		data_track = deezer_api.get_track(isrc)
		track_link = data_track['link']
		album_link = data_track['album']['link']
		artist_link = data_track['artist']['link']
		image_url = data_track['album']['cover_xl']
	else:
		track_link = None
		album_link = None
		image_url = None

	release_date = song_tags['release_date']
	title = song_tags['title']

	return (
		artist, genre,
		album, label,
		track_link, album_link,
		artist_link, image_url,
		release_date, title
	)

#OLD SPOTIFY DOWNLOAD
def track_spo_to_dee_data(link):
	link_dee = SetConfigs.deez_api.convert_spoty_to_dee_link_track(link)
	dee_data = track_dee_data(link_dee)

	return dee_data

def track_spo_data(link, conv: bool):
	if conv:
		return track_spo_to_dee_data(link)

	ids = get_ids(link)
	data = Spo.get_track(ids)
	image_url = data['album']['images'][0]['url']
	name = data['name']
	artist = data['artists'][0]['name']
	album = data['album']['name']
	date = data['album']['release_date']
	duration = data['duration_ms'] // 1000

	return (
		image_url, name,
		artist, album,
		date, link, duration
	)

def track_dee_data(link):
	ids = get_ids(link)
	data = deezer_api.get_track(ids)
	md5_image = data['md5_image']
	image_url = deezer_api.get_img_url(md5_image, size = "1000x1000")
	name = data['title']
	artist = data['artist']['name']
	album = data['album']['title']
	date = data['album']['release_date']
	link_dee = data['link']
	duration = data['duration']

	return (
		image_url, name,
		artist, album,
		date, link_dee, duration
	)

def artist_dee_data(link):
	ids = get_ids(link)
	data = deezer_api.get_artist(ids)
	name = data['name']
	image_url = data['picture_xl']
	nb_album = data['nb_album']
	nb_fan = data['nb_fan']

	return (
		name, image_url,
		nb_album, nb_fan
	)

def playlist_dee_data(link):
	ids = get_ids(link)
	data = deezer_api.get_playlist(ids)
	nb_tracks = data['nb_tracks']
	n_fans = data['fans']
	image_url = data['picture_xl']
	creation_date = data['creation_date']
	creator = data['creator']['name']
	tracks = data['tracks']['data']

	return (
		nb_tracks, n_fans,
		image_url, creation_date,
		creator, tracks
	)

def playlist_spo_data(link):
	ids = get_ids(link)
	data = Spo.get_playlist(ids)
	n_fans = data['followers']['total']
	image_url = data['images'][0]['url']
	creation_date = data['tracks']['items'][0]['added_at']
	creator = data['owner']['display_name']
	tracks = data['tracks']['items']
	nb_tracks = data['tracks']['total']

	return (
		nb_tracks, n_fans,
		image_url, creation_date,
		creator, tracks
	)

def album_dee_data(link):
	ids = get_ids(link)
	data = deezer_api.get_album(ids)
	md5_image = data['md5_image']
	image_url = deezer_api.get_img_url(md5_image, size = "1000x1000")
	album = data['title']
	artist = data['artist']['name']
	date = data['release_date']
	nb_tracks = data['nb_tracks']
	tracks = deezer_api.get_all_album_tracks(data)
	duration = sum(track['duration'] for track in tracks)
	link_dee = data['link']

	return (
		image_url, album,
		artist, date,
		nb_tracks, tracks,
		duration, link_dee
	)

def convert_spoty_to_dee_link_track(link):
	link_dee = SetConfigs.deez_api.convert_spoty_to_dee_link_track(link)

	return link_dee

def album_spo_data_to_dee(link):
	link_dee = SetConfigs.deez_api.convert_spoty_to_dee_link_album(link)
	dee_data = album_dee_data(link_dee)

	return dee_data

def album_spo_data(link, conv: bool):
	if conv:
		return album_spo_data_to_dee(link)

	ids = get_ids(link)
	data = Spo.get_album(ids)
	image_url = data['images'][0]['url']
	album = data['name']
	artist = data['artists'][0]['name']
	date = data['release_date']
	nb_tracks = data['total_tracks']
	tracks = data['tracks']['items']
	duration = 0

	for track in tracks:
		duration += track['duration_ms']

	duration //= 1000

	return (
		image_url, album,
		artist, date,
		nb_tracks, tracks,
		duration, link
	)

def __artist_credits(data):
	# Deezer's search/chart pages name only the MAIN artist; the full credit
	# list (features, collabs, remix producers) lives in the track and album
	# objects' "contributors". Keep the entries Deezer types as artists, in
	# payload order and deduplicated by name (the same artist can appear as
	# both Main and Featured), and fall back to the main artist for a payload
	# with no contributors at all. Every entry carries the artist id next to
	# the name, so the track card can point each performer at its own detail
	# card; "" marks a credit whose payload arrived without an id.
	credits = []

	for contributor in data.get('contributors') or []:
		if type(contributor) is not dict:
			continue

		if contributor.get('type') not in (None, "artist"):
			continue

		name = contributor.get('name')

		if not name or name in [entry['name'] for entry in credits]:
			continue

		ids = contributor.get('id')

		credits.append({
			"id": str(ids) if ids is not None else "",
			"name": name,
		})

	if credits:
		return credits

	artist = data.get('artist')

	if type(artist) is dict and artist.get('name'):
		ids = artist.get('id')

		return [{
			"id": str(ids) if ids is not None else "",
			"name": artist['name'],
		}]

	return []

def __artist_names(data):
	return [entry['name'] for entry in __artist_credits(data)]

def __credits(data):
	return " & ".join(__artist_names(data))

def __display_title(data):
	# The complete title, version suffix included. Deezer usually keeps the
	# edition inside "title" already ("Galway Girl (Live)"), but some payloads
	# carry it only in "title_version" ("Bohemian Rhapsody" + "(Live Aid)"),
	# so show it either way and never repeat it when both hold it.
	title = data['title'] or ""
	version = data.get('title_version') or ""

	if version and version not in title:
		return f"{title} {version}"

	return title

def __item_links(data):
	# Jump ids for the contextual row of the result card: the buttons open
	# the bot's OWN detail card for the exact album/artist (fetched by id
	# via /ctx), never an external deezer.com link. Deezer track/album
	# payloads expose nested artist/album dicts; "" means "not available".
	links = {"album": "", "artist": ""}
	album = data.get('album')
	artist = data.get('artist')

	if type(album) is dict and 'id' in album:
		links['album'] = str(album['id'])

	if type(artist) is dict and 'id' in artist:
		links['artist'] = str(artist['id'])

	return links

def __track_item(data, position = None, link = None):
	contributors = data.get('contributors')
	description = (
		f"Album: {data['album']['title']}" +
		f"\nDuration: {my_round(data['duration'] / 60)}" +
		f"\nRank: {data['rank']}"
	)

	if position is not None:
		description += f"\nPosition: {position}"

	return {
		"id": data['id'],
		"type": "track",
		"title": __display_title(data),
		# the artist credit feeds the list button label and the card's
		# Artist: line; expand_track_credits upgrades it to every performer
		"artist": __credits(data),
		# "full" once every performer is known: a search page only carries
		# the main artist, so "main" marks an item still worth looking up
		"credits": "full" if type(contributors) is list and contributors else "main",
		# one {id, name} entry per known performer: the detail card builds a
		# jump button per artist out of this list, and expand_track_credits
		# completes it with the same lookup that completes item['artist']
		"artists": __artist_credits(data),
		"description": description,
		"link": data['link'] if link is None else link,
		"image": data['album']['cover_big'],
		"links": __item_links(data),
	}

def __artist_item(data, description = None):
	if description is None:
		description = (
			f"Album number: {data['nb_album']}" +
			f"\nFan number: {data['nb_fan']}"
		)

	return {
		"id": data['id'],
		"type": "artist",
		"title": data['name'],
		"description": description,
		"link": data['link'],
		"image": data['picture_big'],
		"links": __item_links(data),
	}

def __album_item(data, description):
	return {
		"id": data['id'],
		"type": "album",
		"title": data['title'],
		"description": description,
		"link": data['link'],
		"image": data['cover_big'],
		"links": __item_links(data),
	}

def __playlist_item(data, description):
	return {
		"id": data['id'],
		"type": "playlist",
		"title": data['title'],
		"description": description,
		"link": data['link'],
		"image": data['picture_big'],
		"links": __item_links(data),
	}

def expand_track_credits(items):
	# Deezer's search and chart pages name only the main artist, so the other
	# performers of a track live one endpoint deeper: the track object. This
	# runs over the results a page is about to RENDER -- at most one lookup per
	# visible track -- and writes the answer back into the cached item, so
	# paging back, re-tapping filters or opening the card never pay twice.
	# A track whose details are unavailable simply keeps its main artist: a
	# missing credit is never worth blocking or emptying the result list.
	for item in items:
		if item.get('type') != "track" or item.get('credits') == "full":
			continue

		try:
			credits = __artist_credits(deezer_api.get_track(item['id']))
		except (NoDataApi, QuotaExceeded, KeyError, TypeError, ValueError, OSError):
			# requests raises its network errors as OSError subclasses and a
			# corrupt body as ValueError; either way the label stays as built
			continue

		if not credits:
			continue

		item['artist'] = " & ".join(entry['name'] for entry in credits)
		item['artists'] = credits
		item['credits'] = "full"

def get_album_card(ids):
	# Detail card behind the "Album 💽" contextual button: the exact album
	# by Deezer id, in the same item shape the "alb: " search branch
	# produces. None means "nothing to show" (NoDataApi or a payload
	# shape the card cannot render) so the callback handler never sees a
	# raise.
	try:
		data = deezer_api.get_album(ids)

		return __album_item(
			data,
			f"Tracks number: {data['nb_tracks']}" +
			f"\nArtist: {__credits(data)}"
		)

	except (NoDataApi, KeyError, TypeError):
		return None

def get_artist_card(ids):
	# Detail card behind the "Artist 👤" contextual button: the exact
	# artist by Deezer id, in the same item shape the "art: " search
	# branch produces. None on NoDataApi or an odd payload shape.
	try:
		data = deezer_api.get_artist(ids)

		return __artist_item(data)

	except (NoDataApi, KeyError, TypeError):
		return None

def execute_search(query: str, user_data):
	# Pure search core for the message-based card flow: same grammar as
	# the old create_response_article, plain display-field dicts out. The
	# per-user search_method setting is gone, so user_data is kept only
	# for seam compatibility and never read here. An empty list means
	# "nothing to show": NoDataApi, unknown artist section, or zero results;
	# the caller renders the not-found photo.
	s_art = "art: "
	s_alb = "alb: "
	s_pla = "pla: "
	s_trk = "trk: "
	s_art_id = "artist:"

	try:
		if query.startswith(s_art):
			c_query = query.replace(s_art, "")
			data = deezer_api.search_artist(c_query)

			return [__artist_item(item) for item in data['data']]

		elif query.startswith(s_alb):
			c_query = query.replace(s_alb, "")
			data = deezer_api.search_album(c_query)

			return [
				__album_item(
					item,
					f"Tracks number: {item['nb_tracks']}" +
					f"\nArtist: {__credits(item)}"
				)
				for item in data['data']
			]

		elif query.startswith(s_pla):
			c_query = query.replace(s_pla, "")
			data = deezer_api.search_playlist(c_query)

			return [
				__playlist_item(
					item,
					f"Tracks number: {item['nb_tracks']}" +
					f"\nUser: {item['user']['name']}" +
					f"\nCreation: {item['creation_date']}"
				)
				for item in data['data']
			]

		elif query.startswith(s_trk):
			c_query = query.replace(s_trk, "")
			data = deezer_api.search_track(c_query)

			return [__track_item(item) for item in data['data']]

		elif query.startswith(s_art_id):
			c_query = query.replace(s_art_id, "")
			s_c_query = c_query.split(":")
			c_query = s_c_query[0]
			path = s_c_query[1]

			if path == "top":
				data = deezer_api.get_artist_top_tracks(c_query)

				return [__track_item(item) for item in data['data']]

			elif path == "albums":
				data = deezer_api.get_artist_top_albums(c_query)

				return [
					__album_item(
						item,
						f"Release date: {item['release_date']}" +
						f"\nFans: {item['fans']}"
					)
					for item in data['data']
				]

			elif path == "related":
				data = deezer_api.get_artist_related(c_query)

				return [__artist_item(item) for item in data['data']]

			elif path == "radio":
				data = deezer_api.get_artist_radio(c_query)

				return [
					__track_item(
						item,
						link = f"https://deezer.com/track/{item['id']}"
					)
					for item in data['data']
				]

			elif path == "playlists":
				data = deezer_api.get_artist_top_playlists(c_query)

				return [
					__playlist_item(
						item,
						f"User: {item['user']['name']}" +
						f"\nCreation: {item['creation_date']}"
					)
					for item in data['data']
				]

			else:
				return []

		else:
			c_query = query

			if c_query == "":
				data = deezer_api.get_chart(c_query)
				results = [
					__track_item(item, position = item['position'])
					for item in data['tracks']['data']
				]
				results += [
					__album_item(
						item,
						f"Position: {item['position']}" +
						f"\nArtist: {__credits(item)}"
					)
					for item in data['albums']['data']
				]
				results += [
					__artist_item(
						item,
						description = f"Position: {item['position']}"
					)
					for item in data['artists']['data']
				]
				results += [
					__playlist_item(
						item,
						f"Tracks number: {item['nb_tracks']}" +
						f"\nUser: {item['user']['name']}" +
						f"\nCreation: {item['creation_date']}"
					)
					for item in data['playlists']['data']
				]

				return results

			data = deezer_api.search(c_query)

			return [__track_item(item) for item in data['data']]

	except NoDataApi:
		return []

