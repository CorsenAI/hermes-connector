#!/usr/bin/env python3
"""Exercise snapshot escaping through a real broker and loaded Chrome extension.

The negative control uses a separate extension copy and a fresh browser profile.
It must complete the same authenticated action and produce only the three
expected label mismatches; a launch, pairing or injection failure is not success.
"""
from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from e2e_chromium import (
    EXTENSION, PLUGIN, Cdp, bridge_client, broker, find_chromium,
    fixture_server, free_port, require_ok, service_worker,
    wait_client, wait_for_extension_apis, wait_for_targets,
)

LABELS = [
    "ordinary chars 123",
    'He said "hi"',
    "C:\\path",
    "ends with backslash\\",
    '"quoted\\" inside"',
    "Crème שלום 日本語",
]


@contextmanager
def process(arguments: list[str], log_path: Path):
    with log_path.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(arguments, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def live_snapshot(extension: Path, browser_binary: Path) -> dict:
    with ExitStack() as stack:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="snapshot-escape-")))
        http_port = stack.enter_context(fixture_server())
        broker_port, debug_port = free_port(), free_port()
        companion = stack.enter_context(process([
            sys.executable, str(PLUGIN / "broker.py"), "--serve", "--root", str(root),
            "--host", "127.0.0.1", "--port", str(broker_port),
        ], root / "broker.log"))
        deadline = time.monotonic() + 10
        while True:
            if companion.poll() is not None:
                raise RuntimeError("snapshot test broker exited before becoming ready")
            try:
                with socket.create_connection(("127.0.0.1", broker_port), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("snapshot test broker did not become ready")
                time.sleep(0.05)
        secret = broker.load_or_create_secret(root)
        browser_log = root / "browser.log"
        browser = stack.enter_context(process([
            str(browser_binary), "--headless=new", f"--user-data-dir={root / 'chrome-data'}",
            f"--remote-debugging-port={debug_port}", "--remote-allow-origins=*",
            f"--disable-extensions-except={extension}", f"--load-extension={extension}",
            "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
            "--disable-component-update", "--disable-sync", "--window-size=1280,900", "about:blank",
        ], browser_log))

        def targets(predicate):
            return wait_for_targets(debug_port, predicate, timeout=30,
                browser_process=browser, browser_log_path=browser_log,
                browser_binary=browser_binary)

        worker = service_worker(targets(lambda items: any(
            item.get("type") == "service_worker"
            and item.get("url", "").endswith("/src/background.js") for item in items)))
        worker_cdp = stack.enter_context(closing(Cdp(worker["webSocketDebuggerUrl"])))
        extension_id = worker["url"].split("/")[2]
        wait_for_extension_apis(worker_cdp, extension_id)
        base = f"http://127.0.0.1:{http_port}"
        initial = {
            "hermesUrl": base + "/",
            "settings": {"bridgeUrl": f"ws://127.0.0.1:{broker_port}", "pairingCode": secret,
                         "trustedInput": False, "showOverlay": False},
            "identity": {"browserId": "snapshot-browser", "browserName": "Snapshot test"},
            "pairing": {"pairedAt": 0}, "bindings": {},
            "selectedScope": {"profileId": "profile-a", "sessionId": "session-a"},
        }
        tab_id = worker_cdp.evaluate(
            "(async()=>{await chrome.storage.local.clear();"
            f"await chrome.storage.local.set({json.dumps(initial)});"
            f"const page=await chrome.tabs.create({{url:{json.dumps(base + '/page-a.html')},active:true}});"
            "await chrome.tabs.create({url:chrome.runtime.getURL('src/sidepanel.html'),active:false});"
            "return page.id;})()")
        all_targets = targets(lambda items: any(
            item.get("type") == "page" and item.get("url", "").endswith("/src/sidepanel.html")
            for item in items) and any(item.get("url") == base + "/page-a.html" for item in items))
        panel = next(item for item in all_targets
                     if item.get("url", "").endswith("/src/sidepanel.html"))
        page = next(item for item in all_targets if item.get("url") == base + "/page-a.html")
        panel_cdp = stack.enter_context(closing(Cdp(panel["webSocketDebuggerUrl"])))
        page_cdp = stack.enter_context(closing(Cdp(page["webSocketDebuggerUrl"])))
        wait_for_extension_apis(panel_cdp, extension_id)
        page_cdp.evaluate(
            "(async()=>{for(let i=0;document.readyState!=='complete';i++){"
            "if(i===100)throw new Error('fixture load timeout');"
            "await new Promise(r=>setTimeout(r,50));}"
            f"const names={json.dumps(LABELS)};document.title='Snapshot escape fixture';"
            "document.body.replaceChildren(...names.map(name=>{const b=document.createElement('button');"
            "b.setAttribute('aria-label',name);b.textContent='fixture';"
            "b.style.cssText='display:block;width:500px;height:40px';return b;}));return true;})()")
        reply = panel_cdp.evaluate(
            "chrome.runtime.sendMessage({cmd:'connect',browserName:'Snapshot test'})")
        if not reply or not reply.get("ok"):
            raise AssertionError("extension connect command was not accepted")
        client = bridge_client.BridgeClient("profile-a", root=root, port=broker_port,
                                           auto_start_broker=False).start()
        stack.callback(client.stop)
        wait_client(client, "snapshot-browser")
        attached = panel_cdp.evaluate(
            "chrome.runtime.sendMessage({cmd:'attachTab',profileId:'profile-a',"
            f"sessionId:'session-a',tabId:{tab_id}}})")
        if not attached or not attached.get("ok"):
            raise AssertionError("snapshot fixture attachment failed")
        deadline = time.monotonic() + 10
        while True:
            state = client.refresh_status()
            if any(item.get("browserId") == "snapshot-browser" and len(item.get("bindings", [])) == 1
                   for item in state.get("browsers", [])):
                break
            if time.monotonic() >= deadline:
                raise AssertionError("broker did not receive the fixture binding")
            time.sleep(0.05)
        result = require_ok(client.request({"kind": "snapshot", "maxChars": 50000},
                            session_id="session-a", timeout=10), "snapshot escape action")
        if result.get("title") != "Snapshot escape fixture" or result.get("truncated"):
            raise AssertionError("snapshot did not come from the complete fixture")
        return result


def mismatches(result: dict) -> list[int]:
    lines = result["content"].splitlines()
    if len(lines) != len(LABELS):
        raise AssertionError(f"expected {len(LABELS)} fixture lines, received {len(lines)}")
    wrong = []
    for index, (label, line) in enumerate(zip(LABELS, lines, strict=True)):
        expected = "button " + json.dumps(label, ensure_ascii=False)
        if not re.fullmatch(re.escape(expected) + r" \[ref_\d+\]", line.strip()):
            wrong.append(index)
    return wrong


def main() -> int:
    browser = find_chromium(os.environ.get("CHROME_BINARY"))
    positive = mismatches(live_snapshot(EXTENSION, browser))
    if positive:
        raise AssertionError(f"corrected snapshot has incorrect fixture labels: {positive}")
    with tempfile.TemporaryDirectory(prefix="snapshot-negative-") as temp:
        negative_extension = Path(temp) / "extension"
        shutil.copytree(EXTENSION, negative_extension)
        source_path = negative_extension / "src" / "page-actions.js"
        source = source_path.read_text(encoding="utf-8")
        added_escape = r'name.replace(/\\/g, "\\\\").replace'
        if source.count(added_escape) != 1:
            raise AssertionError("negative control could not identify the single escape change")
        source_path.write_text(source.replace(added_escape, "name.replace"), encoding="utf-8")
        negative = mismatches(live_snapshot(negative_extension, browser))
        if negative != [2, 3, 4]:
            raise AssertionError(f"negative control had unexpected mismatches: {negative}")
    print("Snapshot escape acceptance passed: 6 exact labels; old-code control: 3 expected mismatches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
