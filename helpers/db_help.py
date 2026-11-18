#!/usr/bin/python3

from configs.bot_settings import db_name, method_save
from sqlite3 import connect as db_connect
from configs.customs import bot_settings_config

# The dwsongs cache has a single implementation in utils.db: stdlib-only, so
# the bot image and the tests reach the same code. The two names above are the
# same values utils.db mirrors, and the four functions re-exported here keep
# the import surface every caller already uses.
from utils.db import (
	initialize_db, write_dwsongs,
	delete_dwsongs, select_dwsongs
)

users_settings_columns = [
	setting[1]
	for setting in bot_settings_config
]

query_insert_users_settings_str_fields = ""
query_insert_users_settings_str_input = ""
query_update_users_settings_str_input = ""

for setting in bot_settings_config:
	query_insert_users_settings_str_fields += f"{setting[1]},"
	query_insert_users_settings_str_input += "?,"
	query_update_users_settings_str_input += f"{setting[1]} = ?,"

query_update_users_settings_str_input = query_update_users_settings_str_input[:-1]
query_insert_users_settings_str_fields = query_insert_users_settings_str_fields[:-1]
query_insert_users_settings_str_input = query_insert_users_settings_str_input[:-1]

def write_users_settings(chat_id):
	con = db_connect(db_name)
	cur = con.cursor()

	query_insert_users_settings = (
		f"INSERT INTO users_settings\
		(chat_id, {query_insert_users_settings_str_fields}) \
		VALUES (?, {query_insert_users_settings_str_input})"
	)

	c_settings = [chat_id]

	c_settings += [
		c_setting[2]
		for c_setting in bot_settings_config
	]

	cur.execute(query_insert_users_settings, c_settings)
	con.commit()
	con.close()

def write_banned(chat_id):
	con = db_connect(db_name)
	cur = con.cursor()
	query_insert_banned = "INSERT INTO banned(chat_id) VALUES (?)"

	cur.execute(
		query_insert_banned,
		(
			chat_id,
		)
	)

	con.commit()
	con.close()

def delete_banned(chat_id):
	con = db_connect(db_name)
	cur = con.cursor()
	query_delete_banned = "DELETE FROM banned WHERE chat_id = ?"

	cur.execute(
		query_delete_banned,
		(
			chat_id,
		)
	)

	con.commit()
	con.close()

def select_banned(chat_id):
	con = db_connect(db_name)
	cur = con.cursor()
	query_select_banned = "SELECT chat_id FROM banned WHERE chat_id = ?"

	cur.execute(
		query_select_banned,
		(
			chat_id,
		)
	)

	match = cur.fetchone()
	con.close()

	return match

def select_all_banned():
	con = db_connect(db_name)
	cur = con.cursor()
	query_select_banned = "SELECT chat_id FROM banned"
	cur.execute(query_select_banned)
	match = cur.fetchall()
	con.close()

	return match

def update_users_settings(user_settings, chat_id):
	con = db_connect(db_name)
	cur = con.cursor()

	query_update_users_settings = (
		f"UPDATE users_settings SET {query_update_users_settings_str_input} WHERE chat_id = ?"
	)

	c_settings = []

	for c_setting in user_settings:
		if c_setting in users_settings_columns:
			c_settings.append(user_settings[c_setting])

	c_settings.append(chat_id)
	cur.execute(query_update_users_settings, c_settings)
	con.commit()
	con.close()

def touch_users_settings(chat_id, last_used, username):
	con = db_connect(db_name)
	cur = con.cursor()

	# MAX() keeps last_used monotonic: callback handlers pass the age of
	# the pressed message, so a tap on an old post must never rewind it
	query_touch_users_settings = "UPDATE users_settings SET last_used = MAX(COALESCE(last_used, ?), ?), username = COALESCE(?, username) WHERE chat_id = ?"

	cur.execute(
		query_touch_users_settings,
		(
			last_used, last_used, username, chat_id
		)
	)

	con.commit()
	con.close()

def select_users_settings(chat_id):
	con = db_connect(db_name)
	cur = con.cursor()

	query_select_users_settings = (
		f"SELECT {query_insert_users_settings_str_fields} FROM users_settings WHERE chat_id = ?"
	)

	cur.execute(
		query_select_users_settings,
		(
			chat_id,
		)
	)

	match = cur.fetchone()
	con.close()

	return match

def select_all_users():
	con = db_connect(db_name)
	cur = con.cursor()
	query_select_users = "SELECT chat_id FROM users_settings"
	cur.execute(query_select_users)
	match = cur.fetchall()
	con.close()

	return match

def select_all_downloads():
	con = db_connect(db_name)
	cur = con.cursor()
	query_select_dwsongs = "SELECT file_id FROM dwsongs"
	cur.execute(query_select_dwsongs)
	match = cur.fetchall()
	con.close()

	return match

def select_users_settings_date(c_month, c_year):
	con = db_connect(db_name)
	cur = con.cursor()

	cur.execute(
		"SELECT date FROM users_settings WHERE strftime('%m', date) = ? AND strftime('%Y', date) = ?",
		(
			c_month, c_year
		)
	)

	match = cur.fetchall()
	con.close()

	return match

def select_dwsongs_top_downloaders(many):
	con = db_connect(db_name)
	cur = con.cursor()

	cur.execute(
		"SELECT chat_id, COUNT(chat_id) as cnt FROM dwsongs GROUP BY chat_id ORDER BY cnt DESC LIMIT ?",
		(many, )
	)

	match = cur.fetchall()
	con.close()

	return match

def select_users_listing(limit, offset):
	con = db_connect(db_name)
	cur = con.cursor()

	# LEFT JOIN keeps users with zero downloads (count 0); never-used
	# users (NULL last_used) sort after every timestamped user
	cur.execute(
		"SELECT u.chat_id, u.username, u.last_used, COUNT(d.id) FROM users_settings u LEFT JOIN dwsongs d ON d.chat_id = u.chat_id GROUP BY u.chat_id ORDER BY u.last_used IS NULL, u.last_used DESC, u.chat_id LIMIT ? OFFSET ?",
		(
			limit, offset
		)
	)

	match = cur.fetchall()
	con.close()

	return match

def count_users_settings():
	con = db_connect(db_name)
	cur = con.cursor()
	query_count_users_settings = "SELECT COUNT(chat_id) FROM users_settings"
	cur.execute(query_count_users_settings)
	match = cur.fetchone()
	con.close()

	return match