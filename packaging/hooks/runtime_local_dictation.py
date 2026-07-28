"""PyInstaller runtime hook: expose the bundled offline speech model to the app."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundled_model_dir() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return root / "models" / "faster-whisper-base"


model_dir = _bundled_model_dir()
if model_dir.is_dir():
    os.environ.setdefault("LOCAL_DICTATION_MODEL_DIR", str(model_dir))
