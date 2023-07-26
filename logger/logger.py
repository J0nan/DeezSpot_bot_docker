import logging
import sys

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)-7s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class LoggerStream:
    def write(self, message):
        if message.rstrip() != "":
            logger.info(message.rstrip())

    def flush(self):
        pass

sys.stdout = LoggerStream()