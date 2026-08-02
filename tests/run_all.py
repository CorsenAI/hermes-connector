"""Fast release gate for source-level Connector invariants.

Live Chrome acceptance is a separate gate; this runner intentionally never
touches the user's installed plugin, broker, dashboard, or Chrome profile.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
PLUGIN = ROOT / "hermes-plugin"


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise SystemExit(f"store gate failed: {path.relative_to(ROOT)} is not a valid PNG")
    return struct.unpack(">II", data[16:24])


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def metadata_gate() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    protocol_source = (EXTENSION / "src" / "protocol.js").read_text(encoding="utf-8")
    plugin_source = (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")

    protocol = re.search(r"PROTOCOL_VERSION\s*=\s*(\d+)", protocol_source)
    plugin_version = re.search(r"^version:\s*([^\s]+)", plugin_source, re.MULTILINE)
    if not protocol or int(protocol.group(1)) != 4:
        raise SystemExit("protocol gate failed: protocol v4 is required")
    if not plugin_version or plugin_version.group(1) != manifest["version"]:
        raise SystemExit("version gate failed: extension and companion versions differ")
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        expected_tag = f"v{manifest['version']}"
        if os.environ.get("GITHUB_REF_NAME") != expected_tag:
            raise SystemExit(
                f"version gate failed: release tag must be {expected_tag}, got {os.environ.get('GITHUB_REF_NAME')}"
            )
    required_permissions = set(manifest.get("permissions") or [])
    expected_permissions = {"storage", "sidePanel", "scripting", "alarms", "debugger"}
    if required_permissions != expected_permissions:
        raise SystemExit(
            f"permission gate failed: expected {sorted(expected_permissions)}, got {sorted(required_permissions)}"
        )
    if manifest.get("optional_permissions"):
        raise SystemExit("permission gate failed: this release has no valid optional permissions")
    if manifest.get("host_permissions") != ["<all_urls>"]:
        raise SystemExit("permission gate failed: the reviewed host permission set changed")

    listing = (ROOT / "store" / "LISTING.md").read_text(encoding="utf-8")
    privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
    if manifest["version"] not in listing:
        raise SystemExit("store gate failed: listing version differs from the manifest")
    for disclosure in ("Website content", "Web history", "Authentication information", "Limited Use"):
        if disclosure not in listing and disclosure not in privacy:
            raise SystemExit(f"store gate failed: missing {disclosure} disclosure")
    expected_artwork = {
        ROOT / "store" / "store-icon-128.png": (128, 128),
        ROOT / "store" / "promo-small-440x280.png": (440, 280),
        ROOT / "store" / "promo-marquee-1400x560.png": (1400, 560),
        ROOT / "store" / "screenshot-product-1280x800.png": (1280, 800),
    }
    for artwork, expected in expected_artwork.items():
        if not artwork.is_file() or png_dimensions(artwork) != expected:
            actual = png_dimensions(artwork) if artwork.is_file() else "missing"
            raise SystemExit(
                f"store gate failed: {artwork.relative_to(ROOT)} expected {expected}, got {actual}"
            )

    runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (EXTENSION, PLUGIN)
        for path in root.rglob("*")
        if path.suffix.lower() in {".js", ".json", ".html", ".py", ".yaml"}
    )
    forbidden = {
        "controlledTabId": "global target-tab lock",
        "select_profile": "non-routing profile selector",
        "bridge_server": "per-profile port server",
        "native messaging": "retired transport",
    }
    for token, label in forbidden.items():
        if token.lower() in runtime.lower():
            raise SystemExit(f"legacy gate failed: {label} remains ({token})")
    if '"pairing_code": self.secret' in runtime:
        raise SystemExit("secret gate failed: pairing code is exposed through a Hermes tool")


def leakage_gate() -> None:
    patterns = [
        r"C:\\Users\\",
        r"@gmail\.",
        r"API_SERVER_KEY",
        r"Authorization\s*:\s*Bearer\s+\S+",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    ]
    local_identities = {
        os.environ.get("USERNAME", "").strip(),
        Path.home().name.strip(),
    }
    local_identities.difference_update({"root", "runner", "runneradmin", "admin", "user"})
    patterns.extend(
        rf"\b{re.escape(identity)}\b"
        for identity in local_identities
        if len(identity) >= 4
    )
    try:
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT
        ).decode("utf-8").split("\0")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit("leakage gate requires a Git worktree") from exc
    text_suffixes = {".cmd", ".css", ".html", ".js", ".json", ".md", ".mjs", ".ps1", ".py", ".sh", ".txt", ".yaml", ".yml"}
    detector_sources = {"scripts/build_release.py", "tests/run_all.py"}
    for relative in tracked:
        if not relative or relative in detector_sources:
            continue
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                raise SystemExit(f"leakage gate failed: {relative} matches {pattern}")


def line_ending_gate() -> None:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    lf_suffixes = {".css", ".html", ".js", ".json", ".md", ".mjs", ".py", ".sh", ".yaml", ".yml"}
    for relative in tracked:
        if not relative:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        if (path.suffix.lower() in lf_suffixes or relative in {".gitattributes", ".gitignore", "LICENSE"}) and b"\r" in data:
            raise SystemExit(f"line-ending gate failed: {relative} must use LF")
        if path.suffix.lower() in {".cmd", ".ps1"}:
            if re.search(br"(?<!\r)\n|\r(?!\n)", data):
                raise SystemExit(f"line-ending gate failed: {relative} must use CRLF")


def main() -> int:
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is required for extension tests")
    # Discover from the repository's tests directory instead of importing the
    # generic top-level package name ``tests``. Some Python installations ship
    # an unrelated package with that name, which could otherwise shadow this
    # release gate or make it fail before running our own test suite.
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
         "-p", "test_*.py", "-v"])
    for source in sorted((EXTENSION / "src").glob("*.js")):
        run([node, "--check", str(source)])
    js_tests = [str(path) for path in sorted((ROOT / "tests").glob("*.test.mjs"))]
    run([node, "--test", *js_tests])
    metadata_gate()
    leakage_gate()
    line_ending_gate()
    print("Fast release gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
