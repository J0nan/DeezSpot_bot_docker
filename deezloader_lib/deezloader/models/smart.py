#!/usr/bin/python3

from .track import Track
from .album import Album
from .playlist import Playlist

class Smart:
	def __init__(self) -> None:
		self.track: Track = None
		self.album: Album = None
		self.playlist: Playlist = None
		self.type = None
		self.source = None