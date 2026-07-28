from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictation_tray.main import self_check


class SelfCheckTests(unittest.TestCase):
    def test_bundled_model_and_local_data_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / "model"
            model.mkdir()
            for name in ("config.json", "model.bin", "tokenizer.json"):
                (model / name).write_text("ok", encoding="utf-8")
            with patch.dict(os.environ, {"APPDATA": str(root / "data"), "LOCAL_DICTATION_MODEL_DIR": str(model)}, clear=False):
                self.assertEqual(self_check(), 0)

    def test_missing_model_files_fail_without_gui(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "model").mkdir()
            with patch.dict(os.environ, {"APPDATA": str(root / "data"), "LOCAL_DICTATION_MODEL_DIR": str(root / "model")}, clear=False):
                self.assertEqual(self_check(), 4)

    def test_missing_model_environment_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"APPDATA": temp}, clear=True):
                self.assertEqual(self_check(), 3)


if __name__ == "__main__":
    unittest.main()
