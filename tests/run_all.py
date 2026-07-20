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
    if not protocol or int(protocol.group(1)) != 3:
        raise SystemExit("protocol gate failed: protocol v3 is required")
    if not plugin_version or plugin_version.group(1) != manifest["version"]:
        raise SystemExit("version gate failed: extension and companion versions differ")
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
    for disclosure in ("Website content", "Web history", "Limited Use"):
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
    patterns.extend(
        rf"\b{re.escape(identity)}\b"
        for identity in local_identities
        if len(identity) >= 4
    )
    for root in (EXTENSION, PLUGIN):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".js", ".json", ".html", ".py", ".yaml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    raise SystemExit(f"leakage gate failed: {path.relative_to(ROOT)} matches {pattern}")


def main() -> int:
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is required for extension tests")
    run([sys.executable, "-m", "unittest", "-v",
         "tests.test_broker", "tests.test_plugin_routing",
         "tests.test_installer", "tests.test_release"])
    for source in sorted((EXTENSION / "src").glob("*.js")):
        run([node, "--check", str(source)])
    js_tests = [str(path) for path in sorted((ROOT / "tests").glob("*.test.mjs"))]
    run([node, "--test", *js_tests])
    metadata_gate()
    leakage_gate()
    print("Fast release gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
