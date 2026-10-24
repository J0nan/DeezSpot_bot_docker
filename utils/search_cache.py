# Bounded in-memory cache for search results. Exactly one active search
# per chat, a lazy 30-minute TTL checked only on access (no background thread,
# no timers), and a global LRU ceiling of MAX_CHATS chats. The card's
# telegram message id rides inside the same entry, so nothing lives outside
# this bounded store; query / scope / user_message_id (in-place filters and
# the Close button) live in the SAME entry too, never in a second store.
# Entries hold only lightweight display fields: audio file_ids come from
# the SQLite select_dwsongs lookup, never from here.
# PTB runs handlers concurrently, so every access is guarded by one lock.

from time import time
from hashlib import md5
from threading import Lock
from collections import OrderedDict

TTL_SECONDS = 30 * 60
MAX_CHATS = 1000

_entries = OrderedDict()
_counter = 0
_lock = Lock()

def _now():
	# injectable time source: the tests monkeypatch this instead of sleeping
	return time()

def __alive_entry(chat_id, token):
	# caller holds _lock; returns the entry or None when the chat is
	# missing, expired (the entry is then purged, storing nothing in its
	# place) or the token belongs to a replaced entry
	entry = _entries.get(chat_id)

	if entry is None:
		return None

	if _now() - entry["stored_at"] > TTL_SECONDS:
		del _entries[chat_id]

		return None

	if entry["token"] != token:
		return None

	return entry

def store(chat_id, items, query = "", user_message_id = None, display = None) -> str:
	global _counter

	with _lock:
		# the counter keeps tokens unique even when two stores land on the
		# same clock tick
		_counter += 1
		seed = f"{chat_id}:{_now()}:{_counter}"
		token = md5(seed.encode()).hexdigest()[:8]
		entry = {
			"token": token,
			"items": list(items),
			"stored_at": _now(),
			"message_id": None,
			"index": 0,
			# the list view's current page, display-side
			# only — the entry clamps nothing, the render layer owns bounds
			"page": 0,
			# the raw query powers the in-place
			# Track/Album/Artist filters; user_message_id lets the Close
			# button delete the text message that started the search;
			# display is the human header ("" for the chart).
			"query": query,
			"scope": "all",
			"user_message_id": user_message_id,
			"display": display if display is not None else query
		}
		# full replace, never accumulate; the fresh entry starts most-recent
		_entries.pop(chat_id, None)
		_entries[chat_id] = entry

		while len(_entries) > MAX_CHATS:
			_entries.popitem(last = False)

	return token

def set_scope(chat_id, token, items, scope) -> bool:
	# Filter tap: swap the result list in place. The token SURVIVES so
	# every callback button already rendered on the message stays alive;
	# only items, scope and the detail index change.
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return False

		entry["items"] = list(items)
		entry["scope"] = scope
		entry["index"] = 0
		# a filter swap replaces the whole list, so page 2
		# of the old result set would dangle over the new one
		entry["page"] = 0
		_entries.move_to_end(chat_id)

	return True

def set_page(chat_id, token, page) -> None:
	# Store the list's current page. Dumb slot on purpose:
	# only negatives are rejected, the render layer clamps against the real
	# page count so this module stays free of display constants.
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return

		if page < 0:
			return

		entry["page"] = page
		_entries.move_to_end(chat_id)

def get_page(chat_id, token) -> int | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		page = entry["page"]

	return page

def clear(chat_id) -> None:
	# Close button: drop the entry immediately instead of waiting for
	# the lazy TTL; unknown chats are a no-op.
	with _lock:
		_entries.pop(chat_id, None)

def get_query(chat_id, token) -> str | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		query = entry["query"]

	return query

def get_scope(chat_id, token) -> str | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		scope = entry["scope"]

	return scope

def get_user_message(chat_id, token) -> int | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		user_message_id = entry["user_message_id"]

	return user_message_id

def get_display(chat_id, token) -> str | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		display = entry["display"]

	return display

def resolve(chat_id, token, index) -> dict | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		items = entry["items"]

		if index < 0 or index >= len(items):
			return None

		_entries.move_to_end(chat_id)
		item = items[index]

	return item

def attach_message(chat_id, token, message_id) -> None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return

		entry["message_id"] = message_id
		_entries.move_to_end(chat_id)

def get_message(chat_id, token) -> int | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		message_id = entry["message_id"]

	return message_id

def get_items(chat_id, token) -> list | None:
	# Whole live result list of the chat's one active search: the /srl detail
	# probe bounds-checks against it, and /srb + /srf rebuild the list view
	# from it.
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		items = entry["items"]

	return items

def set_index(chat_id, token, index) -> None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return

		if index < 0 or index >= len(entry["items"]):
			return

		entry["index"] = index
		_entries.move_to_end(chat_id)

def get_index(chat_id, token) -> int | None:
	with _lock:
		entry = __alive_entry(chat_id, token)

		if entry is None:
			return None

		_entries.move_to_end(chat_id)
		index = entry["index"]

	return index
