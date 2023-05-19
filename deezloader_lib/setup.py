from setuptools import setup

README = open("README.md", "r")
readmed = README.read()
README.close()

setup(
	name = "deezloader",
	version = "2022.03.05",
	description = "Downloads songs, albums or playlists from deezer",
	long_description = readmed,
	long_description_content_type = "text/markdown",
	license = "CC BY-NC-SA 4.0",
	python_requires = ">=3.9",
	author = "An0nimia",
	author_email = "An0nimia@protonmail.com",
	url = "https://github.com/An0nimia/deezloader",

	packages = [
		"deezloader",
		"deezloader/models", "deezloader/spotloader",
		"deezloader/deezloader", "deezloader/libutils"
	],

	install_requires = [
		"mutagen", "pycryptodome", "requests",
		"spotipy", "tqdm", "fastapi",
		"uvicorn[standard]", "librespot"
	],

	scripts = [
		"deezloader/bin/deez-dw.py",
		"deezloader/bin/deez-web.py"
	]
)