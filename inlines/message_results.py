#!/usr/bin/python3

from telegram import (
	InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)

from telegram.error import TelegramError

from configs.customs import (
	empty_image_url, not_found_query_gif, artist_commands_queries
)

from helpers.db_help import select_dwsongs
from utils.utils import get_url_path
from utils.utils_data import expand_track_credits

# Title of the old inline not-found article, kept for the card flow.
not_found_title = "ERROR 404 :)"

# The list view renders up to PAGE_SIZE results as buttons per page, the
# caption is only a header line (the full results live in the buttons),
# track labels read "Title - Artist", and icons key off the item type.
__result_icons = {
	"track": "🎵",
	"album": "💽",
	"artist": "👤",
	"playlist": "📃",
}

# Telegram caps an inline button label at 64 characters, the same budget its
# callback_data gets. python-telegram-bot exports no constant for the label:
# 13.15 has only message/caption/answer sizes, and even 20+'s
# InlineKeyboardButtonLimit carries just MIN/MAX_CALLBACK_DATA. So the budget
# is named once here. The icon and its space are charged 3 of the 64, since
# Telegram counts a non-BMP emoji as two units, and 1 unit stays as spare.
__button_text_max = 64
__list_label_max = __button_text_max - 4

# when a title and its artist credit cannot both fit, the credit still keeps
# a home: the title is cut in the MIDDLE and never squeezed below this
__list_title_floor = 30

# results are paginated, ten buttons per page
PAGE_SIZE = 10

# the header embeds the raw query/display; cap it so a pathological search
# term can never push the caption over Telegram's 1024-char limit
__list_display_max = 200

__list_scopes = [
	("all", "🌐 All"),
	("track", "🎵 Tracks"),
	("album", "💽 Albums"),
	("artist", "👤 Artists"),
]

def __icon(item):
	return __result_icons.get(item['type'], "🔎")

def __middle(text, width):
	# Cut the middle, keep both ends: the start identifies the song, the end
	# carries the version suffix ("(Live Edition)") and the last credit.
	if len(text) <= width:
		return text

	if width <= 1:
		return text[: width]

	head = (width - 1) // 2
	tail = width - 1 - head

	return f"{text[: head]}…{text[len(text) - tail :]}" if tail else f"{text[: head]}…"

def total_pages(items):
	# a never-rendered empty list still reports one page, so the clamp
	# arithmetic never produces negative pages
	return max(1, -(-len(items) // PAGE_SIZE))

def page_items(items, page):
	return items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

def __item_label(item):
	# tracks advertise their artist right on the button: the complete credit
	# list when it is known, the main artist while the page has not been
	# looked up yet. Both the title and the credit get their chance to show.
	title = item['title']
	artist = item.get('artist') if item['type'] == "track" else None

	if not artist:
		return __middle(title, __list_label_max)

	credit = f" - {artist}"

	if len(title) + len(credit) <= __list_label_max:
		return f"{title}{credit}"

	# over budget: the credit is truncated last (down to the title floor) so
	# "who sings it" never disappears, and the title loses its middle so its
	# version suffix stays readable at the end
	credit = __middle(credit, min(len(credit), __list_label_max - __list_title_floor))

	return f"{__middle(title, __list_label_max - len(credit))}{credit}"

def list_caption(display, items, page = 0):
	# Plain text on purpose. The caption is the header ONLY -- the
	# results live exclusively in the buttons, so any query length or title
	# count can never overflow it. The header display stays capped, keeping
	# the whole caption inside 1024 chars.
	if display:
		if len(display) > __list_display_max:
			display = display[: __list_display_max - 1] + "…"

		header = f'🔎 Results for "{display}"'
	else:
		header = "🔎 Deezer chart"

	pages = total_pages(items)

	if pages > 1:
		return f"{header} ({len(items)} · page {page + 1}/{pages})"

	return f"{header} ({len(items)})"

def create_keyboard_list(token, items, has_filters, scope, page = 0):
	visible = page_items(items, page)
	# the missing feat./collab names of the tracks about to be rendered are
	# looked up here, once per track, and cached on the item itself
	expand_track_credits(visible)

	rows = [
		[
			InlineKeyboardButton(
				f"{__icon(item)} {__item_label(item)}",
				callback_data = f"/srl:{token}:{page * PAGE_SIZE + index}"
			)
		]
		for index, item in enumerate(visible)
	]

	pages = total_pages(items)

	if pages > 1:
		# Prev/Next change pages, the indicator sits between
		# them and re-tapping repaints the same page (harmless no-op). The
		# result buttons keep their GLOBAL index so /srl never changed.
		nav_row = []

		if page > 0:
			nav_row.append(
				InlineKeyboardButton(
					"◀️ Prev",
					callback_data = f"/srp:{token}:{page - 1}"
				)
			)

		nav_row.append(
			InlineKeyboardButton(
				f"📄 {page + 1}/{pages}",
				callback_data = f"/srp:{token}:{page}"
			)
		)

		if page < pages - 1:
			nav_row.append(
				InlineKeyboardButton(
					"Next ▶️",
					callback_data = f"/srp:{token}:{page + 1}"
				)
			)

		rows.append(nav_row)

	if has_filters:
		filter_buttons = [
			InlineKeyboardButton(
				f"✅ {text}" if scope == value else text,
				callback_data = f"/srf:{token}:{value}"
			)
			for value, text in __list_scopes
		]

		rows.append(filter_buttons[:2])
		rows.append(filter_buttons[2:])

	rows.append([
		InlineKeyboardButton(
			"❌ Close",
			callback_data = f"/src:{token}"
		)
	])

	list_keyboard = InlineKeyboardMarkup(rows)
	return list_keyboard

def __is_cached(item, user_data):
	# Cache-first label: a track whose link + user quality is already in
	# the SQLite dwsongs table can be replayed instead of downloaded again.
	if item['type'] != "track":
		return False

	match = select_dwsongs(
		get_url_path(item['link']),
		user_data['quality'],
		user_data['method_save']
	)

	return bool(match)

def __card_photo(item):
	return item['image'] if item['image'] else empty_image_url

def __card_caption(item):
	# Plain text on purpose: titles and descriptions may contain
	# markdown characters, and Telegram captions without parse_mode are safe.
	# The track's artist line is composed here instead of being baked into the
	# description: it is the one field expand_track_credits can still upgrade
	# after the item was built, and the card has no button-length budget, so
	# it always shows the complete title and every performer.
	artist = item.get('artist')

	if item['type'] == "track" and artist:
		return f"{item['title']}\n\nArtist: {artist}\n{item['description']}"

	return f"{item['title']}\n\n{item['description']}"

def __contextual_row(token, item):
	# Jump buttons of the card: they open the bot's OWN detail card for
	# the exact album/artist (fetched by Deezer id through /ctx), never a
	# deezer.com URL. A "" id means the result has no such target, so the
	# button is skipped instead of sending the user nowhere.
	item_type = item['type']
	links = item['links']

	if item_type == "track":
		targets = [
			("Album 💽", links['album'], "album"),
			("Artist 👤", links['artist'], "artist"),
		]

	elif item_type == "album":
		targets = [
			("Artist 👤", links['artist'], "artist"),
		]

	elif item_type == "artist":
		return [
			InlineKeyboardButton(
				command['text'],
				callback_data = f"/ctx:{token}:{kind}"
			)
			for kind, command in artist_commands_queries.items()
		]

	else:
		return []

	return [
		InlineKeyboardButton(
			text,
			callback_data = f"/ctx:{token}:{kind}"
		)
		for text, ids, kind in targets
		if ids
	]

def create_keyboard_result(token, items, index, user_data):
	item = items[index]

	download_text = "⬇️ Download"

	if __is_cached(item, user_data):
		download_text = "⬇️ Download cached"

	# The Prev/Next carousel is gone (the LIST view replaced it). The
	# detail card keeps ⬅️ Back to return to that list and ❌ Close.
	card_keyboard = [
		[
			InlineKeyboardButton(
				"⬅️ Back",
				callback_data = f"/srb:{token}"
			),
			InlineKeyboardButton(
				download_text,
				callback_data = f"/sres:{token}:{index}"
			),
		]
	]

	contextual_row = __contextual_row(token, item)

	if contextual_row:
		card_keyboard.append(contextual_row)

	card_keyboard.append([
		InlineKeyboardButton(
			"❌ Close",
			callback_data = f"/src:{token}"
		)
	])

	search_keyboard = InlineKeyboardMarkup(card_keyboard)
	return search_keyboard

def send_list(bot, chat_id, token, items, display, has_filters, scope, page = 0):
	reply_markup = create_keyboard_list(
		token, items, has_filters, scope, page
	)
	caption = list_caption(display, items, page)

	try:
		message = bot.send_photo(
			chat_id = chat_id,
			photo = __card_photo((page_items(items, page) or items)[0]),
			caption = caption,
			reply_markup = reply_markup
		)
	except TelegramError:
		# Dead cover image: the list stays fully usable as text.
		message = bot.send_message(
			chat_id = chat_id,
			text = caption,
			reply_markup = reply_markup
		)

	return message

def edit_list(bot, chat_id, message_id, token, items, display, has_filters, scope, page = 0):
	reply_markup = create_keyboard_list(
		token, items, has_filters, scope, page
	)

	try:
		bot.edit_message_media(
			media = InputMediaPhoto(
				media = __card_photo((page_items(items, page) or items)[0]),
				caption = list_caption(display, items, page)
			),
			chat_id = chat_id,
			message_id = message_id
		)
	except TelegramError:
		# Benign: "message is not modified" and transient errors. The
		# keyboard is refreshed below either way.
		pass

	try:
		bot.edit_message_reply_markup(
			chat_id = chat_id,
			message_id = message_id,
			reply_markup = reply_markup
		)
	except TelegramError as error:
		if "not modified" not in str(error).lower():
			raise

def edit_card(bot, chat_id, message_id, token, items, index, user_data):
	item = items[index]
	# a card can be reached without its page ever having been rendered
	# (contextual jumps, an old message), so the credit list is upgraded here
	# too -- and it is the untruncated copy the caption shows
	expand_track_credits([item])
	reply_markup = create_keyboard_result(
		token, items, index, user_data
	)

	try:
		bot.edit_message_media(
			media = InputMediaPhoto(
				media = __card_photo(item),
				caption = __card_caption(item)
			),
			chat_id = chat_id,
			message_id = message_id
		)
	except TelegramError:
		# Benign: "message is not modified" when paging back to the same
		# result, and transient API errors. The keyboard is refreshed below
		# either way, so the card never gets out of sync with its index.
		pass

	try:
		bot.edit_message_reply_markup(
			chat_id = chat_id,
			message_id = message_id,
			reply_markup = reply_markup
		)
	except TelegramError as error:
		if "not modified" not in str(error).lower():
			raise

def send_not_found(bot, chat_id):
	try:
		message = bot.send_photo(
			chat_id = chat_id,
			photo = not_found_query_gif,
			caption = not_found_title
		)
	except TelegramError:
		message = bot.send_message(
			chat_id = chat_id,
			text = not_found_title
		)

	return message
