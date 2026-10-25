#!/usr/bin/python3

from utils.utils import check_config_bot
import os

print("Starting bot...")
check_config_bot()
mode_bot = int(os.environ.get("MODE_BOT",2))

from configs.set_configs import SetConfigs

SetConfigs(mode_bot)

from sys import argv
from hashlib import md5
#from signal import SIGTERM
#from os import getpid, kill
from time import sleep, time
from telegram import ParseMode
from helpers.download_help import DW
from pyrogram import idle as tg_user_start
from utils.special_thread import magicThread
from utils.converter_bytes import convert_bytes_to
from telegram.error import BadRequest, Unauthorized, TelegramError
from utils.utils_data import execute_search, shazam_song, get_album_card, get_artist_card

from utils.utils_graphs import (
	create_graph_users, create_graph_top_downloaders, get_data_downloaders
)

from telegram import (
	MessageEntity, Update, InputMediaPhoto
)

from helpers.db_help import (
	delete_banned, select_all_users, write_banned, select_dwsongs,
	touch_users_settings, select_users_listing, count_users_settings
)

from configs.customs import (
	not_found_query_gif, shazam_audio_query,
	shazam_function_msg, max_download_user_msg,
	help_msg, help_photo, feedback_text, what_can_I_do,
	donate_text, reasons_text, startup_text, save_methods,
	artist_commands_queries
)

from configs.bot_settings import (
	download_dir_max_size, time_sleep,
	output_shazam, recorded_file_max_size,
	root_ids, bunker_channel,
	owl_channel, max_download_user
)

from utils.utils_users_bot import (
	user_setting_save_db, users_set_cache,
	check_flood, get_banned_ids,
	get_info, kill_threads,
	users_page_size, users_total_pages,
	clamp_users_page, format_users_page
)

from utils.utils import (
	is_supported_link, get_download_dir_size,
	clear_download_dir, clear_recorded_dir,
	my_round, create_tmux, get_url_path,
	extract_supported_link
)

from telegram.ext import (
	CommandHandler, MessageHandler, Filters,
	CallbackQueryHandler
)

from inlines.inline_keyboards import (
	create_keyboad_search, create_keyboard_settings,
	create_keyboard_qualities, create_shazamed_keyboard,
	create_banned_keyboard,
	create_c_dws_user_keyboard, create_info_keyboard,
	create_keyboard_method_save, create_users_keyboard
)

from deezloader.libutils.utils import get_ids

from utils.search_cache import (
	store, resolve, attach_message, get_message,
	get_items, set_index, get_index,
	set_scope, clear, get_query, get_scope,
	get_user_message, get_display,
	set_page, get_page
)

from inlines.message_results import (
	edit_card, send_not_found,
	send_list, edit_list, total_pages
)

bot_chat_id = SetConfigs.tg_bot_api.bot.id
bot = SetConfigs.tg_bot_api.bot

banned_ids = get_banned_ids()

users_data = {}
roots_data = {}

to_ban = Filters.user(banned_ids)
strict_modes = [1, 3]

too_old_answer = "This search is too old, try again"

search_usage_hint = (
	"Write /search plus a query, or a prefix: "
	"art: | alb: | pla: | trk: | artist:<id>:<section>"
)

bare_prefixes = {"art", "alb", "pla", "trk", "artist"}

def is_bare_prefix(query):
	# the /start prefix buttons send "/sq:art: ": a prefix with no term
	# would run an empty-term search and answer the not-found card, so the
	# usage hint replaces it. The colon is required, so a plain word such as
	# "artist" stays a real query and "artist:<id>:<section>" is untouched.
	c_query = query.strip()

	if ":" not in c_query:
		return False

	return c_query.rstrip(":") in bare_prefixes

grammar_query_prefixes = ("art: ", "alb: ", "pla: ", "trk: ", "artist:")

def is_grammar_query(query):
	# the Track/Album/Artist filter buttons re-run the RAW plain-text query
	# with a scoped prefix, so the filter row appears ONLY for searches that
	# started as plain text; grammar queries (and the chart) already fixed
	# their scope, and stacking a prefix onto "artist:13:top" makes no sense
	return query.startswith(grammar_query_prefixes)

# keys mirror __list_scopes in inlines/message_results.py (the filter
# buttons carry exactly these scope names in /srf:<token>:<scope>)
search_filter_prefixes = {
	"all": "",
	"track": "trk: ",
	"album": "alb: ",
	"artist": "art: ",
}

def ban_chat_id(chat_id):
	write_banned(chat_id)
	to_ban.add_chat_ids(chat_id)

def help_check_user(chat_id, date = None, from_user = None):
	if (
		(mode_bot in strict_modes) and 
		(not chat_id in root_ids)
	):
		bot.send_message(
			chat_id = chat_id,
			text = "BOT IS UNDER MAINTENANCE"
		)

		to_ban.add_chat_ids(chat_id)

		return

	user_exist = users_set_cache(chat_id, users_data)

	if date:
		# every tracked interaction refreshes the row: last_used always
		# moves, username is kept when this update carries none.
		# tracking must never abort the interaction: a locked or busy
		# sqlite file degrades to a missing timestamp, not a dead bot
		try:
			c_username = from_user.username if from_user else None
			touch_users_settings(chat_id, date.strftime("%Y-%m-%d %H:%M:%S"), c_username)
		except Exception:
			pass

		user_data = users_data[chat_id]
		result = check_flood(date, user_data, chat_id)

		if result:
			msg, mode = result

			bot.send_message(
				chat_id = chat_id,
				text = msg
			)

			if mode == 1:
				to_ban.add_chat_ids(chat_id)
				del users_data[chat_id]

	if not user_exist:
		bot.send_message(
			chat_id = chat_id,
			text = startup_text,
			parse_mode = ParseMode.MARKDOWN
		)

def help_download(link, chat_id):
	if chat_id in to_ban.user_ids:
		return

	if not is_supported_link(link):
		text = "THIS LINK IS NOT SUPPORTED :("

		bot.send_message(
			chat_id = chat_id,
			text = text
		)

		return

	c_user_data = users_data[chat_id]
	c_downloads = c_user_data['c_downloads']

	if len(c_downloads) == max_download_user:
		bot.send_message(
			chat_id = chat_id,
			text = max_download_user_msg
		)

		return

	to_hash = f"{link}{c_user_data['quality']}{chat_id}{time()}".encode()
	hash_link = md5(to_hash).hexdigest()
	new_ins = DW(chat_id, c_user_data, hash_link)

	t = magicThread(
		target = new_ins.download,
		args = (link, )
	)

	c_downloads[hash_link] = {
		"link": link,
		"thread": t,
		"dw": new_ins
	}

	t.start()

def _run_search(
	chat_id, query, user_data,
	message_id = None, user_message_id = None, display = None
):
	if is_bare_prefix(query):
		bot.send_message(
			chat_id = chat_id,
			text = search_usage_hint
		)

		return

	items = execute_search(query, user_data)

	if not items:
		send_not_found(bot, chat_id)

		return

	has_filters = bool(query) and not is_grammar_query(query)
	# the chart (empty query) and grammar searches are not re-scopeable:
	# the filter row needs a raw text term to re-run, and grammar searches
	# store an empty raw query so /srf can never stack prefixes
	# ("trk: art: x", "trk: trk: x") or search an empty term
	# the header PAINTED first is the header KEPT for later /srb repaints:
	# store receives the caption, not the raw display, so grammar searches
	# never fall back to the chart header on Back
	caption = display if display is not None else query

	token = store(
		chat_id,
		items,
		query if has_filters else "",
		user_message_id,
		caption
	)

	if message_id:
		edit_list(
			bot, chat_id, message_id, token, items,
			caption, has_filters, "all"
		)
	else:
		new_message = send_list(
			bot, chat_id, token, items,
			caption, has_filters, "all"
		)
		message_id = new_message.message_id

	# the card message id and index ride inside the same cache entry,
	# re-attached here when store replaced it (contextual jumps)
	attach_message(chat_id, token, message_id)
	set_index(chat_id, token, 0)

def delete_search_messages(bot, chat_id, msg_id, token):
	# Close and Download cleanup: kill the bot's results message and the user
	# message that started the search, then drop the cache entry. Shared by
	# the Close button (/src) and Download (/sres) so cleanup behaves the
	# same on both paths.
	user_message_id = get_user_message(chat_id, token)
	alive = get_items(chat_id, token) is not None

	if alive:
		clear(chat_id)

	for target_id in (msg_id, user_message_id):
		if target_id is None:
			# get_user_message is None unless the tapped token still
			# owns the chat entry, so a forged/old token can only ever
			# delete the message it sits on
			continue

		try:
			bot.delete_message(
				chat_id = chat_id,
				message_id = target_id
			)
		except TelegramError:
			if target_id == msg_id:
				# no delete rights: strip the buttons instead
				try:
					bot.edit_message_reply_markup(
						chat_id = chat_id,
						message_id = msg_id,
						reply_markup = None
					)
				except TelegramError:
					pass

def handle_callback_queries(update: Update, context):
	callback_query = update.callback_query
	chat_id = callback_query.from_user.id

	if chat_id in to_ban.user_ids:
		return

	msg = callback_query.message
	date = msg.date
	help_check_user(chat_id, date)
	msg_id = msg.message_id
	query_id = callback_query.id
	data = callback_query.data
	c_user_data = users_data[chat_id]
	text = "Your settings"
	answer = "DONE"
	mode = 0

	if data == "/edit_setting_quality":
		text = "Qualities"
		c_keyboard = create_keyboard_qualities()

	elif data == "/edit_setting_method_save":
		text = save_methods
		c_keyboard = create_keyboard_method_save()

	elif data == "/edit_setting_zips":
		zips = c_user_data['zips']

		if zips:
			c_user_data['zips'] = False
		else:
			c_user_data['zips'] = True

		c_keyboard = create_keyboard_settings(c_user_data)
		user_setting_save_db(chat_id, c_user_data)

	elif data == "/edit_setting_tracks":
		tracks = c_user_data['tracks']

		if tracks:
			c_user_data['tracks'] = False
		else:
			c_user_data['tracks'] = True

		c_keyboard = create_keyboard_settings(c_user_data)
		user_setting_save_db(chat_id, c_user_data)

	elif data == "/edit_setting_source":
		source = c_user_data['source']

		if source == "SpoDee":
			c_user_data['source'] = "Dee"
		else:
			c_user_data['source'] = "Dee"

		c_keyboard = create_keyboard_settings(c_user_data)
		user_setting_save_db(chat_id, c_user_data)

	elif data.startswith("/unban_"):
		c_data = data.replace("/unban_", "")
		c_chat_id = int(c_data)
		text = "BANNED USERS"
		delete_banned(c_chat_id)
		to_ban.remove_chat_ids(c_chat_id)
		c_keyboard = create_banned_keyboard()
		answer = f"UNBANNED {c_chat_id}"

	elif data.startswith("/edit_setting_quality_"):
		c_data = data.replace("/edit_setting_quality_", "")
		c_user_data['quality'] = c_data
		c_keyboard = create_keyboard_settings(c_user_data)
		user_setting_save_db(chat_id, c_user_data)

	elif data.startswith("/edit_setting_method_save_"):
		c_data = data.replace("/edit_setting_method_save_", "")
		c_user_data['method_save'] = int(c_data)
		c_keyboard = create_keyboard_settings(c_user_data)
		user_setting_save_db(chat_id, c_user_data)

	elif data.startswith("/srl:"):
		mode = "srl"
		c_data = data.replace("/srl:", "")
		s_data = c_data.split(":")
		token = s_data[0]
		index = int(s_data[1])
		items = get_items(chat_id, token)

		if items is None or index < 0 or index >= len(items):
			answer = too_old_answer
		else:
			set_index(chat_id, token, index)
			edit_card(
				bot, chat_id, msg_id,
				token, items, index, c_user_data
			)

	elif data.startswith("/srb:"):
		mode = "srb"
		token = data.replace("/srb:", "")
		items = get_items(chat_id, token)

		if items is None:
			answer = too_old_answer
		else:
			# filter buttons return only when the entry kept a raw
			# plain-text query (grammar searches stored "")
			has_filters = bool(get_query(chat_id, token))
			edit_list(
				bot, chat_id, msg_id, token, items,
				get_display(chat_id, token),
				has_filters, get_scope(chat_id, token),
				get_page(chat_id, token)
			)

	elif data.startswith("/srp:"):
		mode = "srp"
		c_data = data.replace("/srp:", "")
		s_data = c_data.split(":")
		token = s_data[0]
		page = int(s_data[1])
		items = get_items(chat_id, token)

		if items is None:
			answer = too_old_answer
		else:
			# nav buttons only offer adjacent pages: clamp anyway so a
			# stale message's Next can never render an empty page
			page = min(max(page, 0), total_pages(items) - 1)
			set_page(chat_id, token, page)
			has_filters = bool(get_query(chat_id, token))
			edit_list(
				bot, chat_id, msg_id, token, items,
				get_display(chat_id, token),
				has_filters, get_scope(chat_id, token), page
			)

	elif data.startswith("/srf:"):
		mode = "srf"
		c_data = data.replace("/srf:", "")
		s_data = c_data.split(":")
		token = s_data[0]
		scope = s_data[1]
		query = get_query(chat_id, token)

		if query is None:
			answer = too_old_answer
		elif scope not in search_filter_prefixes:
			answer = "Sorry isn't avalaible :("
		else:
			items = execute_search(
				search_filter_prefixes[scope] + query,
				c_user_data
			)

			if not items:
				answer = "No results for that filter :("
			else:
				# same token, same message: only the result rows swap
				set_scope(chat_id, token, items, scope)
				edit_list(
					bot, chat_id, msg_id, token, items,
					get_display(chat_id, token),
					True, scope, get_page(chat_id, token)
				)

	elif data.startswith("/src:"):
		mode = "src"
		token = data.replace("/src:", "")
		# an expired or replaced entry gives None for both: the tapped
		# message still dies inside the helper, the LIVE entry of the
		# chat does not
		delete_search_messages(bot, chat_id, msg_id, token)

		answer = "CLOSED :)"

	elif data.startswith("/sres:"):
		mode = "sres"
		c_data = data.replace("/sres:", "")
		s_data = c_data.split(":")
		token = s_data[0]
		index = int(s_data[1])
		item = resolve(chat_id, token, index)

		if item is None:
			answer = too_old_answer
		else:
			match = None

			if item['type'] == "track":
				match = select_dwsongs(
					get_url_path(item['link']),
					c_user_data['quality'],
					c_user_data['method_save']
				)

			if match:
				bot.send_audio(
					chat_id = chat_id,
					audio = match[0]
				)
			else:
				help_download(item['link'], chat_id)

			# the download cleans the search up behind it
			delete_search_messages(bot, chat_id, msg_id, token)

	elif data.startswith("/ctx:"):
		mode = "ctx"
		c_data = data.replace("/ctx:", "")
		s_data = c_data.split(":")
		token = s_data[0]
		kind = s_data[1]
		item = resolve(chat_id, token, get_index(chat_id, token))

		if item is None:
			answer = too_old_answer
		elif kind in ("album", "artist"):
			# the contextual buttons jump to the bot's OWN detail card
			# for the exact album/artist, never to a deezer.com URL
			ids = item['links'].get(kind)

			if not ids:
				# card rendered before the url-to-id change: the stale
				# button sits on an item whose links carry no id to jump
				# with, so treat it like an expired entry
				answer = too_old_answer
			else:
				if kind == "album":
					card = get_album_card(ids)
				else:
					card = get_artist_card(ids)

				if card is None:
					answer = "No results :("
				else:
					# single-item card view: same jump bookkeeping order
					# as _run_search, but rendered with edit_card. Read
					# the old entry BEFORE store replaces it, so Close
					# keeps the chat's original text message deletable
					# through the jump
					user_message_id = get_user_message(chat_id, token)
					message_id = get_message(chat_id, token)
					items = [card]
					card_title = card['title']

					token2 = store(
						chat_id,
						items,
						"",
						user_message_id,
						card_title
					)

					edit_card(
						bot, chat_id, message_id,
						token2, items, 0, c_user_data
					)
					attach_message(chat_id, token2, message_id)
					set_index(chat_id, token2, 0)
		else:
			ids = get_ids(item['link'])
			query = f"artist:{ids}:{kind}"
			command = artist_commands_queries.get(kind)
			display = (
				f"{item['title']} · {command['text']}"
				if command else query
			)
			# read the old entry BEFORE store replaces it, so Close keeps
			# the chat's original text message deletable through the jump
			user_message_id = get_user_message(chat_id, token)

			_run_search(
				chat_id,
				query,
				c_user_data,
				message_id = get_message(chat_id, token),
				user_message_id = user_message_id,
				display = display
			)

	elif data.startswith("/sq:"):
		mode = "sq"
		query = data[4:]

		if query.strip():
			_run_search(chat_id, query, c_user_data)
		else:
			bot.send_message(
				chat_id = chat_id,
				text = search_usage_hint
			)

	elif data.startswith("/down:"):
		mode = "down:"
		answer = "GOOD CHOICE :)"
		c_data = data.replace("/down:", "")

	elif data == "/back_home":
		c_keyboard = create_keyboard_settings(c_user_data)

	elif data.startswith("/kill_dw_"):
		mode = "kill"
		answer = "DOWNLOAD DELETED :)"
		c_hash = data.replace("/kill_dw_", "")
		c_dws = c_user_data['c_downloads']

		if not c_hash in c_dws:
			answer = "THIS IS AN OLD DOWNLOAD :)"
		else:
			t = c_dws[c_hash]['thread']
			t.kill()
			del c_dws[c_hash]

	elif data.startswith("/usr_pg:"):
		mode = "usr_pg"
		c_page = int(data.replace("/usr_pg:", ""))

		if not chat_id in root_ids:
			answer = "ONLY ADMINS CAN NAVIGATE THIS LIST"
		else:
			total = count_users_settings()[0]
			pages = users_total_pages(total)

			if pages == 0:
				answer = "No users yet"
			else:
				# a stale message's Next can outlive deleted users:
				# clamp to the last page so no tap renders an empty one
				page = clamp_users_page(c_page, total)
				rows = select_users_listing(users_page_size, page * users_page_size)

				try:
					bot.edit_message_text(
						chat_id = chat_id,
						message_id = msg_id,
						text = format_users_page(rows, total, page),
						reply_markup = create_users_keyboard(page, pages)
					)
				except BadRequest:
					# re-tapping the page indicator edits identical text
					pass

	else:
		mode = 1
		answer = "Sorry isn't avalaible :("

	if mode == 0:
		bot.edit_message_text(
			chat_id = chat_id,
			message_id = msg_id,
			text = text,
			reply_markup = c_keyboard
		)

	bot.answer_callback_query(
		callback_query_id = query_id,
		text = answer
	)

	if mode == "kill":
		bot.delete_message(
			chat_id = chat_id,
			message_id = msg_id
		)

	elif mode == "down:":
		help_download(c_data, chat_id)

def audio_handler(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	msg_id = msg.message_id
	date = msg.date
	help_check_user(chat_id, date)
	audio = msg.audio

	if not audio:
		audio = msg.voice

	audio_size = convert_bytes_to(audio.file_size, "mb")

	if audio_size > recorded_file_max_size:
		bot.send_message(
			chat_id = chat_id,
			text = f"PLEASE SEND A FILE AUDIO/RECORD LOWER THAN {recorded_file_max_size} MB =)"
		)

		return

	file_id = audio.file_id
	c_file = bot.get_file(file_id)

	try:
		SetConfigs.queues_started += 1

		out = c_file.download(
			custom_path = f"{output_shazam}{file_id}"
		)

		resp = shazam_song(out)
	finally:
		SetConfigs.queues_finished += 1

	if not resp:
		bot.send_message(
			chat_id = chat_id,
			text = "I CANNOT SHAZAM THE SONG RETRY :("
		)

		return

	artist, genre,\
		album, label,\
			track_link, album_link,\
				artist_link, image_url,\
					release_date, title = resp

	if track_link:
		reply_markup = create_shazamed_keyboard(track_link, album_link, artist_link)
	else:
		reply_markup = None
		image_url = not_found_query_gif

	bot.send_photo(
		chat_id = chat_id,
		photo = image_url,
		reply_to_message_id = msg_id,
		reply_markup = reply_markup,
		caption = (
			shazam_audio_query
			% (
				artist,
				genre,
				album,
				label,
				release_date,
				title
			)
		)
	)

def start_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)

	bot.send_message(
		chat_id = chat_id,
		text = "YOU JUST PRESSED START YOU WON A NICE DAY :)))\n\nSEND ME ANY LINK OR TEXT AND I WILL SEARCH IT FOR YOU :)\n\nIF YOU WANT TO KNOW THE COMMANDS SEND /help",
	)

def cmd_search(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)
	c_user_data = users_data[chat_id]
	# the command token is dropped whole: Telegram clients emit
	# "/search@BotName ..." in groups, and a prefix replace would leak the
	# bot username into the query and miss the grammar
	parts = msg.text.split(" ", 1)
	query = parts[1] if len(parts) > 1 else ""

	# the command message rides in the entry too: Close deletes whatever
	# message triggered the search, plain or grammar
	_run_search(
		chat_id,
		query,
		c_user_data,
		user_message_id = msg.message_id
	)

def settings_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)
	c_user_data = users_data[chat_id]

	bot.send_message(
		chat_id = chat_id,
		text = "Your settings",
		reply_markup = create_keyboard_settings(c_user_data)
	)

def quality_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)
	c_user_data = users_data[chat_id]

	bot.send_message(
		chat_id = chat_id,
		text = f"Current quality {c_user_data['quality']}",
		reply_markup = create_keyboard_qualities()
	)

def managing_banned_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id

	bot.send_message(
		chat_id = chat_id,
		text = "Banned users",
		reply_markup = create_banned_keyboard()
	)

def add_banned_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id

	if not chat_id in roots_data:
		roots_data[chat_id] = {
			"stage": None
		}

	bot.send_message(
		chat_id = chat_id,
		text = "Send me the user to ban"
	)

	roots_data[chat_id]['stage'] = "add_banned"

def send_global_msg_command(update: Update, context):
	msg = update.channel_post
	text = msg.text
	audio = msg.audio
	document = msg.document
	animation = msg.animation
	sticker = msg.sticker
	video = msg.video
	photo = msg.photo
	to_send = None
	method = None

	if text:
		to_send = text
		method = bot.send_message
	elif audio:
		to_send = audio.file_id
		method = bot.send_audio
	elif document:
		to_send = document.file_id
		method = bot.send_document
	elif animation:
		to_send = animation.file_id
		method = bot.send_animation
	elif sticker:
		to_send = sticker.file_id
		method = bot.send_sticker
	elif video:
		to_send = video.file_id
		method = bot.send_video
	elif photo:
		to_send = photo[0].file_id
		method = bot.send_photo

	def broadcast():
		all_user = select_all_users()
		
		for user_id in all_user:
			c_user_id = user_id[0]

			try:
				method(c_user_id, to_send)
			except (BadRequest, Unauthorized):
				pass

	magicThread(target = broadcast).start()

def shazam_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)

	bot.send_message(
		chat_id = chat_id,
		text = shazam_function_msg
	)

def kill_dw_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)
	c_user_data = users_data[chat_id]
	c_downloads = c_user_data['c_downloads']

	if not c_downloads:
		bot.send_message(
			chat_id = chat_id,
			text = "There aren't any download in progress"
		)

		return

	keybords_dws = create_c_dws_user_keyboard(c_downloads)

	for c_download, keyboard in zip(
		c_downloads.values(), keybords_dws
	):
		c_text = f"{c_download['link']} in {c_user_data['quality']}"

		bot.send_message(
			chat_id = chat_id,
			text = c_text,
			reply_markup = keyboard
		)

def info_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)
	users_graph = create_graph_users()

	bot.send_photo(
		chat_id = chat_id,
		photo = users_graph,
		caption = get_info(),
		reply_markup = create_info_keyboard()
	)

def reasons_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)

	bot.send_message(
		chat_id = chat_id,
		text = reasons_text
	)

def help_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)

	bot.send_photo(
		chat_id = chat_id,
		photo = help_photo,
		caption = help_msg
	)

	bot.send_message(
		chat_id = chat_id,
		text = what_can_I_do
	)

def feedback_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)

	bot.send_message(
		chat_id = chat_id,
		text = feedback_text
	)

def donate_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)

	bot.send_message(
		chat_id = chat_id,
		text = donate_text,
		reply_markup = create_info_keyboard()
	)

def graphs_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)
	downloads_graph = create_graph_top_downloaders()
	users_graph = create_graph_users()
	users, nums_downloads = get_data_downloaders()

	caption_text_download_graph = ""
	times = 1

	for user, num_downloads in zip(users, nums_downloads):
		caption_text_download_graph += f"{times} Place: User `{user}` with {num_downloads} downloads\n"
		times += 1

	medias = [
		InputMediaPhoto(
			media = downloads_graph,
			caption = caption_text_download_graph,
			parse_mode = ParseMode.MARKDOWN_V2
		),
		InputMediaPhoto(
			media = users_graph
		)
	]

	bot.send_media_group(
		chat_id = chat_id,
		media = medias
	)

def users_command(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id

	total = count_users_settings()[0]

	if total == 0:
		bot.send_message(
			chat_id = chat_id,
			text = "No users yet"
		)

		return

	pages = users_total_pages(total)
	rows = select_users_listing(users_page_size, 0)

	bot.send_message(
		chat_id = chat_id,
		text = format_users_page(rows, total, 0),
		reply_markup = create_users_keyboard(0, pages)
	)

def msgs_handler(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	text = msg.text

	if chat_id in roots_data:
		if roots_data[chat_id]['stage'] == "add_banned":
			ban_chat_id(text)
			roots_data[chat_id]['stage'] = None

			bot.send_message(
				chat_id = chat_id,
				text = f"User {text} has been blocked"
			)

			return

	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)

	# a link pasted with rich formatting carries a TEXT_LINK entity, so the
	# control_links handler (URL entity filter) never sees it: try a music
	# link here before falling through to a text search of the link label
	c_link = extract_supported_link(msg.text, msg.entities)

	if c_link:
		help_download(c_link, chat_id)

		return

	if msg.chat.type == "private":
		c_user_data = users_data[chat_id]
		_run_search(
			chat_id,
			text,
			c_user_data,
			user_message_id = msg.message_id
		)

		return

	bot.send_message(
		chat_id = chat_id,
		text = text
	)

def controls_links(update: Update, context):
	msg = update.message
	chat_id = msg.from_user.id
	date = msg.date
	help_check_user(chat_id, date, from_user = msg.from_user)
	link = extract_supported_link(msg.text, msg.entities)

	# no music link among the entities: legacy path, the URL filter
	# guaranteed entities[0] before this change
	if not link:
		entity_link = msg.entities[0]
		link = msg.parse_entity(entity_link)

	help_download(link, chat_id)

dispatcher = SetConfigs.tg_bot_api.dispatcher

start_handler = CommandHandler(
	"start",
	start_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(start_handler)

settings_handler = CommandHandler(
	"settings",
	settings_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(settings_handler)

quality_handler = CommandHandler(
	"quality",
	quality_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(quality_handler)

to_root = Filters.user(root_ids)

managing_banned_handler = CommandHandler(
	"managing_banned",
	managing_banned_command,
	filters = to_root, run_async = True
)

dispatcher.add_handler(managing_banned_handler)

add_banned_handler = CommandHandler(
	"add_banned",
	add_banned_command,
	filters = to_root, run_async = True
)

dispatcher.add_handler(add_banned_handler)

users_handler = CommandHandler(
	"users",
	users_command,
	filters = to_root, run_async = True
)

dispatcher.add_handler(users_handler)

shazam_handler = CommandHandler(
	"shazam",
	shazam_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(shazam_handler)

kill_dw_handler = CommandHandler(
	"kill_dw",
	kill_dw_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(kill_dw_handler)

info_handler = CommandHandler(
	"info",
	info_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(info_handler)

reasons_handler = CommandHandler(
	"reasons",
	reasons_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(reasons_handler)

help_handler = CommandHandler(
	"help",
	help_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(help_handler)

feedback_handler = CommandHandler(
	"feedback",
	feedback_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(feedback_handler)

donate_handler = CommandHandler(
	"donate",
	donate_command,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(donate_handler)

graphs_handler = CommandHandler(
	"graphs",
	graphs_command,
	filters = to_root, run_async = True
)

dispatcher.add_handler(graphs_handler)

search_handler = CommandHandler(
	"search",
	cmd_search,
	filters = ~ to_ban, run_async = True
)

dispatcher.add_handler(search_handler)

filter_owl_channel = Filters.chat(owl_channel)

send_global_msg_handler = MessageHandler(
	filter_owl_channel,
	send_global_msg_command,
	run_async = True
)

dispatcher.add_handler(send_global_msg_handler)

filter_url = Filters.entity(
	MessageEntity.URL
)

control_links = MessageHandler(
	(
		filter_url &
		~ to_ban
	), controls_links, run_async = True
)

dispatcher.add_handler(control_links)

filter_text = Filters.text

msgs = MessageHandler(
	(
		filter_text &
		~ to_ban
	), msgs_handler, run_async = True
)

dispatcher.add_handler(msgs)

filter_shazam = (Filters.voice | Filters.audio)
filter_bunker_channel = Filters.chat(bunker_channel)
filter_no_bot = Filters.via_bot(bot_chat_id)

audio_msgs = MessageHandler(
	(
		filter_shazam &
		~ filter_no_bot &
		~ to_ban &
		~ filter_bunker_channel
	), audio_handler, run_async = True
)

dispatcher.add_handler(audio_msgs)

callback_queries = CallbackQueryHandler(
	handle_callback_queries, run_async = True
)

dispatcher.add_handler(callback_queries)

SetConfigs.tg_bot_api.start_polling()

def checking():
	while True:
		sleep(time_sleep)

		dir_size = my_round(
			get_download_dir_size()
		)

		print(
			f"STATUS DOWNLOADS {SetConfigs.queues_started}/{SetConfigs.queues_finished} {dir_size}/{download_dir_max_size}"
		)

		if (
			dir_size >= download_dir_max_size
		) or (
			SetConfigs.queues_started == SetConfigs.queues_finished
		):
			SetConfigs.tg_bot_api.stop()
			kill_threads(users_data)
			sleep(3)
			SetConfigs.queues_started = 0
			SetConfigs.queues_finished = 0
			clear_download_dir()
			clear_recorded_dir()
			SetConfigs.tg_bot_api.start_polling()

if len(argv) == 1:
	tmux_session = None
else:
	tmux_session = create_tmux()

check_thread = magicThread(target = checking)
check_thread.start()

tg_user_start()

print("\nEXITTING WAIT A FEW SECONDS :)")
clear_download_dir()
clear_recorded_dir()

SetConfigs.tg_bot_api.stop()
check_thread.kill()
kill_threads(users_data)

if tmux_session:
	tmux_session.kill_session()