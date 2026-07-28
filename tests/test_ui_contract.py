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
