from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "LocalDictationTray"


def app_data_dir() -> Path:
    """Return the per-user writable application directory."""
    root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def ensure_app_dirs(base: Path | None = None) -> Path:
    directory = base or app_data_dir()
    (directory / "logs").mkdir(parents=True, exist_ok=True)
    (directory / "recordings").mkdir(parents=True, exist_ok=True)
    return directory
