# Download crash guard: pyrogram's save_file dies with
# "File size equals to 0 B" when send_audio/send_document receives an empty
# BytesIO thumb (a Deezer/Spotify cover URL that answered with nothing). The
# thumbnail is optional -- save_file returns None for None -- so the guard is
# simply: never build the stream from empty bytes. This module is kept free
# of side effects and imports so the crash guard is unit-testable outside the
# bot's credential stack.

from io import BytesIO

def make_thumb_io(image_bytes, name):
	if not image_bytes:
		return None

	io_image = BytesIO(image_bytes)
	io_image.name = name

	return io_image
