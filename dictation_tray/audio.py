from __future__ import annotations

import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AudioSnapshot:
    duration: float
    total_frames: int
    recent_rms: float


class MicrophoneRecorder:
    """Small, thread-safe recording wrapper. Imports audio dependencies lazily."""

    def __init__(self, sample_rate: int, device: str | int | None = None):
        self.sample_rate = sample_rate
        self.device = device
        self._chunks: list[object] = []
        self._lock = threading.Lock()
        self._stream = None
        self._started_at: float | None = None

    @staticmethod
    def input_devices() -> list[str]:
        try:
            import sounddevice as sd
            return [str(device["name"]) for device in sd.query_devices() if device["max_input_channels"] > 0]
        except Exception:
            return []

    def start(self) -> None:
        import numpy as np
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                raise RuntimeError("Запись уже запущена")
            self._chunks.clear()

            def callback(indata, frames, timing, status) -> None:
                if status:
                    # The callback must never throw: sounddevice would otherwise stop the stream.
                    return
                with self._lock:
                    self._chunks.append(np.array(indata[:, 0], copy=True))

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                device=self.device or None,
                channels=1,
                dtype="float32",
                callback=callback,
            )
            try:
                self._stream.start()
                self._started_at = time.monotonic()
            except Exception:
                self._stream.close()
                self._stream = None
                raise

    def stop_to_wav(self, output: Path) -> float:
        import numpy as np

        with self._lock:
            stream, self._stream = self._stream, None
            started_at, self._started_at = self._started_at, None
        if stream is None:
            return 0.0
        try:
            stream.stop()
            stream.close()
        finally:
            with self._lock:
                chunks = self._chunks
                self._chunks = []
        if not chunks:
            return 0.0
        audio = np.concatenate(chunks)
        duration = len(audio) / self.sample_rate
        self._write_wav(output, audio)
        return duration if started_at is None else max(duration, time.monotonic() - started_at)

    def snapshot_to_wav(self, output: Path, start_frame: int = 0) -> AudioSnapshot:
        """Copy the current recording segment without interrupting the microphone."""
        import numpy as np

        with self._lock:
            chunks = list(self._chunks)
        if not chunks:
            return AudioSnapshot(0.0, 0, 0.0)

        audio = np.concatenate(chunks)
        total_frames = len(audio)
        start_frame = max(0, min(start_frame, total_frames))
        segment = audio[start_frame:]
        if not len(segment):
            return AudioSnapshot(0.0, total_frames, 0.0)

        recent_frames = max(1, int(self.sample_rate * 0.65))
        recent = segment[-recent_frames:]
        recent_rms = float(np.sqrt(np.mean(np.square(recent, dtype=np.float64))))
        self._write_wav(output, segment)
        return AudioSnapshot(len(segment) / self.sample_rate, total_frames, recent_rms)

    def _write_wav(self, output: Path, audio) -> None:
        import numpy as np

        output.parent.mkdir(parents=True, exist_ok=True)
        pcm = np.clip(audio, -1, 1)
        pcm = (pcm * 32767).astype("<i2")
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm.tobytes())

    def abort(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
            self._chunks = []
            self._started_at = None
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()
