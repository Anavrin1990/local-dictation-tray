from __future__ import annotations

import html
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QIcon, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .audio import MicrophoneRecorder
from .config import AppConfig, ConfigStore
from .controller import DictationController
from .history import HistoryRepository
from .hotkey import HoldHotkey


def application_icon() -> QIcon:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return QIcon(str(bundle_root / "assets" / "tray-icon.ico"))


class UiEvents(QObject):
    status = Signal(str)
    error = Signal(str)
    recording_started = Signal()
    live_text = Signal(str, str)
    processing_started = Signal()
    recording_finished = Signal(str, bool)


class DictationOverlay(QWidget):
    """Focus-safe, click-through live transcription bubble anchored near the pointer."""

    def __init__(self, config: AppConfig):
        flags = (
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setObjectName("dictationOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        self.status_label = QLabel()
        self.status_label.setFocusPolicy(Qt.NoFocus)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFocusPolicy(Qt.NoFocus)
        self.text.setFrameStyle(0)
        self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text.document().setDocumentMargin(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 11, 16, 13)
        layout.setSpacing(6)
        layout.addWidget(self.status_label)
        layout.addWidget(self.text)

        self.config = config
        self.anchor = QPoint()
        self.confirmed = ""
        self.provisional = ""
        self.apply_config(config)

    def apply_config(self, config: AppConfig) -> None:
        self.config = config
        self.setStyleSheet(
            f"""
            QLabel {{
                color: #73E2FF;
                background: transparent;
                border: none;
                font-size: 11px;
                font-weight: 600;
            }}
            QTextEdit {{
                color: {config.overlay_text_color};
                background: transparent;
                border: none;
                font-size: 14px;
                selection-background-color: transparent;
            }}
            """
        )
        self.update()
        if self.isVisible():
            self._render()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background = QColor(self.config.overlay_background_color)
        background.setAlpha(round(255 * self.config.overlay_opacity / 100))
        border = QColor(132, 143, 255, 95)
        painter.setPen(QPen(border, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 16, 16)
        super().paintEvent(event)

    def show_recording(self) -> None:
        self.anchor = QCursor.pos()
        self.confirmed = ""
        self.provisional = ""
        self.status_label.setText("●  Запись — говорите")
        self._render("Слушаю…")
        self.show()
        self.raise_()
        self._position_near_anchor()

    def set_live_text(self, confirmed: str, provisional: str) -> None:
        self.confirmed = confirmed
        self.provisional = provisional
        self.status_label.setText("●  Запись — говорите")
        self._render()

    def show_processing(self) -> None:
        self.status_label.setText("◆  Уточняю текст и пунктуацию…")
        self._render()

    def show_finished(self, text: str, success: bool) -> None:
        if success and text:
            self.confirmed = text
            self.provisional = ""
            self.status_label.setText("✓  Текст вставлен")
            self._render()
            QTimer.singleShot(700, self.hide)
        else:
            self.hide()

    def _render(self, placeholder: str = "") -> None:
        confirmed = html.escape(self.confirmed)
        provisional = html.escape(self.provisional)
        if confirmed or provisional:
            separator = " " if confirmed and provisional else ""
            content = (
                f'<span style="color:{self.config.overlay_text_color}">{confirmed}</span>'
                f"{separator}"
                f'<span style="color:{self.config.overlay_provisional_color}">{provisional}</span>'
            )
            plain_text = f"{self.confirmed}{separator}{self.provisional}"
        else:
            content = f'<span style="color:{self.config.overlay_provisional_color}">{html.escape(placeholder)}</span>'
            plain_text = placeholder

        self.text.setHtml(content)
        natural_width = self.text.fontMetrics().horizontalAdvance(plain_text[-240:]) + 36
        target_width = max(250, min(self.config.overlay_max_width, natural_width))
        self.text.document().setTextWidth(max(1, target_width - 32))
        document_height = int(self.text.document().size().height())
        target_height = max(76, min(self.config.overlay_max_height, document_height + 52))
        self.resize(target_width, target_height)
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text.setTextCursor(cursor)
        self.text.ensureCursorVisible()
        self._position_near_anchor()

    def _position_near_anchor(self) -> None:
        screen = QGuiApplication.screenAt(self.anchor) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        gap = 14
        width, height = self.width(), self.height()
        position = self.config.overlay_position

        if position == "below":
            x, y = self.anchor.x() - width // 2, self.anchor.y() + gap
        elif position == "left":
            x, y = self.anchor.x() - width - gap, self.anchor.y() - height // 2
        elif position == "right":
            x, y = self.anchor.x() + gap, self.anchor.y() - height // 2
        else:
            x, y = self.anchor.x() - width // 2, self.anchor.y() - height - gap

        x += self.config.overlay_offset_x
        y += self.config.overlay_offset_y

        # Flip to the opposite side before clamping so the bubble stays near the pointer.
        if position == "above" and y < available.top():
            y = self.anchor.y() + gap + self.config.overlay_offset_y
        elif position == "below" and y + height > available.bottom():
            y = self.anchor.y() - height - gap + self.config.overlay_offset_y
        elif position == "left" and x < available.left():
            x = self.anchor.x() + gap + self.config.overlay_offset_x
        elif position == "right" and x + width > available.right():
            x = self.anchor.x() - width - gap + self.config.overlay_offset_x

        x = min(max(x, available.left()), available.right() - width + 1)
        y = min(max(y, available.top()), available.bottom() - height + 1)
        self.move(x, y)


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None, on_open_logs=None, active_execution_device: str | None = None):
        super().__init__(parent)
        self.original_config = config
        self.setWindowTitle("Настройки локальной диктовки")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.hotkey = QLineEdit(config.hotkey)
        self.hotkey.setPlaceholderText("Например: ctrl+alt")
        self.model = QComboBox()
        # The installer bundles this model, so the application remains offline after installation.
        self.model.addItem("small (встроенная, локальная)", "small")
        self.model.setEnabled(False)
        self.execution_device = QComboBox()
        self.execution_device.addItem("GPU NVIDIA", "cuda")
        self.execution_device.addItem("CPU", "cpu")
        self.execution_device.setCurrentIndex(max(0, self.execution_device.findData(config.execution_device)))
        self.model_idle_unload_minutes = QComboBox()
        self.model_idle_unload_minutes.addItem("Не выгружать", 0)
        self.model_idle_unload_minutes.addItem("Через 5 минут", 5)
        self.model_idle_unload_minutes.addItem("Через 10 минут", 10)
        self.model_idle_unload_minutes.addItem("Через 30 минут", 30)
        self.model_idle_unload_minutes.setCurrentIndex(
            max(0, self.model_idle_unload_minutes.findData(config.model_idle_unload_minutes))
        )
        self.unload_model_immediately = QCheckBox("Освобождать память сразу после распознавания")
        self.unload_model_immediately.setChecked(config.unload_model_immediately)
        self.language = QComboBox()
        self.language.addItem("Автоопределение", "")
        self.language.addItem("Русский", "ru")
        self.language.addItem("English", "en")
        index = self.language.findData(config.language or "")
        self.language.setCurrentIndex(max(index, 0))
        self.microphone = QComboBox()
        self.microphone.addItem("Системный микрофон", None)
        for device in MicrophoneRecorder.input_devices():
            self.microphone.addItem(device, device)
        device_index = self.microphone.findData(config.microphone)
        self.microphone.setCurrentIndex(max(device_index, 0))
        self.auto_paste = QCheckBox("Вставлять текст автоматически")
        self.auto_paste.setChecked(config.auto_paste)
        self.keep_recordings = QCheckBox("Сохранять WAV-записи (по умолчанию удаляются)")
        self.keep_recordings.setChecked(config.keep_recordings)
        self.history_limit = QSpinBox()
        self.history_limit.setRange(1, 100_000)
        self.history_limit.setValue(config.history_limit)
        self.live_preview = QCheckBox("Показывать предварительный текст во время диктовки")
        self.live_preview.setChecked(config.live_preview_enabled)
        self.overlay_max_width = QSpinBox()
        self.overlay_max_width.setRange(240, 1400)
        self.overlay_max_width.setSuffix(" px")
        self.overlay_max_width.setValue(config.overlay_max_width)
        self.overlay_max_height = QSpinBox()
        self.overlay_max_height.setRange(80, 900)
        self.overlay_max_height.setSuffix(" px")
        self.overlay_max_height.setValue(config.overlay_max_height)
        self.overlay_position = QComboBox()
        for label, value in (
            ("Сверху от указателя", "above"),
            ("Снизу от указателя", "below"),
            ("Слева от указателя", "left"),
            ("Справа от указателя", "right"),
        ):
            self.overlay_position.addItem(label, value)
        self.overlay_position.setCurrentIndex(max(0, self.overlay_position.findData(config.overlay_position)))
        self.overlay_offset_x = QSpinBox()
        self.overlay_offset_x.setRange(-1000, 1000)
        self.overlay_offset_x.setSuffix(" px")
        self.overlay_offset_x.setValue(config.overlay_offset_x)
        self.overlay_offset_y = QSpinBox()
        self.overlay_offset_y.setRange(-1000, 1000)
        self.overlay_offset_y.setSuffix(" px")
        self.overlay_offset_y.setValue(config.overlay_offset_y)
        self.overlay_opacity = QSpinBox()
        self.overlay_opacity.setRange(20, 100)
        self.overlay_opacity.setSuffix(" %")
        self.overlay_opacity.setValue(config.overlay_opacity)
        background_row, self.overlay_background_color = self._color_editor(config.overlay_background_color)
        text_row, self.overlay_text_color = self._color_editor(config.overlay_text_color)
        provisional_row, self.overlay_provisional_color = self._color_editor(config.overlay_provisional_color)
        form.addRow("Удерживаемая клавиша:", self.hotkey)
        form.addRow("Модель Whisper:", self.model)
        form.addRow("Текущий активный режим:", QLabel(self._device_label(active_execution_device or config.execution_device)))
        form.addRow("Устройство распознавания:", self.execution_device)
        form.addRow("Освобождать модель после простоя:", self.model_idle_unload_minutes)
        form.addRow("Язык:", self.language)
        form.addRow("Микрофон:", self.microphone)
        form.addRow("История (записей):", self.history_limit)
        form.addRow("Максимальная ширина окна:", self.overlay_max_width)
        form.addRow("Максимальная высота окна:", self.overlay_max_height)
        form.addRow("Положение окна:", self.overlay_position)
        form.addRow("Смещение по X:", self.overlay_offset_x)
        form.addRow("Смещение по Y:", self.overlay_offset_y)
        form.addRow("Цвет подложки:", background_row)
        form.addRow("Цвет текста:", text_row)
        form.addRow("Цвет предварительного текста:", provisional_row)
        form.addRow("Непрозрачность подложки:", self.overlay_opacity)
        layout.addLayout(form)
        layout.addWidget(self.auto_paste)
        layout.addWidget(self.keep_recordings)
        layout.addWidget(self.live_preview)
        layout.addWidget(self.unload_model_immediately)
        note = QLabel("Модель загружается единожды при первом распознавании. Данные не отправляются в облако.")
        note.setWordWrap(True)
        layout.addWidget(note)
        logs_button = QPushButton("Открыть папку логов")
        logs_button.setEnabled(on_open_logs is not None)
        if on_open_logs is not None:
            logs_button.clicked.connect(on_open_logs)
        layout.addWidget(logs_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _device_label(device: str) -> str:
        return "GPU NVIDIA" if device == "cuda" else "CPU"

    def _color_editor(self, initial: str) -> tuple[QWidget, QLineEdit]:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        field = QLineEdit(initial)
        field.setMaxLength(7)
        button = QPushButton("Выбрать…")

        def update_preview(value: str) -> None:
            color = QColor(value)
            if color.isValid():
                button.setStyleSheet(
                    f"background:{color.name()}; color:{'#111111' if color.lightness() > 150 else '#FFFFFF'}"
                )

        def choose_color() -> None:
            color = QColorDialog.getColor(QColor(field.text()), self, "Выберите цвет")
            if color.isValid():
                field.setText(color.name().upper())

        field.textChanged.connect(update_preview)
        button.clicked.connect(choose_color)
        update_preview(initial)
        row.addWidget(field)
        row.addWidget(button)
        return container, field

    def result_config(self) -> AppConfig:
        return AppConfig(
            hotkey=self.hotkey.text().strip().lower(), model=self.model.currentData(),
            execution_device=self.execution_device.currentData(),
            language=self.language.currentData() or None, microphone=self.microphone.currentData(),
            auto_paste=self.auto_paste.isChecked(), keep_recordings=self.keep_recordings.isChecked(),
            history_limit=self.history_limit.value(), sample_rate=self.original_config.sample_rate,
            live_preview_enabled=self.live_preview.isChecked(),
            overlay_max_width=self.overlay_max_width.value(),
            overlay_max_height=self.overlay_max_height.value(),
            overlay_position=self.overlay_position.currentData(),
            overlay_offset_x=self.overlay_offset_x.value(),
            overlay_offset_y=self.overlay_offset_y.value(),
            overlay_background_color=self.overlay_background_color.text().strip().upper(),
            overlay_text_color=self.overlay_text_color.text().strip().upper(),
            overlay_provisional_color=self.overlay_provisional_color.text().strip().upper(),
            overlay_opacity=self.overlay_opacity.value(),
            model_idle_unload_minutes=self.model_idle_unload_minutes.currentData(),
            unload_model_immediately=self.unload_model_immediately.isChecked(),
        )

    def accept(self) -> None:
        try:
            self.result_config().validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте настройки", str(exc))
            return
        super().accept()


class HistoryDialog(QDialog):
    def __init__(self, history: HistoryRepository, parent=None):
        super().__init__(parent)
        self.history = history
        self.setWindowTitle("История диктовки")
        self.resize(760, 460)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Время (UTC)", "Длительность", "Текст"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        copy_button = QPushButton("Копировать")
        clear_button = QPushButton("Очистить историю")
        close_button = QPushButton("Закрыть")
        copy_button.clicked.connect(self.copy_selected)
        clear_button.clicked.connect(self.clear_history)
        close_button.clicked.connect(self.close)
        actions.addWidget(copy_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self) -> None:
        entries = self.history.list_recent()
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(entry.created_at.replace("T", " ").replace("+00:00", "")))
            self.table.setItem(row, 1, QTableWidgetItem(f"{entry.duration_seconds:.1f} с"))
            self.table.setItem(row, 2, QTableWidgetItem(entry.text))
        self.table.resizeColumnsToContents()

    def copy_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            QGuiApplication.clipboard().setText(self.table.item(row, 2).text())

    def clear_history(self) -> None:
        if QMessageBox.question(self, "Очистить историю", "Удалить все тексты из истории?") == QMessageBox.Yes:
            self.history.delete_all()
            self.refresh()


class TrayApplication(QObject):
    def __init__(self, app: QApplication, config_store: ConfigStore, history: HistoryRepository, recordings_dir: Path, logger: logging.Logger):
        super().__init__()
        self.app, self.config_store, self.history, self.recordings_dir, self.logger = app, config_store, history, recordings_dir, logger
        self.config = config_store.load()
        self.events = UiEvents()
        self.events.status.connect(self._show_status)
        self.events.error.connect(self._show_error)
        self.overlay = DictationOverlay(self.config)
        self.events.recording_started.connect(self.overlay.show_recording)
        self.events.live_text.connect(self.overlay.set_live_text)
        self.events.processing_started.connect(self.overlay.show_processing)
        self.events.recording_finished.connect(self.overlay.show_finished)
        self.controller = DictationController(
            self.config,
            history,
            recordings_dir,
            self.events.status.emit,
            self.events.error.emit,
            logger=logger,
            on_recording_started=self.events.recording_started.emit,
            on_live_text=self.events.live_text.emit,
            on_processing_started=self.events.processing_started.emit,
            on_recording_finished=self.events.recording_finished.emit,
        )
        self.config = self.controller.config
        self._active_execution_device = self.controller.config.execution_device
        self.tray = QSystemTrayIcon(application_icon(), self)
        self.tray.setToolTip("Локальная диктовка — готово")
        self.menu = QMenu()
        self.status_action = QAction("Готово: удерживайте Ctrl+Alt", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.runtime_action = QAction(self._runtime_status_text(), self.menu)
        self.runtime_action.setEnabled(False)
        self.menu.addAction(self.runtime_action)
        self.menu.addSeparator()
        self.menu.addAction("Настройки…", self.show_settings)
        self.menu.addAction("История…", self.show_history)
        self.menu.addAction("Открыть папку логов", self.open_logs)
        self.menu.addSeparator()
        self.menu.addAction("Выход", self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.hotkey = self._make_hotkey()

    def start(self) -> bool:
        self.tray.show()
        try:
            self.hotkey.start()
        except RuntimeError as exc:
            self.events.error.emit(str(exc))
            return False
        self._show_status(f"Готово: удерживайте {self.config.hotkey}")
        return True

    def _make_hotkey(self) -> HoldHotkey:
        return HoldHotkey(self.config.hotkey, self.controller.begin, self.controller.finish)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show_settings()

    def _show_status(self, message: str) -> None:
        if "GPU NVIDIA недоступен" in message or "Распознавание: CPU" in message:
            self._set_active_execution_device("cpu")
        elif "Распознавание: GPU NVIDIA" in message:
            self._set_active_execution_device("cuda")
        self.status_action.setText(message)
        self.tray.setToolTip(f"Локальная диктовка — {message}")
        self.tray.showMessage("Локальная диктовка", message, QSystemTrayIcon.Information, 2500)

    def _show_error(self, message: str) -> None:
        self.logger.warning("User-visible error: %s", message)
        self.status_action.setText("Ошибка — откройте настройки или логи")
        self.tray.showMessage("Локальная диктовка", message, QSystemTrayIcon.Critical, 7000)

    def _runtime_status_text(self) -> str:
        label = "GPU NVIDIA" if self._active_execution_device == "cuda" else "CPU"
        return f"Режим распознавания: {label}"

    def _set_active_execution_device(self, device: str) -> None:
        self._active_execution_device = device
        self.runtime_action.setText(self._runtime_status_text())

    def show_settings(self) -> None:
        dialog = SettingsDialog(
            self.config,
            on_open_logs=self.open_logs,
            active_execution_device=self._active_execution_device,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        new_config = dialog.result_config()
        old_hotkey = self.hotkey
        old_hotkey.stop()
        self.config = new_config
        self.controller.update_config(new_config)
        self._set_active_execution_device(new_config.execution_device)
        self.hotkey = self._make_hotkey()
        try:
            self.hotkey.start()
            self.config_store.save(new_config)
            self.history.trim_to_limit(new_config.history_limit)
            self.overlay.apply_config(new_config)
            self._show_status(f"Настройки сохранены: {new_config.hotkey}")
        except RuntimeError as exc:
            self.hotkey.stop()
            self.config = self.config_store.load()
            self.controller.update_config(self.config)
            self.overlay.apply_config(self.config)
            self.hotkey = self._make_hotkey()
            try:
                self.hotkey.start()
            except RuntimeError:
                pass
            self._show_error(f"Настройки не сохранены: {exc}")

    def show_history(self) -> None:
        HistoryDialog(self.history).exec()

    def open_logs(self) -> None:
        import os
        try:
            os.startfile(str(self.recordings_dir.parent / "logs"))
        except OSError as exc:
            self._show_error(f"Не удалось открыть журналы: {exc}")

    def quit(self) -> None:
        self.hotkey.stop()
        self.controller.shutdown()
        self.overlay.hide()
        self.tray.hide()
        self.app.quit()
