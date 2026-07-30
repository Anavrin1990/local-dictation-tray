"""PyInstaller hook: expose bundled small and NVIDIA DLLs before CTranslate2 imports."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_DLL_HANDLES: list[object] = []  # Windows unloads paths when these handles are garbage-collected.


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def _register_nvidia_dll_dirs(root: Path) -> None:
    known = {part.casefold() for part in os.environ.get("PATH", "").split(os.pathsep) if part}
    for directory in (root / "nvidia" / "cublas" / "bin", root / "nvidia" / "cudnn" / "bin"):
        if not directory.is_dir():
            continue
        path = str(directory)
        if path.casefold() not in known:
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
            known.add(path.casefold())
        if hasattr(os, "add_dll_directory"):
            _DLL_HANDLES.append(os.add_dll_directory(path))


bundle_root = _bundle_root()
model_dir = bundle_root / "models" / "faster-whisper-small"
if model_dir.is_dir():
    os.environ.setdefault("LOCAL_DICTATION_MODEL_DIR", str(model_dir))
_register_nvidia_dll_dirs(bundle_root)
