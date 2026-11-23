# DeezSpot_bot

<https://hub.docker.com/r/j0n4n/deezspot_bot_docker>

# Disclaimer

- I am not responsible for the usage of this program by other people.
- I do not recommend you doing this illegally or against Deezer's terms of service.
- This project is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)

* ### PYTHON VERSION SUPPORTED ###
	![Python >= 3.11](https://img.shields.io/badge/python-v%3E=3.11-blue)

* ### OS Supported ###
	![Linux Support](https://img.shields.io/badge/Linux-Support-brightgreen.svg)
	![macOS Support](https://img.shields.io/badge/macOS-Support-brightgreen.svg)
	![Windows Support](https://img.shields.io/badge/Windows-Support-brightgreen.svg)

# Commands

Every command the bot answers to, for reference and for the Telegram Bot Father (`/setmycommands`). Root-only commands are marked; leave them out of BotFather's list if you want a clean user menu.

| Command | Args | What it does |
|---------|------|--------------|
| `/start` | — | Main menu with the search prefix buttons |
| `/help` | — | How-to photo + short usage text |
| `/search` | `[query]` | Searches Deezer |
| `/settings` | — | Your settings: quality, source, filename scheme, zip/track sending, YouTube link behaviour |
| `/quality` | — | Quick picker for your download quality |
| `/shazam` | — | Explains that a voice note or audio file gets recognized and downloaded |
| `/kill_dw` | — | Lists your running downloads with a kill button each |
| `/info` | — | Bot usage stats photo (downloads/users graphs) |
| `/graphs` | — | Top downloaders leaderboard photos |
| `/reasons` | — | Why this bot exists |
| `/feedback` | — | Where to send feedback to the owner |
| `/donate` | — | Donation info |
| `/managing_banned` | — | (root only) Banned-users list with unban buttons |
| `/add_banned` | `[chat id]` | (root only) Bans the user id it asks for |
| `/users` | — | (root only) Registered users with last-used date and download count, 20 per page with Prev/Next buttons |

Paste-ready block for the Bot Father (`/setcommands`), user-facing commands only:

```
start - Main menu
help - How to use the bot
search - Search Deezer: /search [art:|alb:|pla:|trk:] query (empty = chart)
settings - Your download settings
quality - Choose audio quality
shazam - Recognize a song from a voice note or audio
kill_dw - List and cancel your running downloads
info - Bot stats
graphs - Top downloaders
reasons - Why this bot exists
feedback - Send feedback
donate - Support the project
managing_banned - ADMIN ONLY
add_banned - ADMIN ONLY
users - ADMIN ONLY
```

Also note: pasting a Deezer or Spotify **link** (track/album/playlist/artist) is not a command but downloads directly, plain or rich-formatted, and any plain text in a private chat runs a search. Pasting a **YouTube** link behaves as described below.

# YouTube links

A pasted YouTube link (`youtube.com/watch?v=…`, `youtu.be/…`, Shorts, `music.youtube.com`, `m.youtube.com`) is handled according to the **YouTube links** setting in `/settings`:

- **Search** (default): the video title is searched on Deezer as a song and the result list is shown with an always-present `⬇️ Download from YouTube` button. The button is there even when Deezer finds nothing — the 404 card carries it too — and it survives paging, the type filters and opening a result's detail card.
- **Download**: the video is downloaded straight away, no Deezer search and no confirmation step.

Tapping `⬇️ Download from YouTube` does not start the audio right away: a **confirmation card** appears with the video artwork and the exact metadata the tags will carry (title, artist(s), album, release date). Its buttons edit any field — `✏️ Title`, `👤 Artists`, `💽 Album` ask for the new value in the chat, `✅ Download` starts the download and `❌ Cancel` drops the card. Different artists are separated with `&`: `"A & B"`, `"A&B"` and `" A  &&  B "` all become `A & B` in the tags, the Telegram performer and the file name. An edited tag set is cached under its own key, so a later request with the untouched metadata never replays a file carrying someone else's edits.

Both paths deliver an **mp3 at 320 kbps** (the maximum MP3 bitrate; the source stream is `bestaudio`, never a downgraded video track) with ID3 tags for title, artist, album and release date, and the **video miniature as the cover art**. YouTube metadata is authoritative; a matched Deezer track only fills in an album or release date YouTube does not report. Downloads are cached like every other track, appear in `/kill_dw` and count against `MAX_DOWNLOAD_USER`, a video longer than `SECONDS_LIMITS_TRACK` is refused, and live or unknown-length streams are refused up front because their duration cannot be bounded. Each download writes its own working file, so two users fetching the same video never overwrite each other.

Only the video id is used: a link that also carries a playlist (`&list=…`) downloads that one video. YouTube support needs `yt-dlp` (installed from `req.txt` with its EJS solver and bundled Deno runtime, hence the Python 3.11 floor) and `ffmpeg` (already in the image) for the mp3 conversion.

# SET UP
Docker Variables:
- **MODE_BOT**: (default: 2)
  - 1 -> Test Mode.
  - 2 -> Cool mode.
  - 3 -> Test Mode (No zip).
  - 4 -> Cool Mode (No zip).

- **WARNING_BANNING**: (default: 6) number of flood strikes a user collects before being banned.
- **FLOOD_WINDOW_SECONDS**: (default: 4) a message that reaches the bot less than this many seconds after the user's previous one counts as flooding. Any slower message clears the burst.
- **FLOOD_MESSAGE_LIMIT**: (default: 12) flooding messages in a burst before the user gets one warning strike. Paging through the search results is normal browsing, so the burst has to be a real flood.

- **USER_ERRORS**: (MANDATORY) Chat id where to send users errors.

- **BUNKER_CHANNEL**: (MANDATORY) Chat id to use as an archive

- **OWL_CHANNEL**: (MANDATORY) Chat id where to listen for announcements to the users

- **ROOT_ID**: (MANDATORY) User id to have admin access

- **METHOD_SAVE**: (default: 3) Method of the naming schema for the song name. Each user can change it using the /setting command. 
  - 0 -> "{album} CD {discnum} TRACK {tracknum}"
  - 1 -> "{songname} - {artist}"
  - 2 -> "{songname} - {artist} [{isrc}]"
  - 3 -> "{discnum}|{tracknum} - {songname} - {artist}"

- **DOWNLOAD_DIR_MAX_SIZE**: (default: 6) Directory max size in GB.
- **PROGRESS_STATUS_RATE**: (default: 15) 
- **TIME_SLEEP**: (default: 8)
- **SECONDS_LIMITS_ALBUM**: (default: 30000) In seconds
- **SECONDS_LIMITS_TRACK**: (default: 7200) In seconds
- **UPLOAD_MAX_SIZE_USER**: (default: 2) In GB
- **MAX_SONGS_PER_PLAYLIST**: (default: 200) Maximum number of song in a playlist to be downloaded
- **MAX_DOWNLOAD_USER**: (default: 3) Maximum parallel downloads per user
- **BOT_NAME**: (MANDATORY) Username with the `@` of the bot.
- **FORUM**: (default: @)
- **ARL_TOKEN**: (MANDATORY) Deezer ARL token.
- **EMAIL_DEE**: (MANDATORY) Email to log in on Deezer
- **PWD_DEE**: (MANDATORY) Password to log in on Deezer
- **SPOTIFY_CLIENT_ID**: (default: `c6b23f1e91f84b6a9361de16aba0ae17` this is the one included in deezloader): can be created in <https://developer.spotify.com/dashboard>
- **SPOTIFY_CLIENT_SECRET**: (default: `237e355acaa24636abc79f1a089e6204` this is the one included in deezloader): can be created in <https://developer.spotify.com/dashboard>
<!-- - **EMAIL_SPO**: (MANDATORY) Email to log in on Spotify
- **PWD_SPO**: (MANDATORY) Password to log in on Spotify -->
- **BOT_TOKEN**: (MANDATORY) Telegram bot token
- **API_ID**: (MANDATORY) Telegram api id
- **API_HASH**: (MANDATORY) Telegram api hash
- **ACRCLOUD_KEY**: for acrcloud key look at [acrcloud](https://docs.acrcloud.com/tutorials/recognize-music)
- **ACRCLOUD_SECRET**: for acrcloud secret look at [acrcloud](https://docs.acrcloud.com/tutorials/recognize-music)
- **ACRCLOUD_HOST**: for host look at [acrcloud](https://docs.acrcloud.com/tutorials/recognize-music)

# Environment file (.env)

`docker-compose.yml` interpolates `${VAR}` from a `.env` file at the repository root (gitignored) or from the host environment. Create `.env` with the template below and fill in your own values — never commit real credentials.

```dotenv
# Required for startup — the bot crashes at import if any of these is missing.
BOT_TOKEN=
API_ID=
API_HASH=
ARL_TOKEN=
# Chat ids (send a message to @JsonDumpBot to get them; channels are usually
# negative). USER_ERRORS: where user errors go. BUNKER_CHANNEL: upload archive.
# OWL_CHANNEL: announcements. ROOT_ID: your admin user id.
USER_ERRORS=
BUNKER_CHANNEL=
OWL_CHANNEL=
ROOT_ID=

# Spotify metadata (search, conversion, cover fallback).
# Empty keeps the public deezloader defaults baked into the code.
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=

# Optional: Deezer account login (only if the ARL expires)
EMAIL_DEE=
PWD_DEE=

# Optional: ACRCloud song recognition
ACRCLOUD_KEY=
ACRCLOUD_SECRET=
ACRCLOUD_HOST=

# Optional: behavior tuning — empty or absent keeps the documented defaults
# (compose applies them). MODE_BOT 2, WARNING_BANNING 6, FLOOD_WINDOW_SECONDS 4,
# FLOOD_MESSAGE_LIMIT 12, METHOD_SAVE 3, DOWNLOAD_DIR_MAX_SIZE 6,
# PROGRESS_STATUS_RATE 150, TIME_SLEEP 8, SECONDS_LIMITS_ALBUM 30000,
# SECONDS_LIMITS_TRACK 7200, UPLOAD_MAX_SIZE_USER 2, MAX_SONGS_PER_PLAYLIST 200,
# MAX_DOWNLOAD_USER 3, BOT_NAME @, FORUM @.
WARNING_BANNING=
FLOOD_WINDOW_SECONDS=
FLOOD_MESSAGE_LIMIT=
METHOD_SAVE=
DOWNLOAD_DIR_MAX_SIZE=
PROGRESS_STATUS_RATE=
TIME_SLEEP=
SECONDS_LIMITS_ALBUM=
SECONDS_LIMITS_TRACK=
UPLOAD_MAX_SIZE_USER=
MAX_SONGS_PER_PLAYLIST=
MAX_DOWNLOAD_USER=
BOT_NAME=
FORUM=
MODE_BOT=

# Not needed for covers or the converted download path (native Spotify only):
# EMAIL_SPO=
# PWD_SPO=
```

No additional API keys are required for cover art: the Deezer CDN, Spotify's image CDN (`i.scdn.co`) and the iTunes lookup API are all public.

# How to set Spotify credentials

1. Download the latest version https://github.com/dspearson/librespot-auth from the release tab
2. Launch using:
   1. Premium: `.\target\release\librespot-auth --name LibreSpot`
   2. Free: `.\target\release\librespot-auth --name LibreSpot --class=computer`
3. Open Spotify app and login
4. Play a random song and select the `LibreSpot` as an audio device
5. Return to the command line and check the filed saved
6. Modify the credentials.json:
   1. Replace the string `"auth_type": 1` with `"type":"AUTHENTICATION_STORED_SPOTIFY_CREDENTIALS"`
   2. Replace the string `"auth_data"` with `"credentials"`
7. Then map the file to container in `/app/credentials/credentials.json`
8. Run the container, it should login with Deezer and Spotify

# Where to get some tokens

  - the pyrogram api_id & api_hash can be created [here](https://my.telegram.org/auth?to=apps)
  - for create a telegram bot look [here](https://t.me/BotFather)
  - for acrcloud key, secret, host look at [acrcloud](https://docs.acrcloud.com/tutorials/recognize-music)
  - If you don't know how to get chat id send messages to him [@JsonDumpBot](https://t.me/JsonDumpBot)

To obtain your Deezer ARL cookie, you can follow these steps:

- Firefox:

1. Open Firefox and go to deezer.com.
2. Log in to your account
3. Click the three horizontal lines in the top right corner of the window to open the menu.
4. Select Tools > Web Developer Tools.
5. Click the Cookies tab.
6. Search for the arl cookie and copy the value.

- Chrome:

1. Open Chrome and go to deezer.com.
2. Log in to your account
3. Click the lock icon in the address bar.
4. Click Cookies.
5. Search for the arl cookie and copy the value.

# Cover art

Covers are fetched through a resilient Deezer → Spotify → iTunes chain with image validation, so refusals never become coverless files and a fallback rung still saves the artwork. Successful fallbacks and failure reason codes (`cdn_403`, `cdn_empty`, `invalid_body`, `no_md5`, `fallback_used`, `all_sources_failed`) are logged to `logs/downloads.log`. Previously coverless files are re-tagged in place and stored coverless uploads are re-uploaded via a soft cache refresh bounded by a one-hour cooldown.
