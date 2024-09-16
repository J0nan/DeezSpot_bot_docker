#!/usr/bin/python3

from pyrogram import Client
from acrcloud import ACRcloud
from telegram.ext import Updater
from deezloader.deezloader import DeeLogin
from deezloader.spotloader import SpoLogin
from .bot_settings import user_session
import os


class SetConfigs:
	queues_started, queues_finished = 0, 0

	__arl_token = os.environ.get("ARL_TOKEN")
	__email_dee = os.environ.get("EMAIL_DEE")
	__pwd_dee = os.environ.get("PWD_DEE")

	# __email_spo = os.environ.get("EMAIL_SPO")
	# __pwd_spo = os.environ.get("PWD_SPO")

	__bot_token = os.environ.get("BOT_TOKEN")

	__acrcloud_key = os.environ.get("ACRCLOUD_KEY")
	__acrcloud_secret = os.environ.get("ACRCLOUD_SECRET")
	__acrcloud_host = os.environ.get("ACRCLOUD_HOST")

	__api_id = int(os.environ.get("API_ID"))
	__api_hash = os.environ.get("API_HASH")

	__acrcloud_config = {
		"key": __acrcloud_key,
		"secret": __acrcloud_secret,
		"host": __acrcloud_host
	}

	@classmethod
	def __init__(cls, mode_bot):
		if mode_bot in [3, 4]:
			cls.create_zips = False
		else:
			cls.create_zips = True

		cls.tg_bot_api = Updater(token = cls.__bot_token)
		cls.tg_bot_id = cls.tg_bot_api.bot.name

		cls.deez_api = DeeLogin(
			arl = cls.__arl_token,
			email = cls.__email_dee,
			password = cls.__pwd_dee
		)

		cls.spot_api = SpoLogin("null", "null")

		if(cls.__acrcloud_key):
			cls.acrcloud_api = ACRcloud(cls.__acrcloud_config)

		cls.tg_user_api = Client(user_session, api_id=cls.__api_id, api_hash=cls.__api_hash, bot_token=cls.__bot_token)
		cls.tg_user_api.start()