from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("dictation_tray")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for old_handler in logger.handlers:
        old_handler.close()
    logger.handlers.clear()
    handler = RotatingFileHandler(log_path, maxBytes=1_500_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    logger.addHandler(handler)
    return logger
