#!/usr/bin/env python3
"""Build deterministic Chrome Store and companion release archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_FILES = (
    "manifest.json",
    "assets/icon-16.png",
    "assets/icon-48.png",
    "assets/icon-128.png",
    "src/background.js",
    "src/bindings.js",
    "src/cdp.js",
    "src/dashboard-api.js",
    "src/page-actions.js",
    "src/protocol.js",
    "src/sidepanel.html",
    "src/sidepanel.js",
)
COMPANION_FILES = (
    "__init__.py",
    "after-install.md",
    "bridge_client.py",
    "broker.py",
    "plugin.yaml",
    "README.md",
)
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def local_identity_patterns() -> tuple[re.Pattern[str], ...]:
    """Detect the current machine identity without publishing it in source."""
    identities = {
        os.environ.get("USERNAME", "").strip(),
        Path.home().name.strip(),
    }
    return tuple(
        re.compile(rf"\b{re.escape(identity)}\b", re.IGNORECASE)
        for identity in identities
        if len(identity) >= 4
    )


LEAK_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/Users/[^/\s]+/"),
    re.compile(r"@gmail\.", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_.-]{24,}", re.IGNORECASE),
) + local_identity_patterns()


def command(*parts: str) -> str:
    return subprocess.check_output(parts, cwd=ROOT, text=True).strip()


def git_state() -> tuple[str, bool]:
    try:
        commit = command("git", "rev-parse", "HEAD")
        dirty = bool(command("git", "status", "--porcelain", "--untracked-files=all"))
        return commit, dirty
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable", True


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_zip(path: Path, entries: dict[str, Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for archive_name in sorted(entries):
            source = entries[archive_name]
            if not source.is_file() or source.is_symlink():
                raise RuntimeError(f"invalid release input: {source}")
            info = zipfile.ZipInfo(archive_name, FIXED_TIME)
            info.create_system = 3  # Unix attributes; keeps install.sh executable after extraction.
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o100755 if source.suffix in {".py", ".sh"} else 0o100644
            info.external_attr = mode << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def validate_no_leaks(entries: dict[str, Path]) -> None:
    for archive_name, source in entries.items():
        if source.suffix.lower() not in {".html", ".js", ".json", ".md", ".ps1", ".py", ".sh", ".yaml"}:
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        for pattern in LEAK_PATTERNS:
            if pattern.search(text):
                raise RuntimeError(f"release leakage gate failed: {archive_name} matches {pattern.pattern}")


def exact_source_files(directory: Path) -> set[str]:
    return {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }


def validate_inputs() -> tuple[str, int]:
    extension = ROOT / "extension"
    actual_extension = exact_source_files(extension)
    expected_extension = set(EXTENSION_FILES)
    if actual_extension != expected_extension:
        extra = sorted(actual_extension - expected_extension)
        missing = sorted(expected_extension - actual_extension)
        raise RuntimeError(f"extension allowlist mismatch; extra={extra}, missing={missing}")

    plugin = ROOT / "hermes-plugin"
    missing_plugin = [name for name in COMPANION_FILES if not (plugin / name).is_file()]
    if missing_plugin:
        raise RuntimeError("companion payload is incomplete: " + ", ".join(missing_plugin))

    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "")
    plugin_yaml = (plugin / "plugin.yaml").read_text(encoding="utf-8")
    plugin_version = re.search(r"^version:\s*([^\s]+)", plugin_yaml, re.MULTILINE)
    protocol_js = (extension / "src" / "protocol.js").read_text(encoding="utf-8")
    protocol = re.search(r"PROTOCOL_VERSION\s*=\s*(\d+)", protocol_js)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("manifest version must use x.y.z")
    if not plugin_version or plugin_version.group(1) != version:
        raise RuntimeError("extension and companion versions differ")
    if not protocol:
        raise RuntimeError("protocol version is missing")
    return version, int(protocol.group(1))


def build(output: Path, *, allow_dirty: bool, run_tests: bool) -> dict:
    version, protocol = validate_inputs()
    commit, dirty = git_state()
    if dirty and not allow_dirty:
        raise RuntimeError("refusing to package a dirty worktree (commit first or pass --allow-dirty)")
    if run_tests:
        subprocess.run([sys.executable, str(ROOT / "tests" / "run_all.py")], cwd=ROOT, check=True)

    extension_zip = output / f"hermes-connector-{version}-chrome.zip"
    companion_zip = output / f"hermes-connector-{version}-companion.zip"
    extension_entries = {
        name: ROOT / "extension" / name for name in EXTENSION_FILES
    }
    validate_no_leaks(extension_entries)
    write_zip(extension_zip, extension_entries)

    companion_entries = {
        "install.py": ROOT / "scripts" / "install_companion.py",
        "install.ps1": ROOT / "scripts" / "install.ps1",
        "install.sh": ROOT / "scripts" / "install.sh",
        "LICENSE": ROOT / "LICENSE",
        "README.md": ROOT / "hermes-plugin" / "README.md",
    }
    companion_entries.update({
        f"hermes-connector/{name}": ROOT / "hermes-plugin" / name
        for name in COMPANION_FILES
    })
    validate_no_leaks(companion_entries)
    write_zip(companion_zip, companion_entries)

    result = {
        "version": version,
        "protocol": protocol,
        "sourceCommit": commit,
        "sourceDirty": dirty,
        "artifacts": [
            {"file": extension_zip.name, "bytes": extension_zip.stat().st_size, "sha256": sha256(extension_zip)},
            {"file": companion_zip.name, "bytes": companion_zip.stat().st_size, "sha256": sha256(companion_zip)},
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    release_file = output / f"release-{version}.json"
    release_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    result["releaseFile"] = str(release_file)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Hermes Connector release archives")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)
    result = build(args.output.resolve(), allow_dirty=args.allow_dirty, run_tests=not args.skip_tests)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
