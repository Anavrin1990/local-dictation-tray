from __future__ import annotations

import time


def paste_unicode(text: str) -> None:
    """Paste arbitrary Unicode while restoring the user's clipboard shortly afterwards."""
    if not text:
        return
    import keyboard
    import pyperclip

    previous: str | None
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = None
    pyperclip.copy(text)
    time.sleep(0.05)  # let Windows publish the clipboard before Ctrl+V
    keyboard.send("ctrl+v")
    if previous is not None:
        time.sleep(0.15)
        try:
            # Never overwrite a clipboard change made by the user immediately after pasting.
            if pyperclip.paste() == text:
                pyperclip.copy(previous)
        except Exception:
            pass
