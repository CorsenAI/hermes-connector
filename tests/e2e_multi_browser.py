#!/usr/bin/env python3
"""Live acceptance for two simultaneous isolated Chrome profiles."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import e2e_chromium as live


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


def launch_profile(
    binary: Path,
    temp_root: Path,
    label: str,
    debug_port: int,
    broker_port: int,
    http_port: int,
    secret: str,
    browser_id: str,
    browser_name: str,
    headed: bool,
) -> dict:
    data_dir = temp_root / f"chrome-{label}"
    log_handle = (temp_root / f"chrome-{label}.log").open("w", encoding="utf-8")
    args = [
        str(binary),
        f"--user-data-dir={data_dir}",
        f"--remote-debugging-port={debug_port}",
        "--remote-allow-origins=*",
        f"--disable-extensions-except={EXTENSION}",
        f"--load-extension={EXTENSION}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--window-size=1100,800",
        "about:blank",
    ]
    if not headed:
        args.insert(1, "--headless=new")
    process = subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=log_handle, stderr=subprocess.STDOUT
    )
    targets = live.wait_for_targets(debug_port, lambda items: any(
        item.get("type") == "service_worker" and item.get("url", "").endswith("/src/background.js")
        for item in items
    ))
    worker = live.service_worker(targets)
    cdp = live.Cdp(worker["webSocketDebuggerUrl"])
    try:
        base = f"http://127.0.0.1:{http_port}"
        page = "page-a.html" if label == "a" else "page-b.html"
        tab_id = cdp.evaluate(
            f"(async()=>{{const t=await chrome.tabs.create({{url:{json.dumps(base + '/' + page)},active:false}});return t.id;}})()"
        )
        profile_id = "profile-a" if label == "a" else "profile-b"
        session_id = "session-a" if label == "a" else "session-b"
        state = {
            "hermesUrl": f"{base}/",
            "settings": {
                "bridgeUrl": f"ws://127.0.0.1:{broker_port}",
                "pairingCode": secret,
                "trustedInput": False,
                "showOverlay": False,
            },
            "identity": {"browserId": browser_id, "browserName": browser_name},
            "pairing": {"pairedAt": 0},
            "bindings": {},
            "selectedScope": {"profileId": profile_id, "sessionId": session_id},
        }
        cdp.evaluate(
            f"(async()=>{{await chrome.storage.local.clear();await chrome.storage.local.set({json.dumps(state)});"
            "const p=await chrome.tabs.create({url:chrome.runtime.getURL('src/sidepanel.html'),active:false});"
            "return p.id;})()"
        )
    finally:
        cdp.close()
    panels = live.wait_for_targets(debug_port, lambda items: any(
        item.get("type") == "page" and item.get("url", "").endswith("/src/sidepanel.html")
        for item in items
    ))
    panel = next(item for item in panels
        if item.get("type") == "page" and item.get("url", "").endswith("/src/sidepanel.html"))
    return {
        "process": process,
        "log": log_handle,
        "debugPort": debug_port,
        "browserId": browser_id,
        "tabId": tab_id,
        "panel": panel,
    }


def panel_message(profile: dict, message: dict) -> dict:
    cdp = live.Cdp(profile["panel"]["webSocketDebuggerUrl"])
    try:
        return cdp.evaluate(
            f"chrome.runtime.sendMessage({json.dumps(message, separators=(',', ':'))})"
        )
    finally:
        cdp.close()


def wait_browsers(client, expected: set[str], timeout: float = 12) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.refresh_status()
        present = {item.get("browserId") for item in last.get("browsers", [])}
        if expected <= present:
            return last
        time.sleep(0.1)
    raise RuntimeError(f"both Chrome profiles did not pair: {last}")


def stop_process(profile: dict) -> None:
    process = profile["process"]
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    profile["log"].close()


def run(browser: Path, headed: bool) -> dict:
    broker_port = live.free_port()
    clients = []
    profiles = []
    with tempfile.TemporaryDirectory(prefix="hermes-connector-multi-browser-") as temp, live.fixture_server() as http_port:
        temp_root = Path(temp)
        broker_log = (temp_root / "broker.log").open("w", encoding="utf-8")
        broker_process = subprocess.Popen(
            [sys.executable, str(ROOT / "hermes-plugin" / "broker.py"), "--serve",
             "--root", str(temp_root), "--port", str(broker_port)],
            stdin=subprocess.DEVNULL, stdout=broker_log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", broker_port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            secret = live.broker.load_or_create_secret(temp_root)
            profiles = [
                launch_profile(browser, temp_root, "a", live.free_port(), broker_port, http_port,
                    secret, "browser-profile-a", "Work Chrome", headed),
                launch_profile(browser, temp_root, "b", live.free_port(), broker_port, http_port,
                    secret, "browser-profile-b", "Personal Chrome", headed),
            ]
            client_a = live.bridge_client.BridgeClient(
                "profile-a", root=temp_root, port=broker_port, auto_start_broker=False
            ).start()
            client_b = live.bridge_client.BridgeClient(
                "profile-b", root=temp_root, port=broker_port, auto_start_broker=False
            ).start()
            clients.extend([client_a, client_b])
            state = wait_browsers(client_a, {"browser-profile-a", "browser-profile-b"})

            attach_a = panel_message(profiles[0], {
                "cmd": "attachTab", "profileId": "profile-a", "sessionId": "session-a",
                "tabId": profiles[0]["tabId"],
            })
            attach_b = panel_message(profiles[1], {
                "cmd": "attachTab", "profileId": "profile-b", "sessionId": "session-b",
                "tabId": profiles[1]["tabId"],
            })
            if not attach_a.get("ok") or not attach_b.get("ok"):
                raise AssertionError(f"cross-profile attachment failed: {attach_a}, {attach_b}")
            time.sleep(0.15)
            read_a = live.require_ok(client_a.request(
                {"kind": "read_text"}, session_id="session-a"
            ), "profile A read")
            read_b = live.require_ok(client_b.request(
                {"kind": "read_text"}, session_id="session-b"
            ), "profile B read")
            if "Connector Page A" not in read_a.get("text", ""):
                raise AssertionError("Chrome profile A received the wrong tab")
            if "Connector Page B" not in read_b.get("text", ""):
                raise AssertionError("Chrome profile B received the wrong tab")

            # Move profile-a/session-a to Chrome profile B through an explicit attachment.
            panel_message(profiles[1], {
                "cmd": "selectScope", "profileId": "profile-a", "sessionId": "session-a",
            })
            transferred = panel_message(profiles[1], {
                "cmd": "attachTab", "profileId": "profile-a", "sessionId": "session-a",
                "tabId": profiles[1]["tabId"],
            })
            if not transferred.get("ok"):
                raise AssertionError(f"explicit Chrome-profile transfer failed: {transferred}")
            deadline = time.time() + 5
            while time.time() < deadline:
                moved = client_a.request({"kind": "read_text"}, timeout=2, session_id="session-a")
                if moved.get("ok") and "Connector Page B" in moved.get("data", {}).get("text", ""):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("transferred session did not route to Chrome profile B")

            old_state = panel_message(profiles[0], {"cmd": "getState"})
            old_keys = set((old_state.get("bindings") or {}).keys())
            if any("session-a" in key for key in old_keys):
                raise AssertionError("old Chrome profile retained a revoked session binding")
            now_unbound_b = client_b.request({"kind": "read_text"}, session_id="session-b")
            if now_unbound_b.get("ok"):
                raise AssertionError("moving the only tab did not remove its previous session owner")

            names = {item["browserId"]: item["name"] for item in state["browsers"]}
            if names != {"browser-profile-a": "Work Chrome", "browser-profile-b": "Personal Chrome"}:
                raise AssertionError(f"browser identities were not deterministic: {names}")
            return {
                "browser": browser.name,
                "protocol": state["protocol"],
                "browserIds": sorted(names),
                "checks": [
                    "two real isolated Chrome profiles paired concurrently",
                    "stable distinct browser identities and names observed",
                    "two Hermes profiles routed to their own Chrome profiles",
                    "explicit transfer rerouted the session",
                    "old browser binding was revoked and previous tab owner became unbound",
                ],
            }
        finally:
            for client in clients:
                try:
                    client.stop()
                except Exception:
                    pass
            for profile in profiles:
                stop_process(profile)
            if broker_process.poll() is None:
                broker_process.terminate()
                try:
                    broker_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    broker_process.kill()
                    broker_process.wait(timeout=3)
            broker_log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live two-Chrome-profile acceptance")
    parser.add_argument("--browser", default=os.environ.get("CHROME_BINARY"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run(live.find_chromium(args.browser), args.headed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
