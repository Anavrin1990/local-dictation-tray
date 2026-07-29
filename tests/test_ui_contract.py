from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TrayUiContractTests(unittest.TestCase):
    """Dependency-free guardrails for tray lifecycle and the user-visible menu."""

    def test_modules_are_valid_python(self) -> None:
        for relative in ("dictation_tray/main.py", "dictation_tray/qt_app.py"):
            ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)

    def test_tray_process_does_not_quit_when_a_dialog_is_closed(self) -> None:
        main_source = (ROOT / "dictation_tray/main.py").read_text(encoding="utf-8")
        self.assertIn(
            "app.setQuitOnLastWindowClosed(False)",
            main_source,
            "QSystemTrayIcon is not a window; closing Settings must not stop dictation.",
        )

    def test_menu_exposes_history_logs_and_a_clean_exit(self) -> None:
        source = (ROOT / "dictation_tray/qt_app.py").read_text(encoding="utf-8")
        for method in ("show_history", "open_logs", "quit"):
            self.assertIn(f"self.menu.addAction(", source)
            self.assertIn(f"self.{method}", source)
        self.assertIn("self.hotkey.stop()", source)
        self.assertIn("self.controller.shutdown()", source)

    def test_custom_microphone_icon_is_used_by_app_and_packaging(self) -> None:
        source = (ROOT / "dictation_tray" / "qt_app.py").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "build-installer.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        self.assertIn('assets" / "tray-icon.ico"', source)
        self.assertIn('"--icon", $iconPath', build)
        self.assertIn("SetupIconFile={#IconFile}", installer)
        self.assertTrue((ROOT / "assets" / "tray-icon.ico").is_file())

    def test_installer_enables_startup_by_default(self) -> None:
        installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        startup_line = next(line for line in installer.splitlines() if 'Name: "startup"' in line)
        self.assertIn("checkedonce", startup_line)
        self.assertNotIn("unchecked", startup_line)

    def test_overlay_is_click_through_and_exposes_visual_settings(self) -> None:
        source = (ROOT / "dictation_tray" / "qt_app.py").read_text(encoding="utf-8")
        config = (ROOT / "dictation_tray" / "config.py").read_text(encoding="utf-8")
        self.assertIn("class DictationOverlay", source)
        self.assertIn("WA_TransparentForMouseEvents", source)
        self.assertIn("WindowDoesNotAcceptFocus", source)
        for setting in (
            "overlay_max_width",
            "overlay_max_height",
            "overlay_position",
            "overlay_background_color",
            "overlay_text_color",
            "overlay_provisional_color",
            "overlay_opacity",
        ):
            self.assertIn(setting, config)
            self.assertIn(setting, source)

    def test_packaging_self_check_contract_is_implemented_by_entrypoint(self) -> None:
        package_test = (ROOT / "scripts" / "test-package.ps1").read_text(encoding="utf-8")
        entrypoint = (ROOT / "dictation_tray" / "main.py").read_text(encoding="utf-8")
        self.assertIn("--self-check", package_test)
        self.assertIn(
            "--self-check",
            entrypoint,
            "The installer build invokes this flag; it must validate without opening a tray UI.",
        )


if __name__ == "__main__":
    unittest.main()
