#!/usr/bin/env python3
"""Isolated live-extension acceptance test against Chromium/Chrome for Testing.

This is intentionally separate from ``run_all.py``: it launches a real browser,
loads the unpacked extension, starts the real companion broker, and exercises
the real ``chrome.tabs`` / ``chrome.scripting`` APIs end to end.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.request import urlopen
from urllib.parse import urlsplit

from websockets.sync.client import connect as websocket_connect


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = Path(os.environ.get("HERMES_EXTENSION_DIR", ROOT / "extension")).resolve()
FIXTURES = ROOT / "tests" / "fixtures"


def load_companion_modules():
    package_name = "hermes_connector_live_test"
    package = type(sys)(package_name)
    package.__path__ = [str(ROOT / "hermes-plugin")]
    sys.modules[package_name] = package
    modules = []
    for name in ("broker", "bridge_client"):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}", ROOT / "hermes-plugin" / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


broker, bridge_client = load_companion_modules()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_chromium(explicit: str | None = None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise RuntimeError(f"browser executable does not exist: {candidate}")

    candidates: list[Path] = []
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        candidates.extend(sorted(
            local.glob("ms-playwright/chromium-*/chrome-win64/chrome.exe"), reverse=True
        ))
        candidates.extend(sorted(
            local.glob("Google/Chrome for Testing/Application/*/chrome.exe"), reverse=True
        ))
    elif sys.platform == "darwin":
        candidates.extend([
            Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ])
    else:
        for name in (
            "google-chrome-for-testing",
            "chromium",
            "chromium-browser",
        ):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "Chrome for Testing or Chromium was not found; set CHROME_BINARY "
        "(branded Google Chrome 137+ cannot load unpacked extensions)"
    )


class QuietHandler(SimpleHTTPRequestHandler):
    dashboard_token = "isolated-dashboard-token-1234567890"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/chat":
            dashboard = (FIXTURES / "dashboard.html").read_text(encoding="utf-8")
            body = dashboard.replace(
                "__HERMES_SESSION_TOKEN_JSON__", json.dumps(self.dashboard_token)
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/profiles/sessions":
            expected = "Bearer " + self.dashboard_token
            if self.headers.get("Authorization") != expected:
                body = b'{"detail":"Unauthorized"}'
                self.send_response(401)
            else:
                body = json.dumps({"sessions": [
                    {"id": "session-a", "profile": "profile-a", "title": "Project Atlas"},
                    {"id": "session-b", "profile": "profile-b", "title": "Release QA"},
                ]}).encode("utf-8")
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


class QuietHttpServer(ThreadingHTTPServer):
    def handle_error(self, _request: Any, _client_address: Any) -> None:
        return


@contextmanager
def fixture_server():
    handler = functools.partial(QuietHandler, directory=str(FIXTURES))
    server = QuietHttpServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def http_json(url: str) -> Any:
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def browser_log_tail(log_path: Path | None, limit: int = 8192) -> str:
    if log_path is None:
        return ""
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"<browser log unavailable: {exc}>"
    return content[-limit:]


def wait_for_targets(
    port: int,
    predicate,
    timeout: float = 15,
    *,
    browser_process: subprocess.Popen | None = None,
    browser_log_path: Path | None = None,
    browser_binary: Path | None = None,
) -> list[dict]:
    deadline = time.time() + timeout
    last: list[dict] = []
    last_error = "none"
    while time.time() < deadline:
        if browser_process is not None and browser_process.poll() is not None:
            break
        try:
            last = http_json(f"http://127.0.0.1:{port}/json/list")
            if predicate(last):
                return last
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    kinds = [(item.get("type"), item.get("url")) for item in last]
    exit_code = browser_process.poll() if browser_process is not None else None
    process_state = f"exited with {exit_code}" if exit_code is not None else "still running"
    log_tail = browser_log_tail(browser_log_path)
    details = (
        f"browser targets did not become ready; browser={browser_binary}; "
        f"process={process_state}; last_cdp_error={last_error}; targets={kinds}"
    )
    if log_tail:
        details += f"\n--- browser.log tail ---\n{log_tail}"
    raise RuntimeError(details)


class Cdp:
    def __init__(self, websocket_url: str):
        self.websocket = websocket_connect(websocket_url, open_timeout=5, max_size=8 * 1024 * 1024)
        self.counter = 0

    def close(self) -> None:
        self.websocket.close()

    def call(self, method: str, params: dict | None = None) -> dict:
        self.counter += 1
        request_id = self.counter
        self.websocket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.websocket.recv(timeout=30))
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method}: {message['error']}")
            return message.get("result") or {}

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            "userGesture": True,
        })
        if result.get("exceptionDetails"):
            raise RuntimeError(f"browser evaluation failed: {result['exceptionDetails']}")
        remote = result.get("result") or {}
        if remote.get("subtype") == "error":
            raise RuntimeError(f"browser evaluation failed: {remote.get('description')}")
        return remote.get("value")


def wait_for_extension_apis(
    cdp: Cdp,
    expected_extension_id: str | None = None,
    timeout: float = 15,
    poll_interval: float = 0.1,
) -> dict:
    cdp.call("Runtime.enable")
    cdp.call("Runtime.runIfWaitingForDebugger")
    deadline = time.monotonic() + timeout
    last: dict = {"ready": False, "namespaces": []}
    last_error = "none"
    while True:
        try:
            value = cdp.evaluate(
                "(()=>{const c=globalThis.chrome;return {"
                "ready:typeof c?.tabs?.create==='function'&&"
                "typeof c?.storage?.local?.set==='function',"
                "runtimeId:c?.runtime?.id||'',"
                "namespaces:c?Object.keys(c).sort().slice(0,128):[]};})()"
            )
            if isinstance(value, dict):
                last = value
                right_extension = (
                    expected_extension_id is None
                    or value.get("runtimeId") == expected_extension_id
                )
                if value.get("ready") and right_extension:
                    return value
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if poll_interval:
            time.sleep(min(poll_interval, remaining))
    raise RuntimeError(
        "Chrome extension APIs did not become ready; "
        f"expected_extension_id={expected_extension_id}; "
        f"runtime_id={last.get('runtimeId', '')}; last_error={last_error}; "
        f"namespaces={last.get('namespaces', [])}"
    )


def service_worker(targets: list[dict]) -> dict:
    for target in targets:
        if target.get("type") == "service_worker" and target.get("url", "").endswith("/src/background.js"):
            return target
    raise RuntimeError("Hermes Connector service worker was not loaded")


def wait_client(client, browser_id: str, timeout: float = 12) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.refresh_status()
        browsers = last.get("browsers") or []
        if any(item.get("browserId") == browser_id for item in browsers):
            return last
        time.sleep(0.2)
    raise RuntimeError(f"extension did not pair with broker: {last.get('error')}")


def require_ok(result: dict, label: str) -> Any:
    if not result.get("ok"):
        raise AssertionError(f"{label} failed: {result.get('error')}")
    return result.get("data")


def run_live(browser_binary: Path, headed: bool) -> dict:
    broker_port = free_port()
    debug_port = free_port()
    clients = []
    with tempfile.TemporaryDirectory(prefix="hermes-connector-e2e-") as temp, fixture_server() as http_port:
        temp_root = Path(temp)
        browser_data = temp_root / "chrome-data"
        broker_log = (temp_root / "broker.log").open("w", encoding="utf-8")
        broker_process = subprocess.Popen(
            [
                sys.executable, str(ROOT / "hermes-plugin" / "broker.py"), "--serve",
                "--root", str(temp_root), "--host", "127.0.0.1", "--port", str(broker_port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=broker_log,
            stderr=subprocess.STDOUT,
        )
        browser_process = None
        try:
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", broker_port), timeout=0.2):
                        break
                except OSError:
                    if broker_process.poll() is not None:
                        raise RuntimeError("broker exited before accepting connections")
                    time.sleep(0.1)
            secret = broker.load_or_create_secret(temp_root)
            arguments = [
                str(browser_binary),
                f"--user-data-dir={browser_data}",
                f"--remote-debugging-port={debug_port}",
                "--remote-allow-origins=*",
                f"--disable-extensions-except={EXTENSION}",
                f"--load-extension={EXTENSION}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--window-size=1280,900",
                "about:blank",
            ]
            if not headed:
                arguments.insert(1, "--headless=new")
            browser_log_path = temp_root / "browser.log"
            browser_log = browser_log_path.open("w", encoding="utf-8")
            browser_process = subprocess.Popen(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=browser_log,
                stderr=subprocess.STDOUT,
            )
            wait_browser = functools.partial(
                wait_for_targets,
                debug_port,
                browser_process=browser_process,
                browser_log_path=browser_log_path,
                browser_binary=browser_binary,
            )
            targets = wait_browser(
                lambda items: any(
                    item.get("type") == "service_worker"
                    and item.get("url", "").endswith("/src/background.js")
                    for item in items
                ),
                timeout=45,
            )
            worker = service_worker(targets)
            extension_id = worker["url"].split("/")[2]
            cdp = Cdp(worker["webSocketDebuggerUrl"])
            try:
                wait_for_extension_apis(cdp, extension_id)
                if cdp.evaluate("1 + 1") != 2:
                    raise RuntimeError("extension service worker evaluation is unavailable")
                base = f"http://127.0.0.1:{http_port}"
                tabs = cdp.evaluate(
                    "(async()=>{"
                    f"const a=await chrome.tabs.create({{url:{json.dumps(base + '/page-a.html')},active:false}});"
                    f"const b=await chrome.tabs.create({{url:{json.dumps(base + '/page-b.html')},active:false}});"
                    "return {a:a.id,b:b.id};})()"
                )
                browser_id = "e2e-browser"
                profile_a, profile_b = "profile-a", "profile-b"
                session_a, session_b = "session-a", "session-b"
                initial_state = {
                    "hermesUrl": f"{base}/",
                    "settings": {
                        "bridgeUrl": f"ws://127.0.0.1:{broker_port}",
                        "pairingCode": secret,
                        "trustedInput": True,
                        "showOverlay": False,
                    },
                    "identity": {"browserId": browser_id, "browserName": "Isolated Chromium"},
                    "pairing": {"pairedAt": 0},
                    "bindings": {},
                    "selectedScope": {"profileId": profile_a, "sessionId": session_a},
                    "upgradeNotice": {
                        "id": "companion-reinstall-0.2.1",
                        "previousVersion": "0.2.0",
                        "extensionVersion": "0.2.1",
                    },
                }
                cdp.evaluate(
                    f"(async()=>{{await chrome.storage.local.clear();await chrome.storage.local.set({json.dumps(initial_state)});return true;}})()"
                )
                # Opening a real extension page makes the side-panel client send
                # its normal `connect` command to the service worker. This uses
                # the product path instead of reaching into module-local state.
                panel_tab_id = cdp.evaluate(
                    "(async()=>{const t=await chrome.tabs.create({url:chrome.runtime.getURL('src/sidepanel.html'),active:false});return t.id;})()"
                )
            finally:
                try:
                    cdp.close()
                except Exception:
                    pass

            targets = wait_browser(lambda items: any(
                item.get("type") == "service_worker" and item.get("url", "").endswith("/src/background.js")
                for item in items
            ))
            panel_targets = wait_browser(lambda items: any(
                item.get("type") == "page" and item.get("url", "").endswith("/src/sidepanel.html")
                for item in items
            ))
            panel_target = next(item for item in panel_targets
                if item.get("type") == "page" and item.get("url", "").endswith("/src/sidepanel.html"))
            panel_cdp = Cdp(panel_target["webSocketDebuggerUrl"])
            try:
                panel_state = panel_cdp.evaluate(
                    "(async()=>{for(let i=0;i<100;i++){const values=[...document.querySelectorAll('#sessionSelect option')].map(o=>o.value);"
                    "if(values.some(v=>v.includes('session-a'))){return {values,selected:document.querySelector('#sessionSelect').value,"
                    "frame:document.querySelector('#hermes').src,status:document.querySelector('#status').textContent,"
                    "setupHidden:document.querySelector('#setupNotice').hidden,"
                    "noticeHidden:document.querySelector('#upgradeNotice').hidden,"
                    "noticeText:document.querySelector('#upgradeNotice').textContent};}"
                    "await new Promise(r=>setTimeout(r,50));}return null;})()"
                )
            finally:
                panel_cdp.close()
            expected_scope = "profile-a\x1fsession-a"
            if not panel_state or panel_state.get("selected") != expected_scope:
                raise AssertionError(f"real side panel did not load authenticated Hermes sessions: {panel_state}")
            frame_url = panel_state.get("frame", "")
            if "resume=session-a" not in frame_url or "profile=profile-a" not in frame_url:
                raise AssertionError(f"real side panel did not resume the selected session: {frame_url}")
            if panel_state.get("noticeHidden") or "0.2.1" not in panel_state.get("noticeText", ""):
                raise AssertionError(f"companion update notice was not visible: {panel_state}")
            if not panel_state.get("setupHidden"):
                raise AssertionError(f"first-run setup stayed visible after pairing configuration: {panel_state}")
            panel_cdp = Cdp(panel_target["webSocketDebuggerUrl"])
            try:
                notice_dismissed = panel_cdp.evaluate(
                    "(async()=>{document.querySelector('#dismissUpgradeNotice').click();"
                    "for(let i=0;i<100;i++){const saved=await chrome.storage.local.get('upgradeNotice');"
                    "if(!saved.upgradeNotice&&document.querySelector('#upgradeNotice').hidden)return true;"
                    "await new Promise(r=>setTimeout(r,20));}return false;})()"
                )
            finally:
                panel_cdp.close()
            if not notice_dismissed:
                raise AssertionError("companion update notice did not dismiss persistently")

            client_a = bridge_client.BridgeClient(
                profile_a, root=temp_root, port=broker_port, auto_start_broker=False
            ).start()
            client_b = bridge_client.BridgeClient(
                profile_b, root=temp_root, port=broker_port, auto_start_broker=False
            ).start()
            clients.extend([client_a, client_b])
            state = wait_client(client_a, browser_id)

            # Exercise the real extension-page -> service-worker attachment path after pairing.
            panel_cdp = Cdp(panel_target["webSocketDebuggerUrl"])
            try:
                attached = panel_cdp.evaluate(
                    "(async()=>{"
                    f"const a=await chrome.runtime.sendMessage({{cmd:'attachTab',profileId:'{profile_a}',sessionId:'{session_a}',tabId:{tabs['a']}}});"
                    f"const b=await chrome.runtime.sendMessage({{cmd:'attachTab',profileId:'{profile_b}',sessionId:'{session_b}',tabId:{tabs['b']}}});"
                    "return {a,b};})()"
                )
            finally:
                panel_cdp.close()
            if not attached or not attached["a"].get("ok") or not attached["b"].get("ok"):
                raise AssertionError(f"real extension attachment commands failed: {attached}")
            panel_cdp = Cdp(panel_target["webSocketDebuggerUrl"])
            try:
                # Drain the legitimate bindingsChanged event created by the
                # preceding attach commands before measuring read-only calls.
                panel_cdp.evaluate(
                    "(async()=>{await chrome.runtime.sendMessage("
                    f"{{cmd:'listTabs',profileId:'{profile_a}',sessionId:'{session_a}'}});"
                    "await new Promise(r=>setTimeout(r,250));return true;})()"
                )
                no_op_binding_events = panel_cdp.evaluate(
                    "(async()=>{let count=0;const listener=(message)=>{"
                    "if(message&&message.from==='bg'&&message.cmd==='bindingsChanged')count++;};"
                    "chrome.runtime.onMessage.addListener(listener);"
                    "try{for(let i=0;i<3;i++){const result=await chrome.runtime.sendMessage("
                    f"{{cmd:'listTabs',profileId:'{profile_a}',sessionId:'{session_a}'}});"
                    "if(!result||!result.ok)throw new Error('listTabs failed');}"
                    "await new Promise(r=>setTimeout(r,250));return count;}"
                    "finally{chrome.runtime.onMessage.removeListener(listener);}})()"
                )
            finally:
                panel_cdp.close()
            if no_op_binding_events != 0:
                raise AssertionError(
                    f"unchanged tab rendering rebroadcast bindingsChanged {no_op_binding_events} times"
                )
            deadline = time.time() + 5
            while time.time() < deadline:
                state = client_a.refresh_status()
                browser_match = next((item for item in state.get("browsers", [])
                    if item.get("browserId") == browser_id), None)
                if browser_match and len(browser_match.get("bindings", [])) == 2:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("the broker did not receive both real extension attachments")

            read_a = require_ok(client_a.request({"kind": "read_text"}, session_id=session_a), "read A")
            read_b = require_ok(client_b.request({"kind": "read_text"}, session_id=session_b), "read B")
            if "Connector Page A" not in read_a.get("text", "") or "Connector Page B" in read_a.get("text", ""):
                raise AssertionError("session A read the wrong tab")
            if "Connector Page B" not in read_b.get("text", "") or "Connector Page A" in read_b.get("text", ""):
                raise AssertionError("session B read the wrong tab")

            snap_a = require_ok(client_a.request({"kind": "snapshot"}, session_id=session_a), "snapshot A")
            textbox = re.search(r"textbox[^\n]*\[(ref_\d+)\]", snap_a.get("content", ""))
            button = re.search(r"button \"Action A\" \[(ref_\d+)\]", snap_a.get("content", ""))
            confirm_button = re.search(r"button \"Confirm A\" \[(ref_\d+)\]", snap_a.get("content", ""))
            hover_button = re.search(r"button \"Hover A\" \[(ref_\d+)\]", snap_a.get("content", ""))
            choice = re.search(r"combobox \"Project A choice\" \[(ref_\d+)\]", snap_a.get("content", ""))
            drag_from = re.search(r"button \"Drag A\" \[(ref_\d+)\]", snap_a.get("content", ""))
            drag_to = re.search(r"button \"Drop A\" \[(ref_\d+)\]", snap_a.get("content", ""))
            if not all((textbox, button, confirm_button, hover_button, choice, drag_from, drag_to)):
                raise AssertionError(f"expected refs are absent from snapshot: {snap_a.get('content')}")
            require_ok(client_a.request(
                {"kind": "type", "ref": textbox.group(1), "text": "changed-by-session-a"},
                session_id=session_a,
            ), "type A")
            require_ok(client_a.request(
                {"kind": "click", "ref": button.group(1)}, session_id=session_a
            ), "click A")
            cancelled = client_a.request(
                {"kind": "click", "ref": confirm_button.group(1)}, session_id=session_a
            )
            if cancelled.get("ok") or "auto-cancelled" not in str(cancelled.get("error")):
                raise AssertionError(f"trusted confirm dialog was not cancelled honestly: {cancelled}")
            require_ok(client_a.request(
                {"kind": "hover", "ref": hover_button.group(1)}, session_id=session_a
            ), "hover A")
            require_ok(client_a.request(
                {"kind": "key", "key": "End", "ref": textbox.group(1)}, session_id=session_a
            ), "key A")
            require_ok(client_a.request(
                {"kind": "select_option", "ref": choice.group(1), "value": "two"}, session_id=session_a
            ), "select A")
            require_ok(client_a.request(
                {"kind": "drag", "from": drag_from.group(1), "to": drag_to.group(1)}, session_id=session_a
            ), "drag A")
            require_ok(client_a.request(
                {"kind": "scroll", "dy": 400}, session_id=session_a
            ), "scroll A")
            found = require_ok(client_a.request(
                {"kind": "find", "text": "Unique searchable target A"}, session_id=session_a
            ), "find A")
            if found.get("matches") != 1 or not found.get("scrolledToFirst"):
                raise AssertionError(f"find did not locate its target: {found}")
            screenshot = require_ok(client_a.request({"kind": "screenshot"}, session_id=session_a), "screenshot A")
            if not screenshot.get("dataUrl", "").startswith("data:image/png;base64,"):
                raise AssertionError("visible-tab screenshot was not returned as PNG")
            require_ok(client_a.request({"kind": "wait", "ms": 25}, session_id=session_a), "wait A")

            worker = service_worker(targets)
            cdp = Cdp(worker["webSocketDebuggerUrl"])
            try:
                wait_for_extension_apis(cdp, extension_id)
                trusted_attached = cdp.evaluate(
                    f"(async()=>{{const t=await chrome.debugger.getTargets();return t.some(x=>x.tabId==={tabs['a']}&&x.attached);}})()"
                )
            finally:
                cdp.close()
            if not trusted_attached:
                raise AssertionError("Trusted input did not attach Chrome's debugger transport")

            new_tab = require_ok(client_a.request(
                {"kind": "new_tab", "url": f"{base}/page-b.html"}, session_id=session_a
            ), "new scoped tab")
            listed = require_ok(client_a.request({"kind": "list_tabs"}, session_id=session_a), "list scoped tabs")
            if len(listed.get("tabs", [])) != 2 or new_tab.get("tabId") == tabs["b"]:
                raise AssertionError("new tab did not stay inside session A scope")
            require_ok(client_a.request({"kind": "switch_tab", "index": 0}, session_id=session_a), "switch A")
            require_ok(client_a.request({"kind": "close_tab", "index": 1}, session_id=session_a), "close A")

            unbound = client_a.request({"kind": "read_text"}, session_id="unbound-session")
            if unbound.get("ok") or "no Chrome tabs are attached" not in str(unbound.get("error")):
                raise AssertionError(f"unbound session did not fail closed: {unbound}")

            current_b = require_ok(client_b.request({"kind": "current_url"}, session_id=session_b), "current B")
            if not current_b.get("url", "").endswith("/page-b.html"):
                raise AssertionError("session A changed session B's tab")

            worker = service_worker(targets)
            cdp = Cdp(worker["webSocketDebuggerUrl"])
            try:
                wait_for_extension_apis(cdp, extension_id)
                observed = cdp.evaluate(
                    f"(async()=>{{const a=await chrome.tabs.get({tabs['a']});const b=await chrome.tabs.get({tabs['b']});"
                    f"const av=await chrome.scripting.executeScript({{target:{{tabId:{tabs['a']}}},func:()=>({{value:document.querySelector('#project-a').value,clicked:document.querySelector('#button-a').dataset.clicked||'',hovered:document.querySelector('#hover-a').dataset.hovered||'',choice:document.querySelector('#choice-a').value,choiceChanged:document.querySelector('#choice-a').dataset.changed||'',dropped:document.querySelector('#drop-a').dataset.dropped||''}})}});"
                    f"const bv=await chrome.scripting.executeScript({{target:{{tabId:{tabs['b']}}},func:()=>document.querySelector('#project-b').value}});"
                    "return {aUrl:a.url,bUrl:b.url,a:av[0].result,bValue:bv[0].result};})()"
                )
                stale_debugger_attached = cdp.evaluate(
                    f"(async()=>{{const t=await chrome.debugger.getTargets();return t.some(x=>x.tabId==={tabs['a']}&&x.attached);}})()"
                )
            finally:
                cdp.close()
            if observed["a"] != {"value": "changed-by-session-a", "clicked": "yes", "hovered": "yes",
                                  "choice": "two", "choiceChanged": "yes", "dropped": "drag-a"}:
                raise AssertionError(f"real page actions were not applied: {observed['a']}")
            if observed["bValue"] != "beta":
                raise AssertionError("session A modified session B's page")
            if stale_debugger_attached:
                raise AssertionError("switching the active target left Chrome's debugger on the old tab")

            invalid_nav = client_a.request({"kind": "navigate", "url": "chrome://settings"}, session_id=session_a)
            if invalid_nav.get("ok") or "http/https" not in str(invalid_nav.get("error")):
                raise AssertionError(f"restricted navigation did not fail safely: {invalid_nav}")
            navigated = require_ok(client_a.request(
                {"kind": "navigate", "url": f"{base}/page-b.html"}, session_id=session_a
            ), "navigate A")
            if not navigated.get("url", "").endswith("/page-b.html"):
                raise AssertionError(f"navigation landed on an unexpected URL: {navigated}")
            require_ok(client_a.request({"kind": "back"}, session_id=session_a), "history back A")
            require_ok(client_a.request({"kind": "forward"}, session_id=session_a), "history forward A")
            require_ok(client_a.request({"kind": "reload"}, session_id=session_a), "reload A")
            require_ok(client_a.request({"kind": "back"}, session_id=session_a), "history restore A")
            current_a = require_ok(client_a.request({"kind": "current_url"}, session_id=session_a), "current A")
            if not current_a.get("url", "").endswith("/page-a.html"):
                raise AssertionError(f"history did not return session A to its own page: {current_a}")

            panel_cdp = Cdp(panel_target["webSocketDebuggerUrl"])
            try:
                disabled = panel_cdp.evaluate(
                    "chrome.runtime.sendMessage({cmd:'saveSettings',settings:{trustedInput:false}})"
                )
            finally:
                panel_cdp.close()
            if not disabled or not disabled.get("ok"):
                raise AssertionError(f"could not disable Trusted input: {disabled}")
            worker = service_worker(wait_browser(lambda items: any(
                item.get("type") == "service_worker" and item.get("url", "").endswith("/src/background.js")
                for item in items
            )))
            cdp = Cdp(worker["webSocketDebuggerUrl"])
            try:
                wait_for_extension_apis(cdp, extension_id)
                detached_after = cdp.evaluate(
                    f"(async()=>{{for(let i=0;i<40;i++){{const t=await chrome.debugger.getTargets();"
                    f"if(!t.some(x=>x.tabId==={tabs['a']}&&x.attached)){{return true;}}"
                    "await new Promise(r=>setTimeout(r,25));}return false;})()"
                )
            finally:
                cdp.close()
            if not detached_after:
                raise AssertionError("disabling Trusted input did not detach Chrome's debugger transport")

            # A normal first launch must explain and link the complete companion
            # setup without requiring the user to discover the support site.
            panel_cdp = Cdp(panel_target["webSocketDebuggerUrl"])
            try:
                panel_cdp.evaluate(
                    "(async()=>{await chrome.runtime.sendMessage({cmd:'unpair'});"
                    "const saved=(await chrome.storage.local.get('settings')).settings||{};"
                    "await chrome.storage.local.set({settings:{...saved,pairingCode:''}});return true;})()"
                )
                panel_cdp.call("Page.reload", {"ignoreCache": True})
                first_run = panel_cdp.evaluate(
                    "(async()=>{for(let i=0;i<100;i++){const notice=document.querySelector('#setupNotice');"
                    "const cfg=document.querySelector('#cfg');const link=notice&&notice.querySelector('a.primaryLink');"
                    "const title=document.querySelector('#setupTitle');"
                    "if(notice&&cfg&&link&&title&&!notice.hidden&&cfg.classList.contains('open')&&title.textContent.includes('already installed')){"
                    "const platform=await chrome.runtime.getPlatformInfo();return {"
                    "text:notice.textContent,href:link.href,status:document.querySelector('#status').textContent,platform:platform.os};}"
                    "await new Promise(r=>setTimeout(r,25));}return null;})()"
                )
            finally:
                panel_cdp.close()
            if (not first_run or "What is the companion?" not in first_run.get("text", "") or
                    "Do not reinstall" not in first_run.get("text", "") or
                    not first_run.get("href", "").endswith("hermes-connector-0.2.1-companion.zip") or
                    first_run.get("status") != "companion detected — enter pairing code"):
                raise AssertionError(f"first-run companion setup was incomplete: {first_run}")

            browser_state = next(item for item in state["browsers"] if item["browserId"] == browser_id)
            return {
                "browser": browser_binary.name,
                "extensionId": extension_id,
                "protocol": state["protocol"],
                "browserBindings": len(browser_state.get("bindings", [])),
                "checks": [
                    "real extension service worker loaded",
                    "real side panel loaded authenticated Hermes sessions",
                    "first launch detected the installed companion and explained profile re-pairing",
                    "0.2.0 users received a persistent companion update notice",
                    "unchanged tab rendering stayed storage/event-loop silent",
                    "mutual pairing succeeded",
                    "real post-pair tab attachment commands succeeded",
                    "two profiles routed to exact tabs",
                    "trusted snapshot/type/click changed only session A",
                    "read/navigation/screenshot/scroll/hover/key/select/drag/find/history passed",
                    "confirm dialog cancelled and debugger detached honestly",
                    "scoped new/list/switch/close tab passed",
                    "unbound session failed closed",
                ],
            }
        finally:
            for client in clients:
                try:
                    client.stop()
                except Exception:
                    pass
            if browser_process is not None and browser_process.poll() is None:
                browser_process.terminate()
                try:
                    browser_process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    browser_process.kill()
                    browser_process.wait(timeout=3)
            if broker_process.poll() is None:
                broker_process.terminate()
                try:
                    broker_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    broker_process.kill()
                    broker_process.wait(timeout=3)
            broker_log.close()
            if "browser_log" in locals():
                browser_log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live Hermes Connector Chromium acceptance")
    parser.add_argument("--browser", default=os.environ.get("CHROME_BINARY"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)
    result = run_live(find_chromium(args.browser), args.headed)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
