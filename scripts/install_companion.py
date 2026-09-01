#!/usr/bin/env python3
"""Install the Hermes Connector companion into a user's Hermes home."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time


PLUGIN_NAME = "hermes-connector"
LEGACY_PLUGIN_NAME = "agent-bridge"
LEGACY_PLUGIN_VERSION = "0.1.0"
LEGACY_DESCRIPTION_PREFIX = "Drive a paired Chrome extension from the agent:"
INSTALL_LOCK_NAME = ".hermes-connector-install.lock"
PLUGIN_FILES = (
    "__init__.py",
    "after-install.md",
    "bridge_client.py",
    "broker.py",
    "plugin.yaml",
    "README.md",
)


def is_reparse_path(path: Path) -> bool:
    """Detect symlinks and Windows junction/reparse points on Python 3.10+."""

    try:
        if path.is_symlink():
            return True
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_flag)
    except OSError:
        return False


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


def installation_homes(hermes_root: Path) -> list[Path]:
    """Return the shared home and every existing named Hermes profile.

    Hermes profiles have independent plugin payloads and activation lists. A
    root-only install looks successful but leaves profile sessions without the
    Connector tools, so the companion must be copied and enabled in both
    scopes. Re-running the installer picks up profiles created later.
    """

    root = normalize_hermes_home(hermes_root)
    homes = [root]
    profiles = root / "profiles"
    if is_reparse_path(profiles):
        raise RuntimeError("unsafe Hermes profiles directory")
    if not profiles.is_dir():
        return homes
    for child in sorted(profiles.iterdir(), key=lambda item: item.name.casefold()):
        if is_reparse_path(child) or not child.is_dir() or not (child / "config.yaml").is_file():
            continue
        resolved = child.resolve()
        if resolved.parent == profiles.resolve():
            homes.append(resolved)
    return homes


@contextmanager
def installation_lock(hermes_root: Path):
    """Prevent concurrent installers from interleaving payload/config rollback."""

    root = normalize_hermes_home(hermes_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / INSTALL_LOCK_NAME
    if is_reparse_path(lock_path):
        raise RuntimeError("unsafe Hermes Connector install lock")
    open_flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    try:
        file_descriptor = os.open(lock_path, open_flags, 0o600)
    except OSError as exc:
        raise RuntimeError("could not safely open the Hermes Connector install lock") from exc
    locked = False
    try:
        opened = os.fstat(file_descriptor)
        lexical = os.stat(lock_path, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(lexical.st_mode) or
                opened.st_nlink != 1 or
                (opened.st_ino and lexical.st_ino and opened.st_ino != lexical.st_ino)):
            raise RuntimeError("unsafe Hermes Connector install lock")
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(file_descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise RuntimeError(
                "another Hermes Connector installer is already running"
            ) from None
        yield
    finally:
        if locked:
            try:
                os.lseek(file_descriptor, 0, os.SEEK_SET)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(file_descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(file_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(file_descriptor)
        except OSError:
            pass


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


def verify_installed_payload(source: Path, target: Path) -> None:
    """Prove that the published target is the exact bundled companion payload."""

    expected = set(PLUGIN_FILES)
    actual = {path.name for path in target.iterdir() if path.is_file()}
    if actual != expected:
        raise RuntimeError(
            f"installed companion file set differs from source: expected={sorted(expected)}, actual={sorted(actual)}"
        )
    for name in PLUGIN_FILES:
        if (target / name).read_bytes() != (source / name).read_bytes():
            raise RuntimeError(f"installed companion verification failed for {name}")


def install(source: Path, hermes_home: Path) -> tuple[Path, Path | None]:
    source = source.resolve()
    hermes_home = hermes_home.expanduser().resolve()
    validate_source(source)
    plugins = hermes_home / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    if is_reparse_path(plugins):
        raise RuntimeError("unsafe Hermes plugins directory")
    plugins = plugins.resolve()
    target = plugins / PLUGIN_NAME
    if is_reparse_path(target) or (target.exists() and not target.is_dir()):
        raise RuntimeError("unsafe Hermes plugin target")
    if target.parent != plugins:
        raise RuntimeError("unsafe Hermes plugin target")

    stage = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_NAME}-install-", dir=plugins))
    previous = None
    failed_target = None
    publish_started = False
    try:
        for name in PLUGIN_FILES:
            shutil.copy2(source / name, stage / name)
        if target.exists():
            suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
            previous = plugins / f".{PLUGIN_NAME}-previous-{suffix}"
            os.replace(target, previous)
        publish_started = True
        os.replace(stage, target)
        verify_installed_payload(source, target)
    except BaseException:
        # A KeyboardInterrupt can arrive after an atomic OS move completed but
        # before os.replace returned to Python. Infer that state from the paths
        # and restore the exact pre-install payload (or pre-install absence).
        target_present = target.exists() or is_reparse_path(target)
        if previous is not None and previous.exists():
            if target_present:
                failed_target = plugins / f".{PLUGIN_NAME}-rollback-{secrets.token_hex(3)}"
                os.replace(target, failed_target)
            os.replace(previous, target)
        elif publish_started and not stage.exists() and target_present:
            failed_target = plugins / f".{PLUGIN_NAME}-rollback-{secrets.token_hex(3)}"
            os.replace(target, failed_target)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if failed_target is not None and failed_target.exists():
            shutil.rmtree(failed_target, ignore_errors=True)
    return target, previous


def rollback_install(target: Path, previous: Path | None) -> None:
    """Restore the payload that existed before ``install`` was called."""

    target = target.expanduser().absolute()
    plugins = target.parent
    if target.name != PLUGIN_NAME or plugins.name != "plugins":
        raise RuntimeError("unsafe Hermes plugin rollback target")
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    if previous is not None and previous.exists():
        if previous.parent.resolve() != plugins.resolve() or not previous.name.startswith(
            f".{PLUGIN_NAME}-previous-"
        ):
            raise RuntimeError("unsafe previous companion rollback target")
        os.replace(previous, target)


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


def restore_config(config_path: Path, content: bytes | None, mode: int | None) -> None:
    """Atomically restore the exact pre-migration Hermes plugin config."""

    if content is None:
        try:
            config_path.unlink()
        except FileNotFoundError:
            pass
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, stage_name = tempfile.mkstemp(
        prefix=".config-restore-", dir=config_path.parent
    )
    stage = Path(stage_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
        if mode is not None:
            os.chmod(stage, mode)
        os.replace(stage, config_path)
    finally:
        try:
            stage.unlink()
        except FileNotFoundError:
            pass


def config_snapshot(hermes_home: Path) -> tuple[Path, bytes | None, int | None]:
    config_path = hermes_home.expanduser().resolve() / "config.yaml"
    if is_reparse_path(config_path):
        raise RuntimeError("unsafe Hermes config target")
    if not config_path.is_file():
        return config_path, None, None
    return config_path, config_path.read_bytes(), config_path.stat().st_mode


def known_legacy_bridge(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    description = " ".join(str(item.get("description") or "").split())
    return (
        item.get("name") == LEGACY_PLUGIN_NAME
        and item.get("status") == "enabled"
        and str(item.get("version") or "") == LEGACY_PLUGIN_VERSION
        and description.startswith(LEGACY_DESCRIPTION_PREFIX)
    )


def enable_plugin(hermes_home: Path) -> None:
    executable = find_hermes()
    if not executable:
        raise RuntimeError("Hermes CLI was not found; restart Hermes installation, then run this installer again")
    hermes_home = hermes_home.expanduser().resolve()
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    config_path, config_content, config_mode = config_snapshot(hermes_home)
    try:
        listed = subprocess.run(
            [executable, "plugins", "list", "--json", "--no-bundled"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            plugins = json.loads(listed.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Hermes returned an invalid plugin inventory") from exc
        named_collisions = [
            item for item in plugins
            if isinstance(item, dict)
            and item.get("name") == LEGACY_PLUGIN_NAME
            and item.get("status") == "enabled"
        ]
        legacy_enabled = bool(named_collisions) and all(
            known_legacy_bridge(item) for item in named_collisions
        )
        if named_collisions and not legacy_enabled:
            raise RuntimeError(
                "an unrelated enabled plugin is named agent-bridge; no plugin state was changed"
            )
        if legacy_enabled:
            subprocess.run(
                [executable, "plugins", "disable", LEGACY_PLUGIN_NAME],
                env=env,
                check=True,
            )
        subprocess.run(
            [executable, "plugins", "enable", PLUGIN_NAME, "--no-allow-tool-override"],
            env=env,
            check=True,
        )
    except BaseException:
        # The CLI may have persisted a partial disable/enable before failing.
        # Restore the exact bytes so legacy grants and all unrelated settings
        # remain precisely as they were before migration.
        restore_config(config_path, config_content, config_mode)
        raise


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

    root = normalize_hermes_home(args.hermes_home or default_hermes_home())
    source = (args.source or bundled_source()).expanduser().resolve()
    installed = []
    code = None
    with installation_lock(root):
        homes = installation_homes(root)
        snapshots = {home: config_snapshot(home) for home in homes}
        try:
            for home in homes:
                target, previous = install(source, home)
                installed.append((home, target, previous))
            if not args.no_enable:
                for home, _, _ in installed:
                    enable_plugin(home)
            if not args.no_show_code:
                root_target = next(target for home, target, _ in installed if home == root)
                code = pairing_code(root_target, root)
        except BaseException:
            # Installation is one transaction across the shared home and every
            # discovered profile. Do not leave users with a silent half-migration.
            for config_path, content, mode in snapshots.values():
                try:
                    restore_config(config_path, content, mode)
                except BaseException as rollback_error:
                    print(f"Warning: could not restore {config_path}: {rollback_error}", file=sys.stderr)
            for _, target, previous in reversed(installed):
                try:
                    rollback_install(target, previous)
                except BaseException as rollback_error:
                    print(f"Warning: could not restore {target}: {rollback_error}", file=sys.stderr)
            raise

    for home, target, previous in installed:
        scope = "shared Hermes home" if home == root else f"profile {home.name}"
        print(f"Installed Hermes Connector companion for {scope} at {target}")
        if previous is not None:
            print(f"Previous companion preserved at {previous}")
    print(f"Migrated enabled {LEGACY_PLUGIN_NAME} profiles to {PLUGIN_NAME} where necessary.")
    if code is not None:
        print("\nPairing code (keep private; paste once into the Chrome extension):")
        print(code)
    print("\nFully quit and reopen Hermes Desktop, or restart running Hermes dashboard, gateway, and chat processes.")
    print("Re-run this installer after creating a new Hermes profile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
