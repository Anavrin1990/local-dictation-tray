from __future__ import annotations

import importlib.util
import tempfile
import unittest
import wave
from pathlib import Path

from dictation_tray.audio import MicrophoneRecorder


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is installed in the application environment")
class AudioSnapshotTests(unittest.TestCase):
    def test_snapshot_copies_live_audio_without_stopping_recorder(self) -> None:
        import numpy as np

        recorder = MicrophoneRecorder(16000)
        recorder._chunks = [np.full(8000, 0.1, dtype=np.float32), np.full(8000, 0.2, dtype=np.float32)]

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "preview.wav"
            snapshot = recorder.snapshot_to_wav(output, start_frame=8000)
            with wave.open(str(output), "rb") as wav:
                frame_count = wav.getnframes()

        self.assertAlmostEqual(snapshot.duration, 0.5)
        self.assertEqual(snapshot.total_frames, 16000)
        self.assertGreater(snapshot.recent_rms, 0.19)
        self.assertEqual(frame_count, 8000)


if __name__ == "__main__":
    unittest.main()
