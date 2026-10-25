#!/usr/bin/python3

from configs.bot_settings import db_name, method_save
from sqlite3 import connect as db_connect
from configs.customs import bot_settings_config

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

def initialize_db():
	query_create_table_dwsongs = (
		"CREATE TABLE IF NOT EXISTS dwsongs(\
		id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, \
		link VARCHAR(255) NOT NULL, \
		file_id VARCHAR(255) UNIQUE NOT NULL, \
		quality VARCHAR(5) NOT NULL, \
		date DATE DEFAULT (datetime('now', 'localtime')), \
		chat_id INT NOT NULL, \
		method_save INT NOT NULL, \
		UNIQUE(link, quality, method_save))"
	)

	query_create_table_users_settings = (
		"CREATE TABLE IF NOT EXISTS users_settings(\
		id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, \
		chat_id INT UNIQUE NOT NULL, \
		quality VARCHAR(5) NOT NULL, \
		zips BOOLEAN NOT NULL, \
		tracks BOOLEAN NOT NULL, \
		lang VARCHAR(5) NOT NULL, \
		date DATE DEFAULT (datetime('now', 'localtime')), \
		source VARCHAR(8) NOT NULL, \
		method_save INT NOT NULL, \
		search_method VARCHAR(15) NOT NULL)"
	)

	query_create_table_banned = (
		"CREATE TABLE IF NOT EXISTS banned(\
		id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, \
		date DATE DEFAULT (datetime('now', 'localtime')), \
		chat_id INT UNIQUE NOT NULL)"
	)

	con = db_connect(db_name)
	cur = con.cursor()
	cur.execute(query_create_table_dwsongs)
	cur.execute(query_create_table_users_settings)
	cur.execute(query_create_table_banned)

	# guarded migration: old DBs carry neither column, and the `date`
	# column keeps its registration meaning (utils_graphs reads it)
	cur.execute("PRAGMA table_info(users_settings)")
	users_settings_existing_columns = [
		column[1]
		for column in cur.fetchall()
	]

	if "last_used" not in users_settings_existing_columns:
		cur.execute("ALTER TABLE users_settings ADD COLUMN last_used DATE")

	if "username" not in users_settings_existing_columns:
		cur.execute("ALTER TABLE users_settings ADD COLUMN username VARCHAR(32)")

	con.commit()
	con.close()

def write_dwsongs(link, file_id, quality, chat_id, method_save=method_save):
	con = db_connect(db_name)
	cur = con.cursor()
	query_insert_dwsongs = "INSERT INTO dwsongs(link, file_id, quality, chat_id, method_save) VALUES (?, ?, ?, ?, ?)"

	cur.execute(
		query_insert_dwsongs,
		(
			link, file_id,
			quality, chat_id,
			method_save
		)
	)

	con.commit()
	con.close()

def delete_dwsongs(file_id):
	con = db_connect(db_name)
	cur = con.cursor()
	query_delete_dwsongs = "DELETE FROM dwsongs WHERE file_id = ?"

	cur.execute(
		query_delete_dwsongs,
		(
			file_id,
		)
	)

	con.commit()
	con.close()

def select_dwsongs(link, quality, method_save=method_save):
	con = db_connect(db_name)
	cur = con.cursor()
	query_select_dwsongs = "SELECT file_id FROM dwsongs WHERE link = ? AND quality = ? AND method_save = ?"

	cur.execute(
		query_select_dwsongs,
		(
			link, quality, method_save
		)
	)

	match = cur.fetchone()
	con.close()

	return match

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