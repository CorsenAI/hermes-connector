"""Protocol and routing tests for the multiplexed local broker."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest

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
        self.client = bridge_client.BridgeClient(
            profile_id="client-profile",
            root=self.temp.name,
            host="127.0.0.1",
            port=self.server.port,
            auto_start_broker=False,
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


class BridgeClientLifecycleTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
