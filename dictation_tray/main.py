from __future__ import annotations

import sys
import os
from pathlib import Path

from .history import HistoryRepository
from .logging_setup import configure_logging
from .paths import ensure_app_dirs
from .config import ConfigStore


REQUIRED_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


def self_check() -> int:
    """Fast deterministic package verification; deliberately does not open GUI/audio/model."""
    try:
        base = ensure_app_dirs()
        config = ConfigStore(base / "config.json").load()
        config.validate()
        history = HistoryRepository(base / "history.sqlite3")
        history.list_recent(1)
        # Do not leave a Windows file handle open: packaging runs this in a short-lived process.
        with (base / "logs" / "app.log").open("a", encoding="utf-8") as log_file:
            log_file.write("Self-check completed\n")
        model_dir = os.environ.get("LOCAL_DICTATION_MODEL_DIR")
        if not model_dir:
            return 3
        if not all((Path(model_dir) / name).is_file() for name in REQUIRED_MODEL_FILES):
            return 4
        return 0
    except Exception:
        return 2


def main() -> int:
    if "--self-check" in sys.argv[1:]:
        return self_check()
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from .qt_app import TrayApplication
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Локальная диктовка")
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 2
    base = ensure_app_dirs()
    logger = configure_logging(base / "logs" / "app.log")
    tray_app = TrayApplication(app, ConfigStore(base / "config.json"), HistoryRepository(base / "history.sqlite3"), base / "recordings", logger)
    if not tray_app.start():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
