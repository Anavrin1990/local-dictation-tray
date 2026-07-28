from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictation_tray.config import AppConfig, ConfigStore
from dictation_tray.history import HistoryRepository
from dictation_tray.logging_setup import configure_logging
from dictation_tray.paths import APP_NAME, app_data_dir, ensure_app_dirs


class ConfigStoreTests(unittest.TestCase):
    def test_missing_file_returns_valid_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = ConfigStore(Path(temp) / "config.json").load()
        self.assertEqual(config, AppConfig())

    def test_save_round_trip_preserves_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "config.json"
            expected = AppConfig(hotkey="ctrl+shift+ё", language="ru", history_limit=17)
            ConfigStore(path).save(expected)
            self.assertEqual(ConfigStore(path).load(), expected)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["language"], "ru")

    def test_bad_or_invalid_user_file_never_blocks_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text('{"sample_rate": 123}', encoding="utf-8")
            self.assertEqual(ConfigStore(path).load(), AppConfig())
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(ConfigStore(path).load(), AppConfig())

    def test_validate_rejects_unsafe_history_limit(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(history_limit=0).validate()


class HistoryRepositoryTests(unittest.TestCase):
    def test_unicode_text_is_normalized_and_listed_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = HistoryRepository(Path(temp) / "history.sqlite3")
            first = repository.add("  Привет\nмир  ", 1.25, "ru", limit=10)
            second = repository.add("emoji 😀", 0.5, None, limit=10)
            recent = repository.list_recent()

        self.assertEqual(first.text, "Привет мир")
        self.assertEqual([entry.id for entry in recent], [second.id, first.id])
        self.assertEqual(recent[1].language, "ru")

    def test_limit_removes_old_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = HistoryRepository(Path(temp) / "history.sqlite3")
            repository.add("one", 1, "ru", limit=2)
            repository.add("two", 1, "ru", limit=2)
            newest = repository.add("three", 1, "ru", limit=2)
            recent = repository.list_recent(10)

        self.assertEqual([entry.text for entry in recent], ["three", "two"])
        self.assertEqual(recent[0].id, newest.id)

    def test_invalid_history_limit_is_rejected_at_storage_boundary(self) -> None:
        """Storage must not silently discard the just-transcribed text on a bad setting."""
        with tempfile.TemporaryDirectory() as temp:
            repository = HistoryRepository(Path(temp) / "history.sqlite3")
            with self.assertRaises(ValueError):
                repository.add("important dictation", 1, "ru", limit=0)
            self.assertEqual(repository.list_recent(), [])

    def test_empty_dictation_is_not_persisted_and_delete_all_works(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = HistoryRepository(Path(temp) / "history.sqlite3")
            with self.assertRaises(ValueError):
                repository.add(" \t\n", 1, "ru", limit=2)
            repository.add("text", 1, "ru", limit=2)
            repository.delete_all()
            self.assertEqual(repository.list_recent(), [])


class EnvironmentTests(unittest.TestCase):
    def test_app_data_path_prefers_roaming_appdata(self) -> None:
        with patch.dict("os.environ", {"APPDATA": r"C:\\User\\AppData\\Roaming"}, clear=True):
            self.assertEqual(app_data_dir(), Path(r"C:\User\AppData\Roaming") / APP_NAME)

    def test_ensure_app_dirs_creates_expected_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = ensure_app_dirs(Path(temp) / "app")
            self.assertTrue((root / "logs").is_dir())
            self.assertTrue((root / "recordings").is_dir())

    def test_logging_writes_utf8_and_replaces_old_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log_path = Path(temp) / "app.log"
            logger = configure_logging(log_path)
            try:
                logger.info("микрофон подключён")
                for handler in logger.handlers:
                    handler.flush()
                self.assertIn("микрофон подключён", log_path.read_text(encoding="utf-8"))
                self.assertEqual(len(logger.handlers), 1)
                self.assertFalse(logger.propagate)
            finally:
                for handler in logger.handlers:
                    handler.close()
                logger.handlers.clear()


if __name__ == "__main__":
    unittest.main()
