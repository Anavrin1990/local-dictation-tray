from __future__ import annotations

import ctypes
import gc
import logging
import os
import sys
import threading
from pathlib import Path


def trim_process_working_set() -> bool:
    """Ask Windows to return unused physical pages; intentionally a no-op elsewhere."""
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetProcessWorkingSetSize.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t)
        kernel32.SetProcessWorkingSetSize.restype = ctypes.c_bool
        process = kernel32.GetCurrentProcess()
        trim = ctypes.c_size_t(-1).value
        return bool(kernel32.SetProcessWorkingSetSize(process, trim, trim))
    except (AttributeError, OSError):
        return False


class LocalWhisperTranscriber:
    """Offline bundled Whisper small with safe NVIDIA CUDA -> CPU fallback."""

    def __init__(
        self,
        model_name: str = "small",
        language: str | None = None,
        execution_device: str = "cuda",
        logger: logging.Logger | None = None,
    ):
        if model_name != "small":
            raise ValueError("Only bundled Whisper small is supported")
        if execution_device not in {"cuda", "cpu"}:
            raise ValueError("execution_device must be cuda or cpu")
        self.model_name = model_name
        self.language = language or None
        self.requested_device = execution_device
        self.effective_device: str | None = None
        self.effective_compute_type: str | None = None
        self.fallback_error: str | None = None
        self._logger = logger or logging.getLogger("dictation_tray")
        self._model = None
        self._model_lock = threading.RLock()
        self._transcribe_lock = threading.Lock()

    @staticmethod
    def cuda_device_count() -> int:
        try:
            import ctranslate2

            return int(ctranslate2.get_cuda_device_count())
        except Exception:
            return 0

    @classmethod
    def detect_execution_device(cls) -> str:
        """Fast startup probe: queries CTranslate2 only, never loads Whisper."""
        return "cuda" if cls.cuda_device_count() > 0 else "cpu"

    def model_source(self) -> tuple[str, bool]:
        """Require an installer/local checked-in model; never permit HF network access."""
        bundled = os.environ.get("LOCAL_DICTATION_MODEL_DIR")
        if bundled:
            return bundled, True
        candidate = Path(__file__).resolve().parents[1] / "assets" / "models" / "faster-whisper-small"
        if candidate.is_dir():
            return str(candidate), True
        raise RuntimeError("Локальная модель Whisper small не найдена; переустановите приложение")

    def _create_model(self, device: str, compute_type: str):
        source, local_only = self.model_source()
        from faster_whisper import WhisperModel

        return WhisperModel(source, device=device, compute_type=compute_type, local_files_only=local_only)

    def _set_model(self, device: str, compute_type: str):
        self._model = self._create_model(device, compute_type)
        self.effective_device = device
        self.effective_compute_type = compute_type
        self._log_runtime("loaded")
        return self._model

    def _fallback_to_cpu(self, exc: Exception, phase: str):
        self.fallback_error = f"CUDA {phase}: {type(exc).__name__}: {exc}"
        self._logger.warning("CUDA unavailable, falling back to CPU: %s", self.fallback_error, exc_info=True)
        self._model = None
        return self._set_model("cpu", "int8")

    def _get_model(self):
        with self._model_lock:
            if self._model is not None:
                return self._model
            if self.requested_device == "cpu":
                return self._set_model("cpu", "int8")
            should_try_cuda = self.requested_device == "cuda" and self.cuda_device_count() > 0
            if not should_try_cuda:
                self.fallback_error = "CUDA load: no NVIDIA CUDA device reported by CTranslate2"
                self._logger.info("%s; using CPU int8", self.fallback_error)
                return self._set_model("cpu", "int8")
            try:
                return self._set_model("cuda", "float16")
            except Exception as exc:
                return self._fallback_to_cpu(exc, "load failure")

    def _log_runtime(self, event: str) -> None:
        self._logger.info(
            "Whisper runtime %s: model=%s requested_device=%s effective_device=%s compute_type=%s fallback_error=%s",
            event,
            self.model_name,
            self.requested_device,
            self.effective_device,
            self.effective_compute_type,
            self.fallback_error,
        )

    def diagnostics(self) -> dict[str, object]:
        return {
            "model": self.model_name,
            "requested_device": self.requested_device,
            "effective_device": self.effective_device,
            "compute_type": self.effective_compute_type,
            "cuda_count": self.cuda_device_count(),
            "fallback_error": self.fallback_error,
        }

    def prepare(self) -> None:
        """Load the selected runtime early so the first live preview is not late."""
        with self._transcribe_lock:
            self._get_model()

    def unload(self) -> bool:
        """Release the model safely after all preview/final work has completed."""
        # Keep the lock order identical to transcribe(): transcribe -> model.
        with self._transcribe_lock:
            with self._model_lock:
                if self._model is None:
                    return False
                model = self._model
                self._model = None
                self._logger.info(
                    "Whisper runtime unloaded: effective_device=%s compute_type=%s",
                    self.effective_device,
                    self.effective_compute_type,
                )
                self.effective_device = None
                self.effective_compute_type = None
            # CTranslate2 releases its model when the final Python reference is
            # gone.  Collect before trimming so Windows can reclaim unused pages.
            del model
            gc.collect()
            trimmed = trim_process_working_set()
            self._logger.debug("Whisper runtime memory cleanup completed: working_set_trimmed=%s", trimmed)
            return True

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        # CTranslate2 instances are shared by preview/final workers; CUDA failure
        # is retried exactly once with a fresh CPU int8 model.
        with self._transcribe_lock:
            model = self._get_model()
            try:
                segments, info = model.transcribe(
                    str(audio_path), language=self.language, vad_filter=True, beam_size=5,
                    condition_on_previous_text=False,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                return text, getattr(info, "language", self.language)
            except Exception as exc:
                if self.effective_device != "cuda":
                    raise
                with self._model_lock:
                    model = self._fallback_to_cpu(exc, "inference failure")
                segments, info = model.transcribe(
                    str(audio_path), language=self.language, vad_filter=True, beam_size=5,
                    condition_on_previous_text=False,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                return text, getattr(info, "language", self.language)
