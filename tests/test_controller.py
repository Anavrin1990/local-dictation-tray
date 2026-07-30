from __future__ import annotations

import logging
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dictation_tray.audio import AudioSnapshot
from dictation_tray.config import AppConfig
from dictation_tray.controller import DictationController, DictationState
from dictation_tray.history import HistoryRepository
from dictation_tray.transcriber import LocalWhisperTranscriber


class FakeRecorder:
    def __init__(self, sample_rate: int, device: str | None, duration: float = 1.0, start_error: Exception | None = None):
        self.duration = duration
        self.start_error = start_error
        self.started = False
        self.aborted = False

    def start(self) -> None:
        if self.start_error:
            raise self.start_error
        self.started = True

    def stop_to_wav(self, output: Path) -> float:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake audio")
        return self.duration

    def abort(self) -> None:
        self.aborted = True


class FakeTranscriber:
    def __init__(self, text: str = "готовый текст", error: Exception | None = None):
        self.text = text
        self.error = error

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        if self.error:
            raise self.error
        return self.text, "ru"

    def unload(self) -> None:
        self.unloaded = getattr(self, "unloaded", 0) + 1

    def prepare(self) -> None:
        self.prepared = getattr(self, "prepared", 0) + 1


class LiveFakeRecorder(FakeRecorder):
    def snapshot_to_wav(self, output: Path, start_frame: int = 0) -> AudioSnapshot:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"live audio")
        return AudioSnapshot(duration=1.2, total_frames=19200, recent_rms=0.02)


class PreviewAwareTranscriber(FakeTranscriber):
    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        if audio_path.name.startswith(".live-"):
            return "предварительный текст", "ru"
        return "финальный текст.", "ru"


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.statuses: list[str] = []
        self.errors: list[str] = []
        self.pasted: list[str] = []
        self.done = threading.Event()

    def tearDown(self) -> None:
        logging.getLogger("dictation_tray").handlers.clear()
        self.temp.cleanup()

    def controller(self, recorder: FakeRecorder, transcriber: FakeTranscriber, **config_values: object) -> DictationController:
        config = AppConfig(**config_values)
        controller = DictationController(
            config=config,
            history=HistoryRepository(self.root / "history.sqlite3"),
            recordings_dir=self.root / "recordings",
            status=lambda message: self.statuses.append(message),
            error=lambda message: self.errors.append(message),
            recorder_factory=lambda *_: recorder,
            transcriber_factory=lambda *_: transcriber,
            paste=lambda text: self.pasted.append(text),
        )
        original_finish = controller._finish_worker

        def record_finish(value: FakeRecorder) -> None:
            try:
                original_finish(value)
            finally:
                self.done.set()

        controller._finish_worker = record_finish  # type: ignore[method-assign]
        return controller

    def test_successful_hold_transcribes_pastes_records_history_and_removes_audio(self) -> None:
        recorder = FakeRecorder(16000, None)
        controller = self.controller(recorder, FakeTranscriber("  Привет\nмир  "))

        self.assertTrue(controller.begin())
        self.assertEqual(controller.state, DictationState.RECORDING)
        self.assertFalse(controller.begin(), "repeat press must not open a second microphone stream")
        controller.finish()
        self.assertTrue(self.done.wait(2), "background processing did not finish")

        self.assertEqual(controller.state, DictationState.IDLE)
        self.assertEqual(self.pasted, ["  Привет\nмир  "])
        self.assertEqual([item.text for item in controller.history.list_recent()], ["Привет мир"])
        self.assertTrue(recorder.aborted)
        self.assertEqual(list((self.root / "recordings").glob("*.wav")), [])

    def test_short_recording_never_calls_whisper_or_paste(self) -> None:
        recorder = FakeRecorder(16000, None, duration=0.1)
        controller = self.controller(recorder, FakeTranscriber())

        self.assertTrue(controller.begin())
        controller.finish()
        self.assertTrue(self.done.wait(2))
        self.assertEqual(self.pasted, [])
        self.assertEqual(controller.history.list_recent(), [])
        self.assertEqual(controller.state, DictationState.IDLE)

    def test_transcription_error_returns_to_idle_and_removes_audio(self) -> None:
        recorder = FakeRecorder(16000, None)
        controller = self.controller(recorder, FakeTranscriber(error=RuntimeError("model unavailable")))

        self.assertTrue(controller.begin())
        controller.finish()
        self.assertTrue(self.done.wait(2))
        self.assertEqual(controller.state, DictationState.IDLE)
        self.assertEqual(self.pasted, [])
        self.assertTrue(self.errors)
        self.assertEqual(list((self.root / "recordings").glob("*.wav")), [])

    def test_microphone_start_failure_resets_state_and_reports_error(self) -> None:
        recorder = FakeRecorder(16000, None, start_error=RuntimeError("permission denied"))
        controller = self.controller(recorder, FakeTranscriber())

        self.assertFalse(controller.begin())
        self.assertEqual(controller.state, DictationState.IDLE)
        self.assertTrue(self.errors)
        self.assertFalse(self.done.is_set())

    def test_keep_recordings_preserves_wav_when_explicitly_requested(self) -> None:
        recorder = FakeRecorder(16000, None)
        controller = self.controller(recorder, FakeTranscriber(), keep_recordings=True)

        self.assertTrue(controller.begin())
        controller.finish()
        self.assertTrue(self.done.wait(2))
        self.assertEqual(len(list((self.root / "recordings").glob("*.wav"))), 1)

    def test_whisper_instance_is_reused_between_dictations(self) -> None:
        """Recreating it per hold reloads a several-hundred-MB local model each time."""
        calls: list[FakeTranscriber] = []

        def transcriber_factory(*_: object) -> FakeTranscriber:
            item = FakeTranscriber()
            calls.append(item)
            return item

        controller = DictationController(
            AppConfig(unload_model_immediately=False, model_idle_unload_minutes=0), HistoryRepository(self.root / "history.sqlite3"), self.root / "recordings",
            self.statuses.append, self.errors.append,
            recorder_factory=lambda *_: FakeRecorder(16000, None),
            transcriber_factory=transcriber_factory,
            paste=self.pasted.append,
        )
        for _ in range(2):
            self.assertTrue(controller.begin())
            controller.finish()
            deadline = time.monotonic() + 2
            while controller.state is not DictationState.IDLE and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(controller.state, DictationState.IDLE)
        self.assertEqual(len(calls), 1)

    def test_immediate_engine_unload_releases_cached_transcriber_after_final_pass(self) -> None:
        recorder = FakeRecorder(16000, None)
        transcriber = FakeTranscriber()
        controller = self.controller(recorder, transcriber, unload_model_immediately=True)

        self.assertTrue(controller.begin())
        controller.finish()
        self.assertTrue(self.done.wait(2))
        deadline = time.monotonic() + 2
        while controller._transcriber is not None and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(transcriber.unloaded, 1)
        self.assertIsNone(controller._transcriber)

    def test_begin_prepares_model_for_first_live_preview(self) -> None:
        recorder = LiveFakeRecorder(16000, None)
        transcriber = FakeTranscriber()
        controller = self.controller(recorder, transcriber)

        self.assertTrue(controller.begin())
        deadline = time.monotonic() + 2
        while not hasattr(transcriber, "prepared") and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(transcriber.prepared, 1)
        controller.finish()
        self.assertTrue(self.done.wait(2))

    def test_idle_engine_unload_is_disabled_when_timeout_is_never(self) -> None:
        recorder = FakeRecorder(16000, None)
        transcriber = FakeTranscriber()
        controller = self.controller(recorder, transcriber, model_idle_unload_minutes=0, unload_model_immediately=False)

        self.assertTrue(controller.begin())
        controller.finish()
        self.assertTrue(self.done.wait(2))
        time.sleep(0.05)
        self.assertIs(controller._transcriber, transcriber)
        self.assertFalse(hasattr(transcriber, "unloaded"))

    def test_startup_resolves_unavailable_cuda_to_cpu_without_creating_model(self) -> None:
        with patch.object(LocalWhisperTranscriber, "detect_execution_device", return_value="cpu"):
            controller = DictationController(
                AppConfig(execution_device="cuda"),
                HistoryRepository(self.root / "history.sqlite3"),
                self.root / "recordings",
                self.statuses.append,
                self.errors.append,
            )
        self.assertEqual(controller.config.execution_device, "cpu")
        self.assertIsNone(controller._transcriber)

    def test_live_preview_is_replaced_by_final_full_transcription(self) -> None:
        recorder = LiveFakeRecorder(16000, None)
        live_updates: list[tuple[str, str]] = []
        started = threading.Event()
        preview_ready = threading.Event()
        finished: list[tuple[str, bool]] = []

        def on_live_text(confirmed: str, provisional: str) -> None:
            live_updates.append((confirmed, provisional))
            if provisional:
                preview_ready.set()

        controller = DictationController(
            AppConfig(),
            HistoryRepository(self.root / "history.sqlite3"),
            self.root / "recordings",
            self.statuses.append,
            self.errors.append,
            recorder_factory=lambda *_: recorder,
            transcriber_factory=lambda *_: PreviewAwareTranscriber(),
            paste=self.pasted.append,
            on_recording_started=started.set,
            on_live_text=on_live_text,
            on_recording_finished=lambda text, success: finished.append((text, success)),
            live_interval_seconds=0.01,
        )

        self.assertTrue(controller.begin())
        self.assertTrue(started.wait(1))
        self.assertTrue(preview_ready.wait(2))
        controller.finish()
        deadline = time.monotonic() + 3
        while controller.state is not DictationState.IDLE and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertIn(("", "предварительный текст"), live_updates)
        self.assertEqual(self.pasted, ["финальный текст."])
        self.assertEqual(finished, [("финальный текст.", True)])


if __name__ == "__main__":
    unittest.main()
