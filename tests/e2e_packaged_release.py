#!/usr/bin/env python3
"""Run both live Chrome acceptances against the exact packaged extension ZIP."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def release_zip(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    return ROOT / "dist" / f"hermes-connector-{manifest['version']}-chrome.zip"


def extract_exact(archive_path: Path, destination: Path) -> None:
    if not archive_path.is_file():
        raise RuntimeError(f"packaged Chrome ZIP does not exist: {archive_path}")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test the exact packaged Chrome extension")
    parser.add_argument("--chrome-zip", type=Path)
    args = parser.parse_args(argv)
    archive_path = release_zip(args.chrome_zip)
    with tempfile.TemporaryDirectory(prefix="hermes-connector-packaged-") as temp:
        extracted = Path(temp) / "extension"
        extracted.mkdir()
        extract_exact(archive_path, extracted)
        env = os.environ.copy()
        env["HERMES_EXTENSION_DIR"] = str(extracted)
        for test_script in ("e2e_chromium.py", "e2e_multi_browser.py"):
            subprocess.run(
                [sys.executable, str(ROOT / "tests" / test_script)],
                cwd=ROOT,
                env=env,
                check=True,
            )
    print(f"Packaged Chrome acceptance passed: {archive_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
