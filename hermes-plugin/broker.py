"""Multiplexed loopback broker for Hermes Connector.

One detached broker process owns the public loopback port. Chrome extension
instances and Hermes plugin instances authenticate as different roles, then the
broker routes an exact ``profileId + sessionId`` scope to its bound browser.

This module deliberately has no package-relative imports so it can be launched
directly by :mod:`bridge_client` on Windows, macOS, and Linux.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any, Dict, Optional

try:
    import websockets
except ImportError:  # pragma: no cover - reported by the companion client
    websockets = None


PROTOCOL_VERSION = 3
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_BINDINGS_PER_BROWSER = 256
MAX_TABS_PER_BINDING = 64
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def hermes_root(home: Optional[str] = None) -> Path:
    """Return the Hermes root even when HERMES_HOME points at a profile."""

    raw = home or os.environ.get("HERMES_HOME")
    if raw:
        path = Path(raw).expanduser().resolve()
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"
    else:
        path = Path.home() / ".hermes"

    if path.parent.name == "profiles":
        return path.parent.parent
    return path


def connector_dir(root: Optional[str | Path] = None) -> Path:
    base = Path(root).expanduser().resolve() if root else hermes_root()
    return base / "connector"


def secret_path(root: Optional[str | Path] = None) -> Path:
    return connector_dir(root) / "credentials.json"


def state_path(root: Optional[str | Path] = None) -> Path:
    return connector_dir(root) / "broker-state.json"


def log_path(root: Optional[str | Path] = None) -> Path:
    return connector_dir(root) / "broker.log"


def _restrict_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_create_secret(root: Optional[str | Path] = None) -> str:
    """Return a persistent 256-bit pairing secret, creating it atomically."""

    path = secret_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = str(data.get("secret", ""))
        if re.fullmatch(r"[0-9a-f]{64}", value):
            _restrict_file(path)
            return value
        raise RuntimeError("invalid Hermes Connector credentials file")
    except FileNotFoundError:
        pass

    value = secrets.token_hex(32)
    payload = json.dumps({"version": 1, "secret": value}, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        # Another Hermes profile won the creation race.
        return load_or_create_secret(root)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
    _restrict_file(path)
    return value


def role_proof(secret: str, role: str, client_id: str, nonce: str) -> str:
    message = f"{role}:{client_id}:{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def broker_proof(secret: str, role: str, client_id: str, nonce: str) -> str:
    message = f"broker:{role}:{client_id}:{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def scope_key(profile_id: str, session_id: str) -> str:
    return f"{profile_id}\u001f{session_id}"


def clean_id(value: Any, label: str) -> str:
    text = str(value or "")
    if not CLIENT_ID_RE.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


@dataclass
class Binding:
    profile_id: str
    session_id: str
    tab_ids: list[int]
    active_tab_id: int
    updated_at: float = field(default_factory=time.time)

    @property
    def key(self) -> str:
        return scope_key(self.profile_id, self.session_id)

    def wire(self) -> dict:
        return {
            "profileId": self.profile_id,
            "sessionId": self.session_id,
            "tabIds": list(self.tab_ids),
            "activeTabId": self.active_tab_id,
        }


@dataclass
class BrowserPeer:
    websocket: Any
    browser_id: str
    name: str
    origin: str
    bindings: Dict[str, Binding] = field(default_factory=dict)
    connected_at: float = field(default_factory=time.time)


@dataclass
class AgentPeer:
    websocket: Any
    profile_id: str
    process_id: str
    connected_at: float = field(default_factory=time.time)

    @property
    def key(self) -> str:
        return f"{self.profile_id}:{self.process_id}"


@dataclass
class PendingAction:
    broker_id: str
    agent: AgentPeer
    agent_request_id: str
    browser_id: str
    created_at: float = field(default_factory=time.time)


class BrokerServer:
    """Authenticated in-memory router with a small persistent preference map."""

    def __init__(self, root: Optional[str | Path] = None, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, secret: Optional[str] = None):
        self.root = connector_dir(root).parent
        self.host = host
        self.port = int(port)
        self.secret = secret or load_or_create_secret(self.root)
        self.server = None
        self.browsers: Dict[str, BrowserPeer] = {}
        self.agents: Dict[str, AgentPeer] = {}
        self.pending: Dict[str, PendingAction] = {}
        self.scope_browsers: Dict[str, str] = self._load_preferences()
        self.binding_lock = asyncio.Lock()

    # -- persistence -----------------------------------------------------

    def _load_preferences(self) -> Dict[str, str]:
        path = state_path(self.root)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("scopeBrowsers", {})
            if not isinstance(raw, dict):
                return {}
            return {
                str(key): str(value)
                for key, value in raw.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        except Exception:
            return {}

    def _save_preferences(self) -> None:
        path = state_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {
            "version": 1,
            "scopeBrowsers": self.scope_browsers,
            "updatedAt": int(time.time()),
        }
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        _restrict_file(tmp)
        os.replace(tmp, path)
        _restrict_file(path)

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        if websockets is None:
            raise RuntimeError("the websockets package is required")
        self.server = await websockets.serve(
            self._handler,
            self.host,
            self.port,
            max_size=MAX_FRAME_BYTES,
            ping_interval=20,
            ping_timeout=20,
        )
        sockets = getattr(self.server, "sockets", None) or []
        if sockets:
            self.port = int(sockets[0].getsockname()[1])

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        peers = [p.websocket for p in self.browsers.values()]
        peers += [p.websocket for p in self.agents.values()]
        for websocket in peers:
            try:
                await websocket.close()
            except Exception:
                pass

    async def serve_forever(self) -> None:
        await self.start()
        await asyncio.Future()

    # -- authentication --------------------------------------------------

    @staticmethod
    def _origin(websocket: Any) -> str:
        request = getattr(websocket, "request", None)
        headers = getattr(request, "headers", None) or getattr(websocket, "request_headers", None)
        if headers is None:
            return ""
        try:
            return str(headers.get("Origin") or headers.get("origin") or "")
        except Exception:
            return ""

    async def _handler(self, websocket: Any) -> None:
        nonce = secrets.token_hex(16)
        peer: BrowserPeer | AgentPeer | None = None
        try:
            await websocket.send(json.dumps({
                "type": "challenge",
                "nonce": nonce,
                "protocol": PROTOCOL_VERSION,
            }))
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            hello = self._parse(raw)
            if hello.get("type") != "hello" or hello.get("protocol") != PROTOCOL_VERSION:
                await websocket.close(code=1002, reason="protocol mismatch")
                return

            role = str(hello.get("role") or "")
            if role == "browser":
                peer = await self._authenticate_browser(websocket, hello, nonce)
            elif role == "agent":
                peer = await self._authenticate_agent(websocket, hello, nonce)
            else:
                await websocket.close(code=1008, reason="invalid role")
                return
            if peer is None:
                return

            async for next_raw in websocket:
                message = self._parse(next_raw)
                if isinstance(peer, BrowserPeer):
                    await self._on_browser(peer, message)
                else:
                    await self._on_agent(peer, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Network disconnects and malformed local clients are isolated to
            # their own connection. Detailed tracebacks belong in broker.log.
            pass
        finally:
            if isinstance(peer, BrowserPeer):
                await self._drop_browser(peer)
            elif isinstance(peer, AgentPeer):
                await self._drop_agent(peer)

    @staticmethod
    def _parse(raw: Any) -> dict:
        if not isinstance(raw, str) or len(raw) > MAX_TEXT_CHARS:
            raise ValueError("invalid frame")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("message must be an object")
        return value

    async def _authenticate_browser(self, websocket: Any, hello: dict,
                                    server_nonce: str) -> Optional[BrowserPeer]:
        origin = self._origin(websocket)
        if not origin.startswith("chrome-extension://"):
            await websocket.close(code=1008, reason="browser origin required")
            return None
        browser_id = clean_id(hello.get("browserId"), "browserId")
        supplied = str(hello.get("proof") or "")
        expected = role_proof(self.secret, "browser", browser_id, server_nonce)
        if not hmac.compare_digest(supplied, expected):
            await websocket.send(json.dumps({"type": "pair_denied", "reason": "invalid pairing code"}))
            await websocket.close(code=1008, reason="authentication failed")
            return None

        name = str(hello.get("browserName") or "Chrome")[:120]
        old = self.browsers.get(browser_id)
        peer = BrowserPeer(websocket, browser_id, name, origin)
        self.browsers[browser_id] = peer
        if old is not None and old.websocket is not websocket:
            try:
                await old.websocket.close(code=1000, reason="browser reconnected")
            except Exception:
                pass

        client_nonce = clean_id(hello.get("nonce"), "nonce")
        await websocket.send(json.dumps({
            "type": "paired",
            "ok": True,
            "role": "browser",
            "browserId": browser_id,
            "browserName": name,
            "proof": broker_proof(self.secret, "browser", browser_id, client_nonce),
            "protocol": PROTOCOL_VERSION,
            "brokerState": self._public_state(),
        }))
        await self._broadcast_state()
        return peer

    async def _authenticate_agent(self, websocket: Any, hello: dict,
                                  server_nonce: str) -> Optional[AgentPeer]:
        # Python websocket clients do not send an Origin. Reject an HTTP page or
        # extension trying to impersonate the privileged companion role.
        if self._origin(websocket):
            await websocket.close(code=1008, reason="agent origin forbidden")
            return None
        profile_id = clean_id(hello.get("profileId"), "profileId")
        process_id = clean_id(hello.get("processId"), "processId")
        client_id = f"{profile_id}:{process_id}"
        supplied = str(hello.get("proof") or "")
        expected = role_proof(self.secret, "agent", client_id, server_nonce)
        if not hmac.compare_digest(supplied, expected):
            await websocket.close(code=1008, reason="authentication failed")
            return None

        peer = AgentPeer(websocket, profile_id, process_id)
        old = self.agents.get(peer.key)
        self.agents[peer.key] = peer
        if old is not None and old.websocket is not websocket:
            try:
                await old.websocket.close(code=1000, reason="agent reconnected")
            except Exception:
                pass

        client_nonce = clean_id(hello.get("nonce"), "nonce")
        await websocket.send(json.dumps({
            "type": "agent_paired",
            "ok": True,
            "role": "agent",
            "profileId": profile_id,
            "proof": broker_proof(self.secret, "agent", client_id, client_nonce),
            "protocol": PROTOCOL_VERSION,
            "brokerState": self._public_state(),
        }))
        await self._broadcast_state()
        return peer

    # -- browser messages ------------------------------------------------

    @staticmethod
    def _binding(payload: dict) -> Binding:
        profile_id = clean_id(payload.get("profileId"), "profileId")
        session_id = clean_id(payload.get("sessionId"), "sessionId")
        raw_tabs = payload.get("tabIds")
        if not isinstance(raw_tabs, list) or len(raw_tabs) > MAX_TABS_PER_BINDING:
            raise ValueError("invalid tabIds")
        tab_ids = []
        for raw in raw_tabs:
            if not isinstance(raw, int) or raw < 0:
                raise ValueError("invalid tabId")
            if raw not in tab_ids:
                tab_ids.append(raw)
        active = payload.get("activeTabId")
        if not isinstance(active, int) or active not in tab_ids:
            raise ValueError("activeTabId must belong to tabIds")
        return Binding(profile_id, session_id, tab_ids, active)

    async def _on_browser(self, peer: BrowserPeer, message: dict) -> None:
        kind = message.get("type")
        if kind == "binding_sync":
            async with self.binding_lock:
                raw_bindings = message.get("bindings")
                if not isinstance(raw_bindings, list) or len(raw_bindings) > MAX_BINDINGS_PER_BROWSER:
                    raise ValueError("invalid bindings")
                incoming: Dict[str, Binding] = {}
                for raw in raw_bindings:
                    if not isinstance(raw, dict):
                        raise ValueError("invalid binding")
                    binding = self._binding(raw)
                    incoming[binding.key] = binding

                # A reconnect is a state restoration, not a new ownership claim. If another Chrome
                # profile owns a scope, reject this stale local copy and tell the reconnecting extension
                # to remove it. Moving a scope requires an explicit binding_update from the UI.
                accepted: Dict[str, Binding] = {}
                revoked: list[Binding] = []
                for key, binding in incoming.items():
                    owner = self.scope_browsers.get(key)
                    if owner and owner != peer.browser_id:
                        revoked.append(binding)
                        continue
                    accepted[key] = binding
                    self.scope_browsers[key] = peer.browser_id

                # Missing bindings from the browser's full sync are explicit local detachments.
                for key, owner in list(self.scope_browsers.items()):
                    if owner == peer.browser_id and key not in incoming:
                        self.scope_browsers.pop(key, None)
                peer.bindings = accepted
                self._save_preferences()
                for binding in revoked:
                    await self._send_binding_revoked(peer, binding)
                await self._broadcast_state()
        elif kind == "binding_update":
            async with self.binding_lock:
                binding = self._binding(message)
                # Explicit UI attachment transfers this exact scope and clears stale ownership in any
                # other connected Chrome profile. The lock makes simultaneous UI transfers last-writer-wins
                # without leaving two browser peers claiming the same session.
                for other in list(self.browsers.values()):
                    if other is peer or binding.key not in other.bindings:
                        continue
                    other.bindings.pop(binding.key, None)
                    await self._send_binding_revoked(other, binding)
                peer.bindings[binding.key] = binding
                self.scope_browsers[binding.key] = peer.browser_id
                self._save_preferences()
                await self._broadcast_state()
        elif kind == "binding_remove":
            async with self.binding_lock:
                profile_id = clean_id(message.get("profileId"), "profileId")
                session_id = clean_id(message.get("sessionId"), "sessionId")
                key = scope_key(profile_id, session_id)
                peer.bindings.pop(key, None)
                if self.scope_browsers.get(key) == peer.browser_id:
                    self.scope_browsers.pop(key, None)
                    self._save_preferences()
                await self._broadcast_state()
        elif kind == "action_result":
            await self._finish_action(peer, message)
        elif kind in {"event", "pong"}:
            return

    @staticmethod
    async def _send_binding_revoked(peer: BrowserPeer, binding: Binding) -> None:
        try:
            await peer.websocket.send(json.dumps({
                "type": "binding_revoked",
                "profileId": binding.profile_id,
                "sessionId": binding.session_id,
                "reason": "this Hermes session was attached in another Chrome profile",
            }))
        except Exception:
            pass

    async def _finish_action(self, peer: BrowserPeer, message: dict) -> None:
        broker_id = str(message.get("id") or "")
        pending = self.pending.get(broker_id)
        if pending is None or pending.browser_id != peer.browser_id:
            return
        self.pending.pop(broker_id, None)
        payload = {
            "type": "agent_response",
            "id": pending.agent_request_id,
            "ok": bool(message.get("ok")),
            "data": message.get("data"),
            "error": message.get("error"),
        }
        try:
            await pending.agent.websocket.send(json.dumps(payload))
        except Exception:
            pass

    # -- agent messages --------------------------------------------------

    async def _on_agent(self, peer: AgentPeer, message: dict) -> None:
        kind = message.get("type")
        if kind == "agent_request":
            await self._route_action(peer, message)
        elif kind == "status_request":
            await peer.websocket.send(json.dumps({
                "type": "status_response",
                "id": str(message.get("id") or ""),
                "ok": True,
                "data": self._public_state(),
            }))
        elif kind in {"event", "pong"}:
            return

    async def _route_action(self, peer: AgentPeer, message: dict) -> None:
        request_id = str(message.get("id") or "")
        if not request_id or len(request_id) > 160:
            raise ValueError("invalid request id")
        profile_id = clean_id(message.get("profileId") or peer.profile_id, "profileId")
        if profile_id != peer.profile_id:
            await self._agent_error(peer, request_id, "agent cannot impersonate another Hermes profile")
            return
        session_id = clean_id(message.get("sessionId"), "sessionId")
        action = message.get("action")
        if not isinstance(action, dict):
            await self._agent_error(peer, request_id, "invalid action")
            return

        key = scope_key(profile_id, session_id)
        browser_id = self.scope_browsers.get(key)
        browser = self.browsers.get(browser_id or "")
        binding = browser.bindings.get(key) if browser else None
        if browser is None or binding is None:
            await self._agent_error(
                peer,
                request_id,
                "no Chrome tabs are attached to this Hermes session; open Hermes Connector and attach a tab",
            )
            return

        broker_id = secrets.token_hex(16)
        pending = PendingAction(broker_id, peer, request_id, browser.browser_id)
        self.pending[broker_id] = pending
        timeout = min(max(float(message.get("timeout") or 30), 1), 120)
        payload = {
            "type": "action",
            "id": broker_id,
            "action": action,
            "scope": {"profileId": profile_id, "sessionId": session_id},
            "targetTabId": binding.active_tab_id,
        }
        try:
            await browser.websocket.send(json.dumps(payload))
        except Exception:
            self.pending.pop(broker_id, None)
            await self._agent_error(peer, request_id, "the bound Chrome instance disconnected")
            return
        asyncio.create_task(self._expire_action(broker_id, timeout))

    async def _expire_action(self, broker_id: str, timeout: float) -> None:
        await asyncio.sleep(timeout)
        pending = self.pending.pop(broker_id, None)
        if pending is not None:
            await self._agent_error(pending.agent, pending.agent_request_id, "browser action timed out")

    @staticmethod
    async def _agent_error(peer: AgentPeer, request_id: str, error: str) -> None:
        try:
            await peer.websocket.send(json.dumps({
                "type": "agent_response",
                "id": request_id,
                "ok": False,
                "error": error,
            }))
        except Exception:
            pass

    # -- state and disconnects -------------------------------------------

    def _public_state(self) -> dict:
        browsers = []
        for peer in sorted(self.browsers.values(), key=lambda item: item.browser_id):
            browsers.append({
                "browserId": peer.browser_id,
                "name": peer.name,
                "connected": True,
                "bindings": [binding.wire() for binding in peer.bindings.values()],
            })
        return {
            "protocol": PROTOCOL_VERSION,
            "browsers": browsers,
            "agentProfiles": sorted({peer.profile_id for peer in self.agents.values()}),
            "pendingActions": len(self.pending),
        }

    async def _broadcast_state(self) -> None:
        payload = json.dumps({"type": "broker_state", "data": self._public_state()})
        peers = [peer.websocket for peer in self.agents.values()]
        peers += [peer.websocket for peer in self.browsers.values()]
        for websocket in peers:
            try:
                await websocket.send(payload)
            except Exception:
                pass

    async def _drop_browser(self, peer: BrowserPeer) -> None:
        if self.browsers.get(peer.browser_id) is not peer:
            return
        self.browsers.pop(peer.browser_id, None)
        doomed = [item for item in self.pending.values() if item.browser_id == peer.browser_id]
        for pending in doomed:
            self.pending.pop(pending.broker_id, None)
            await self._agent_error(pending.agent, pending.agent_request_id,
                                    "the bound Chrome instance disconnected")
        await self._broadcast_state()

    async def _drop_agent(self, peer: AgentPeer) -> None:
        if self.agents.get(peer.key) is not peer:
            return
        self.agents.pop(peer.key, None)
        doomed = [item.broker_id for item in self.pending.values() if item.agent is peer]
        for broker_id in doomed:
            self.pending.pop(broker_id, None)
        await self._broadcast_state()


async def _run_from_args(args: argparse.Namespace) -> None:
    server = BrokerServer(root=args.root, host=args.host, port=args.port)
    await server.start()
    print(f"Hermes Connector broker listening on ws://{server.host}:{server.port}", flush=True)
    try:
        await asyncio.Future()
    finally:
        await server.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Connector local broker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="run the broker")
    mode.add_argument("--show-code", action="store_true", help="print the local pairing code")
    parser.add_argument("--root", default=None, help="Hermes root directory")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    if args.show_code:
        print(load_or_create_secret(args.root), flush=True)
        return 0
    try:
        asyncio.run(_run_from_args(args))
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"Hermes Connector broker failed: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
