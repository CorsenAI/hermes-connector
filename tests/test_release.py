"""Release archives are allowlisted and byte-reproducible."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hermes_connector_release_test", ROOT / "scripts" / "build_release.py"
)
release = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(release)


class ReleaseArchiveTests(unittest.TestCase):
    def test_archives_are_exact_and_reproducible(self):
        with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
            first = release.build(Path(first_temp), allow_dirty=True, run_tests=False)
            second = release.build(Path(second_temp), allow_dirty=True, run_tests=False)
            first_artifacts = {item["file"]: item for item in first["artifacts"]}
            second_artifacts = {item["file"]: item for item in second["artifacts"]}
            first_output = Path(first["releaseFile"]).parent
            second_output = Path(second["releaseFile"]).parent
            self.assertEqual(
                {name: item["sha256"] for name, item in first_artifacts.items()},
                {name: item["sha256"] for name, item in second_artifacts.items()},
            )

            chrome_name = next(name for name in first_artifacts if name.endswith("-chrome.zip"))
            companion_name = next(name for name in first_artifacts if name.endswith("-companion.zip"))
            with zipfile.ZipFile(first_output / chrome_name) as archive:
                self.assertEqual(set(archive.namelist()), set(release.EXTENSION_FILES))
                self.assertIn("manifest.json", archive.namelist())
            with zipfile.ZipFile(first_output / companion_name) as archive:
                expected = {
                    "Install Hermes Connector.cmd", "install.py", "install.ps1", "install.sh",
                    "LICENSE", "README.md",
                }
                expected.update(f"hermes-connector/{name}" for name in release.COMPANION_FILES)
                self.assertEqual(set(archive.namelist()), expected)
                install_mode = archive.getinfo("install.sh")
                self.assertEqual(install_mode.create_system, 3)
                self.assertEqual((install_mode.external_attr >> 16) & 0o777, 0o755)

            if first["sourceDirty"]:
                self.assertEqual(first_output, Path(first_temp) / "dev")
                self.assertEqual(second_output, Path(second_temp) / "dev")
                self.assertFalse((Path(first_temp) / chrome_name).exists())


if __name__ == "__main__":
    unittest.main()
