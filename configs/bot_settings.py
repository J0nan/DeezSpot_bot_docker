#!/usr/bin/python3

import os
from logging import ERROR, INFO, FileHandler, Formatter, getLogger
from utils.converter_bytes import convert_bytes_to
from telegram.constants import MAX_FILESIZE_DOWNLOAD

logs_path = "logs/"
log_downloads = f"{logs_path}downloads.log"
log_uploads = f"{logs_path}uploads.log"
log_telegram = f"{logs_path}telegram.log"
log_links = f"{logs_path}links.log"

spotify_client_id = str(os.environ.get("SPOTIFY_CLIENT_ID", "c6b23f1e91f84b6a9361de16aba0ae17"))
spotify_client_secret = str(os.environ.get("SPOTIFY_CLIENT_SECRET", "237e355acaa24636abc79f1a089e6204"))
spotify_cache_file = os.environ.get("SPOTIFY_CACHE_FILE", ".cache_spoty_token.json")

logger_names = [
	("telegram.ext.dispatcher", ERROR, log_telegram),
	("uploads", INFO, log_uploads),
	("downloads", ERROR, log_downloads),
	("links", INFO, log_links)
]

# The vendored deezloader loggers have no handler of their own; register their
# parent on the bot download log, at INFO so cover fallbacks reach
# downloads.log instead of being dropped by the `downloads` ERROR level.
cover_logger_name = "deezloader"
cover_log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def register_cover_logger():
	logger = getLogger(cover_logger_name)
	# delay=True: this runs before logs/ exists (utils.check_config_bot creates
	# it), so the file opens on the first cover record instead of here.
	downloads_suffix = log_downloads.replace("/", os.sep)

	for handler in logger.handlers:
		if (
			isinstance(handler, FileHandler)
			and handler.baseFilename.endswith(downloads_suffix)
		):
			return logger

	handler = FileHandler(log_downloads, delay = True)
	handler.setFormatter(Formatter(cover_log_format))
	logger.setLevel(INFO)
	logger.addHandler(handler)

	return logger

# flood guard: FLOOD_MESSAGE_LIMIT messages in a row, each less than
# FLOOD_WINDOW_SECONDS after the previous one, take one strike; a chat that
# collects WARNING_BANNING strikes is banned. The list/paging interface makes
# one burst of fast taps normal browsing, so a strike needs a real flood.
flood_window_seconds = int(os.environ.get('FLOOD_WINDOW_SECONDS',4)) #seconds
flood_message_limit = int(os.environ.get('FLOOD_MESSAGE_LIMIT',12))
warning_for_banning = int(os.environ.get('WARNING_BANNING',6))
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
download_dir_max_size = int(os.environ.get("DOWNLOAD_DIR_MAX_SIZE", 6)) #GB
progress_status_rate = int(os.environ.get("PROGRESS_STATUS_RATE", 150))

supported_link = [
	"www.deezer.com", "open.spotify.com",
	"deezer.com", "spotify.com", "deezer.page.link", "spotify.link"
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

# Registered last: this module can fail while its settings are missing, and a
# partial import must not leak a handler.
register_cover_logger()