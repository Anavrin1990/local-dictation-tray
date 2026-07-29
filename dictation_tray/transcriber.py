from __future__ import annotations

import threading
import os
from pathlib import Path


class LocalWhisperTranscriber:
    """Caches one local Whisper model; model download occurs only on first use."""

    def __init__(self, model_name: str, language: str | None = "ru"):
        self.model_name = model_name
        self.language = language or None
        self._model = None
        self._model_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

    def model_source(self) -> tuple[str, bool]:
        """Resolve the installer-bundled model without allowing a network fallback."""
        bundled = os.environ.get("LOCAL_DICTATION_MODEL_DIR")
        if bundled:
            return bundled, True
        return self.model_name, False

    def _get_model(self):
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                # int8 is supported on ordinary Windows CPUs and keeps the app offline after caching.
                source, local_only = self.model_source()
                self._model = WhisperModel(source, device="cpu", compute_type="int8", local_files_only=local_only)
            return self._model

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        # CTranslate2 model instances are cached and shared by preview/final workers.
        # Serialize calls so a final pass never races a still-running preview pass.
        with self._transcribe_lock:
            model = self._get_model()
            segments, info = model.transcribe(
                str(audio_path), language=self.language, vad_filter=True, beam_size=5,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text, getattr(info, "language", self.language)
