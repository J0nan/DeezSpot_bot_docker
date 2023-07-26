#!/usr/bin/python3

from os import popen
from time import sleep
from psutil import process_iter, AccessDenied

import logging
from logger.logger import logger

interested = [
	"pid", "name"
]

script = "deez_bot.py"
cmd = f"screen -S Deez_Bot_Anonimia python3 {script}"

def bot_exist():
	exist = False

	for proc in process_iter(interested):
		try:
			cmdline = " ".join(
				proc.cmdline()
			)

			if ("python" in cmdline) and (script in cmdline):
				exist = True
				break
		except AccessDenied:
			pass

	return exist

while True:
	exist = bot_exist()

	if exist:
		logger.warn(f"THE BOT IS RUNNING")
	else:
		logger.warn(f"THE BOT IS NOT RUNNING")

	if not exist:
		popen(cmd).read()

	sleep(4)