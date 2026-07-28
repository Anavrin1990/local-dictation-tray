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
        with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": r"C:\Program Files\LocalDictation\models\faster-whisper-base"}):
            transcriber = LocalWhisperTranscriber("base", "ru")
            self.assertEqual(transcriber.model_source(), (r"C:\Program Files\LocalDictation\models\faster-whisper-base", True))

    def test_model_constructor_receives_offline_flag(self) -> None:
        calls: list[tuple[object, ...]] = []

        class FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": "bundled-model"}):
            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                LocalWhisperTranscriber("base")._get_model()
        self.assertEqual(calls[0][0][0], "bundled-model")
        self.assertTrue(calls[0][1]["local_files_only"])

    def test_unbundled_development_model_does_not_claim_offline_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(LocalWhisperTranscriber("base").model_source(), ("base", False))


if __name__ == "__main__":
    unittest.main()
