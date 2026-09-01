#!/usr/bin/env python3
"""Opt-in acceptance against the user's running Hermes Desktop backend.

This test never opens the user's Chrome profile and never reads conversation
content. It loads the exact packaged extension into an isolated Chrome profile,
pairs it to the already-installed local companion, and proves that a real
``hermes serve --port 0`` process announces its dynamic backend and exposes a
session list through the Desktop-mode panel.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

from websockets.sync.client import connect

import e2e_chromium as live
from e2e_packaged_release import extract_exact


ROOT = Path(__file__).resolve().parents[1]


def read_existing_secret(hermes_root: Path) -> str:
    path = hermes_root / "connector" / "credentials.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    secret = str(payload.get("secret") or "")
    if len(secret) != 64 or any(character not in "0123456789abcdef" for character in secret):
        raise RuntimeError("the installed Connector pairing credential is invalid")
    return secret


def read_broker_state(secret: str, timeout: float = 90) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        browser_id = f"live-desktop-probe-{os.getpid()}"
        client_nonce = secrets.token_hex(16)
        try:
            with connect(
                f"ws://127.0.0.1:{live.broker.DEFAULT_PORT}",
                origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                open_timeout=3,
                close_timeout=2,
            ) as socket:
                challenge = json.loads(socket.recv(timeout=3))
                if (challenge.get("protocol") != live.broker.PROTOCOL_VERSION or
                        challenge.get("brokerVersion") != live.broker.BROKER_VERSION):
                    raise RuntimeError("the live broker does not match release 0.2.4")
                socket.send(json.dumps({
                    "type": "hello",
                    "role": "browser",
                    "browserId": browser_id,
                    "browserName": "Hermes Desktop prerelease probe",
                    "proof": live.broker.role_proof(
                        secret, "browser", browser_id, challenge["nonce"]
                    ),
                    "nonce": client_nonce,
                    "extVersion": "0.2.4",
                    "protocol": live.broker.PROTOCOL_VERSION,
                }))
                paired = json.loads(socket.recv(timeout=3))
                expected = live.broker.broker_proof(
                    secret, "browser", browser_id, client_nonce
                )
                if paired.get("type") != "paired" or paired.get("proof") != expected:
                    raise RuntimeError(
                        "the live broker did not authenticate as the installed companion"
                    )
                if paired.get("brokerVersion") != live.broker.BROKER_VERSION:
                    raise RuntimeError("the authenticated broker is not release 0.2.4")
                last = paired.get("brokerState") or {}
        except (OSError, TimeoutError):
            time.sleep(0.25)
            continue
        if last.get("agentBackends"):
            return last
        time.sleep(0.25)
    raise RuntimeError(
        "the restarted Hermes Desktop companion did not announce a dynamic backend; "
        f"agentProfiles={len(last.get('agentProfiles') or [])}"
    )


def run(browser: Path, extension_zip: Path, hermes_root: Path) -> dict:
    if not extension_zip.is_file():
        raise RuntimeError(f"packaged Chrome ZIP does not exist: {extension_zip}")
    secret = read_existing_secret(hermes_root)
    broker_state = read_broker_state(secret)
    debug_port = live.free_port()
    browser_process = None
    browser_log = None
    with tempfile.TemporaryDirectory(
        prefix="hermes-connector-live-desktop-", ignore_cleanup_errors=True
    ) as temp:
        temp_root = Path(temp)
        extension = temp_root / "extension"
        extension.mkdir()
        extract_exact(extension_zip, extension)
        manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
        browser_log_path = temp_root / "browser.log"
        browser_log = browser_log_path.open("w", encoding="utf-8")
        browser_process = subprocess.Popen(
            [
                str(browser),
                "--headless=new",
                f"--user-data-dir={temp_root / 'chrome-data'}",
                f"--remote-debugging-port={debug_port}",
                "--remote-allow-origins=*",
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "about:blank",
            ],
            stdin=subprocess.DEVNULL,
            stdout=browser_log,
            stderr=subprocess.STDOUT,
        )
        try:
            targets = live.wait_for_targets(
                debug_port,
                lambda items: any(
                    item.get("type") == "service_worker"
                    and item.get("url", "").endswith("/src/background.js")
                    for item in items
                ),
                timeout=45,
                browser_process=browser_process,
                browser_log_path=browser_log_path,
                browser_binary=browser,
            )
            worker = live.service_worker(targets)
            extension_id = worker["url"].split("/")[2]
            worker_cdp = live.Cdp(worker["webSocketDebuggerUrl"])
            try:
                live.wait_for_extension_apis(worker_cdp, extension_id)
                state = {
                    "hermesUrl": f"http://127.0.0.1:{live.free_port()}/",
                    "settings": {
                        "bridgeUrl": f"ws://127.0.0.1:{live.broker.DEFAULT_PORT}",
                        "pairingCode": secret,
                        "trustedInput": False,
                        "showOverlay": False,
                    },
                    "identity": {
                        "browserId": f"live-desktop-e2e-{os.getpid()}",
                        "browserName": "Hermes Desktop E2E",
                    },
                    "bindings": {},
                }
                worker_cdp.evaluate(
                    "(async()=>{await chrome.storage.local.clear();"
                    f"await chrome.storage.local.set({json.dumps(state)});"
                    "const panel=await chrome.tabs.create({url:chrome.runtime.getURL('src/sidepanel.html'),active:false});"
                    "return panel.id;})()"
                )
            finally:
                worker_cdp.close()

            panels = live.wait_for_targets(
                debug_port,
                lambda items: any(
                    item.get("type") == "page"
                    and item.get("url", "").endswith("/src/sidepanel.html")
                    for item in items
                ),
                timeout=20,
                browser_process=browser_process,
                browser_log_path=browser_log_path,
                browser_binary=browser,
            )
            panel = next(
                item for item in panels
                if item.get("type") == "page"
                and item.get("url", "").endswith("/src/sidepanel.html")
            )
            panel_cdp = live.Cdp(panel["webSocketDebuggerUrl"])
            try:
                proof = panel_cdp.evaluate(
                    "(async()=>{for(let i=0;i<600;i++){"
                    "const state=await chrome.runtime.sendMessage({cmd:'getState'});"
                    "const backends=state?.brokerState?.agentBackends||[];"
                    "const options=[...document.querySelectorAll('#sessionSelect option')].filter(o=>o.value);"
                    "const desktop=document.querySelector('#desktopMode');"
                    "const frame=document.querySelector('#hermes');"
                    "if(state?.paired&&backends.length&&options.length&&!desktop?.hidden&&frame?.hidden){"
                    "return {ready:true,paired:true,backendCount:backends.length,sessionCount:options.length,"
                    "loopbackOnly:backends.every(item=>item.mode==='headless'&&"
                    "['127.0.0.1','localhost'].includes(new URL(item.url).hostname)),"
                    "desktopText:desktop.textContent,status:document.querySelector('#status').textContent};}"
                    "await new Promise(r=>setTimeout(r,50));}"
                    "return {ready:false,status:document.querySelector('#status')?.textContent||'',"
                    "desktopHidden:document.querySelector('#desktopMode')?.hidden};})()"
                )
            finally:
                panel_cdp.close()
            if (not proof or not proof.get("ready") or not proof.get("loopbackOnly") or
                    "Hermes Desktop connected" not in proof.get("desktopText", "")):
                raise RuntimeError(f"packaged extension did not discover live Hermes Desktop: {proof}")
            return {
                "browser": browser.name,
                "extensionVersion": manifest.get("version"),
                "paired": True,
                "backendCount": proof["backendCount"],
                "sessionCount": proof["sessionCount"],
                "surface": "Hermes Desktop connected",
                "dataExposure": "counts only; no session titles or conversation content read by the harness",
            }
        finally:
            if browser_process is not None and browser_process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(browser_process.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=20,
                        check=False,
                    )
                else:
                    browser_process.terminate()
                try:
                    browser_process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    browser_process.kill()
                    browser_process.wait(timeout=3)
            if browser_log is not None:
                browser_log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test the packaged extension against live Hermes Desktop")
    parser.add_argument("--browser")
    parser.add_argument(
        "--extension-zip",
        type=Path,
        default=ROOT / "dist" / "hermes-connector-0.2.4-chrome.zip",
    )
    parser.add_argument(
        "--hermes-root",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "hermes",
    )
    args = parser.parse_args(argv)
    result = run(
        live.find_chromium(args.browser),
        args.extension_zip.expanduser().resolve(),
        args.hermes_root.expanduser().resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
