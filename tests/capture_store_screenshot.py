#!/usr/bin/env python3
"""Capture a real 1280x800 Chrome window with the actual extension side panel.

The browser profile, broker secret, dashboard data, and attached page are all
isolated fixtures. The resulting Store asset therefore demonstrates the real
unpacked extension without exposing a user's browser or Hermes history.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from PIL import ImageGrab

import e2e_chromium as live


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "store" / "screenshot-product-1280x800.png"
WIDTH = 1280
HEIGHT = 800


@contextmanager
def temporary_capture_root():
    path = Path(tempfile.mkdtemp(prefix="hermes-connector-store-capture-"))
    try:
        yield path
    finally:
        for attempt in range(20):
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)


def wait_for_port(port: int, process: subprocess.Popen, timeout: float = 8) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            if process.poll() is not None:
                raise RuntimeError("broker exited before accepting connections")
            time.sleep(0.1)
    raise RuntimeError("broker did not start in time")


def wait_panel(panel: live.Cdp, timeout: float = 12) -> dict:
    expression = """
      (async()=>{
        for(let i=0;i<240;i++){
          const status=document.querySelector('#status')?.textContent||'';
          const scope=document.querySelector('#scopeInfo')?.textContent||'';
          const selected=document.querySelector('#sessionSelect')?.value||'';
          const frame=document.querySelector('#hermes');
          if(status==='browser paired' && scope.startsWith('1 attached tab') &&
             selected.includes('session-a') && frame?.src.includes('resume=session-a')){
            return {ready:true,status,scope,selected,frame:frame.src};
          }
          await new Promise(r=>setTimeout(r,50));
        }
        return {ready:false,status:document.querySelector('#status')?.textContent||'',
          scope:document.querySelector('#scopeInfo')?.textContent||'',
          selected:document.querySelector('#sessionSelect')?.value||'',
          frame:document.querySelector('#hermes')?.src||''};
      })()
    """
    state = panel.evaluate(expression)
    if not state or not state.get("ready"):
        raise RuntimeError(f"real side panel did not reach its captured state: {state}")
    return state


def find_browser_window(process_id: int, timeout: float = 12) -> int:
    user32 = ctypes.windll.user32
    deadline = time.time() + timeout
    while time.time() < deadline:
        matches: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == process_id and user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    matches.append(int(hwnd))
            return True

        user32.EnumWindows(visit, 0)
        if matches:
            return matches[0]
        time.sleep(0.1)
    raise RuntimeError(f"visible Chrome window not found for process {process_id}")


def visible_window_rect(hwnd: int) -> wintypes.RECT:
    """Return DWM's visible frame, excluding transparent resize borders/shadow."""
    rect = wintypes.RECT()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)  # DWMWA_EXTENDED_FRAME_BOUNDS
    )
    if result != 0 and not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    return rect


def prepare_window(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    user32.AllowSetForegroundWindow(0xFFFFFFFF)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if not user32.SetWindowPos(hwnd, 0, 0, 0, WIDTH, HEIGHT, 0x0040):
        raise ctypes.WinError()
    # GetWindowRect includes transparent resize borders. Grow the outer window
    # until DWM's actually visible frame is the exact Store canvas size.
    for _attempt in range(3):
        visible = visible_window_rect(hwnd)
        visible_width = visible.right - visible.left
        visible_height = visible.bottom - visible.top
        if (visible_width, visible_height) == (WIDTH, HEIGHT):
            break
        outer = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(outer)):
            raise ctypes.WinError()
        outer_width = outer.right - outer.left + (WIDTH - visible_width)
        outer_height = outer.bottom - outer.top + (HEIGHT - visible_height)
        if not user32.SetWindowPos(hwnd, 0, 0, 0, outer_width, outer_height, 0x0040):
            raise ctypes.WinError()
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetActiveWindow(hwnd)
    time.sleep(1.0)


def open_extension_from_keyboard(hwnd: int) -> None:
    """Send the manifest's Ctrl+Shift+H action as a genuine OS key gesture."""
    user32 = ctypes.windll.user32
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetActiveWindow(hwnd)
    time.sleep(0.15)
    key_up = 0x0002
    for virtual_key in (0x11, 0x10, 0x48):  # Ctrl, Shift, H
        user32.keybd_event(virtual_key, 0, 0, 0)
    for virtual_key in (0x48, 0x10, 0x11):
        user32.keybd_event(virtual_key, 0, key_up, 0)


def open_side_panel(debug_port: int, hwnd: int) -> list[dict]:
    last_error = None
    for _attempt in range(3):
        open_extension_from_keyboard(hwnd)
        try:
            return live.wait_for_targets(debug_port, lambda items: any(
                item.get("url", "").endswith("/src/sidepanel.html") for item in items
            ), timeout=4)
        except RuntimeError as error:
            last_error = error
    raise RuntimeError(f"extension keyboard action did not open the side panel: {last_error}")


def capture_window(hwnd: int, output: Path) -> tuple[int, int]:
    time.sleep(1.5)
    rect = visible_window_rect(hwnd)
    bounds = (rect.left, rect.top, rect.right, rect.bottom)
    image = ImageGrab.grab(bbox=bounds, all_screens=True)
    if image.size != (WIDTH, HEIGHT):
        raise RuntimeError(f"captured window is {image.width}x{image.height}, expected {WIDTH}x{HEIGHT}")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
    return image.size


def capture(browser_binary: Path, output: Path, force: bool) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("the Store screenshot capture currently requires Windows")
    if output.exists() and not force:
        raise RuntimeError(f"refusing to overwrite existing screenshot: {output}")

    broker_port = live.free_port()
    debug_port = live.free_port()
    browser_process = None
    client = None
    with temporary_capture_root() as temp_root, live.fixture_server() as http_port:
        broker_log = (temp_root / "broker.log").open("w", encoding="utf-8")
        browser_log = (temp_root / "browser.log").open("w", encoding="utf-8")
        broker_process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "hermes-plugin" / "broker.py"),
                "--serve",
                "--root",
                str(temp_root),
                "--host",
                "127.0.0.1",
                "--port",
                str(broker_port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=broker_log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_port(broker_port, broker_process)
            secret = live.broker.load_or_create_secret(temp_root)
            demo_url = f"http://127.0.0.1:{http_port}/store-demo.html"
            browser_process = subprocess.Popen(
                [
                    str(browser_binary),
                    f"--user-data-dir={temp_root / 'chrome-data'}",
                    f"--remote-debugging-port={debug_port}",
                    "--remote-allow-origins=*",
                    f"--disable-extensions-except={live.EXTENSION}",
                    f"--load-extension={live.EXTENSION}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-infobars",
                    "--test-type=browser",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-sync",
                    "--force-device-scale-factor=1",
                    f"--window-size={WIDTH},{HEIGHT}",
                    "--window-position=0,0",
                    demo_url,
                ],
                stdin=subprocess.DEVNULL,
                stdout=browser_log,
                stderr=subprocess.STDOUT,
            )
            targets = live.wait_for_targets(debug_port, lambda items: any(
                item.get("type") == "service_worker" and item.get("url", "").endswith("/src/background.js")
                for item in items
            ))
            worker = live.service_worker(targets)
            browser_id = "store-capture-browser"
            initial_state = {
                "hermesUrl": f"http://127.0.0.1:{http_port}/",
                "settings": {
                    "bridgeUrl": f"ws://127.0.0.1:{broker_port}",
                    "pairingCode": secret,
                    "trustedInput": False,
                    "showOverlay": False,
                },
                "identity": {"browserId": browser_id, "browserName": "Personal Chrome"},
                "pairing": {"pairedAt": 0},
                "bindings": {},
                "selectedScope": {"profileId": "profile-a", "sessionId": "session-a"},
            }
            worker_cdp = live.Cdp(worker["webSocketDebuggerUrl"])
            try:
                worker_cdp.call("Runtime.enable")
                setup = worker_cdp.evaluate(
                    "(async()=>{"
                    "const [tab]=await chrome.tabs.query({active:true,lastFocusedWindow:true});"
                    f"await chrome.storage.local.clear();await chrome.storage.local.set({json.dumps(initial_state)});"
                    "return {tabId:tab.id,windowId:tab.windowId};})()"
                )
                commands = worker_cdp.evaluate("(async()=>await chrome.commands.getAll())()")
            finally:
                worker_cdp.close()

            action_command = next((item for item in commands if item.get("name") == "_execute_action"), None)
            if not action_command or action_command.get("shortcut") != "Ctrl+Shift+H":
                raise RuntimeError(f"extension action shortcut was not registered: {commands}")

            client = live.bridge_client.BridgeClient(
                "profile-a", root=temp_root, port=broker_port, auto_start_broker=False
            ).start()

            hwnd = find_browser_window(browser_process.pid)
            prepare_window(hwnd)
            panel_targets = open_side_panel(debug_port, hwnd)
            panel_target = next(
                item for item in panel_targets if item.get("url", "").endswith("/src/sidepanel.html")
            )
            live.wait_client(client, browser_id)
            panel = live.Cdp(panel_target["webSocketDebuggerUrl"])
            try:
                attached = panel.evaluate(
                    "(async()=>await chrome.runtime.sendMessage({"
                    "cmd:'attachTab',profileId:'profile-a',sessionId:'session-a',"
                    f"tabId:{setup['tabId']}"
                    "}))()"
                )
                if not attached or not attached.get("ok"):
                    raise RuntimeError(f"could not attach the demo tab: {attached}")
                state = wait_panel(panel)
            finally:
                panel.close()

            width, height = capture_window(hwnd, output)
            return {
                "ok": True,
                "output": str(output),
                "width": width,
                "height": height,
                "panel": state,
            }
        finally:
            if client is not None:
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
            browser_log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture the real Hermes Connector Store screenshot")
    parser.add_argument("--browser", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    result = capture(live.find_chromium(args.browser), args.output.resolve(), args.force)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
