from __future__ import annotations

import unittest

from dictation_tray.single_instance import SingleInstanceGuard


class FakeBackend:
    def __init__(self, *, already_running: bool = False, signalled: bool = False) -> None:
        self.already_running = already_running
        self.signalled = signalled
        self.created: list[str] = []
        self.closed: list[object] = []
        self.notifications: list[str] = []

    def create_mutex(self, name: str) -> tuple[object, bool]:
        self.created.append(name)
        return object(), self.already_running

    def create_event(self, name: str) -> object:
        self.created.append(name)
        return object()

    def close_handle(self, handle: object) -> None:
        self.closed.append(handle)

    def signal_event(self, name: str) -> None:
        self.notifications.append(name)

    def consume_event(self, name: str) -> bool:
        self.created.append(f"consume:{name}")
        value, self.signalled = self.signalled, False
        return value


class SingleInstanceGuardTests(unittest.TestCase):
    def test_first_instance_acquires_named_mutex_and_releases_it(self) -> None:
        backend = FakeBackend()
        guard = SingleInstanceGuard("LocalDictationTray", backend=backend)

        self.assertTrue(guard.acquire())
        self.assertEqual(backend.created, ["Local\\LocalDictationTray.singleton", "Local\\LocalDictationTray.activate"])
        guard.close()
        self.assertEqual(len(backend.closed), 2)

    def test_second_instance_notifies_first_and_does_not_keep_mutex(self) -> None:
        backend = FakeBackend(already_running=True)
        guard = SingleInstanceGuard("LocalDictationTray", backend=backend)

        self.assertFalse(guard.acquire())
        self.assertEqual(backend.notifications, ["Local\\LocalDictationTray.activate"])
        self.assertEqual(len(backend.closed), 1)

    def test_first_instance_consumes_one_activation_signal(self) -> None:
        backend = FakeBackend(signalled=True)
        guard = SingleInstanceGuard("LocalDictationTray", backend=backend)
        self.assertTrue(guard.acquire())

        self.assertTrue(guard.consume_activation_request())
        self.assertFalse(guard.consume_activation_request())


if __name__ == "__main__":
    unittest.main()
