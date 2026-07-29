from __future__ import annotations

import re
import unittest
from pathlib import Path

from dictation_tray import __version__


ROOT = Path(__file__).resolve().parents[1]


class VersionContractTests(unittest.TestCase):
    def test_application_packaging_and_build_defaults_match(self) -> None:
        installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "build-installer.ps1").read_text(encoding="utf-8")
        installer_version = re.search(r'#define AppVersion "([^"]+)"', installer)
        build_version = re.search(r'\[string\]\$Version = "([^"]+)"', build)
        self.assertIsNotNone(installer_version)
        self.assertIsNotNone(build_version)
        self.assertEqual(installer_version.group(1), __version__)
        self.assertEqual(build_version.group(1), __version__)


if __name__ == "__main__":
    unittest.main()
