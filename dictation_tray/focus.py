from __future__ import annotations

import os


def foreground_window() -> int | None:
    """Capture the field's top-level window before background transcription."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return int(hwnd) or None
    except Exception:
        return None


def restore_foreground_window(hwnd: int | None) -> bool:
    """Best-effort focus restore. Windows can refuse it by OS focus-stealing policy."""
    if not hwnd or os.name != "nt":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False
