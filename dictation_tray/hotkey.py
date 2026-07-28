from __future__ import annotations

import threading
import time
from collections.abc import Callable


class HoldHotkey:
    """Starts once the configured chord is pressed, stops only when it is released."""

    def __init__(self, hotkey: str, on_pressed: Callable[[], None], on_released: Callable[[], None]):
        self.hotkey = hotkey
        self.on_pressed = on_pressed
        self.on_released = on_released
        self._handle = None
        self._watcher: threading.Thread | None = None
        self._stop = threading.Event()
        self._active = threading.Event()

    def start(self) -> None:
        import keyboard
        self.stop()
        self._stop.clear()
        try:
            self._handle = keyboard.add_hotkey(self.hotkey, self._pressed, suppress=False, trigger_on_release=False)
        except Exception as exc:
            raise RuntimeError(f"Не удалось зарегистрировать горячую клавишу: {exc}") from exc

    def _pressed(self) -> None:
        if self._active.is_set():
            return
        self._active.set()
        self.on_pressed()
        self._watcher = threading.Thread(target=self._watch_release, name="hotkey-release", daemon=True)
        self._watcher.start()

    def _watch_release(self) -> None:
        import keyboard
        try:
            while not self._stop.is_set() and keyboard.is_pressed(self.hotkey):
                time.sleep(0.025)
        finally:
            if self._active.is_set():
                self._active.clear()
                self.on_released()

    def stop(self) -> None:
        self._stop.set()
        if self._handle is not None:
            try:
                import keyboard
                keyboard.remove_hotkey(self._handle)
            finally:
                self._handle = None
        if self._active.is_set():
            self._active.clear()
            self.on_released()
