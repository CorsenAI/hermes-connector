"""Companion installation and local pairing-code tests."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hermes_connector_installer_test", ROOT / "scripts" / "install_companion.py"
)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(installer)


class CompanionInstallerTests(unittest.TestCase):
    def test_profile_home_normalizes_to_shared_hermes_root(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profiles" / "work"
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(profile)}):
                self.assertEqual(installer.default_hermes_home(), Path(temp).resolve())
            self.assertEqual(installer.normalize_hermes_home(profile), Path(temp).resolve())

    def test_install_is_atomic_and_preserves_previous_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            target, previous = installer.install(ROOT / "hermes-plugin", home)
            self.assertIsNone(previous)
            self.assertEqual(
                {path.name for path in target.iterdir() if path.is_file()},
                set(installer.PLUGIN_FILES),
            )
            marker = target / "local-note.txt"
            marker.write_text("preserve me", encoding="utf-8")

            target2, previous2 = installer.install(ROOT / "hermes-plugin", home)
            self.assertEqual(target2, target)
            self.assertIsNotNone(previous2)
            self.assertEqual((previous2 / "local-note.txt").read_text(encoding="utf-8"), "preserve me")
            self.assertFalse((target2 / "local-note.txt").exists())

    def test_pairing_code_is_persistent_and_not_in_bridge_status(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            target, _ = installer.install(ROOT / "hermes-plugin", home)
            first = installer.pairing_code(target, home)
            second = installer.pairing_code(target, home)
            self.assertEqual(first, second)
            self.assertRegex(first, re.compile(r"^[0-9a-f]{64}$"))
            client_source = (target / "bridge_client.py").read_text(encoding="utf-8")
            self.assertNotIn('"pairing_code": self.secret', client_source)


if __name__ == "__main__":
    unittest.main()
