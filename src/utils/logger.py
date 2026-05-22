"""Centralised logger factory.

Every stage of the pipeline logs through ``get_logger(__name__)`` so that the
output format is consistent and every event lands in both the console and a
rotating log file on disk.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from config.settings import settings

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger. Safe to call repeatedly for the same name."""
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured
        return logger

    logger.setLevel(settings.LOG_LEVEL)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # Rotating file handler (5 MB per file, keep 3 backups)
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.LOG_DIR / "idp.log", maxBytes=5_000_000, backupCount=3
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
