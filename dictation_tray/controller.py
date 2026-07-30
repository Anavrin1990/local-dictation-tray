from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import replace
from enum import Enum
from pathlib import Path
from collections.abc import Callable

from .audio import MicrophoneRecorder
from .config import AppConfig
from .focus import foreground_window, restore_foreground_window
from .history import HistoryRepository
from .paste import paste_unicode
from .transcriber import LocalWhisperTranscriber


class DictationState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class DictationController:
    def __init__(
        self, config: AppConfig, history: HistoryRepository, recordings_dir: Path,
        status: Callable[[str], None], error: Callable[[str], None],
        recorder_factory: Callable[..., MicrophoneRecorder] = MicrophoneRecorder,
        transcriber_factory: Callable[..., LocalWhisperTranscriber] = LocalWhisperTranscriber,
        paste: Callable[[str], None] = paste_unicode,
        logger: logging.Logger | None = None,
        on_recording_started: Callable[[], None] | None = None,
        on_live_text: Callable[[str, str], None] | None = None,
        on_processing_started: Callable[[], None] | None = None,
        on_recording_finished: Callable[[str, bool], None] | None = None,
        live_interval_seconds: float = 1.1,
    ):
        # Resolve the initial device without loading the Whisper model. Settings
        # only expose explicit CPU/GPU choices; unavailable CUDA becomes CPU.
        if config.execution_device == "cuda":
            detected = LocalWhisperTranscriber.detect_execution_device()
            if detected != "cuda":
                config = replace(config, execution_device="cpu")
                self._logger = logger or logging.getLogger("dictation_tray")
                self._logger.info("CUDA device not found at startup; selected CPU")
        self.config, self.history, self.recordings_dir = config, history, recordings_dir
        self._status, self._error, self._paste = status, error, paste
        self._recorder_factory, self._transcriber_factory = recorder_factory, transcriber_factory
        self._logger = logger or logging.getLogger("dictation_tray")
        self._on_recording_started = on_recording_started or (lambda: None)
        self._on_live_text = on_live_text or (lambda _confirmed, _provisional: None)
        self._on_processing_started = on_processing_started or (lambda: None)
        self._on_recording_finished = on_recording_finished or (lambda _text, _success: None)
        self._live_interval_seconds = max(0.01, live_interval_seconds)
        self._state = DictationState.IDLE
        self._lock = threading.Lock()
        self._recorder: MicrophoneRecorder | None = None
        self._transcriber: LocalWhisperTranscriber | None = None
        self._target_window: int | None = None
        self._live_stop = threading.Event()
        self._live_thread: threading.Thread | None = None
        self._unload_timer: threading.Timer | None = None

    @property
    def state(self) -> DictationState:
        with self._lock:
            return self._state

    def begin(self) -> bool:
        self._cancel_unload_timer()
        with self._lock:
            if self._state is not DictationState.IDLE:
                return False
            self._state = DictationState.RECORDING
            self._target_window = foreground_window()
        try:
            recorder = self._recorder_factory(self.config.sample_rate, self.config.microphone)
            recorder.start()
            with self._lock:
                self._recorder = recorder
            self._live_stop.clear()
            self._on_recording_started()
            if self.config.live_preview_enabled and hasattr(recorder, "snapshot_to_wav"):
                self._live_thread = threading.Thread(
                    target=self._live_worker,
                    args=(recorder,),
                    name="whisper-preview-worker",
                    daemon=True,
                )
                self._live_thread.start()
            self._status("● Идёт запись… отпустите горячую клавишу")
            return True
        except Exception as exc:
            with self._lock:
                self._state = DictationState.IDLE
                self._recorder = None
            self._logger.exception("Could not start microphone recording")
            self._error(f"Не удалось открыть микрофон: {exc}")
            return False

    def finish(self) -> None:
        with self._lock:
            if self._state is not DictationState.RECORDING or self._recorder is None:
                return
            self._state = DictationState.TRANSCRIBING
            recorder, self._recorder = self._recorder, None
        self._live_stop.set()
        self._on_processing_started()
        threading.Thread(target=self._finish_worker, args=(recorder,), name="whisper-worker", daemon=True).start()

    def _finish_worker(self, recorder: MicrophoneRecorder) -> None:
        wav_path = self.recordings_dir / f"{uuid.uuid4().hex}.wav"
        final_text = ""
        success = False
        try:
            self._status("Расшифровка локальной моделью Whisper…")
            duration = recorder.stop_to_wav(wav_path)
            if duration < 0.15:
                self._status("Слишком короткая запись")
                return
            transcriber = self._get_transcriber()
            text, language = transcriber.transcribe(wav_path)
            fallback_error = getattr(transcriber, "fallback_error", None)
            effective_device = getattr(transcriber, "effective_device", None)
            if fallback_error:
                self._status("GPU NVIDIA недоступен — распознавание на CPU")
                self._logger.warning("Whisper GPU fallback shown to user: %s", fallback_error)
            elif effective_device == "cuda":
                self._status("Распознавание: GPU NVIDIA (CUDA float16)")
            elif effective_device == "cpu":
                self._status("Распознавание: CPU (int8)")
            if not text:
                self._status("Речь не распознана")
                return
            final_text = text
            self.history.add(text, duration, language, self.config.history_limit)
            if self.config.auto_paste:
                restore_foreground_window(self._target_window)
                self._paste(text)
                self._status("Текст вставлен")
            else:
                self._status("Текст сохранён в истории")
            success = True
        except Exception as exc:
            self._logger.exception("Dictation processing failed")
            self._error(f"Ошибка расшифровки: {exc}")
        finally:
            try:
                recorder.abort()
            except Exception:
                pass
            if not self.config.keep_recordings:
                try:
                    wav_path.unlink(missing_ok=True)
                except OSError:
                    self._logger.warning("Could not remove temporary recording")
            with self._lock:
                self._state = DictationState.IDLE
                self._target_window = None
            self._on_recording_finished(final_text, success)
            self._schedule_engine_unload()

    def _live_worker(self, recorder: MicrophoneRecorder) -> None:
        """Transcribe growing speech segments while recording; the final pass remains authoritative."""
        committed = ""
        segment_start_frame = 0
        live_path = self.recordings_dir / f".live-{uuid.uuid4().hex}.wav"
        try:
            while not self._live_stop.wait(self._live_interval_seconds):
                with self._lock:
                    if self._state is not DictationState.RECORDING:
                        return
                snapshot = recorder.snapshot_to_wav(live_path, segment_start_frame)
                if snapshot.duration < 0.65:
                    continue
                text, _language = self._get_transcriber().transcribe(live_path)
                if self._live_stop.is_set():
                    return
                text = text.strip()
                if not text:
                    continue

                ended_on_pause = snapshot.duration >= 1.1 and snapshot.recent_rms < 0.008
                if ended_on_pause:
                    committed = f"{committed} {text}".strip()
                    segment_start_frame = snapshot.total_frames
                    self._on_live_text(committed, "")
                else:
                    self._on_live_text(committed, text)
        except Exception:
            # Preview is optional: a failed interim pass must never break the final dictation.
            self._logger.warning("Live transcription preview failed", exc_info=True)
        finally:
            try:
                live_path.unlink(missing_ok=True)
            except OSError:
                self._logger.warning("Could not remove live preview recording")

    def _get_transcriber(self) -> LocalWhisperTranscriber:
        with self._lock:
            if self._transcriber is None:
                self._transcriber = self._transcriber_factory(
                    self.config.model, self.config.language, self.config.execution_device, self._logger,
                )
            return self._transcriber

    def _cancel_unload_timer(self) -> None:
        with self._lock:
            timer, self._unload_timer = self._unload_timer, None
        if timer is not None:
            timer.cancel()

    def _schedule_engine_unload(self) -> None:
        if self.config.unload_model_immediately:
            delay_seconds = 0.0
        elif self.config.model_idle_unload_minutes:
            delay_seconds = self.config.model_idle_unload_minutes * 60.0
        else:
            return
        self._cancel_unload_timer()
        timer = threading.Timer(delay_seconds, self._unload_engine_if_idle)
        timer.daemon = True
        with self._lock:
            self._unload_timer = timer
        timer.start()

    def _unload_engine_if_idle(self) -> None:
        """Do not release a model while a preview/final worker can still use it."""
        with self._lock:
            live_running = self._live_thread is not None and self._live_thread.is_alive()
            if self._state is not DictationState.IDLE or live_running:
                # A preview worker is normally exiting after finish; retry briefly.
                timer = threading.Timer(0.25, self._unload_engine_if_idle)
                timer.daemon = True
                self._unload_timer = timer
                timer.start()
                return
            transcriber, self._transcriber = self._transcriber, None
            self._unload_timer = None
        if transcriber is not None:
            unload = getattr(transcriber, "unload", None)
            if callable(unload):
                unload()
            self._logger.info("Whisper engine released after idle period")

    def update_config(self, config: AppConfig) -> None:
        """Apply persisted settings and discard the model when its runtime changes."""
        with self._lock:
            changed_model = (self.config.model, self.config.language, self.config.execution_device) != (
                config.model, config.language, config.execution_device,
            )
            self.config = config
            if changed_model:
                previous, self._transcriber = self._transcriber, None
            else:
                previous = None
        if previous is not None:
            unload = getattr(previous, "unload", None)
            if callable(unload):
                unload()
        self._cancel_unload_timer()

    def shutdown(self) -> None:
        self._live_stop.set()
        self._cancel_unload_timer()
        with self._lock:
            recorder, self._recorder = self._recorder, None
            transcriber, self._transcriber = self._transcriber, None
            self._state = DictationState.IDLE
            self._target_window = None
        if recorder is not None:
            recorder.abort()
        if transcriber is not None:
            unload = getattr(transcriber, "unload", None)
            if callable(unload):
                unload()
        self._on_recording_finished("", False)
