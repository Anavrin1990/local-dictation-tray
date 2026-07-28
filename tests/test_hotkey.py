from __future__ import annotations

import sys
import threading
import unittest
from unittest.mock import patch

from dictation_tray.hotkey import HoldHotkey


class FakeKeyboard:
    def __init__(self) -> None:
        self.registered_hotkey = None
        self.callback = None
        self.removed_handle = None

    def add_hotkey(self, hotkey, callback, **_kwargs):
        self.registered_hotkey = hotkey
        self.callback = callback
        return 42

    def is_pressed(self, hotkey):
        return False

    def remove_hotkey(self, handle):
        self.removed_handle = handle


class HoldHotkeyTests(unittest.TestCase):
    def test_modifier_only_default_starts_and_releases_dictation(self) -> None:
        keyboard = FakeKeyboard()
        pressed = threading.Event()
        released = threading.Event()
        hotkey = HoldHotkey("ctrl+alt", pressed.set, released.set)

        with patch.dict(sys.modules, {"keyboard": keyboard}):
            hotkey.start()
            self.assertEqual(keyboard.registered_hotkey, "ctrl+alt")
            keyboard.callback()
            self.assertTrue(pressed.wait(1))
            self.assertTrue(released.wait(1))
            hotkey.stop()

        self.assertEqual(keyboard.removed_handle, 42)


if __name__ == "__main__":
    unittest.main()
