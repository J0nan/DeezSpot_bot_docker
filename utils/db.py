#!/usr/bin/python3

"""The dwsongs cache helpers, isolated so they stay importable and testable.

helpers.db_help imports configs.bot_settings, which pulls the telegram stack;
the bot image runs Python 3.11 with a working python-telegram-bot 13.x, but a
local 3.12 checkout cannot import it. These helpers depend on nothing but the
stdlib, so they live here and the bot helpers reuse them. The table layout,
query text and function bodies are the ones helpers.db_help used, plus two
additive nullable columns:

	cover_ok            NULL -> legacy row, trusted (no mass re-upload)
	                       1 -> the stored file carries artwork
	                       0 -> the stored file has no artwork, the caller
	                            refreshes it in place
	cover_attempted_at  epoch seconds of the last refresh attempt, stamped
	                    only on cover_ok == 0 writes, so a permanently
	                    coverless file is retried on a cooldown
"""

from os import environ
from time import time
from sqlite3 import (
	IntegrityError,
	connect as db_connect
)

# Mirrors configs.bot_settings (db_name, method_save) without importing it.
db_name = "DB/deez_bot.db"
method_save = int(environ.get('METHOD_SAVE', 3))

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

	# additive cover flag: existing rows keep NULL (legacy, trusted), so the
	# migration never re-uploads the whole cache
	cur.execute("PRAGMA table_info(dwsongs)")
	dwsongs_existing_columns = [
		column[1]
		for column in cur.fetchall()
	]

	if "cover_ok" not in dwsongs_existing_columns:
		cur.execute("ALTER TABLE dwsongs ADD COLUMN cover_ok INTEGER")

	# second additive column, same guard: the cooldown clock for coverless
	# rows, so permanently coverless content converges instead of looping
	if "cover_attempted_at" not in dwsongs_existing_columns:
		cur.execute("ALTER TABLE dwsongs ADD COLUMN cover_attempted_at REAL")

	con.commit()
	con.close()

def write_dwsongs(link, file_id, quality, chat_id, method_save=method_save, cover_ok=None):
	con = db_connect(db_name)

	# write_db swallows IntegrityError on a duplicate row, so the connection
	# is closed in a finally: otherwise the failed handle outlives the call
	try:
		cur = con.cursor()
		# atomic replace: one transaction drops the row this key owns and
		# inserts the newest upload, so a successful write always lands the
		# new file_id and a failed one leaves the old row untouched
		query_delete_dwsongs = "DELETE FROM dwsongs WHERE link = ? AND quality = ? AND method_save = ?"
		query_insert_dwsongs = "INSERT INTO dwsongs(link, file_id, quality, chat_id, method_save, cover_ok, cover_attempted_at) VALUES (?, ?, ?, ?, ?, ?, ?)"

		# only a coverless upload starts the retry cooldown
		cover_attempted_at = time() if cover_ok == 0 else None

		cur.execute(
			query_delete_dwsongs,
			(
				link, quality, method_save
			)
		)

		cur.execute(
			query_insert_dwsongs,
			(
				link, file_id,
				quality, chat_id,
				method_save, cover_ok,
				cover_attempted_at
			)
		)

		con.commit()
	finally:
		con.close()

def write_db(track_md5, file_id, n_quality, chat_id, n_method_save, cover_ok=None):
	try:
		write_dwsongs(track_md5, file_id, n_quality, chat_id, n_method_save, cover_ok)
	except IntegrityError:
		pass

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
	# cover_ok and cover_attempted_at are appended last: every existing
	# caller keeps reading the file_id at index 0
	query_select_dwsongs = "SELECT file_id, cover_ok, cover_attempted_at FROM dwsongs WHERE link = ? AND quality = ? AND method_save = ?"

	cur.execute(
		query_select_dwsongs,
		(
			link, quality, method_save
		)
	)

	match = cur.fetchone()
	con.close()

	return match