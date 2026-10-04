#!/usr/bin/python3

from pathlib import Path
from base64 import b64encode
from urllib.parse import quote_plus
from fastapi import FastAPI, Request
from uvicorn import run as run_server
from configparser import ConfigParser
from deezloader.deezloader import DeeLogin
from deezloader.exceptions import InvalidLink
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
settings_file = ".deez_settings.ini"
download_dir = "Songs/"
p_download_dir = Path(download_dir)

config = ConfigParser()
config.read(settings_file)

try:
	token = config['deez_login']['token']
	email = config['deez_login']['mail']
	password = config['deez_login']['password']
except KeyError:
	print("Something went wrong with configuration file")
	exit()

downloa = DeeLogin(
	email = email,
	password = password
)

@app.exception_handler(InvalidLink)
async def invalid_link_handler(
	request: Request,
	exc: InvalidLink
):
	error_dict = {
		"msg": exc.msg,
		"url": exc.url
	}

	return JSONResponse(
		status_code = 406,
		content = error_dict
	)

@app.get("/play")
async def play(path: Path):
	where_is = path.parent.parent

	if where_is != p_download_dir:
		error_dict = {
			"msg": "Where are you trying to access?",
			"error": "Unauthorized"
		}

		return JSONResponse(
			status_code = 401,
			content = error_dict
		)

	c_file = str(
		path.absolute()
	)

	extension = c_file.split(".")[-1]

	def iter_file():
		with open(c_file, "rb") as audio:
			yield from audio

	return StreamingResponse(
		iter_file(),
		media_type = f"audio/{extension}"
	)

@app.get("/download")
async def download(link: str):
	data = downloa.download_smart(
		link,
		output_dir = download_dir,
		recursive_download = True
	)

	c_type = data.type

	if c_type == "track":
		track = data.track
		track.tags['image'] = b64encode(track.tags['image'])
		enc_url = quote_plus(track.song_path)

		resp = {
			"tags": track.tags,
			"song_name": track.song_name,
			"song_path": track.song_path,
			"file_format": track.file_format,
			"quality": track.quality,
			"link": track.link,
			"ids": track.ids,
			"md5_image": track.md5_image,
			"track_md5": track.track_md5,
			"fallback_ids": track.fallback_ids,
			"fallback_track_md5": track.fallback_track_md5,
			"song_url": f"/play?path={enc_url}"
		}

	return resp

if __name__ == "__main__":
	run_server(
		app,
		host = "0.0.0.0",
		port = 8000
	)