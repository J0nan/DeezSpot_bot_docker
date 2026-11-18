#!/usr/bin/python3

"""T5 tests: cover-art observability (S5).

The tagger logger `deezloader.__taggers__` was never registered by
configs/bot_settings.py, so "no cover art available for %s" reached docker
stderr only -- never logs/downloads.log -- and a cover failure carried no
reason code. These tests pin both seams of the fix:

- cover_art emits INFO "cover fallback used key=... source=... reason=..."
  when a fallback rung saves a track, and WARNING "cover failed key=...
  reason=all_sources_failed detail=..." when every source refuses;
- importing configs.bot_settings registers the `deezloader` parent logger on
  logs/downloads.log (same formatter as the bot loggers, INFO level so the
  fallback rescue line survives), which is how `deezloader.cover_art` and
  `deezloader.__taggers__` reach the file.

No network: the scripted transport from tests/test_cover_art.py and the
iTunes fixtures from tests/test_cover_carrier.py are reused. The bot stack
(PTB 13.x) cannot import on local Python 3.12, so a minimal telegram stub is
installed before configs.bot_settings is imported, and every import runs from
a scratch working directory so the repository logs/ tree is never written.

Run as: .venv\\Scripts\\python -m pytest tests/test_cover_logging.py -q
     or: .venv\\Scripts\\python tests/test_cover_logging.py
"""

import importlib
import logging
import os
import shutil
import sys
import tempfile
import types

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "deezloader_lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _stub_module(name, **attributes):
	"""Register a stand-in module only when the real one cannot be imported."""
	module = types.ModuleType(name)

	for attribute, value in attributes.items():
		setattr(module, attribute, value)

	sys.modules.setdefault(name, module)

	return sys.modules[name]

# configs.bot_settings needs this single telegram name; the real package is
# unimportable on local 3.12 (PTB 13.x vendors broken urllib3/six).
if "telegram" not in sys.modules:
	_telegram = types.ModuleType("telegram")
	_telegram.__path__ = []
	sys.modules["telegram"] = _telegram
	_stub_module("telegram.constants", MAX_FILESIZE_DOWNLOAD = 2_000_000_000)

from test_cover_art import (
	HttpRecorder, patched, require_cover_art,
	JPEG, PNG, HTML, MD5, SPOTIFY_URL,
)
from test_cover_carrier import LOOKUP_BODY, UPC

from deezloader.deezloader import cover_art

COVER_LOGGER = "deezloader.cover_art"
PARENT_LOGGER = "deezloader"
TAGGER_LOGGER = "deezloader.__taggers__"
COVER_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DOWNLOAD_LOG = os.path.join("logs", "downloads.log")
BOT_LOGGERS = ("downloads", "uploads", "links", "telegram.ext.dispatcher")

# The deezloader import chain (easy_spoty) imports configs.bot_settings inside
# a try/except. When this suite runs with the bot environment present, that
# import registers the cover logger against the repository logs/ tree; detach
# that handler so no test writes the worktree, whatever the environment.
_REPOSITORY_LOG = os.path.abspath(os.path.join(_root, "logs", "downloads.log"))

def _detach_repository_cover_handler():
	logger = logging.getLogger(PARENT_LOGGER)
	detached = False

	for handler in list(logger.handlers):
		if (
			isinstance(handler, logging.FileHandler)
			and handler.baseFilename == _REPOSITORY_LOG
		):
			logger.removeHandler(handler)
			handler.close()
			detached = True

	if detached:
		logger.setLevel(logging.NOTSET)

	return detached

_detach_repository_cover_handler()

class LogCapture:
	"""Capture every record that reaches a logger by name, pytest-free."""

	def __init__(self, name = COVER_LOGGER):
		self.logger = logging.getLogger(name)
		self.records = []

	def __enter__(self):
		self.previous_level = self.logger.level
		self.handler = logging.Handler()
		self.handler.emit = self.records.append
		self.logger.addHandler(self.handler)
		self.logger.setLevel(logging.DEBUG)

		return self

	def __exit__(self, *exc_info):
		self.logger.removeHandler(self.handler)
		self.logger.setLevel(self.previous_level)

		return False

	def messages(self, level = None):
		return [
			record.getMessage() for record in self.records
			if level is None or record.levelno == level
		]

class bot_settings_imported:
	"""Import the real configs.bot_settings from a scratch directory.

	The module is executed in isolation: the telegram stubs above stand in for
	the bot stack, the environment names it reads without defaults are set
	during the import, and the working directory is a temporary tree so the
	downloads.log handler the module registers cannot touch the repository.
	Every effect of the import (logger handlers and level, modules, env, cwd)
	is reverted on exit.
	"""

	REQUIRED_ENV = {
		"USER_ERRORS": "3",
		"BUNKER_CHANNEL": "-1001",
		"OWL_CHANNEL": "-1002",
		"ROOT_ID": "-1003",
	}

	WATCHED_LOGGERS = (PARENT_LOGGER, COVER_LOGGER) + BOT_LOGGERS

	def __enter__(self):
		self.saved_modules = {
			name: sys.modules.get(name)
			for name in ("configs", "configs.bot_settings")
		}

		for name in self.saved_modules:
			sys.modules.pop(name, None)

		self.saved_env = {
			name: os.environ.get(name) for name in self.REQUIRED_ENV
		}
		os.environ.update(self.REQUIRED_ENV)

		self.saved_loggers = {}
		logger = logging.getLogger(PARENT_LOGGER)
		self.saved_loggers[PARENT_LOGGER] = (
			list(logger.handlers), logger.level, logger.propagate
		)
		self.saved_handlers = {
			name: list(logging.getLogger(name).handlers)
			for name in BOT_LOGGERS
		}

		self.cwd = os.getcwd()
		self.tmp = tempfile.mkdtemp(prefix = "cover-logging-")
		os.makedirs(os.path.join(self.tmp, "logs"))
		os.chdir(self.tmp)

		self.bot_settings = importlib.import_module("configs.bot_settings")

		return self

	def __exit__(self, *exc_info):
		os.chdir(self.cwd)

		logger = logging.getLogger(PARENT_LOGGER)
		before_handlers, before_level, before_propagate = (
			self.saved_loggers[PARENT_LOGGER]
		)

		for handler in list(logger.handlers):
			if handler in before_handlers:
				continue

			logger.removeHandler(handler)
			handler.close()

		logger.setLevel(before_level)
		logger.propagate = before_propagate

		for name, module in self.saved_modules.items():
			sys.modules.pop(name, None)

			if module is not None:
				sys.modules[name] = module

		for name, value in self.saved_env.items():
			if value is None:
				os.environ.pop(name, None)
			else:
				os.environ[name] = value

		shutil.rmtree(self.tmp, ignore_errors = True)

		return False

	def downloads_log_path(self):
		return os.path.join(self.tmp, "logs", "downloads.log")

	def read_downloads_log(self):
		with open(self.downloads_log_path(), encoding = "utf-8") as log_file:
			return log_file.read()

# --- producer seam: reason codes at the cover service ---

def test_spotify_fallback_logs_info_with_key_source_and_reason():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))

	with LogCapture() as logs:
		with patched(http):
			result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == JPEG
	assert result.source == "spotify"
	assert result.reason == "fallback_used"

	infos = logs.messages(logging.INFO)
	assert len(infos) == 1, logs.records
	assert infos[0].startswith("cover fallback used")
	assert f"key={MD5}" in infos[0]
	assert "source=spotify" in infos[0]
	assert "reason=fallback_used" in infos[0]
	assert logs.messages(logging.WARNING) == []

def test_itunes_fallback_logs_info_with_the_itunes_source():
	require_cover_art()
	http = HttpRecorder().on("itunes.apple.com/lookup", (200, LOOKUP_BODY))
	http.on("mzstatic", (200, JPEG))

	with LogCapture() as logs:
		with patched(http):
			result = cover_art.fetch_cover(
				MD5, fallback_url = SPOTIFY_URL, upc = UPC
			)

	assert result.data == JPEG
	assert result.source == "itunes"
	assert result.reason == "fallback_used"

	infos = logs.messages(logging.INFO)
	assert len(infos) == 1, logs.records
	assert f"key={MD5}" in infos[0]
	assert "source=itunes" in infos[0]
	assert "reason=fallback_used" in infos[0]

def test_total_failure_logs_warning_with_reason_and_detail():
	require_cover_art()
	http = HttpRecorder()

	with LogCapture() as logs:
		with patched(http):
			result = cover_art.fetch_cover(
				MD5, fallback_url = SPOTIFY_URL, upc = UPC
			)

	assert result.data == b""
	assert result.reason == "all_sources_failed"
	assert result.detail == "cdn_403"
	assert logs.messages(logging.WARNING) == [
		f"cover failed key={MD5} reason=all_sources_failed detail=cdn_403"
	]
	assert logs.messages(logging.INFO) == []

def test_invalid_body_detail_reaches_the_failure_warning():
	require_cover_art()
	http = HttpRecorder()
	http.default = (200, HTML)

	with LogCapture() as logs:
		with patched(http):
			result = cover_art.fetch_cover(MD5)

	assert result.reason == "all_sources_failed"
	assert logs.messages(logging.WARNING) == [
		f"cover failed key={MD5} reason=all_sources_failed detail=invalid_body"
	]

def test_primary_deezer_success_emits_no_cover_log():
	require_cover_art()
	http = HttpRecorder().on(MD5, (200, JPEG)).on("i.scdn.co", (200, PNG))

	with LogCapture() as logs:
		with patched(http):
			result = cover_art.fetch_cover(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == JPEG
	assert result.source == "deezer"
	assert result.reason == ""
	assert logs.records == []

def test_negative_cache_hit_does_not_repeat_the_failure_warning():
	require_cover_art()
	http = HttpRecorder()

	with LogCapture() as logs:
		with patched(http):
			cover_art.fetch_cover(MD5)
			cover_art.fetch_cover(MD5)

	assert len(logs.messages(logging.WARNING)) == 1, logs.records

def test_fetch_thumb_fallback_keeps_its_contract_and_logs_the_thumb_key():
	require_cover_art()
	http = HttpRecorder().on("i.scdn.co", (200, JPEG))
	thumb_url = SPOTIFY_URL.replace("ab67616d0000b273", "ab67616d00001e02")

	with LogCapture() as logs:
		with patched(http):
			result = cover_art.fetch_thumb(MD5, fallback_url = SPOTIFY_URL)

	assert result.data == JPEG
	assert result.source == "spotify"
	assert result.reason == "fallback_used"
	# Preservation: the thumb rung still asks for the rewritten 300 px token.
	assert http.urls()[-1] == thumb_url

	infos = logs.messages(logging.INFO)
	assert len(infos) == 1, logs.records
	assert f"key=thumb:90x90:{MD5}" in infos[0]
	assert "source=spotify" in infos[0]

# --- consumer seam: the deezloader logger registration ---

def test_bot_settings_registers_the_deezloader_logger_for_downloads_log():
	with bot_settings_imported():
		logger = logging.getLogger(PARENT_LOGGER)

		assert logger.level == logging.INFO
		assert logger.isEnabledFor(logging.INFO)
		assert logger.propagate is True
		assert len(logger.handlers) == 1, logger.handlers

		handler = logger.handlers[0]
		assert isinstance(handler, logging.FileHandler)
		assert handler.baseFilename.endswith(DOWNLOAD_LOG), handler.baseFilename
		assert handler.formatter is not None
		assert handler.formatter._fmt == COVER_LOG_FORMAT

def test_cover_and_tagger_records_land_in_downloads_log():
	with bot_settings_imported() as imported:
		logging.getLogger(COVER_LOGGER).info("cover probe info")
		logging.getLogger(TAGGER_LOGGER).warning("cover probe warning")

		for handler in logging.getLogger(PARENT_LOGGER).handlers:
			handler.flush()

		content = imported.read_downloads_log()

	assert f"{COVER_LOGGER} - INFO - cover probe info" in content
	assert f"{TAGGER_LOGGER} - WARNING - cover probe warning" in content

def test_register_call_is_idempotent():
	with bot_settings_imported() as imported:
		imported.bot_settings.register_cover_logger()
		imported.bot_settings.register_cover_logger()

		assert len(logging.getLogger(PARENT_LOGGER).handlers) == 1

def test_registration_leaves_the_existing_bot_loggers_untouched():
	with bot_settings_imported() as imported:
		for name in BOT_LOGGERS:
			assert (
				list(logging.getLogger(name).handlers) == imported.saved_handlers[name]
			), name

		assert imported.bot_settings.logger_names == [
			("telegram.ext.dispatcher", logging.ERROR, "logs/telegram.log"),
			("uploads", logging.INFO, "logs/uploads.log"),
			("downloads", logging.ERROR, "logs/downloads.log"),
			("links", logging.INFO, "logs/links.log"),
		]
		assert imported.bot_settings.log_downloads == "logs/downloads.log"

if __name__ == "__main__":
	tests = [
		(name, fn) for name, fn in sorted(globals().items())
		if name.startswith("test_") and callable(fn)
	]

	if not tests:
		print("no tests collected")
		sys.exit(1)

	failures = 0

	for name, fn in tests:
		try:
			fn()
			print(f"PASS {name}")
		except Exception as error:
			failures += 1
			print(f"FAIL {name}: {error}")

	print(f"{len(tests) - failures}/{len(tests)} passed")
	sys.exit(1 if failures else 0)