#!/usr/bin/env python3
"""Run both live acceptances against the exact Chrome and companion ZIP pair."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def release_zip(explicit: Path | None, kind: str) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    return ROOT / "dist" / f"hermes-connector-{manifest['version']}-{kind}.zip"


def extract_exact(archive_path: Path, destination: Path) -> None:
    if not archive_path.is_file():
        raise RuntimeError(f"packaged release ZIP does not exist: {archive_path}")
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"unsafe archive member: {info.filename}")
            unix_type = (info.external_attr >> 16) & 0o170000
            if unix_type == 0o120000:
                raise RuntimeError(f"symbolic links are forbidden: {info.filename}")
        archive.extractall(destination)


def assert_matching_pair(extension: Path, companion: Path) -> str:
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    plugin_yaml = (companion / "plugin.yaml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^version:\s*([^\s]+)\s*$", plugin_yaml)
    if not match or match.group(1) != manifest.get("version"):
        raise RuntimeError("packaged Chrome and companion versions differ")
    return str(manifest["version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test the exact packaged Chrome and companion ZIPs")
    parser.add_argument("--chrome-zip", type=Path)
    parser.add_argument("--companion-zip", type=Path)
    args = parser.parse_args(argv)
    chrome_archive = release_zip(args.chrome_zip, "chrome")
    companion_archive = release_zip(args.companion_zip, "companion")
    with tempfile.TemporaryDirectory(prefix="hermes-connector-packaged-") as temp:
        extracted = Path(temp) / "extension"
        companion_root = Path(temp) / "companion"
        extracted.mkdir()
        companion_root.mkdir()
        extract_exact(chrome_archive, extracted)
        extract_exact(companion_archive, companion_root)
        companion = companion_root / "hermes-connector"
        version = assert_matching_pair(extracted, companion)
        env = os.environ.copy()
        env["HERMES_EXTENSION_DIR"] = str(extracted)
        env["HERMES_PLUGIN_DIR"] = str(companion)
        for test_script in ("e2e_chromium.py", "e2e_multi_browser.py"):
            subprocess.run(
                [sys.executable, str(ROOT / "tests" / test_script)],
                cwd=ROOT,
                env=env,
                check=True,
            )
    print(
        f"Packaged release pair acceptance passed: {version} "
        f"({chrome_archive.name} + {companion_archive.name})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
