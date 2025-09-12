#!/usr/bin/python3

import os
from datetime import datetime

version = 2.0
bot_name = os.environ.get("BOT_NAME", "@")
creator = "@ReddingtonRedsLeaks & J0n4n (docker)"
donation = "https://www.google.com"
source_code_bot = "https://github.com/J0nan/DeezSpot_bot_docker"
source_code_lib = "https://pypi.org/project/deezloader/"
forum = os.environ.get("FORUM", "@")
active_since = "20/08/2025"
date_start = datetime.now()
last_reset = datetime.strftime(date_start, "%d/%m/%Y %H:%M:%S")

not_found_query_gif = "https://i1.wp.com/blog-pantheon-prod.global.ssl.fastly.net/blog/wp-content/uploads/2017/03/coding-programming-errors-404-page-not-found.gif?resize=625%2C469&ssl=1"
empty_image_url = "https://e-cdns-images.dzcdn.net/images/cover/1000x1000-000000-80-0-0.jpg"

banning_msg1 = "WE ARE DETECTING A FLOOD OF MESSAGES PLEASE DON'T SEND TOO MUCH MESSAGES"
banning_msg2 = "CONGRATULATIONS YOU ARE BANNED =)"

album_too_long = "DON'T YOU GET BORE LISTENING AN ALBUM SO LONG :)))"
track_too_long = "DON'T YOU GET BORE LISTENING A TRACK SO LONG :)))"

shazam_function_msg = "You found a fantastic function, if you send a vocal message or an audio, you will see :)"
max_download_user_msg = "You have reached, max download per time avalaible, wait or kill someone :)"
help_msg = f"WELCOME IN {bot_name} here you can find the commands avalaible, JUST TRY IT :)"
help_photo = open("photos/help_msg.jpg", "rb")

feedback_text = f"If you have any question, just ask to this dude {creator}"
donate_text = f"If you are poor like me, I understand you, IF NOT, I will appreciate a little donation 🥺"

startup_text = (
	f"""
	Hello guys welcome in {bot_name}⚡️, developed by {creator}.
	If you want to stay updated join to {forum}
	If you like my project support my buying a kebab [DONATE]({donation})

		*DISCLAIMER*:
			1): DO NOT USE THIS BOT FOR YOUR OWN PURPOSE
			2): I AM NOT RESPONSABLE FOR ANY ILLEGIT USAGE
			3): The source code can be found here:
					a): [DeezSpot_bot]({source_code_bot})
					b): [Main lib]({source_code_lib})
			5): ENJOY THE MUSIC ART🔥
	"""
)

reasons_text = (
	"WHY I MADE THIS BOT?"
)

what_can_I_do = (
	"Glad you asked, I can do:\
	\n1): Download songs in three different qualities (/quality)\
	\n2): Zip sending\
	\n3): I hope enough performing JAJAJAJAJAJ\
	\n4): I am too lazy to continue, found out by yourself :)"
)

save_methods = (
	"File name templates:\n\n"
	"0: {album} CD {discnum} TRACK {tracknum}\n"
	"1: {artist} - {music}\n"
	"2: {artist} - {music} [{isrc}]\n"
	"3: {discnumber}|{tracknumber} - {artist} - {music}"
    #"4: {tracknumber}. {music}" example
)

bot_settings_config = [
	("Quality", "quality", "MP3_320"),
	("Send zips", "zips", True),
	("Send tracks", "tracks", True),
	("Language", "lang", "en"),
	("Download Source", "source", "Dee"),
	("Search Method", "search_method", "results_audio_article"),
	("Save Method", "method_save", "1")
]

search_methods = [
	("results_audio", "Results in Audio"), 
	("results_article", "Results in Articles"),
	("results_audio_article", "Results Smooth ;)")
]

send_image_track_query = (
	"🎧 Track title: %s\
	\n👤 Artist: %s\
	\n💽 Album: %s\
	\n📅 Release date: %s"
)

send_image_album_query = (
	"💽 Album: %s\
	\n👤 Artist: %s\
	\n📅 Date: %s\
	\n🎧 Tracks amount: %d"
)

send_image_artist_query = (
	"👤 Artist: %s\
	\n💽 Album numbers: %d\
	\n👥 Fans on Deezer: %d"
)

send_image_playlist_query = (
	"📅 Creation: %s\
	\n👤 User: %s\
	\n🎧 Tracks amount: %d\
	\n👥 Fans on Deezer: %d"
)

shazam_audio_query = (
	"👤 Artist: %s\
	\nGenre: %s\
	\n💽 Album: %s\
	\nLabel: %s\
	\n📅 Release date: %s\
	\n🎧 Track title: %s"
)

inline_textes = {
	"download_track": {
		"text": "⬇️ Download track 🎧"
	},

	"download_album": {
		"text": "⬇️ Download album 💽"
	},

	"download_artist": {
		"text": "⬇️ Get artist 👤"
	},

	"back": {
		"text": "BACK 🔙"
	}
}

commands_queries = {
	"s_art": {
		"query": "art: %s",
		"text": "Search by artist 👤"
	},

	"s_alb": {
		"query": "alb: %s",
		"text": "Search by album 💽"
	},

	"s_pla": {
		"query": "pla: %s",
		"text": "Search playlist 📂"
	},

	"s_trk": {
		"query": "trk: %s",
		"text": "Search track 🎧"
	},

	"s_global": {
		"query": "%s",
		"text": "Global search 📊"
	}
}

artist_commands_queries = {
	"top": {
		"query": "%s:top",
		"text": "TOP 30 🔝"
	},

	"albums": {
		"query": "%s:albums",
		"text": "ALBUMS 💽"
	},

	"related": {
		"query": "%s:related",
		"text": "RELATED 🗣"
	},

	"radio": {
		"query": "%s:radio",
		"text": "RADIO 📻"
	},

	"playlists": {
		"query": "%s:playlists",
		"text": "PLAYLISTS 📂"
	}
}