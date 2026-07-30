from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    hotkey: str = "ctrl+alt"
    # Only this locally bundled model is supported; legacy `base` configs migrate on load.
    model: str = "small"
    # The initial value is resolved to CUDA or CPU during tray startup.
    execution_device: str = "cuda"
    language: str = "ru"
    microphone: str | None = None
    sample_rate: int = 16000
    auto_paste: bool = True
    keep_recordings: bool = False
    history_limit: int = 2000
    live_preview_enabled: bool = True
    overlay_max_width: int = 520
    overlay_max_height: int = 220
    overlay_position: str = "above"
    overlay_offset_x: int = 0
    overlay_offset_y: int = 0
    overlay_background_color: str = "#17172B"
    overlay_text_color: str = "#F7F7FF"
    overlay_provisional_color: str = "#AEB4D0"
    overlay_opacity: int = 88
    # 0 means keep the engine resident until the application exits.
    model_idle_unload_minutes: int = 10
    unload_model_immediately: bool = False

    def validate(self) -> None:
        if self.model != "small":
            raise ValueError("Only the bundled Whisper small model is supported")
        if self.execution_device not in {"cuda", "cpu"}:
            raise ValueError("Execution device must be cuda or cpu")
        if self.model_idle_unload_minutes not in {0, 5, 10, 30}:
            raise ValueError("Model idle unload timeout must be 0, 5, 10, or 30 minutes")
        if not self.hotkey or not self.hotkey.strip():
            raise ValueError("Горячая клавиша не может быть пустой")
        if self.sample_rate not in (8000, 16000, 22050, 44100, 48000):
            raise ValueError("Неподдерживаемая частота дискретизации")
        if self.history_limit < 1 or self.history_limit > 100_000:
            raise ValueError("Лимит истории должен быть от 1 до 100000")
        if not 240 <= self.overlay_max_width <= 1400:
            raise ValueError("Максимальная ширина окна должна быть от 240 до 1400")
        if not 80 <= self.overlay_max_height <= 900:
            raise ValueError("Максимальная высота окна должна быть от 80 до 900")
        if self.overlay_position not in {"above", "below", "left", "right"}:
            raise ValueError("Неизвестное положение окна диктовки")
        if not -1000 <= self.overlay_offset_x <= 1000 or not -1000 <= self.overlay_offset_y <= 1000:
            raise ValueError("Смещение окна должно быть от -1000 до 1000")
        if not 20 <= self.overlay_opacity <= 100:
            raise ValueError("Прозрачность подложки должна быть от 20 до 100")
        color_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for color in (
            self.overlay_background_color,
            self.overlay_text_color,
            self.overlay_provisional_color,
        ):
            if not color_pattern.fullmatch(color):
                raise ValueError("Цвет должен быть записан в формате #RRGGBB")


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
            if values.get("model") in {None, "base"}:
                values["model"] = "small"
            # v0.3 removes the ambiguous automatic mode. The controller chooses a
            # concrete CUDA/CPU mode when the application starts.
            if values.get("execution_device") == "auto":
                values["execution_device"] = "cuda"
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
