#!/usr/bin/python3

from datetime import datetime, timezone
from configs.bot_settings import (
	root_ids, warning_for_banning,
	flood_window_seconds, flood_message_limit
)

from configs.customs import (
	banning_msg1, banning_msg2,
	version, bot_name, creator,
	forum, active_since,
	last_reset, date_start
)

from helpers.db_help import (
	select_users_settings, write_users_settings,
	update_users_settings, write_banned,
	select_banned, select_all_banned,
	select_all_downloads, select_all_users
)

users_page_size = 20

def users_total_pages(total):
	if total <= 0:
		return 0

	return (total + users_page_size - 1) // users_page_size

def clamp_users_page(page, total):
	pages = users_total_pages(total)

	if pages == 0:
		return 0

	return max(0, min(page, pages - 1))

def format_users_page(rows, total, page):
	# plain text by design: usernames arrive unescaped, so the /users
	# message must never be sent with a parse_mode
	offset = page * users_page_size
	lines = [f"👥 {total} users — page {page + 1}/{users_total_pages(total)}"]

	for index, row in enumerate(rows):
		chat_id, username, last_used, dw_count = row
		name = f"@{username} (id: {chat_id})" if username else str(chat_id)
		last = last_used if last_used else "never"
		lines.append(f"{offset + index + 1}. {name} | last: {last} | dw: {dw_count}")

	return "\n".join(lines)

def users_set_cache(chat_id, users_data):
	user_exist = True

	if not chat_id in users_data:
		match = select_users_settings(chat_id)

		if not match:
			user_exist = False
			write_users_settings(chat_id)
			match = select_users_settings(chat_id)

		quality = match[0]
		zips = bool(match[1])
		tracks = bool(match[2])
		lang = match[3]
		source = match[4]
		search_method = match[5]
		method_save = match[6] 

		users_data[chat_id] = {
			"quality": quality,
			"zips": zips,
			"tracks": tracks,
			"lang": lang,
			"source": source,
			"search_method": search_method,
			"method_save": method_save, 
			"last_message": None,
			"messages_sent": 0,
			"times": 0,
			"c_downloads": {}
		}

	return user_exist

def user_setting_save_db(chat_id, user_data):
	update_users_settings(user_data, chat_id)

def check_flood(user_data, chat_id, date = None):
	# Rate guard of one chat. Messages that follow each other inside
	# flood_window_seconds build a burst; one burst of flood_message_limit
	# messages takes a strike and clears the burst, and warning_for_banning
	# strikes ban the chat.
	if chat_id in root_ids:
		return

	# the clock is when the update reached the bot, never the date written on
	# the message: a callback carries the age of the message its buttons sit
	# on, so an hour-old result card tapped five times in a second used to
	# look like five messages that were all hours apart
	date = datetime.now(timezone.utc) if date is None else date
	last_message = user_data['last_message']

	user_data['last_message'] = date

	if not last_message:
		return

	# total_seconds(): timedelta.seconds is only the sub-day remainder, so a
	# gap of one day and two seconds used to be read as a two second gap and
	# charged as a rapid message
	time_passed = (date - last_message).total_seconds()

	# a negative delta is an out-of-order arrival (clock skew, or a queued
	# update losing the race against a newer one): a calm gap, not a flood
	if 0 <= time_passed < flood_window_seconds:
		user_data['messages_sent'] += 1
	else:
		user_data['messages_sent'] = 0

	messages_sent = user_data['messages_sent']

	# >= instead of ==: a burst that overshoots the limit must strike, not
	# step past the guard untouched
	if messages_sent >= flood_message_limit:
		user_data['messages_sent'] = 0
		user_data['times'] += 1
		return banning_msg1, 0

	times = user_data['times']

	if times >= warning_for_banning:
		write_banned(chat_id)
		return banning_msg2, 1

def kill_threads(users_data):
	for c_user_data in users_data.values():
		for c_thread in c_user_data['c_downloads'].values():
			c_thread['thread'].kill()

		c_user_data['c_downloads'].clear()

def is_banned(chat_id):
	match = select_banned(chat_id)

	if match:
		return True

	return False

def get_banned_ids():
	match = select_all_banned()

	chat_ids = [
		chat_id[0]
		for chat_id in match
	]

	chat_ids = set(chat_ids)
	return chat_ids

def get_tot_downloads():
	match = select_all_downloads()
	tot = len(match)
	return tot

def get_tot_users():
	match = select_all_users()
	tot = len(match)
	return tot

def get_info():
	tot_users = get_tot_users()
	tot_downloads = get_tot_downloads()
	time_now = datetime.now()
	days_no_accidents = (time_now - date_start).days

	info_msg = (
		f"🔺 Version: {version}\
		\n📅 Active since: {active_since}\
		\n🔻 Name: {bot_name}\
		\n✒️ Creator: {creator}\
		\n📅 Last reset: {last_reset}\
		\n📣 Forum: {forum}\
		\n👥 Users: {tot_users}\
		\n⬇️ Total downloads: {tot_downloads}\
		\n📅 DAYS WITHOUT ACCIDENTS⚠️: {days_no_accidents}"
	)

	return info_msg