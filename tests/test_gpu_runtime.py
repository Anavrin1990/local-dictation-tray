from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from dictation_tray.config import AppConfig, ConfigStore
from dictation_tray.controller import DictationController
from dictation_tray.history import HistoryRepository
from dictation_tray.transcriber import LocalWhisperTranscriber


class _Segment:
    text = "готово"


class _Info:
    language = "ru"


class GpuRuntimeTests(unittest.TestCase):
    def _model_module(self, failures: dict[str, object] | None = None, calls: list | None = None):
        failures, calls = failures or {}, calls if calls is not None else []

        class Model:
            def __init__(self, source, **kwargs):
                calls.append((source, kwargs))
                if kwargs["device"] in failures and isinstance(failures[kwargs["device"]], Exception):
                    raise failures[kwargs["device"]]
                self.device = kwargs["device"]

            def transcribe(self, *_args, **_kwargs):
                value = failures.get(f"infer-{self.device}")
                if isinstance(value, Exception):
                    raise value
                return iter([_Segment()]), _Info()

        return types.SimpleNamespace(WhisperModel=Model), calls

    def test_config_defaults_migrates_base_and_validates_execution_modes(self) -> None:
        self.assertEqual(AppConfig().model, "small")
        self.assertEqual(AppConfig().execution_device, "cuda")
        for mode in ("cuda", "cpu"):
            AppConfig(execution_device=mode).validate()
        with self.assertRaises(ValueError):
            AppConfig(execution_device="auto").validate()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text('{"model":"base", "execution_device":"cuda"}', encoding="utf-8")
            migrated = ConfigStore(path).load()
        self.assertEqual((migrated.model, migrated.execution_device), ("small", "cuda"))

    def test_cuda_success_uses_float16_and_local_small(self) -> None:
        module, calls = self._model_module()
        with patch.object(LocalWhisperTranscriber, "cuda_device_count", return_value=1):
            with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": "bundled-small"}):
                with patch.dict(sys.modules, {"faster_whisper": module}):
                    transcriber = LocalWhisperTranscriber("small", execution_device="cuda")
                    self.assertEqual(transcriber.transcribe(Path("audio.wav"))[0], "готово")
        self.assertEqual(calls[0][1]["device"], "cuda")
        self.assertEqual(calls[0][1]["compute_type"], "float16")
        self.assertTrue(calls[0][1]["local_files_only"])
        self.assertEqual(transcriber.effective_device, "cuda")

    def test_explicit_gpu_falls_back_to_cpu_when_cuda_load_fails(self) -> None:
        module, calls = self._model_module({"cuda": RuntimeError("CUDA DLL missing")})
        with patch.object(LocalWhisperTranscriber, "cuda_device_count", return_value=1):
            with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": "bundled-small"}):
                with patch.dict(sys.modules, {"faster_whisper": module}):
                    transcriber = LocalWhisperTranscriber("small", execution_device="cuda")
                    transcriber.transcribe(Path("audio.wav"))
        self.assertEqual([call[1]["device"] for call in calls], ["cuda", "cpu"])
        self.assertEqual(transcriber.effective_device, "cpu")
        self.assertIn("CUDA DLL missing", transcriber.fallback_error or "")

    def test_detect_execution_device_checks_cuda_without_loading_model(self) -> None:
        with patch.object(LocalWhisperTranscriber, "cuda_device_count", return_value=1):
            self.assertEqual(LocalWhisperTranscriber.detect_execution_device(), "cuda")
        with patch.object(LocalWhisperTranscriber, "cuda_device_count", return_value=0):
            self.assertEqual(LocalWhisperTranscriber.detect_execution_device(), "cpu")

    def test_cpu_never_attempts_cuda(self) -> None:
        module, calls = self._model_module()
        with patch.object(LocalWhisperTranscriber, "cuda_device_count", side_effect=AssertionError("not allowed")):
            with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": "bundled-small"}):
                with patch.dict(sys.modules, {"faster_whisper": module}):
                    LocalWhisperTranscriber("small", execution_device="cpu").transcribe(Path("audio.wav"))
        self.assertEqual([call[1]["device"] for call in calls], ["cpu"])
        self.assertEqual(calls[0][1]["compute_type"], "int8")

    def test_cuda_inference_failure_retries_once_on_cpu(self) -> None:
        module, calls = self._model_module({"infer-cuda": RuntimeError("CUDA execution failed")})
        with patch.object(LocalWhisperTranscriber, "cuda_device_count", return_value=1):
            with patch.dict(os.environ, {"LOCAL_DICTATION_MODEL_DIR": "bundled-small"}):
                with patch.dict(sys.modules, {"faster_whisper": module}):
                    transcriber = LocalWhisperTranscriber("small", execution_device="cuda")
                    self.assertEqual(transcriber.transcribe(Path("audio.wav"))[0], "готово")
        self.assertEqual([call[1]["device"] for call in calls], ["cuda", "cpu"])
        self.assertEqual(transcriber.effective_device, "cpu")
        self.assertIn("CUDA execution failed", transcriber.fallback_error or "")

    def test_controller_discards_cached_model_when_execution_device_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(LocalWhisperTranscriber, "detect_execution_device", return_value="cuda"):
                controller = DictationController(
                    AppConfig(), HistoryRepository(Path(temp) / "history.sqlite3"), Path(temp), lambda _: None, lambda _: None,
                )
            cached = object()
            controller._transcriber = cached  # type: ignore[assignment]
            controller.update_config(AppConfig(execution_device="cpu"))
        self.assertIsNone(controller._transcriber)

    def test_ui_and_packaging_require_small_and_cuda_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ui = (root / "dictation_tray" / "qt_app.py").read_text(encoding="utf-8")
        build = (root / "scripts" / "build-installer.ps1").read_text(encoding="utf-8")
        hook = (root / "packaging" / "hooks" / "runtime_local_dictation.py").read_text(encoding="utf-8")
        self.assertNotIn("Авто (рекомендуется)", ui)
        self.assertIn("GPU NVIDIA", ui)
        self.assertIn("faster-whisper-small", build)
        self.assertIn("nvidia.cublas", build)
        self.assertIn("nvidia.cudnn", build)
        self.assertIn("add_dll_directory", hook)

    def test_controller_reports_a_user_visible_gpu_fallback(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dictation_tray" / "controller.py").read_text(encoding="utf-8")
        self.assertIn("GPU NVIDIA недоступен — распознавание на CPU", source)


if __name__ == "__main__":
    unittest.main()
