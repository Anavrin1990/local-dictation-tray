from __future__ import annotations

import logging
import threading
import uuid
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
    ):
        self.config, self.history, self.recordings_dir = config, history, recordings_dir
        self._status, self._error, self._paste = status, error, paste
        self._recorder_factory, self._transcriber_factory = recorder_factory, transcriber_factory
        self._logger = logger or logging.getLogger("dictation_tray")
        self._state = DictationState.IDLE
        self._lock = threading.Lock()
        self._recorder: MicrophoneRecorder | None = None
        self._transcriber: LocalWhisperTranscriber | None = None
        self._target_window: int | None = None

    @property
    def state(self) -> DictationState:
        with self._lock:
            return self._state

    def begin(self) -> bool:
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
        threading.Thread(target=self._finish_worker, args=(recorder,), name="whisper-worker", daemon=True).start()

    def _finish_worker(self, recorder: MicrophoneRecorder) -> None:
        wav_path = self.recordings_dir / f"{uuid.uuid4().hex}.wav"
        try:
            self._status("Расшифровка локальной моделью Whisper…")
            duration = recorder.stop_to_wav(wav_path)
            if duration < 0.15:
                self._status("Слишком короткая запись")
                return
            text, language = self._get_transcriber().transcribe(wav_path)
            if not text:
                self._status("Речь не распознана")
                return
            self.history.add(text, duration, language, self.config.history_limit)
            if self.config.auto_paste:
                restore_foreground_window(self._target_window)
                self._paste(text)
                self._status("Текст вставлен")
            else:
                self._status("Текст сохранён в истории")
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

    def _get_transcriber(self) -> LocalWhisperTranscriber:
        with self._lock:
            if self._transcriber is None:
                self._transcriber = self._transcriber_factory(self.config.model, self.config.language)
            return self._transcriber

    def update_config(self, config: AppConfig) -> None:
        """Apply persisted settings and discard the cache only if its model changed."""
        with self._lock:
            changed_model = (self.config.model, self.config.language) != (config.model, config.language)
            self.config = config
            if changed_model:
                self._transcriber = None

    def shutdown(self) -> None:
        with self._lock:
            recorder, self._recorder = self._recorder, None
            self._state = DictationState.IDLE
            self._target_window = None
        if recorder is not None:
            recorder.abort()
