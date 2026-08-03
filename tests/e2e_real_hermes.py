#!/usr/bin/env python3
"""Opt-in acceptance with a real Hermes model turn and a real Chrome tab.

The normal release gate is deterministic and never consumes model inference.
This test clones only the selected profile's model configuration into a
temporary Hermes home, installs the candidate companion there, launches an
isolated Chrome profile with the candidate extension, and proves from Hermes'
own agent log that the model called the ``bridge_*`` tools.
"""

from __future__ import annotations

import argparse
import atexit
from contextlib import contextmanager
import importlib.util
import io
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

import e2e_chromium as live
import capture_store_screenshot as store_capture
from PIL import Image, ImageChops, ImageStat


ROOT = Path(__file__).resolve().parents[1]
SESSION_RE = re.compile(r"(?im)^session_id:\s*([A-Za-z0-9_-]+)\s*$")


def retry_private_cleanup(path: Path, *, required: bool = False) -> bool:
    """Remove a private test profile and optionally fail if any secret-bearing file remains."""

    for _ in range(75):
        if not path.exists():
            return True
        try:
            shutil.rmtree(path)
            return not path.exists()
        except OSError:
            # Windows may report either sharing violations or
            # ERROR_DIR_NOT_EMPTY while a just-terminated dashboard child
            # finishes closing/recreating its SQLite WAL files.
            time.sleep(0.2)
    if required:
        raise RuntimeError(f"private Hermes test profile could not be removed: {path}")
    return False


@contextmanager
def temporary_test_root(named_profile: bool):
    """Create a fully isolated Hermes home, optionally with a named profile layout."""

    if not named_profile:
        with tempfile.TemporaryDirectory(
            prefix="hermes-connector-real-model-", ignore_cleanup_errors=True
        ) as temp:
            root = Path(temp)
            atexit.register(retry_private_cleanup, root)
            try:
                yield root
            finally:
                retry_private_cleanup(root, required=True)
        return
    isolated_home = Path(tempfile.mkdtemp(prefix="hermes-connector-demo-home-"))
    root = isolated_home / "profiles" / "connector-demo"
    root.mkdir(parents=True)
    atexit.register(retry_private_cleanup, isolated_home)
    try:
        yield root
    finally:
        retry_private_cleanup(isolated_home, required=True)


def wait_for_port(port: int, process: subprocess.Popen, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            if process.poll() is not None:
                raise RuntimeError("candidate companion broker exited before listening")
            time.sleep(0.1)
    raise RuntimeError("candidate companion broker did not start")


def run_hermes(
    executable: str,
    env: dict[str, str],
    prompt: str,
    *,
    resume: str | None = None,
    max_turns: int = 12,
    timeout: int = 240,
    cwd: Path = ROOT,
) -> tuple[str, str]:
    command = [
        executable,
        "chat",
        "-q",
        prompt,
        "-Q",
        "--ignore-rules",
        "--max-turns",
        str(max_turns),
    ]
    if resume:
        command.extend(["--resume", resume, "--no-restore-cwd"])
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"Hermes model turn exited with code {completed.returncode}")
    return completed.stdout, completed.stderr


def copy_profile_inputs(source: Path, destination: Path) -> None:
    if not (source / "config.yaml").is_file():
        raise RuntimeError(f"Hermes source profile has no config.yaml: {source}")
    # Never copy provider secrets into the temporary profile. This acceptance
    # uses credentials already exported to the process environment (or a local
    # model configuration) and keeps the source .env at its original path.
    for name in ("config.yaml", "SOUL.md"):
        candidate = source / name
        if candidate.is_file():
            shutil.copy2(candidate, destination / name)


def install_candidate_companion(destination: Path) -> Path:
    spec = importlib.util.spec_from_file_location(
        "hermes_connector_candidate_installer", ROOT / "scripts" / "install_companion.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate companion installer could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target, previous = module.install(live.PLUGIN, destination)
    if previous is not None:
        raise RuntimeError("temporary profile unexpectedly contained an older companion")
    return target


def launch_browser(
    binary: Path,
    root: Path,
    debug_port: int,
    broker_port: int,
    secret: str,
    session_id: str,
    profile_id: str,
    headed: bool,
    dashboard_port: int | None = None,
) -> tuple[subprocess.Popen, object, dict, int]:
    browser_data = root / "chrome-data"
    browser_log_path = root / "browser.log"
    browser_log = browser_log_path.open("w", encoding="utf-8")
    arguments = [
        str(binary),
        f"--user-data-dir={browser_data}",
        f"--remote-debugging-port={debug_port}",
        "--remote-allow-origins=*",
        f"--disable-extensions-except={live.EXTENSION}",
        f"--load-extension={live.EXTENSION}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-infobars",
        "--disable-features=LaunchOnStartup",
        "--window-size=1280,900",
        "about:blank",
    ]
    if not headed:
        arguments.insert(1, "--headless=new")
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=browser_log,
        stderr=subprocess.STDOUT,
    )
    targets = live.wait_for_targets(
        debug_port,
        lambda items: any(
            item.get("type") == "service_worker"
            and item.get("url", "").endswith("/src/background.js")
            for item in items
        ),
        timeout=45,
        browser_process=process,
        browser_log_path=browser_log_path,
        browser_binary=binary,
    )
    worker = live.service_worker(targets)
    extension_id = worker["url"].split("/")[2]
    cdp = live.Cdp(worker["webSocketDebuggerUrl"])
    try:
        live.wait_for_extension_apis(cdp, extension_id)
        tab_id = cdp.evaluate(
            "(async()=>{const t=await chrome.tabs.create({url:'https://example.com/',active:true});"
            "for(let i=0;i<200;i++){const now=await chrome.tabs.get(t.id);"
            "if(now.status==='complete'&&now.url.startsWith('https://example.com'))return t.id;"
            "await new Promise(r=>setTimeout(r,50));}throw new Error('example.com did not load');})()"
        )
        initial_state = {
            "hermesUrl": f"http://127.0.0.1:{dashboard_port}/" if dashboard_port else None,
            "settings": {
                "bridgeUrl": f"ws://127.0.0.1:{broker_port}",
                "pairingCode": secret,
                "trustedInput": False,
                "showOverlay": False,
            },
            "identity": {
                "browserId": "real-hermes-e2e",
                "browserName": "Real Hermes E2E",
            },
            "bindings": {},
            "selectedScope": {"profileId": profile_id, "sessionId": session_id},
        }
        cdp.evaluate(
            "(async()=>{await chrome.storage.local.clear();"
            f"await chrome.storage.local.set({json.dumps(initial_state)});"
            "const panel=await chrome.tabs.create({url:chrome.runtime.getURL('src/sidepanel.html'),active:false});"
            "return panel.id;})()"
        )
    finally:
        cdp.close()

    panels = live.wait_for_targets(
        debug_port,
        lambda items: any(
            item.get("type") == "page" and item.get("url", "").endswith("/src/sidepanel.html")
            for item in items
        ),
        browser_process=process,
        browser_log_path=browser_log_path,
        browser_binary=binary,
    )
    panel = next(
        item for item in panels
        if item.get("type") == "page" and item.get("url", "").endswith("/src/sidepanel.html")
    )
    panel_cdp = live.Cdp(panel["webSocketDebuggerUrl"])
    try:
        paired = panel_cdp.evaluate(
            "(async()=>{for(let i=0;i<200;i++){const s=await chrome.runtime.sendMessage({cmd:'getState'});"
            "if(s&&s.paired)return true;await new Promise(r=>setTimeout(r,50));}return false;})()"
        )
        if not paired:
            raise RuntimeError("candidate extension did not pair with the candidate companion")
        attached = panel_cdp.evaluate(
            "chrome.runtime.sendMessage("
            f"{{cmd:'attachTab',profileId:{json.dumps(profile_id)},sessionId:{json.dumps(session_id)},tabId:{tab_id}}})"
        )
        if not attached or not attached.get("ok"):
            raise RuntimeError(f"real tab attachment failed: {(attached or {}).get('error')}")
    finally:
        panel_cdp.close()
    return process, browser_log, panel, int(tab_id)


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if os.name == "nt" and process.poll() is None:
        # Chrome and `hermes dashboard` spawn children. Terminating only the
        # parent can leave a PTY/SQLite child holding the cloned .env and local
        # Connector credential files. taskkill /T targets only the exact tree
        # created by this harness; verified profile cleanup below remains the
        # final fail-closed check.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def start_window_recording(hwnd: int, output: Path) -> subprocess.Popen:
    if os.name != "nt":
        raise RuntimeError("real product recording currently requires Windows")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found")
    output = output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing recording: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    rect = store_capture.visible_window_rect(hwnd)
    if (rect.right - rect.left, rect.bottom - rect.top) != (
        store_capture.WIDTH,
        store_capture.HEIGHT,
    ):
        raise RuntimeError("Chrome window must be prepared before recording")
    process = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "gdigrab",
            "-framerate",
            "30",
            "-offset_x",
            str(rect.left),
            "-offset_y",
            str(rect.top),
            "-video_size",
            f"{store_capture.WIDTH}x{store_capture.HEIGHT}",
            "-draw_mouse",
            "0",
            "-i",
            "desktop",
            "-an",
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-tune",
            "hq",
            "-rc",
            "vbr",
            "-cq",
            "18",
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    if process.poll() is not None:
        raise RuntimeError("ffmpeg exited before the real Chrome recording began")
    return process


def finish_window_recording(process: subprocess.Popen, *, check: bool) -> None:
    if process.poll() is None:
        try:
            process.stdin.write(b"q\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, AttributeError):
            pass
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    if check and process.returncode:
        raise RuntimeError(f"ffmpeg recording failed with code {process.returncode}")


def recording_frame(path: Path, timestamp: float) -> Image.Image:
    """Decode one real frame without writing another potentially stale artifact."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found")
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode or not completed.stdout:
        raise RuntimeError("could not decode a verification frame from the real recording")
    with Image.open(io.BytesIO(completed.stdout)) as decoded:
        return decoded.convert("RGB")


def validate_recording(path: Path, reference_capture: Path) -> dict:
    """Reject black/static/obstructed recordings and prove the intended UI transition."""

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe was not found")
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if probe.returncode:
        raise RuntimeError("ffprobe could not validate the real recording")
    metadata = json.loads(probe.stdout)
    streams = metadata.get("streams") or []
    video = next((stream for stream in streams if stream.get("width")), None)
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    if not video or (video.get("width"), video.get("height")) != (
        store_capture.WIDTH,
        store_capture.HEIGHT,
    ) or duration < 7:
        raise RuntimeError(f"real recording has invalid geometry/duration: {metadata}")

    timestamps = (1.5, min(3.5, duration / 2), max(1.5, duration - 1.0))
    frames = [recording_frame(path, timestamp) for timestamp in timestamps]
    for index, frame in enumerate(frames):
        gray = frame.convert("L")
        histogram = gray.histogram()
        black_fraction = sum(histogram[:4]) / (frame.width * frame.height)
        contrast = ImageStat.Stat(gray).stddev[0]
        if black_fraction > 0.65 or contrast < 15:
            raise RuntimeError(
                f"real recording frame {index} is black/blank: "
                f"black_fraction={black_fraction:.3f}, contrast={contrast:.2f}"
            )

    def mean_difference(left: Image.Image, right: Image.Image) -> float:
        return sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3

    open_delta = mean_difference(frames[0], frames[1])
    close_delta = mean_difference(frames[1], frames[2])
    if open_delta < 0.5 or close_delta < 0.5:
        raise RuntimeError(
            f"real recording did not visibly open and close the Tabs UI: "
            f"open_delta={open_delta:.3f}, close_delta={close_delta:.3f}"
        )

    with Image.open(reference_capture) as reference_image:
        reference = reference_image.convert("RGB")
    if reference.size != frames[2].size:
        raise RuntimeError("recording and final proof capture have different dimensions")
    end_delta = mean_difference(frames[2], reference)
    if end_delta > 35:
        raise RuntimeError(
            f"recording end differs too much from the unobstructed proof capture: {end_delta:.2f}"
        )
    return {
        "duration": round(duration, 3),
        "dimensions": [video["width"], video["height"]],
        "frameTimestamps": list(timestamps),
        "openDelta": round(open_delta, 3),
        "closeDelta": round(close_delta, 3),
        "endReferenceDelta": round(end_delta, 3),
    }


def run(
    source_profile: Path,
    browser: Path,
    headed: bool,
    capture: Path | None = None,
    record: Path | None = None,
) -> dict:
    hermes = shutil.which("hermes")
    if not hermes:
        raise RuntimeError("Hermes CLI was not found")
    broker_port = live.free_port()
    debug_port = live.free_port()
    browser_process = None
    broker_process = None
    dashboard_process = None
    recorder_process = None
    browser_log = None
    broker_log = None
    dashboard_log = None
    named_profile = capture is not None and os.name == "nt"
    with temporary_test_root(named_profile) as temp_root:
        profile_id = temp_root.name if named_profile else "default"
        shared_root = temp_root.parent.parent if temp_root.parent.name == "profiles" else temp_root
        copy_profile_inputs(source_profile, temp_root)
        demo_workspace = temp_root / "Example Domain Demo"
        demo_workspace.mkdir()
        installed_plugin = install_candidate_companion(temp_root)
        secret = live.broker.load_or_create_secret(shared_root)
        broker_log = (temp_root / "broker.log").open("w", encoding="utf-8")
        broker_process = subprocess.Popen(
            [
                sys.executable,
                str(installed_plugin / "broker.py"),
                "--serve",
                "--root",
                str(shared_root),
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
            hermes_env = os.environ.copy()
            hermes_env["HERMES_HOME"] = str(temp_root)
            hermes_env["HERMES_BRIDGE_PORT"] = str(broker_port)
            _, setup_stderr = run_hermes(
                hermes,
                hermes_env,
                "Reply exactly SESSION_READY. Do not call any tool.",
                max_turns=3,
                cwd=demo_workspace,
            )
            match = SESSION_RE.search(setup_stderr)
            if not match:
                raise RuntimeError("Hermes did not report a parseable session_id")
            session_id = match.group(1)

            # Reserve the dashboard URL for the extension, but do not start
            # its PTY yet. The real model turn below must be the sole process
            # resuming this session; afterward the dashboard can render the
            # persisted, proven transcript without racing a concurrent CLI.
            dashboard_port = live.free_port() if capture is not None else None

            browser_process, browser_log, panel, tab_id = launch_browser(
                browser,
                temp_root,
                debug_port,
                broker_port,
                secret,
                session_id,
                profile_id,
                headed,
                dashboard_port,
            )
            prompt = (
                "On the attached real Chrome tab, call only bridge_status, bridge_current_url, "
                "then bridge_read. After all three succeed, output four lines: CONNECTOR_E2E_OK; "
                "Page heading: <heading>; URL scheme: <scheme without punctuation>; URL host: "
                "<hostname with spaces around dots>. Never use browser_* or a Markdown link."
            )
            stdout, _ = run_hermes(
                hermes,
                hermes_env,
                prompt,
                resume=session_id,
                max_turns=10,
                cwd=demo_workspace,
            )
            agent_log_path = temp_root / "logs" / "agent.log"
            agent_log = agent_log_path.read_text(encoding="utf-8", errors="replace") \
                if agent_log_path.is_file() else ""
            required_tools = ("bridge_status", "bridge_current_url", "bridge_read")
            successful_tools = {
                name for name in required_tools
                if re.search(
                    rf"(?m)^.*\bINFO\s+\[{re.escape(session_id)}\]\s+"
                    rf"agent\.tool_executor:\s+tool\s+{re.escape(name)}\s+completed\s+\(",
                    agent_log,
                )
            }
            missing_tools = [name for name in required_tools if name not in successful_tools]
            if missing_tools:
                diagnostic_lines = [line[:500] for line in agent_log.splitlines()
                    if any(name in line for name in required_tools)][-20:]
                raise AssertionError(
                    f"Hermes did not successfully complete required Connector tools: {missing_tools}; "
                    f"tool_log_lines={diagnostic_lines!r}"
                )
            normalized = " ".join(stdout.split()).lower()
            expected_markers = (
                "connector_e2e_ok",
                "example domain",
                "url scheme: https",
                "url host: example . com",
            )
            missing_markers = [marker for marker in expected_markers if marker not in normalized]
            if missing_markers:
                diagnostic = " ".join(stdout.split())[:800]
                raise AssertionError(
                    f"Hermes called the tools but omitted {missing_markers}; final={diagnostic!r}"
                )
            if capture is not None:
                renamed = subprocess.run(
                    [
                        hermes,
                        "sessions",
                        "rename",
                        session_id,
                        "Example Domain",
                    ],
                    cwd=demo_workspace,
                    env=hermes_env,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if renamed.returncode:
                    raise RuntimeError("could not give the proven demo session a readable title")

            panel_cdp = live.Cdp(panel["webSocketDebuggerUrl"])
            try:
                list_message = json.dumps({
                    "cmd": "listTabs",
                    "profileId": profile_id,
                    "sessionId": session_id,
                })
                state = panel_cdp.evaluate(
                    f"chrome.runtime.sendMessage({list_message})"
                )
                tab_proof = panel_cdp.evaluate(
                    f"(async()=>{{const tab=await chrome.tabs.get({tab_id});"
                    "return {url:tab.url,title:tab.title};})()"
                )
            finally:
                panel_cdp.close()
            binding = (state.get("bindings") or {}).get(f"{profile_id}\x1f{session_id}")
            if not binding or binding.get("activeTabId") != tab_id:
                raise AssertionError("Hermes model turn was not pinned to the attached real tab")
            if tab_proof.get("url") != "https://example.com/" or \
                    tab_proof.get("title") != "Example Domain":
                raise AssertionError(f"attached real Chrome tab changed unexpectedly: {tab_proof}")
            result = {
                "browser": browser.name,
                "profile": f"{profile_id} (isolated clone)",
                "session": session_id,
                "page": "https://example.com/",
                "tools": list(required_tools),
                "result": "CONNECTOR_E2E_OK",
            }
            if capture is not None:
                dashboard_log = (temp_root / "dashboard.log").open("w", encoding="utf-8")
                dashboard_process = subprocess.Popen(
                    [
                        hermes,
                        "dashboard",
                        "--port",
                        str(dashboard_port),
                        "--host",
                        "127.0.0.1",
                        "--no-open",
                        "--isolated",
                        "--skip-build",
                    ],
                    cwd=ROOT,
                    env=hermes_env,
                    stdin=subprocess.DEVNULL,
                    stdout=dashboard_log,
                    stderr=subprocess.STDOUT,
                )
                wait_for_port(dashboard_port, dashboard_process, timeout=30)
                targets = live.wait_for_targets(
                    debug_port,
                    lambda items: any(
                        item.get("type") == "service_worker"
                        and item.get("url", "").endswith("/src/background.js")
                        for item in items
                    ),
                    browser_process=browser_process,
                    browser_binary=browser,
                )
                worker = live.service_worker(targets)
                worker_cdp = live.Cdp(worker["webSocketDebuggerUrl"])
                try:
                    worker_cdp.evaluate(
                        "(async()=>{const tabs=await chrome.tabs.query({});"
                        f"await chrome.tabs.update({tab_id},{{active:true}});"
                        f"const ids=tabs.filter(t=>t.id!=={tab_id}).map(t=>t.id);"
                        "if(ids.length)await chrome.tabs.remove(ids);return ids.length;})()"
                    )
                finally:
                    worker_cdp.close()
                remaining = live.http_json(f"http://127.0.0.1:{debug_port}/json/list")
                stale_panel_targets = {
                    item.get("id") for item in remaining
                    if item.get("url", "").endswith("/src/sidepanel.html")
                }
                stale_dashboard_targets = {
                    item.get("id") for item in remaining
                    if item.get("url", "").startswith(f"http://127.0.0.1:{dashboard_port}/chat")
                }
                hwnd = store_capture.find_browser_window(browser_process.pid)
                store_capture.prepare_window(hwnd)
                panel_targets = store_capture.open_side_panel(
                    debug_port, hwnd, stale_panel_targets
                )
                live_panel = next(
                    item for item in panel_targets
                    if item.get("url", "").endswith("/src/sidepanel.html")
                    and item.get("id") not in stale_panel_targets
                )
                live_panel_cdp = live.Cdp(live_panel["webSocketDebuggerUrl"])
                try:
                    panel_ready = live_panel_cdp.evaluate(
                        "(async()=>{for(let i=0;i<300;i++){const f=document.querySelector('#hermes');"
                        "const selected=document.querySelector('#sessionSelect').value;"
                        "const target=document.querySelector('#attachedTabs').textContent;"
                        "const status=document.querySelector('#status').textContent;"
                        f"if(f&&f.src.includes({json.dumps(session_id)})&&selected.includes({json.dumps(session_id)})"
                        "&&target.includes('Example Domain')&&status==='Ready · Hermes + Chrome')"
                        "return {src:f.src,status,selected,target};"
                        "await new Promise(r=>setTimeout(r,50));}return null;})()"
                    )
                finally:
                    live_panel_cdp.close()
                if not panel_ready or session_id not in panel_ready.get("src", ""):
                    raise RuntimeError(f"real Hermes dashboard did not load the tested session: {panel_ready}")
                dashboard_targets = live.wait_for_targets(
                    debug_port,
                    lambda items: any(
                        item.get("url", "").startswith(f"http://127.0.0.1:{dashboard_port}/chat")
                        and item.get("id") not in stale_dashboard_targets
                        for item in items
                    ),
                    browser_process=browser_process,
                    browser_binary=browser,
                )
                dashboard_target = next(
                    item for item in dashboard_targets
                    if item.get("url", "").startswith(f"http://127.0.0.1:{dashboard_port}/chat")
                    and item.get("id") not in stale_dashboard_targets
                )
                dashboard_cdp = live.Cdp(dashboard_target["webSocketDebuggerUrl"])
                try:
                    dashboard_text = dashboard_cdp.evaluate(
                        "(async()=>{for(let i=0;i<300;i++){const text=document.body.innerText||'';"
                        "const lower=text.toLowerCase();"
                        "if(text.includes('CONNECTOR_E2E_OK')&&text.includes('Example Domain')"
                        "&&lower.includes('url scheme: https')"
                        "&&lower.includes('url host: example . com')&&lower.includes('bridge status')"
                        "&&lower.includes('bridge current url')&&lower.includes('bridge read'))return text;"
                        "await new Promise(r=>setTimeout(r,50));}return document.body.innerText||'';})()"
                    )
                finally:
                    dashboard_cdp.close()
                dashboard_markers = (
                    "CONNECTOR_E2E_OK",
                    "Example Domain",
                    "URL scheme: https",
                    "URL host: example . com",
                    "bridge status",
                    "bridge current url",
                    "bridge read",
                )
                dashboard_lower = dashboard_text.lower()
                missing_dashboard_markers = [marker for marker in dashboard_markers
                    if marker.lower() not in dashboard_lower]
                if missing_dashboard_markers:
                    log_tail = ""
                    if dashboard_log is not None:
                        dashboard_log.flush()
                        dashboard_log_path = temp_root / "dashboard.log"
                        if dashboard_log_path.is_file():
                            log_tail = dashboard_log_path.read_text(
                                encoding="utf-8", errors="replace"
                            )[-2000:]
                    visible = " ".join(dashboard_text.split())[-800:]
                    raise RuntimeError(
                        f"real dashboard omitted proven tool/result markers "
                        f"{missing_dashboard_markers}; "
                        f"visible={visible!r}; dashboard_log={log_tail!r}"
                    )
                if record is not None:
                    store_capture.set_window_topmost(hwnd, True)
                    recorder_process = start_window_recording(hwnd, record)
                    time.sleep(1.5)
                    interaction_cdp = live.Cdp(live_panel["webSocketDebuggerUrl"])
                    try:
                        interaction_cdp.evaluate(
                            "document.querySelector('#manageTabs').click();true"
                        )
                        time.sleep(2.5)
                        interaction_cdp.evaluate(
                            "document.querySelector('#manageTabs').click();true"
                        )
                    finally:
                        interaction_cdp.close()
                    time.sleep(4)
                    finish_window_recording(recorder_process, check=True)
                    recorder_process = None
                    result["record"] = str(record.expanduser().resolve())
                capture = capture.expanduser().resolve()
                store_capture.capture_window(hwnd, capture)
                result["capture"] = str(capture)
                result["panelStatus"] = panel_ready.get("status")
                if record is not None:
                    result["recordValidation"] = validate_recording(
                        record.expanduser().resolve(), capture
                    )
            return result
        finally:
            if recorder_process is not None:
                finish_window_recording(recorder_process, check=False)
            stop_process(browser_process)
            stop_process(dashboard_process)
            stop_process(broker_process)
            if browser_log is not None:
                browser_log.close()
            if broker_log is not None:
                broker_log.close()
            if dashboard_log is not None:
                dashboard_log.close()


def main(argv: list[str] | None = None) -> int:
    default_profile = Path(os.environ.get("LOCALAPPDATA", Path.home())) / \
        "hermes" / "profiles" / "test-chrome"
    parser = argparse.ArgumentParser(description="Run a real Hermes-model + real Chrome acceptance")
    parser.add_argument("--source-profile", type=Path, default=default_profile)
    parser.add_argument("--browser")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args(argv)
    if (args.capture or args.record) and not args.headed:
        parser.error("--capture and --record require --headed")
    if args.record and not args.capture:
        parser.error("--record requires --capture so the final frame is independently verified")
    result = run(
        args.source_profile.expanduser().resolve(),
        live.find_chromium(args.browser),
        args.headed,
        args.capture,
        args.record,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
