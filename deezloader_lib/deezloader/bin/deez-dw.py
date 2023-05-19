#!/usr/bin/python3

from os.path import isfile
from argparse import ArgumentParser
from configparser import ConfigParser
from deezloader.deezloader import DeeLogin
from deezloader.spotloader import SpoLogin
from deezloader.libutils.others_settings import sources, method_saves
from deezloader.deezloader.deezer_settings import qualities as dee_qualities
from deezloader.spotloader.spotify_settings import qualities as spo_qualities

qualities_dee = list(
	dee_qualities.keys()
)

qualities_spo = list(
	spo_qualities.keys()
)

settings_file = ".deez_settings.ini"

logo = """
	d8888b. d88888b d88888b d88888D        d8888b. db   d8b   db 
	88  `8D 88'     88'     YP  d8'        88  `8D 88   I8I   88 
	88   88 88ooooo 88ooooo    d8'         88   88 88   I8I   88 
	88   88 88~~~~~ 88~~~~~   d8'   C8888D 88   88 Y8   I8I   88 
	88  .8D 88.     88.      d8' db        88  .8D `8b d8'8b d8' 
	Y8888D' Y88888P Y88888P d88888P        Y8888D'  `8b8' `8d8'
"""

print(logo)

def download_link(
	link, output, quality,
	recursive_quality, recursive_download,
	not_gui, zips, method_save
):
	downloa.download_smart(
		link, output, quality,
		recursive_quality, recursive_download,
		not_gui, zips, int(method_save)
	)

parser = ArgumentParser(description = "Deezloader downloader")

if not isfile(settings_file):
	parser.add_argument(
		"deez_settings",
		default = settings_file,
		help = "Path for the deez_settings file"
	)

parser.add_argument(
	"-so", "--source",
	choices = sources,
	default = sources[0],
	help = "Choose if download from Spotify or Deezer"
)

parser.add_argument(
	"-l", "--link",
	help = "Deezer or Spotify link for download"
)

parser.add_argument(
	"-s", "--song",
	help = "song name"
)

parser.add_argument(
	"-a", "--artist",
	help = "artist song"
)

parser.add_argument(
	"-o", "--output",
	default = "Songs/",
	help = "Output folder"
)

args = parser.parse_known_args()[0]

config = ConfigParser()

if not isfile(settings_file):
	config.read(args.deez_settings)
else:
	config.read(settings_file)

try:
	dee_token = config['deez_login']['arl']
	dee_email = config['deez_login']['mail']
	dee_pwd = config['deez_login']['pwd']
	spo_email = config['spot_login']['mail']
	spo_pwd = config['spot_login']['pwd']
except KeyError:
	print("Something went wrong with configuration file")
	exit()

source = args.source

if source == "dee":
	downloa = DeeLogin(
		arl = dee_token,
		email = dee_email,
		password = dee_pwd
	)

	qualities = qualities_dee

elif source == "spo":
	downloa = SpoLogin(spo_email, spo_pwd)
	qualities = qualities_spo

parser.add_argument(
	"-q", "--quality",
	default = qualities[0],
	choices = qualities,
)

parser.add_argument(
	"-rq", "--recursive_quality",
	action = "store_true",
	help = "If choosen quality doesn't exist download with best possible quality (True or False)"
)

parser.add_argument(
	"-rd", "--recursive_download",
	action = "store_true",
	help = "If the song has already downloaded skip (True or False)"
)

parser.add_argument(
	"-g", "--not_gui",
	action = "store_true",
	help = "Show the little not_gui (True or False)"
)

parser.add_argument(
	"-z", "--zip",
	action = "store_true",
	help = "If is an album or playlist link create a zip archive (True or False)"
)

parser.add_argument(
	"-sa", "--save",
	default = "2",
	choices = method_saves,
)

args = parser.parse_args()
link = args.link
output = args.output
quality = args.quality
recursive_quality = args.recursive_quality
recursive_download = args.recursive_download
zips = args.zip
song = args.song
artist = args.artist
not_gui = args.not_gui
save = args.save

if link:
	download_link(
		link, output, quality,
		recursive_quality, recursive_download,
		not_gui, zips, save
	)

if song and artist:
	downloa.download_name(
		artist, song,
		output, quality,
		recursive_quality,
		recursive_download, not_gui
	)