"""Windows single-instance coordination, kept independent of Qt for unit tests."""
from __future__ import annotations

import ctypes
import os
from typing import Protocol


class InstanceBackend(Protocol):
    def create_mutex(self, name: str) -> tuple[object, bool]: ...
    def create_event(self, name: str) -> object: ...
    def close_handle(self, handle: object) -> None: ...
    def signal_event(self, name: str) -> None: ...
    def consume_event(self, name: str) -> bool: ...


class WindowsInstanceBackend:
    """Thin wrapper around named Win32 synchronization objects."""

    _ERROR_ALREADY_EXISTS = 183
    _EVENT_MODIFY_STATE = 0x0002
    _SYNCHRONIZE = 0x00100000
    _WAIT_OBJECT_0 = 0
    _WAIT_TIMEOUT = 258

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Single-instance coordination is supported on Windows only")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._kernel32.CreateEventW.restype = ctypes.c_void_p
        self._kernel32.OpenEventW.restype = ctypes.c_void_p

    def create_mutex(self, name: str) -> tuple[object, bool]:
        handle = self._kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle, ctypes.get_last_error() == self._ERROR_ALREADY_EXISTS

    def create_event(self, name: str) -> object:
        handle = self._kernel32.CreateEventW(None, False, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def close_handle(self, handle: object) -> None:
        self._kernel32.CloseHandle(handle)

    def signal_event(self, name: str) -> None:
        handle = self._kernel32.OpenEventW(self._EVENT_MODIFY_STATE, False, name)
        if not handle:
            return
        try:
            self._kernel32.SetEvent(handle)
        finally:
            self.close_handle(handle)

    def consume_event(self, name: str) -> bool:
        handle = self._kernel32.OpenEventW(self._SYNCHRONIZE, False, name)
        if not handle:
            return False
        try:
            result = self._kernel32.WaitForSingleObject(handle, 0)
            return result == self._WAIT_OBJECT_0
        finally:
            self.close_handle(handle)


class SingleInstanceGuard:
    """Keeps one process alive and lets later launches request its activation."""

    def __init__(self, app_id: str, backend: InstanceBackend | None = None) -> None:
        prefix = f"Local\\{app_id}"
        self._mutex_name = f"{prefix}.singleton"
        self._event_name = f"{prefix}.activate"
        self._backend = backend or WindowsInstanceBackend()
        self._mutex_handle: object | None = None
        self._event_handle: object | None = None

    def acquire(self) -> bool:
        """Return True for the primary process; notify and return False otherwise."""
        if self._mutex_handle is not None:
            return True
        mutex, already_running = self._backend.create_mutex(self._mutex_name)
        if already_running:
            self._backend.signal_event(self._event_name)
            self._backend.close_handle(mutex)
            return False
        try:
            event = self._backend.create_event(self._event_name)
        except Exception:
            self._backend.close_handle(mutex)
            raise
        self._mutex_handle = mutex
        self._event_handle = event
        return True

    def consume_activation_request(self) -> bool:
        """Return whether a second launch asked the primary app to come forward."""
        if self._event_handle is None:
            return False
        return self._backend.consume_event(self._event_name)

    def close(self) -> None:
        for handle_name in ("_event_handle", "_mutex_handle"):
            handle = getattr(self, handle_name)
            if handle is not None:
                self._backend.close_handle(handle)
                setattr(self, handle_name, None)
