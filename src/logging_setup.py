import logging
import time
from typing import Optional

from .config import Settings


class UTCFormatter(logging.Formatter):
    converter = time.gmtime

    def formatTime(self, record, datefmt=None):
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", self.converter(record.created))
        return timestamp


def setup_logging(settings: Settings) -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    root_logger.setLevel(settings.log_level.upper())
    handler = logging.StreamHandler()
    formatter = UTCFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name)
