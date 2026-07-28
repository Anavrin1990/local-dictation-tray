from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox,
    QStyle, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .audio import MicrophoneRecorder
from .config import AppConfig, ConfigStore
from .controller import DictationController
from .history import HistoryRepository
from .hotkey import HoldHotkey


class UiEvents(QObject):
    status = Signal(str)
    error = Signal(str)


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки локальной диктовки")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.hotkey = QLineEdit(config.hotkey)
        self.hotkey.setPlaceholderText("Например: ctrl+alt+space")
        self.model = QComboBox()
        # The installer bundles this model, so the application remains offline after installation.
        self.model.addItem("base (встроенная, локальная)", "base")
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
        form.addRow("Удерживаемая клавиша:", self.hotkey)
        form.addRow("Модель Whisper:", self.model)
        form.addRow("Язык:", self.language)
        form.addRow("Микрофон:", self.microphone)
        form.addRow("История (записей):", self.history_limit)
        layout.addLayout(form)
        layout.addWidget(self.auto_paste)
        layout.addWidget(self.keep_recordings)
        note = QLabel("Модель загружается единожды при первом распознавании. Данные не отправляются в облако.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_config(self) -> AppConfig:
        return AppConfig(
            hotkey=self.hotkey.text().strip().lower(), model=self.model.currentData(),
            language=self.language.currentData() or None, microphone=self.microphone.currentData(),
            auto_paste=self.auto_paste.isChecked(), keep_recordings=self.keep_recordings.isChecked(),
            history_limit=self.history_limit.value(),
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
        self.controller = DictationController(
            self.config, history, recordings_dir, self.events.status.emit, self.events.error.emit, logger=logger
        )
        self.tray = QSystemTrayIcon(app.style().standardIcon(QStyle.SP_MediaVolume), self)
        self.tray.setToolTip("Локальная диктовка — готово")
        self.menu = QMenu()
        self.status_action = QAction("Готово: удерживайте Ctrl+Alt+Space", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
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
        self.status_action.setText(message)
        self.tray.setToolTip(f"Локальная диктовка — {message}")
        self.tray.showMessage("Локальная диктовка", message, QSystemTrayIcon.Information, 2500)

    def _show_error(self, message: str) -> None:
        self.logger.warning("User-visible error: %s", message)
        self.status_action.setText("Ошибка — откройте настройки или логи")
        self.tray.showMessage("Локальная диктовка", message, QSystemTrayIcon.Critical, 7000)

    def show_settings(self) -> None:
        dialog = SettingsDialog(self.config)
        if dialog.exec() != QDialog.Accepted:
            return
        new_config = dialog.result_config()
        old_hotkey = self.hotkey
        old_hotkey.stop()
        self.config = new_config
        self.controller.update_config(new_config)
        self.hotkey = self._make_hotkey()
        try:
            self.hotkey.start()
            self.config_store.save(new_config)
            self._show_status(f"Настройки сохранены: {new_config.hotkey}")
        except RuntimeError as exc:
            self.hotkey.stop()
            self.config = self.config_store.load()
            self.controller.update_config(self.config)
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
        self.tray.hide()
        self.app.quit()
