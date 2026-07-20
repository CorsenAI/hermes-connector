#!/usr/bin/env python3
"""Install the Hermes Connector companion into a user's Hermes home."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time


PLUGIN_NAME = "hermes-connector"
PLUGIN_FILES = (
    "__init__.py",
    "after-install.md",
    "bridge_client.py",
    "broker.py",
    "plugin.yaml",
    "README.md",
)


def normalize_hermes_home(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.parent.name == "profiles":
        resolved = resolved.parent.parent
    return resolved


def default_hermes_home() -> Path:
    raw = os.environ.get("HERMES_HOME")
    if raw:
        path = Path(raw)
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"
    else:
        path = Path.home() / ".hermes"
    return normalize_hermes_home(path)


def bundled_source() -> Path:
    script_dir = Path(__file__).resolve().parent
    packaged = script_dir / PLUGIN_NAME
    if packaged.is_dir():
        return packaged
    repository = script_dir.parent / "hermes-plugin"
    if repository.is_dir():
        return repository
    raise RuntimeError("the companion payload is missing")


def validate_source(source: Path) -> None:
    source = source.resolve()
    missing = [name for name in PLUGIN_FILES if not (source / name).is_file()]
    if missing:
        raise RuntimeError("incomplete companion payload: " + ", ".join(missing))
    for path in source.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"symbolic links are not allowed in the companion payload: {path.name}")


def install(source: Path, hermes_home: Path) -> tuple[Path, Path | None]:
    source = source.resolve()
    hermes_home = hermes_home.expanduser().resolve()
    validate_source(source)
    plugins = hermes_home / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    target = (plugins / PLUGIN_NAME).resolve()
    if target.parent != plugins.resolve():
        raise RuntimeError("unsafe Hermes plugin target")

    stage = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_NAME}-install-", dir=plugins))
    previous = None
    try:
        for name in PLUGIN_FILES:
            shutil.copy2(source / name, stage / name)
        if target.exists():
            suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
            previous = plugins / f".{PLUGIN_NAME}-previous-{suffix}"
            os.replace(target, previous)
        try:
            os.replace(stage, target)
        except Exception:
            if previous is not None and previous.exists() and not target.exists():
                os.replace(previous, target)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
    return target, previous


def find_hermes() -> str | None:
    found = shutil.which("hermes")
    if found:
        return found
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        candidate = local / "hermes" / "hermes-agent" / "venv" / "Scripts" / "hermes.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def enable_plugin(hermes_home: Path) -> None:
    executable = find_hermes()
    if not executable:
        raise RuntimeError("Hermes CLI was not found; run `hermes plugins enable hermes-connector` later")
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    subprocess.run(
        [executable, "plugins", "enable", PLUGIN_NAME, "--no-allow-tool-override"],
        env=env,
        check=True,
    )


def pairing_code(target: Path, hermes_home: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(target / "broker.py"), "--show-code", "--root", str(hermes_home)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the Hermes Connector companion")
    parser.add_argument("--hermes-home", type=Path, default=None, help="override the Hermes home")
    parser.add_argument("--source", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-enable", action="store_true", help="copy without enabling the plugin")
    parser.add_argument("--no-show-code", action="store_true", help="do not print the pairing code")
    args = parser.parse_args(argv)

    home = normalize_hermes_home(args.hermes_home or default_hermes_home())
    source = (args.source or bundled_source()).expanduser().resolve()
    target, previous = install(source, home)
    if not args.no_enable:
        enable_plugin(home)

    print(f"Installed Hermes Connector companion at {target}")
    if previous is not None:
        print(f"Previous companion preserved at {previous}")
    if not args.no_show_code:
        print("\nPairing code (keep private; paste once into the Chrome extension):")
        print(pairing_code(target, home))
    print("\nRestart running Hermes dashboard, gateway, and chat processes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
