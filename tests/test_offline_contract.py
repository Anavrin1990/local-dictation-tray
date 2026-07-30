from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from dictation_tray.transcriber import LocalWhisperTranscriber


class OfflineModelContractTests(unittest.TestCase):
    def test_bundled_model_path_forces_local_files_only(self) -> None:
        with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": r"C:\Program Files\LocalDictation\models\faster-whisper-small"}):
            transcriber = LocalWhisperTranscriber("small", "ru")
            self.assertEqual(transcriber.model_source(), (r"C:\Program Files\LocalDictation\models\faster-whisper-small", True))

    def test_model_constructor_receives_offline_flag(self) -> None:
        calls: list[tuple[object, ...]] = []

        class FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": "bundled-model"}):
            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                LocalWhisperTranscriber("small")._get_model()
        self.assertEqual(calls[0][0][0], "bundled-model")
        self.assertTrue(calls[0][1]["local_files_only"])

    def test_development_uses_checked_in_small_without_downloading(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source, local_only = LocalWhisperTranscriber("small").model_source()
        self.assertTrue(source.endswith("assets\\models\\faster-whisper-small"))
        self.assertTrue(local_only)


if __name__ == "__main__":
    unittest.main()
