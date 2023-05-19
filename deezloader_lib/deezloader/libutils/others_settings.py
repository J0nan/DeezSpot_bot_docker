#!/usr/bin/python3

method_saves = ["0", "1", "2", "3"]

sources = [
	"dee", "spo"
]

header = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0",
	"Accept-Language": "en-US;q=0.5,en;q=0.3"
}

supported_link = [
	"www.deezer.com", "open.spotify.com",
	"deezer.com", "spotify.com",
	"deezer.page.link", "www.spotify.com"
]

answers = ["Y", "y", "Yes", "YES"]
stock_output = "Songs"
stock_recursive_quality = False
stock_recursive_download = False
stock_not_interface = False
stock_zip = False
method_save = 2
is_thread = False # WARNING FOR TRUE, LOOP ON DEFAULT