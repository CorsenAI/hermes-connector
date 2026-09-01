"""Protocol and routing tests for the multiplexed local broker."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import websockets


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "hermes_connector_test_package"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(ROOT / "hermes-plugin")]
sys.modules[PACKAGE_NAME] = PACKAGE
SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.broker", ROOT / "hermes-plugin" / "broker.py"
)
broker = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = broker
SPEC.loader.exec_module(broker)

CLIENT_SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.bridge_client", ROOT / "hermes-plugin" / "bridge_client.py"
)
bridge_client = importlib.util.module_from_spec(CLIENT_SPEC)
assert CLIENT_SPEC and CLIENT_SPEC.loader
sys.modules[CLIENT_SPEC.name] = bridge_client
CLIENT_SPEC.loader.exec_module(bridge_client)


async def receive_type(websocket, expected: str, limit: int = 12) -> dict:
    for _ in range(limit):
        payload = json.loads(await websocket.recv())
        if payload.get("type") == expected:
            return payload
    raise AssertionError(f"did not receive {expected}")


class CredentialLifecycleTests(unittest.TestCase):
    def test_concurrent_creation_publishes_one_complete_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            barrier = threading.Barrier(2)
            real_link = broker.os.link

            def synchronized_link(source, destination):
                barrier.wait(timeout=2)
                return real_link(source, destination)

            with mock.patch.object(broker.os, "link", side_effect=synchronized_link):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(broker.load_or_create_secret, temp) for _ in range(2)]
                    values = [future.result(timeout=3) for future in futures]
            self.assertEqual(values[0], values[1])
            self.assertRegex(values[0], r"^[0-9a-f]{64}$")
            persisted = json.loads(broker.secret_path(temp).read_text(encoding="utf-8"))
            self.assertEqual(persisted["secret"], values[0])
            self.assertFalse(list(broker.connector_dir(temp).glob(".credentials-*.tmp")))

    def test_broker_rejects_non_loopback_bind_target(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "loopback"):
                broker.BrokerServer(
                    root=temp,
                    host="0.0.0.0",
                    port=0,
                    secret="0123456789abcdef" * 4,
                )


class AgentBackendValidationTests(unittest.TestCase):
    def test_accepts_only_canonical_loopback_headless_urls(self):
        self.assertEqual(
            broker.clean_agent_backend("http://127.0.0.1:51329/", "headless"),
            ("http://127.0.0.1:51329/", "headless"),
        )
        self.assertEqual(
            broker.clean_agent_backend("http://localhost:80/", "headless"),
            ("http://localhost:80/", "headless"),
        )

    def test_rejects_non_loopback_or_ambiguous_backend_metadata(self):
        invalid = (
            ("https://127.0.0.1:51329/", "headless"),
            ("http://127.0.0.2:51329/", "headless"),
            ("http://localhost:0/", "headless"),
            ("http://localhost:65536/", "headless"),
            ("http://localhost:51329", "headless"),
            ("http://localhost:51329/api/sessions", "headless"),
            ("http://localhost:51329/?token=secret", "headless"),
            ("http://user@localhost:51329/", "headless"),
            ("http://[::1]:51329/", "headless"),
            ("http://localhost:51329/", "dashboard"),
        )
        for url, mode in invalid:
            with self.subTest(url=url, mode=mode), self.assertRaises(ValueError):
                broker.clean_agent_backend(url, mode)


class BrokerStateMigrationTests(unittest.TestCase):
    def write_state(self, path: Path, owner: str, *, protocol=None) -> str:
        key = broker.scope_key("profile-a", "session-a")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "scopeBrowsers": {key: owner}}
        if protocol is not None:
            payload["protocol"] = protocol
        path.write_text(json.dumps(payload), encoding="utf-8")
        return key

    def test_v4_imports_legacy_once_and_ignores_late_v3_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            key = self.write_state(broker.legacy_state_path(temp), "browser-v3")
            first = broker.BrokerServer(
                root=temp, port=0, secret="0123456789abcdef" * 4
            )
            self.assertEqual(first.scope_browsers[key], "browser-v3")
            persisted = json.loads(broker.state_path(temp).read_text(encoding="utf-8"))
            self.assertEqual(persisted["protocol"], 4)
            self.assertEqual(persisted["scopeBrowsers"][key], "browser-v3")

            # The detached legacy process is still alive and writes later.
            self.write_state(broker.legacy_state_path(temp), "browser-zombie")
            restarted = broker.BrokerServer(
                root=temp, port=0, secret="0123456789abcdef" * 4
            )
            self.assertEqual(restarted.scope_browsers[key], "browser-v3")

    def test_present_invalid_v4_state_never_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as temp:
            key = self.write_state(broker.legacy_state_path(temp), "legacy-owner")
            self.write_state(broker.state_path(temp), "wrong-protocol-owner", protocol=3)
            server = broker.BrokerServer(
                root=temp, port=0, secret="0123456789abcdef" * 4
            )
            self.assertNotIn(key, server.scope_browsers)

    def test_concurrent_v4_saves_use_distinct_complete_temp_files(self):
        with tempfile.TemporaryDirectory() as temp:
            server = broker.BrokerServer(
                root=temp, port=0, secret="0123456789abcdef" * 4
            )
            barrier = threading.Barrier(2)
            sources = []
            seen_sources = set()
            source_lock = threading.Lock()
            real_replace = broker.os.replace

            def synchronized_replace(source, destination):
                source_name = Path(source).name
                with source_lock:
                    first_attempt = source_name not in seen_sources
                    if first_attempt:
                        seen_sources.add(source_name)
                        sources.append(source_name)
                # Synchronize only each stage's first replace. A Windows
                # PermissionError retry must not wait for the other writer,
                # which may already have completed successfully.
                if first_attempt:
                    barrier.wait(timeout=5)
                return real_replace(source, destination)

            with mock.patch.object(broker.os, "replace", side_effect=synchronized_replace):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(server._write_preferences, {
                            broker.scope_key("profile-a", f"session-{index}"): f"browser-{index}"
                        })
                        for index in range(2)
                    ]
                    for future in futures:
                        future.result(timeout=3)
            self.assertEqual(len(set(sources)), 2)
            persisted = json.loads(broker.state_path(temp).read_text(encoding="utf-8"))
            self.assertEqual(persisted["protocol"], 4)
            self.assertFalse(list(
                broker.connector_dir(temp).glob(".broker-state-v4-*.tmp")
            ))


class BrokerRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secret = "0123456789abcdef" * 4
        self.server = broker.BrokerServer(
            root=self.temp.name,
            host="127.0.0.1",
            port=0,
            secret=self.secret,
        )
        await self.server.start()
        self.url = f"ws://127.0.0.1:{self.server.port}"
        self.clients = []

    async def asyncTearDown(self):
        for websocket in self.clients:
            try:
                await websocket.close()
            except Exception:
                pass
        await self.server.close()
        self.temp.cleanup()

    async def browser(self, browser_id: str, name: str = "Chrome"):
        websocket = await websockets.connect(
            self.url,
            origin="chrome-extension://unit-test/",
        )
        self.clients.append(websocket)
        challenge = json.loads(await websocket.recv())
        nonce = f"browser-nonce-{browser_id}"
        await websocket.send(json.dumps({
            "type": "hello",
            "role": "browser",
            "browserId": browser_id,
            "browserName": name,
            "nonce": nonce,
            "proof": broker.role_proof(
                self.secret, "browser", browser_id, challenge["nonce"]
            ),
            "protocol": broker.PROTOCOL_VERSION,
        }))
        paired = json.loads(await websocket.recv())
        self.assertEqual(paired["type"], "paired")
        self.assertEqual(
            paired["proof"],
            broker.broker_proof(self.secret, "browser", browser_id, nonce),
        )
        return websocket

    async def agent(self, profile_id: str, process_id: str):
        websocket = await websockets.connect(self.url)
        self.clients.append(websocket)
        challenge = json.loads(await websocket.recv())
        client_id = f"{profile_id}:{process_id}"
        nonce = f"agent-nonce-{process_id}"
        await websocket.send(json.dumps({
            "type": "hello",
            "role": "agent",
            "profileId": profile_id,
            "processId": process_id,
            "nonce": nonce,
            "proof": broker.role_proof(
                self.secret, "agent", client_id, challenge["nonce"]
            ),
            "protocol": broker.PROTOCOL_VERSION,
        }))
        paired = json.loads(await websocket.recv())
        self.assertEqual(paired["type"], "agent_paired")
        self.assertEqual(
            paired["proof"],
            broker.broker_proof(self.secret, "agent", client_id, nonce),
        )
        return websocket

    async def bind(self, websocket, profile: str, session: str,
                   tabs: list[int], active: int, settle: bool = True):
        await websocket.send(json.dumps({
            "type": "binding_update",
            "profileId": profile,
            "sessionId": session,
            "tabIds": tabs,
            "activeTabId": active,
        }))
        if settle:
            key = broker.scope_key(profile, session)
            for _ in range(100):
                if any(
                    binding.active_tab_id == active
                    for peer in self.server.browsers.values()
                    for binding_key, binding in peer.bindings.items()
                    if binding_key == key
                ):
                    return
                await asyncio.sleep(0.01)
            self.fail(f"broker did not apply binding {profile}/{session} -> {active}")

    async def request(self, websocket, request_id: str, profile: str,
                      session: str, kind: str = "snapshot"):
        await websocket.send(json.dumps({
            "type": "agent_request",
            "id": request_id,
            "profileId": profile,
            "sessionId": session,
            "taskId": session,
            "action": {"kind": kind},
            "timeout": 2,
        }))

    async def test_exact_sessions_route_to_different_browsers(self):
        chrome_a = await self.browser("chrome-a", "Work Chrome")
        chrome_b = await self.browser("chrome-b", "Personal Chrome")
        agent_a = await self.agent("alpha", "proc-a")
        agent_b = await self.agent("beta", "proc-b")
        await self.bind(chrome_a, "alpha", "session-a", [11], 11)
        await self.bind(chrome_b, "beta", "session-b", [22], 22)

        await self.request(agent_b, "request-b", "beta", "session-b")
        action_b = await receive_type(chrome_b, "action")
        self.assertEqual(action_b["targetTabId"], 22)
        self.assertEqual(action_b["scope"], {
            "profileId": "beta", "sessionId": "session-b"
        })

        await self.request(agent_a, "request-a", "alpha", "session-a")
        action_a = await receive_type(chrome_a, "action")
        self.assertEqual(action_a["targetTabId"], 11)
        self.assertNotEqual(action_a["id"], action_b["id"])

        await chrome_b.send(json.dumps({
            "type": "action_result", "id": action_b["id"],
            "ok": True, "data": {"browser": "b"},
        }))
        await chrome_a.send(json.dumps({
            "type": "action_result", "id": action_a["id"],
            "ok": True, "data": {"browser": "a"},
        }))
        response_b = await receive_type(agent_b, "agent_response")
        response_a = await receive_type(agent_a, "agent_response")
        self.assertEqual(response_b["data"]["browser"], "b")
        self.assertEqual(response_a["data"]["browser"], "a")

    async def test_one_session_keeps_multiple_tabs_and_active_target(self):
        chrome = await self.browser("chrome-main")
        agent = await self.agent("default", "proc-main")
        await self.bind(chrome, "default", "project-1", [7, 8, 9], 8)

        await self.request(agent, "multi-tab", "default", "project-1", "read_text")
        action = await receive_type(chrome, "action")
        self.assertEqual(action["targetTabId"], 8)

        await chrome.send(json.dumps({
            "type": "action_result", "id": action["id"],
            "ok": True, "data": {"text": "right tab"},
        }))
        response = await receive_type(agent, "agent_response")
        self.assertTrue(response["ok"])

    async def test_explicit_cross_browser_transfer_revokes_stale_owner(self):
        chrome_a = await self.browser("chrome-a", "Work Chrome")
        chrome_b = await self.browser("chrome-b", "Personal Chrome")
        agent = await self.agent("alpha", "proc-alpha")
        await self.bind(chrome_a, "alpha", "shared-session", [11], 11)
        await self.bind(chrome_b, "alpha", "shared-session", [22], 22)

        revoked = await receive_type(chrome_a, "binding_revoked")
        self.assertEqual(
            (revoked["profileId"], revoked["sessionId"]),
            ("alpha", "shared-session"),
        )
        await self.request(agent, "after-transfer", "alpha", "shared-session")
        action = await receive_type(chrome_b, "action")
        self.assertEqual(action["targetTabId"], 22)

        # A reconnect/full state sync is restoration, not an explicit claim: the old Chrome profile
        # cannot silently steal the scope back from B.
        await chrome_a.send(json.dumps({
            "type": "binding_sync",
            "bindings": [{
                "profileId": "alpha", "sessionId": "shared-session",
                "tabIds": [11], "activeTabId": 11,
            }],
        }))
        stale_revoked = await receive_type(chrome_a, "binding_revoked")
        self.assertEqual(stale_revoked["sessionId"], "shared-session")
        await self.request(agent, "after-stale-sync", "alpha", "shared-session")
        still_b = await receive_type(chrome_b, "action")
        self.assertEqual(still_b["targetTabId"], 22)

    async def test_result_is_rejected_if_scope_moves_during_action(self):
        chrome_a = await self.browser("chrome-a")
        chrome_b = await self.browser("chrome-b")
        agent = await self.agent("alpha", "proc-alpha")
        await self.bind(chrome_a, "alpha", "moving-session", [11], 11)
        await self.request(agent, "moving-request", "alpha", "moving-session")
        action = await receive_type(chrome_a, "action")

        await self.bind(chrome_b, "alpha", "moving-session", [22], 22)
        await receive_type(chrome_a, "binding_revoked")
        await chrome_a.send(json.dumps({
            "type": "action_result",
            "id": action["id"],
            "ok": True,
            "data": {"sensitive": "must not cross the transfer"},
        }))
        rejected = await receive_type(agent, "agent_response")
        self.assertEqual(rejected["id"], "moving-request")
        self.assertFalse(rejected["ok"])
        self.assertNotIn("data", rejected)
        self.assertIn("binding changed", rejected["error"])

    async def test_result_is_rejected_if_active_target_changes_during_action(self):
        chrome = await self.browser("chrome-main")
        agent = await self.agent("alpha", "proc-alpha")
        await self.bind(chrome, "alpha", "changing-target", [11, 12], 11)
        await self.request(agent, "old-target", "alpha", "changing-target", "read_text")
        action = await receive_type(chrome, "action")
        self.assertEqual(action["targetTabId"], 11)

        await self.bind(chrome, "alpha", "changing-target", [11, 12], 12)
        await chrome.send(json.dumps({
            "type": "action_result",
            "id": action["id"],
            "ok": True,
            "data": {"sensitive": "must not survive an active-target change"},
        }))
        rejected = await receive_type(agent, "agent_response")
        self.assertFalse(rejected["ok"])
        self.assertNotIn("data", rejected)
        self.assertIn("binding changed", rejected["error"])

    async def test_tab_mutation_result_is_bounded_to_documented_metadata(self):
        chrome = await self.browser("chrome-main")
        agent = await self.agent("alpha", "proc-alpha")
        await self.bind(chrome, "alpha", "switching", [11, 12], 11)
        await self.request(agent, "switch-target", "alpha", "switching", "switch_tab")
        action = await receive_type(chrome, "action")

        await self.bind(chrome, "alpha", "switching", [11, 12], 12)
        await chrome.send(json.dumps({
            "type": "action_result",
            "id": action["id"],
            "ok": True,
            "data": {"switched": 1, "tabId": 12, "sensitive": "must be stripped"},
        }))
        response = await receive_type(agent, "agent_response")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"], {"switched": 1, "tabId": 12})

    async def test_reconnect_with_same_browser_id_cancels_old_pending_action(self):
        chrome_old = await self.browser("stable-browser", "First connection")
        old_peer = self.server.browsers["stable-browser"]
        agent = await self.agent("alpha", "proc-alpha")
        await self.bind(chrome_old, "alpha", "reconnect-session", [11], 11)
        await self.request(agent, "before-reconnect", "alpha", "reconnect-session")
        await receive_type(chrome_old, "action")

        chrome_new = await self.browser("stable-browser", "Replacement connection")
        cancelled = await receive_type(agent, "agent_response")
        self.assertEqual(cancelled["id"], "before-reconnect")
        self.assertFalse(cancelled["ok"])
        self.assertIn("reconnected", cancelled["error"])
        self.assertFalse(self.server.pending)

        await self.server._on_browser(old_peer, {
            "type": "binding_update",
            "profileId": "alpha",
            "sessionId": "stale-buffered-update",
            "tabIds": [99],
            "activeTabId": 99,
        })
        self.assertNotIn(
            broker.scope_key("alpha", "stale-buffered-update"),
            self.server.browsers["stable-browser"].bindings,
        )

        await self.bind(chrome_new, "alpha", "reconnect-session", [22], 22)
        await self.request(agent, "after-reconnect", "alpha", "reconnect-session")
        fresh = await receive_type(chrome_new, "action")
        self.assertEqual(fresh["targetTabId"], 22)

    async def test_invalid_reconnect_nonce_cannot_evict_live_browser(self):
        live_socket = await self.browser("stable-browser", "Live browser")
        live_peer = self.server.browsers["stable-browser"]
        candidate = await websockets.connect(
            self.url, origin="chrome-extension://unit-test/"
        )
        self.clients.append(candidate)
        challenge = json.loads(await candidate.recv())
        await candidate.send(json.dumps({
            "type": "hello",
            "role": "browser",
            "browserId": "stable-browser",
            "browserName": "Invalid replacement",
            "nonce": "!",
            "proof": broker.role_proof(
                self.secret, "browser", "stable-browser", challenge["nonce"]
            ),
            "protocol": broker.PROTOCOL_VERSION,
        }))
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await candidate.recv()
        self.assertIs(self.server.browsers.get("stable-browser"), live_peer)
        await live_socket.send(json.dumps({"type": "keepalive"}))

    async def test_invalid_reconnect_nonce_cannot_evict_live_agent(self):
        live_socket = await self.agent("alpha", "stable-process")
        live_peer = self.server.agents["alpha:stable-process"]
        candidate = await websockets.connect(self.url)
        self.clients.append(candidate)
        challenge = json.loads(await candidate.recv())
        client_id = "alpha:stable-process"
        await candidate.send(json.dumps({
            "type": "hello",
            "role": "agent",
            "profileId": "alpha",
            "processId": "stable-process",
            "nonce": "!",
            "proof": broker.role_proof(
                self.secret, "agent", client_id, challenge["nonce"]
            ),
            "protocol": broker.PROTOCOL_VERSION,
        }))
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await candidate.recv()
        self.assertIs(self.server.agents.get("alpha:stable-process"), live_peer)
        await live_socket.send(json.dumps({"type": "keepalive"}))

    async def test_stale_browser_cannot_mutate_after_waiting_for_binding_lock(self):
        chrome_old = await self.browser("stable-browser", "First connection")
        old_peer = self.server.browsers["stable-browser"]
        await self.server.binding_lock.acquire()
        stale_task = asyncio.create_task(self.server._on_browser(old_peer, {
            "type": "binding_update",
            "profileId": "alpha",
            "sessionId": "stale-race",
            "tabIds": [99],
            "activeTabId": 99,
        }))
        await asyncio.sleep(0)
        try:
            await self.browser("stable-browser", "Replacement connection")
        finally:
            self.server.binding_lock.release()
        await stale_task
        key = broker.scope_key("alpha", "stale-race")
        self.assertNotIn(key, self.server.scope_browsers)
        self.assertNotIn(key, self.server.browsers["stable-browser"].bindings)

    async def test_simultaneous_transfers_leave_exactly_one_owner(self):
        chrome_a = await self.browser("chrome-a")
        chrome_b = await self.browser("chrome-b")
        chrome_c = await self.browser("chrome-c")
        agent = await self.agent("alpha", "proc-alpha")
        key = broker.scope_key("alpha", "race-session")
        await self.bind(chrome_a, "alpha", "race-session", [11], 11)
        await asyncio.gather(
            self.bind(chrome_b, "alpha", "race-session", [22], 22, settle=False),
            self.bind(chrome_c, "alpha", "race-session", [33], 33, settle=False),
        )
        for _ in range(100):
            owners = [
                browser_id for browser_id, peer in self.server.browsers.items()
                if key in peer.bindings
            ]
            if len(owners) == 1 and owners[0] in {"chrome-b", "chrome-c"}:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(len(owners), 1)
        winner_id = owners[0]
        self.assertEqual(self.server.scope_browsers[key], winner_id)
        winner = chrome_b if winner_id == "chrome-b" else chrome_c
        loser = chrome_c if winner_id == "chrome-b" else chrome_b
        revoked = await receive_type(loser, "binding_revoked")
        self.assertEqual(revoked["sessionId"], "race-session")

        await self.request(agent, "after-race", "alpha", "race-session")
        action = await receive_type(winner, "action")
        self.assertEqual(action["targetTabId"], 22 if winner_id == "chrome-b" else 33)

    async def test_unbound_session_fails_instead_of_guessing(self):
        await self.browser("chrome-main")
        agent = await self.agent("default", "proc-main")
        await self.request(agent, "unbound", "default", "missing-session")
        response = await receive_type(agent, "agent_response")
        self.assertFalse(response["ok"])
        self.assertIn("attach a tab", response["error"])
        self.assertEqual(self.server.pending, {})

    async def test_agent_cannot_impersonate_another_profile(self):
        chrome = await self.browser("chrome-main")
        agent = await self.agent("alpha", "proc-main")
        await self.bind(chrome, "beta", "session-b", [4], 4)
        await self.request(agent, "spoof", "beta", "session-b")
        response = await receive_type(agent, "agent_response")
        self.assertFalse(response["ok"])
        self.assertIn("impersonate", response["error"])

    async def test_authenticated_agent_advertises_headless_backend(self):
        chrome = await self.browser("chrome-main")
        agent = await self.agent("alpha", "desktop-process")
        await agent.send(json.dumps({
            "type": "agent_backend_update",
            "backendUrl": "http://127.0.0.1:51329/",
            "backendMode": "headless",
            # Identity is socket-bound. Extra untrusted identity fields cannot
            # publish this endpoint under another profile or process.
            "profileId": "beta",
            "processId": "spoofed-process",
        }))

        advertised = None
        for _ in range(20):
            state_message = await receive_type(chrome, "broker_state")
            backends = state_message["data"].get("agentBackends") or []
            if backends:
                advertised = backends
                break
        self.assertEqual(advertised, [{
            "profileId": "alpha",
            "processId": "desktop-process",
            "url": "http://127.0.0.1:51329/",
            "mode": "headless",
        }])

        await agent.close()
        for _ in range(100):
            if not self.server._public_state()["agentBackends"]:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.server._public_state()["agentBackends"], [])

    async def test_invalid_agent_backend_metadata_drops_only_that_agent(self):
        agent = await self.agent("alpha", "invalid-backend-process")
        await agent.send(json.dumps({
            "type": "agent_backend_update",
            "backendUrl": "http://attacker.example:51329/",
            "backendMode": "headless",
        }))
        for _ in range(20):
            try:
                await agent.recv()
            except websockets.exceptions.ConnectionClosed:
                break
        else:
            self.fail("invalid backend metadata did not close the agent socket")
        for _ in range(100):
            if "alpha:invalid-backend-process" not in self.server.agents:
                break
            await asyncio.sleep(0.01)
        self.assertNotIn("alpha:invalid-backend-process", self.server.agents)
        self.assertEqual(self.server._public_state()["agentBackends"], [])

    async def test_http_origin_cannot_authenticate_as_browser(self):
        websocket = await websockets.connect(
            self.url,
            origin="http://127.0.0.1:9999",
        )
        self.clients.append(websocket)
        challenge = json.loads(await websocket.recv())
        browser_id = "rogue-web-page"
        await websocket.send(json.dumps({
            "type": "hello",
            "role": "browser",
            "browserId": browser_id,
            "browserName": "Rogue",
            "nonce": "rogue-nonce",
            "proof": broker.role_proof(
                self.secret, "browser", browser_id, challenge["nonce"]
            ),
            "protocol": broker.PROTOCOL_VERSION,
        }))
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await websocket.recv()

    async def test_protocol_three_client_is_rejected_by_release_four_broker(self):
        websocket = await websockets.connect(
            self.url,
            origin="chrome-extension://legacy-release/",
        )
        self.clients.append(websocket)
        challenge = json.loads(await websocket.recv())
        self.assertEqual(challenge["protocol"], 4)
        browser_id = "legacy-browser"
        await websocket.send(json.dumps({
            "type": "hello",
            "role": "browser",
            "browserId": browser_id,
            "browserName": "Legacy Chrome",
            "nonce": "legacy-nonce",
            "proof": broker.role_proof(
                self.secret, "browser", browser_id, challenge["nonce"]
            ),
            "protocol": 3,
        }))
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await websocket.recv()


class BridgeClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secret = broker.load_or_create_secret(self.temp.name)
        self.server = broker.BrokerServer(
            root=self.temp.name,
            host="127.0.0.1",
            port=0,
            secret=self.secret,
        )
        await self.server.start()
        self.url = f"ws://127.0.0.1:{self.server.port}"
        self.browser_socket = None
        self.backend_metadata = None
        self.client = bridge_client.BridgeClient(
            profile_id="client-profile",
            root=self.temp.name,
            host="127.0.0.1",
            port=self.server.port,
            auto_start_broker=False,
            backend_metadata_provider=lambda: self.backend_metadata,
        )
        self.client.start(wait=0)
        for _ in range(100):
            if self.client.connected:
                break
            await __import__("asyncio").sleep(0.02)
        self.assertTrue(self.client.connected, self.client.last_error)

    async def asyncTearDown(self):
        if self.browser_socket is not None:
            await self.browser_socket.close()
        await __import__("asyncio").to_thread(self.client.stop)
        await self.server.close()
        self.temp.cleanup()

    async def connect_browser(self):
        websocket = await websockets.connect(
            self.url,
            origin="chrome-extension://bridge-client-test/",
        )
        challenge = json.loads(await websocket.recv())
        browser_id = "client-test-browser"
        nonce = "client-test-browser-nonce"
        await websocket.send(json.dumps({
            "type": "hello",
            "role": "browser",
            "browserId": browser_id,
            "browserName": "Client Test Chrome",
            "nonce": nonce,
            "proof": broker.role_proof(
                self.secret, "browser", browser_id, challenge["nonce"]
            ),
            "protocol": broker.PROTOCOL_VERSION,
        }))
        paired = json.loads(await websocket.recv())
        self.assertEqual(paired["type"], "paired")
        self.browser_socket = websocket
        return websocket

    async def test_sync_client_forwards_real_profile_and_session(self):
        import asyncio

        browser_socket = await self.connect_browser()
        await browser_socket.send(json.dumps({
            "type": "binding_update",
            "profileId": "client-profile",
            "sessionId": "real-session-123",
            "tabIds": [31, 32],
            "activeTabId": 32,
        }))

        result_task = asyncio.create_task(asyncio.to_thread(
            self.client.request,
            {"kind": "snapshot"},
            3,
            "real-session-123",
            "real-task-123",
        ))
        action = await receive_type(browser_socket, "action")
        self.assertEqual(action["scope"], {
            "profileId": "client-profile",
            "sessionId": "real-session-123",
        })
        self.assertEqual(action["targetTabId"], 32)
        await browser_socket.send(json.dumps({
            "type": "action_result",
            "id": action["id"],
            "ok": True,
            "data": {"snapshot": "ok"},
        }))
        result = await result_task
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"snapshot": "ok"})
        self.assertNotIn("error", result)

    async def test_sync_client_announces_backend_after_ephemeral_port_binds(self):
        self.assertEqual(self.server._public_state()["agentBackends"], [])
        self.backend_metadata = {
            "backendUrl": "http://127.0.0.1:53566/",
            "backendMode": "headless",
        }
        for _ in range(100):
            advertised = self.server._public_state()["agentBackends"]
            if advertised:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(advertised, [{
            "profileId": "client-profile",
            "processId": self.client.process_id,
            "url": "http://127.0.0.1:53566/",
            "mode": "headless",
        }])


class BridgeClientBackendDiscoveryTests(unittest.TestCase):
    def test_reads_bound_port_from_loaded_headless_web_server(self):
        web_server = types.SimpleNamespace(
            app=types.SimpleNamespace(
                state=types.SimpleNamespace(bound_port=51329),
            ),
        )
        with mock.patch.dict(
            bridge_client.os.environ, {"HERMES_SERVE_HEADLESS": "1"}, clear=False
        ), mock.patch.dict(
            bridge_client.sys.modules, {"hermes_cli.web_server": web_server}
        ):
            self.assertEqual(
                bridge_client.BridgeClient._headless_backend_metadata(),
                {
                    "backendUrl": "http://127.0.0.1:51329/",
                    "backendMode": "headless",
                },
            )

    def test_does_not_advertise_before_bind_or_outside_headless_serve(self):
        web_server = types.SimpleNamespace(
            app=types.SimpleNamespace(
                state=types.SimpleNamespace(bound_port=None),
            ),
        )
        with mock.patch.dict(
            bridge_client.os.environ, {"HERMES_SERVE_HEADLESS": "1"}, clear=False
        ), mock.patch.dict(
            bridge_client.sys.modules, {"hermes_cli.web_server": web_server}
        ):
            self.assertIsNone(
                bridge_client.BridgeClient._headless_backend_metadata()
            )

        with mock.patch.dict(
            bridge_client.os.environ, {"HERMES_SERVE_HEADLESS": "0"}, clear=False
        ):
            self.assertIsNone(
                bridge_client.BridgeClient._headless_backend_metadata()
            )


class BridgeClientResponseShapeTests(unittest.TestCase):
    def test_request_success_omits_error_key(self):
        with tempfile.TemporaryDirectory() as temp:
            client = bridge_client.BridgeClient(
                profile_id="response-shape-profile",
                root=temp,
                auto_start_broker=False,
            )
            broker_response = {
                "ok": True,
                "data": {"text": "ready"},
                "error": None,
            }
            with mock.patch.object(client, "_call", return_value=broker_response):
                result = client.request(
                    {"kind": "read_text"},
                    session_id="response-shape-session",
                )

        self.assertEqual(result, {"ok": True, "data": {"text": "ready"}})
        self.assertNotIn("error", result)

    def test_request_failure_has_false_ok_and_error(self):
        cases = (
            ({"ok": False, "error": "Browser action failed"}, "Browser action failed"),
            ({"ok": False, "error": None}, "Connector request failed"),
        )
        for broker_response, expected_error in cases:
            with self.subTest(broker_response=broker_response), \
                    tempfile.TemporaryDirectory() as temp:
                client = bridge_client.BridgeClient(
                    profile_id="response-shape-profile",
                    root=temp,
                    auto_start_broker=False,
                )
                with mock.patch.object(
                    client, "_call", return_value=broker_response
                ):
                    result = client.request(
                        {"kind": "snapshot"},
                        session_id="response-shape-session",
                    )

                self.assertIs(result["ok"], False)
                self.assertEqual(result["error"], expected_error)
                self.assertNotIn("data", result)

    def test_status_omits_error_until_a_real_error_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            client = bridge_client.BridgeClient(
                profile_id="response-shape-profile",
                root=temp,
                auto_start_broker=False,
            )
            self.assertNotIn("error", client.status())

            client.last_error = "Broker unavailable"
            self.assertEqual(client.status()["error"], "Broker unavailable")


class BridgeClientLifecycleTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "POSIX TIME_WAIT semantics")
    def test_port_probe_distinguishes_listener_from_time_wait(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            client = bridge_client.BridgeClient(
                profile_id="port-probe-profile",
                root=temp,
                host="127.0.0.1",
                port=port,
                auto_start_broker=False,
            )
            self.assertTrue(client._port_claimed())

            peer = socket.create_connection(("127.0.0.1", port), timeout=1)
            accepted, _ = listener.accept()
            accepted.close()  # Active close leaves the server port in TIME_WAIT.
            self.assertEqual(peer.recv(1), b"")  # ACK the FIN instead of resetting it.
            peer.close()
            listener.close()
            self.assertFalse(client._port_claimed())

    def test_broker_launch_is_locked_and_throttled(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            unused_port = reservation.getsockname()[1]
            client = bridge_client.BridgeClient(
                profile_id="launch-profile",
                root=temp,
                host="127.0.0.1",
                port=unused_port,
                auto_start_broker=True,
            )
            with mock.patch.object(client, "_port_claimed", return_value=False), \
                    mock.patch.object(client, "_port_accepting", side_effect=[False, True]), \
                    mock.patch.object(bridge_client.subprocess, "Popen") as popen:
                popen.return_value.poll.return_value = None
                client._ensure_broker_process()
                client._ensure_broker_process()
            self.assertEqual(popen.call_count, 1)
            self.assertFalse((Path(temp) / "connector" / "broker-start.lock").exists())

    def test_stop_cancels_disconnected_reconnect_backoff(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            unused_port = reservation.getsockname()[1]
            client = bridge_client.BridgeClient(
                profile_id="lifecycle-profile",
                root=temp,
                host="127.0.0.1",
                port=unused_port,
                auto_start_broker=False,
            ).start(wait=0.5)
            client.stop(wait=1)
            self.assertIsNotNone(client.thread)
            self.assertFalse(client.thread.is_alive())

    def test_stop_interrupts_broker_start_poll(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            client = bridge_client.BridgeClient(
                profile_id="stopping-launch",
                root=temp,
                host="127.0.0.1",
                port=reservation.getsockname()[1],
                auto_start_broker=True,
            )
            spawned = threading.Event()
            process = mock.Mock()
            process.poll.return_value = None

            def fake_popen(*_args, **_kwargs):
                spawned.set()
                return process

            with mock.patch.object(client, "_port_claimed", return_value=False), \
                    mock.patch.object(client, "_port_accepting", return_value=False), \
                    mock.patch.object(bridge_client.subprocess, "Popen", side_effect=fake_popen):
                worker = threading.Thread(target=client._ensure_broker_process)
                worker.start()
                self.assertTrue(spawned.wait(timeout=1))
                client.stop(wait=0)
                worker.join(timeout=1)
            self.assertFalse(worker.is_alive())

    def test_reconnect_loop_restarts_a_missing_broker(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            unused_port = reservation.getsockname()[1]
            client = bridge_client.BridgeClient(
                profile_id="recovery-profile",
                root=temp,
                host="127.0.0.1",
                port=unused_port,
                auto_start_broker=True,
            )
            attempts = 0

            async def disconnected():
                nonlocal attempts
                attempts += 1
                if attempts >= 2:
                    client._stop.set()
                raise OSError("broker unavailable")

            client._connect_once = disconnected
            with mock.patch.object(client, "_ensure_broker_process") as ensure:
                asyncio.run(client._connect_forever())
            self.assertEqual(attempts, 2)
            self.assertEqual(ensure.call_count, 1)


if __name__ == "__main__":
    unittest.main()
