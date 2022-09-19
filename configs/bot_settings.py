#!/usr/bin/python3

import os
from logging import ERROR, INFO
from utils.converter_bytes import convert_bytes_to
from telegram.constants import MAX_FILESIZE_DOWNLOAD

def get_env(name, message, cast=str):
	if name in os.environ:
		return os.environ[name].strip()
	else:
		return message

logs_path = "logs/"
log_downloads = f"{logs_path}downloads.log"
log_uploads = f"{logs_path}uploads.log"
log_telegram = f"{logs_path}telegram.log"
log_links = f"{logs_path}links.log"

logger_names = [
	("telegram.ext.dispatcher", ERROR, log_telegram),
	("uploads", INFO, log_uploads),
	("downloads", ERROR, log_downloads),
	("links", INFO, log_links)
]

warning_for_banning = int(os.environ.get('WARNING_BANNING',4))
user_session = "my_account"
user_errors = int(os.environ.get('USER_ERRORS'))
bunker_channel = int(os.environ.get('BUNKER_CHANNEL'))
owl_channel = int(os.environ.get('OWL_CHANNEL'))
db_name = "DB/deez_bot.db"

root_ids = inputs = { int(os.environ.get("ROOT_ID"))}

output_songs = "Songs/"
output_shazam = "Records/"
recursive_quality = os.environ.get("RECURSIVE_QUALITY", True)
recursive_download = os.environ.get("RECURSIVE_DOWNLOAD", True)
make_zip = os.environ.get("MAKE_ZIP", True)
method_save = int(os.environ.get('METHOD_SAVE',3))
is_thread = os.environ.get("IS_THREAD", True)
download_dir_max_size = int(os.environ.get("DONLOAD_DIR_MAX_SIZE", 6)) #GB
progress_status_rate = int(os.environ.get("PROGRESS_STATUS_RATE", 15))

supported_link = [
	"www.deezer.com", "open.spotify.com",
	"deezer.com", "spotify.com", "deezer.page.link"
]

time_sleep = int(os.environ.get("TIME_SLEEP", 8))
seconds_limits_album = int(os.environ.get("SECONDS_LIMITS_ALBUM", 30000)) #seconds
seconds_limits_track = int(os.environ.get("SECONDS_LIMITS_TRACK", 7200))
upload_max_size_user = int(os.environ.get("UPLOAD_MAX_SIZE_USER", 2)) #GB
max_song_per_playlist = int(os.environ.get("MAX_SONGS_PER_PLAYLIST", 200))
max_download_user = int(os.environ.get("MAX_DOWNLOAD_USER", 3))

recorded_file_max_size = int(
	convert_bytes_to(
		MAX_FILESIZE_DOWNLOAD, "mb"
	)
)