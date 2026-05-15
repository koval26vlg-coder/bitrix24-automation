from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join("reports", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "bitrix24.log")
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_HANDLER_MARK = "_bitrix24_hygiene_handler"


def _already_configured(logger: logging.Logger) -> bool:
    return any(getattr(h, _HANDLER_MARK, False) for h in logger.handlers)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if _already_configured(logger):
        return logger

    os.makedirs(_LOG_DIR, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)

    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setFormatter(formatter)
    setattr(stream_handler, _HANDLER_MARK, True)
    logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=2000000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_MARK, True)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger

