import logging
import logging.handlers


logger = logging.getLogger('chatgpt')
logger.setLevel(logging.DEBUG)

_handler = logging.handlers.TimedRotatingFileHandler('chatgpt.log', when='MIDNIGHT', interval=1, backupCount=30)
_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
_handler.setFormatter(formatter)
logger.addHandler(_handler)


def color(code: int):
    def warpper(text):
        return '\033[{}m{}\033[0m'.format(code, text)

    return warpper



red = color(31)
green = color(32)
yellow = color(33)
blue = color(34)
