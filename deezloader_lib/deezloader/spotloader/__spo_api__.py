#!/usr/bin/python3

from ..easy_spoty import Spo
from datetime import datetime
from ..libutils.utils import convert_to_date

def tracking(ids, album = None):
	datas = {}
	json_track = Spo.get_track(ids)

	if not album:
		album_ids = json_track['album']['id']
		json_album = Spo.get_album(album_ids)
		datas['image'] = json_album['images'][0]['url']
		datas['image2'] = json_album['images'][1]['url']
		datas['image3'] = json_album['images'][2]['url']
		datas['genre'] = " & ".join(json_album['genres'])

		ar_album = [
			artist['name']
			for artist in json_album['artists']
		]

		datas['ar_album'] = " & ".join(ar_album)
		datas['album'] = json_album['name']
		datas['label'] = json_album['label']

		external_ids = json_album['external_ids']

		if external_ids:
			datas['upc'] = external_ids['upc']

		datas['nb_tracks'] = json_album['total_tracks']

	datas['music'] = json_track['name']

	artists = [
		artist['name']
		for artist in json_track['artists']
	]

	datas['artist'] = " & ".join(artists)
	datas['tracknum'] = json_track['track_number']
	datas['discnum'] = json_track['disc_number']

	datas['year'] = convert_to_date(
		json_track['album']['release_date']
	)

	datas['bpm'] = "Unknown"
	datas['duration'] = json_track['duration_ms'] // 1000

	external_ids = json_track['external_ids']

	if external_ids:
		datas['isrc'] = external_ids['isrc']

	datas['gain'] = "Unknown"
	datas['ids'] = ids

	return datas

def tracking_album(album_json):
	song_metadata: dict[
		str,
		list or str or int or datetime
	] = {
		"music": [],
		"artist": [],
		"tracknum": [],
		"discnum": [],
		"bpm": [],
		"duration": [],
		"isrc": [],
		"gain": [],
		"ids": [],
		"image": album_json['images'][0]['url'],
		"image2": album_json['images'][1]['url'],
		"image3": album_json['images'][2]['url'],
		"album": album_json['name'],
		"label": album_json['label'],
		"year": convert_to_date(album_json['release_date']),
		"nb_tracks": album_json['total_tracks'],
		"genre": " & ".join(album_json['genres'])
	}

	ar_album = [
		artist['name']
		for artist in album_json['artists']
	]

	song_metadata['ar_album'] = " & ".join(ar_album)

	external_ids = album_json['external_ids']

	if external_ids:
		song_metadata['upc'] = external_ids['upc']

	sm_items = song_metadata.items()

	for track in album_json['tracks']['items']:
		c_ids = track['id']
		detas = tracking(c_ids, album = True)

		for key, item in sm_items:
			if type(item) is list:
				song_metadata[key].append(detas[key])

	return song_metadata