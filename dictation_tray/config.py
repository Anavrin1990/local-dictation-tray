from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    hotkey: str = "ctrl+alt"
    model: str = "base"
    language: str = "ru"
    microphone: str | None = None
    sample_rate: int = 16000
    auto_paste: bool = True
    keep_recordings: bool = False
    history_limit: int = 2000

    def validate(self) -> None:
        if not self.hotkey or not self.hotkey.strip():
            raise ValueError("Горячая клавиша не может быть пустой")
        if self.sample_rate not in (8000, 16000, 22050, 44100, 48000):
            raise ValueError("Неподдерживаемая частота дискретизации")
        if self.history_limit < 1 or self.history_limit > 100_000:
            raise ValueError("Лимит истории должен быть от 1 до 100000")


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = {field.name for field in fields(AppConfig)}
            values = {k: v for k, v in raw.items() if k in allowed}
            # v0.1.1 changes the original default chord while preserving custom hotkeys.
            if values.get("hotkey") == "ctrl+alt+space":
                values["hotkey"] = "ctrl+alt"
            config = AppConfig(**values)
            config.validate()
            return config
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # Broken user configuration must not prevent the tray application from starting.
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.stem, suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(config), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
