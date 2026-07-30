from __future__ import annotations

import sys
import os
import json
import math
import tempfile
import wave
from pathlib import Path

from .history import HistoryRepository
from .logging_setup import configure_logging
from .paths import APP_NAME, ensure_app_dirs
from .config import ConfigStore
from .single_instance import SingleInstanceGuard


REQUIRED_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


def self_check() -> int:
    """Fast deterministic package verification; deliberately does not open GUI/audio/model."""
    try:
        base = ensure_app_dirs()
        config = ConfigStore(base / "config.json").load()
        config.validate()
        history = HistoryRepository(base / "history.sqlite3")
        history.list_recent(1)
        # Do not open app.log: a running tray instance can hold it exclusively on Windows.
        # The check must remain safe to invoke while the application is running.
        if not (base / "logs").is_dir():
            return 2
        model_dir = os.environ.get("LOCAL_DICTATION_MODEL_DIR")
        if not model_dir:
            return 3
        if not all((Path(model_dir) / name).is_file() for name in REQUIRED_MODEL_FILES):
            return 4
        return 0
    except Exception:
        return 2


def gpu_self_check() -> int:
    """Run the actual bundled model once and require CUDA rather than merely importing it."""
    if self_check() != 0:
        return self_check()
    wav_name: str | None = None
    try:
        from .transcriber import LocalWhisperTranscriber

        with tempfile.NamedTemporaryFile(prefix="dictation-gpu-check-", suffix=".wav", delete=False) as wav_file:
            wav_name = wav_file.name
        # A short tone forces encoder inference without needing a microphone or network.
        sample_rate = 16000
        samples = bytearray()
        for index in range(sample_rate):
            value = int(2200 * math.sin(2 * math.pi * 440 * index / sample_rate))
            samples.extend(value.to_bytes(2, byteorder="little", signed=True))
        with wave.open(wav_name, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(samples)
        transcriber = LocalWhisperTranscriber("small", execution_device="cuda")
        model = transcriber._get_model()
        segments, _info = model.transcribe(wav_name, vad_filter=False, beam_size=1, condition_on_previous_text=False)
        list(segments)  # faster-whisper inference is lazy; consume it before declaring success.
        result = transcriber.diagnostics()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["effective_device"] == "cuda" else 1
    except Exception as exc:
        result = {
            "requested_device": "cuda",
            "effective_device": None,
            "compute_type": None,
            "fallback_error": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(result, ensure_ascii=False))
        return 1
    finally:
        if wav_name:
            try:
                Path(wav_name).unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    if "--self-check" in sys.argv[1:]:
        return self_check()
    if "--gpu-self-check" in sys.argv[1:]:
        return gpu_self_check()
    instance_guard = SingleInstanceGuard(APP_NAME)
    if not instance_guard.acquire():
        return 0
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from .qt_app import TrayApplication, application_icon
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Локальная диктовка")
    app.setWindowIcon(application_icon())
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 2
    base = ensure_app_dirs()
    logger = configure_logging(base / "logs" / "app.log")
    tray_app = TrayApplication(app, ConfigStore(base / "config.json"), HistoryRepository(base / "history.sqlite3"), base / "recordings", logger)
    if not tray_app.start():
        instance_guard.close()
        return 1
    activation_timer = QTimer(app)
    activation_timer.setInterval(250)
    activation_timer.timeout.connect(
        lambda: tray_app.show_settings() if instance_guard.consume_activation_request() else None
    )
    activation_timer.start()
    result = app.exec()
    instance_guard.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
