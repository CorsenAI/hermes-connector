"""Hermes-side client for the single multiplexed Connector broker."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Optional

try:
    import websockets
except ImportError:  # pragma: no cover - reported in status
    websockets = None

from . import broker


class BridgeClient:
    """Thread-safe synchronous facade used by Hermes tool handlers.

    The network connection lives on a dedicated asyncio thread. Every request
    carries the real Hermes profile and tool-call session id to the broker.
    """

    def __init__(self, profile_id: str, root: Optional[str | Path] = None,
                 host: str = broker.DEFAULT_HOST, port: Optional[int] = None,
                 auto_start_broker: bool = True):
        self.profile_id = broker.clean_id(profile_id or "default", "profileId")
        self.root = broker.hermes_root(str(root)) if root else broker.hermes_root()
        self.host = host
        self.port = int(port or os.environ.get("HERMES_BRIDGE_PORT", broker.DEFAULT_PORT))
        self.url = f"ws://{self.host}:{self.port}"
        self.auto_start_broker = auto_start_broker
        self.process_id = f"{os.getpid()}-{secrets.token_hex(4)}"
        self.secret = broker.load_or_create_secret(self.root)

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._main_task: Optional[asyncio.Task] = None
        self.conn = None
        self.connected = False
        self.last_error: Optional[str] = None
        self.broker_state = {"protocol": broker.PROTOCOL_VERSION, "browsers": [], "agentProfiles": []}
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = 0
        self._ready = threading.Event()
        self._stop = threading.Event()

    # -- properties ------------------------------------------------------

    @property
    def paired(self) -> bool:
        return self.connected and bool(self.broker_state.get("browsers"))

    @property
    def browser_name(self) -> Optional[str]:
        browsers = self.broker_state.get("browsers") or []
        return browsers[0].get("name") if len(browsers) == 1 else None

    # -- lifecycle -------------------------------------------------------

    def start(self, wait: float = 5.0):
        if websockets is None or self.thread is not None:
            if websockets is None:
                self.last_error = "the websockets package is not installed"
            return self
        if self.auto_start_broker:
            self._ensure_broker_process()
        self.thread = threading.Thread(
            target=self._thread_main,
            name=f"hermes-connector-{self.profile_id}",
            daemon=True,
        )
        self.thread.start()
        self._ready.wait(timeout=wait)
        return self

    def stop(self, wait: float = 3.0) -> None:
        self._stop.set()
        if self.loop and self.loop.is_running():
            task = self._main_task
            if task is not None:
                self.loop.call_soon_threadsafe(task.cancel)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=wait)

    def _thread_main(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self._main_task = self.loop.create_task(self._connect_forever())
            self.loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        finally:
            self.connected = False
            self.conn = None
            self._main_task = None
            try:
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            except Exception:
                pass
            self.loop.close()

    def _port_open(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=0.25):
                return True
        except OSError:
            return False

    def _ensure_broker_process(self) -> None:
        if self._port_open():
            return
        directory = broker.connector_dir(self.root)
        directory.mkdir(parents=True, exist_ok=True)
        log_file = open(broker.log_path(self.root), "a", encoding="utf-8")
        command = [
            sys.executable,
            str(Path(broker.__file__).resolve()),
            "--serve",
            "--root", str(self.root),
            "--host", self.host,
            "--port", str(self.port),
        ]
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_file,
            "stderr": log_file,
            "cwd": str(directory),
            "close_fds": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(command, **kwargs)
        except Exception as exc:
            self.last_error = f"could not start broker: {type(exc).__name__}"
        finally:
            log_file.close()

    # -- websocket -------------------------------------------------------

    async def _connect_forever(self) -> None:
        delay = 0.25
        while not self._stop.is_set():
            try:
                await self._connect_once()
                delay = 0.25
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)[:300] or type(exc).__name__
            finally:
                self.connected = False
                self.conn = None
                self._fail_pending("broker disconnected")
                self._ready.set()
            if not self._stop.is_set():
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)

    async def _connect_once(self) -> None:
        async with websockets.connect(
            self.url,
            max_size=broker.MAX_FRAME_BYTES,
            open_timeout=3,
            ping_interval=20,
            ping_timeout=20,
        ) as websocket:
            challenge = self._parse(await asyncio.wait_for(websocket.recv(), timeout=5))
            if challenge.get("type") != "challenge" or challenge.get("protocol") != broker.PROTOCOL_VERSION:
                raise RuntimeError("another or incompatible service owns the Connector port")
            server_nonce = broker.clean_id(challenge.get("nonce"), "nonce")
            client_id = f"{self.profile_id}:{self.process_id}"
            client_nonce = secrets.token_hex(16)
            await websocket.send(json.dumps({
                "type": "hello",
                "role": "agent",
                "profileId": self.profile_id,
                "processId": self.process_id,
                "nonce": client_nonce,
                "proof": broker.role_proof(self.secret, "agent", client_id, server_nonce),
                "protocol": broker.PROTOCOL_VERSION,
            }))
            paired = self._parse(await asyncio.wait_for(websocket.recv(), timeout=5))
            expected = broker.broker_proof(
                self.secret, "agent", client_id, client_nonce
            )
            if paired.get("type") != "agent_paired" or not paired.get("ok"):
                raise RuntimeError("broker rejected the Hermes companion")
            if not secrets.compare_digest(str(paired.get("proof") or ""), expected):
                raise RuntimeError("broker identity check failed")

            self.conn = websocket
            self.connected = True
            self.last_error = None
            if isinstance(paired.get("brokerState"), dict):
                self.broker_state = paired["brokerState"]
            self._ready.set()
            async for raw in websocket:
                message = self._parse(raw)
                kind = message.get("type")
                if kind == "broker_state" and isinstance(message.get("data"), dict):
                    self.broker_state = message["data"]
                elif kind in {"agent_response", "status_response"}:
                    future = self._pending.get(str(message.get("id") or ""))
                    if future is not None and not future.done():
                        future.set_result(message)

    @staticmethod
    def _parse(raw: Any) -> dict:
        if not isinstance(raw, str) or len(raw) > broker.MAX_TEXT_CHARS:
            raise RuntimeError("invalid broker frame")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError("invalid broker message")
        return value

    def _fail_pending(self, error: str) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_result({"ok": False, "error": error})

    # -- synchronous facade ---------------------------------------------

    def _call(self, payload: dict, timeout: float) -> dict:
        if not self.connected or self.conn is None or self.loop is None:
            return {"ok": False, "error": self.last_error or "Connector broker is not connected"}
        future = asyncio.run_coroutine_threadsafe(self._rpc(payload, timeout), self.loop)
        try:
            return future.result(timeout=timeout + 2)
        except Exception as exc:
            return {"ok": False, "error": f"broker did not respond: {type(exc).__name__}"}

    async def _rpc(self, payload: dict, timeout: float) -> dict:
        if self.conn is None:
            return {"ok": False, "error": "Connector broker is not connected"}
        self._counter += 1
        request_id = f"{self.process_id}-{self._counter}"
        message = {**payload, "id": request_id}
        result = self.loop.create_future()
        self._pending[request_id] = result
        try:
            await self.conn.send(json.dumps(message))
            return await asyncio.wait_for(result, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    def request(self, action: dict, timeout: float = 30,
                session_id: Optional[str] = None, task_id: Optional[str] = None) -> dict:
        if not session_id:
            return {"ok": False, "error": "Hermes did not provide a session_id for this tool call"}
        payload = {
            "type": "agent_request",
            "profileId": self.profile_id,
            "sessionId": str(session_id),
            "taskId": str(task_id or session_id),
            "action": action,
            "timeout": timeout,
        }
        response = self._call(payload, float(timeout))
        return {
            "ok": bool(response.get("ok")),
            "data": response.get("data"),
            "error": response.get("error"),
        }

    def refresh_status(self, timeout: float = 3) -> dict:
        response = self._call({"type": "status_request"}, timeout)
        if response.get("ok") and isinstance(response.get("data"), dict):
            self.broker_state = response["data"]
        return self.status()

    def status(self) -> dict:
        return {
            "server": self.connected,
            "connected": self.connected,
            "paired": self.paired,
            "port": self.port,
            "profile": self.profile_id,
            "browser": self.browser_name,
            "browsers": self.broker_state.get("browsers") or [],
            "agent_profiles": self.broker_state.get("agentProfiles") or [],
            "protocol": broker.PROTOCOL_VERSION,
            "error": self.last_error,
        }
