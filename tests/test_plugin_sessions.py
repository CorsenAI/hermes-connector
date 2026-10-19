"""Companion session service: projection, provider fallbacks, and the client answer path."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

import websockets


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "hermes_connector_sessions_test_package"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(ROOT / "hermes-plugin")]
sys.modules[PACKAGE_NAME] = PACKAGE


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{name}", ROOT / "hermes-plugin" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


broker = _load("broker")
sessions = _load("sessions")
bridge_client = _load("bridge_client")


RAW_ROW = {
    "id": "local-abc123",
    "profile": "work",
    "title": "Plan the launch",
    "display_name": None,
    "source": "local",
    "last_active": 1792424762.7,
    "is_active": 1,
    # Never forwarded:
    "cwd": "/Users/someone/private/project",
    "git_repo_root": "/Users/someone/private/project",
    "estimated_cost_usd": 1.25,
    "input_tokens": 12000,
    "model": "some-model",
    "preview": "secret things",
}


class ProjectionTests(unittest.TestCase):
    def test_projection_keeps_only_label_and_identity_fields(self):
        projected = sessions.project_session(RAW_ROW)
        self.assertEqual(set(projected), set(sessions.ALLOWED_FIELDS))
        self.assertEqual(projected["id"], "local-abc123")
        self.assertEqual(projected["profile"], "work")
        self.assertEqual(projected["title"], "Plan the launch")
        self.assertIsNone(projected["display_name"])
        self.assertEqual(projected["source"], "local")
        self.assertAlmostEqual(projected["last_active"], 1792424762.7)
        self.assertIs(projected["is_active"], True)
        for forbidden in ("cwd", "git_repo_root", "estimated_cost_usd", "input_tokens", "model", "preview"):
            self.assertNotIn(forbidden, projected)

    def test_projection_caps_lengths_and_row_count_and_drops_junk(self):
        rows = [dict(RAW_ROW, id=f"s-{index}", title="x" * 1000) for index in range(300)]
        rows.append({"title": "no id"})          # dropped: no identity
        rows.append("not a row")                 # dropped: wrong type
        rows.append(dict(RAW_ROW, id="odd", profile=None, last_active="not-a-number"))
        projected = sessions.project_sessions(rows, limit=200)
        self.assertEqual(len(projected), 200)
        self.assertTrue(all(len(item["title"]) <= sessions.MAX_TEXT for item in projected))
        self.assertTrue(all(item["id"].startswith("s-") for item in projected))
        odd = sessions.project_sessions([dict(RAW_ROW, id="odd", profile=None, last_active="nope")], limit=5)
        self.assertEqual(odd[0]["profile"], "default")
        self.assertIsNone(odd[0]["last_active"])


class ProviderTests(unittest.TestCase):
    def test_uses_hermes_aggregated_listing_first(self):
        calls = []

        def hermes_listing(limit):
            calls.append(("hermes", limit))
            return [RAW_ROW]

        def fallback(limit):
            calls.append(("fallback", limit))
            return []

        result = sessions.list_sessions(50, hermes_listing=hermes_listing, fallback_listing=fallback)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["source"], "hermes-api")
        self.assertEqual([row["id"] for row in result["data"]["sessions"]], ["local-abc123"])
        self.assertEqual(calls, [("hermes", 50)])

    def test_falls_back_to_direct_store_when_hermes_listing_fails(self):
        def hermes_listing(limit):
            raise ImportError("no hermes_cli here")

        def fallback(limit):
            return [dict(RAW_ROW, id="direct-1")]

        result = sessions.list_sessions(10, hermes_listing=hermes_listing, fallback_listing=fallback)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["source"], "state-db")
        self.assertEqual(result["data"]["sessions"][0]["id"], "direct-1")

    def test_every_path_failing_is_a_bounded_error_not_an_exception(self):
        def boom(limit):
            raise RuntimeError("database is locked " * 50)

        result = sessions.list_sessions(10, hermes_listing=boom, fallback_listing=boom)
        self.assertFalse(result["ok"])
        self.assertNotIn("data", result)
        self.assertLessEqual(len(result["error"]), 300)
        self.assertIn("session store", result["error"])

    def test_limit_is_clamped(self):
        seen = []
        sessions.list_sessions(10_000, hermes_listing=lambda limit: seen.append(limit) or [],
                               fallback_listing=lambda limit: [])
        self.assertEqual(seen, [sessions.MAX_SESSIONS])
        seen.clear()
        sessions.list_sessions(-4, hermes_listing=lambda limit: seen.append(limit) or [],
                               fallback_listing=lambda limit: [])
        self.assertEqual(seen, [1])


class ClientQueryAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secret = broker.load_or_create_secret(self.temp.name)
        self.server = broker.BrokerServer(root=self.temp.name, host="127.0.0.1", port=0,
                                          secret=self.secret)
        await self.server.start()
        self.url = f"ws://127.0.0.1:{self.server.port}"
        self.provider_calls = []
        self.provider_result = {"ok": True, "data": {"sessions": [sessions.project_session(RAW_ROW)],
                                                      "source": "test"}}

        def provider(limit, profile_id):
            self.provider_calls.append((limit, profile_id))
            if isinstance(self.provider_result, Exception):
                raise self.provider_result
            return self.provider_result

        self.client = bridge_client.BridgeClient(
            profile_id="work", root=self.temp.name, host="127.0.0.1", port=self.server.port,
            auto_start_broker=False, session_provider=provider,
        )
        self.client.start(wait=0)
        for _ in range(100):
            if self.client.connected:
                break
            await asyncio.sleep(0.02)
        self.assertTrue(self.client.connected, self.client.last_error)
        self.browser_socket = None

    async def asyncTearDown(self):
        if self.browser_socket is not None:
            await self.browser_socket.close()
        await asyncio.to_thread(self.client.stop)
        await self.server.close()
        self.temp.cleanup()

    async def connect_browser(self):
        websocket = await websockets.connect(self.url, origin="chrome-extension://sessions-test/")
        challenge = json.loads(await websocket.recv())
        browser_id, nonce = "sessions-test-browser", "sessions-test-nonce"
        await websocket.send(json.dumps({
            "type": "hello", "role": "browser", "browserId": browser_id, "browserName": "Test",
            "nonce": nonce,
            "proof": broker.role_proof(self.secret, "browser", browser_id, challenge["nonce"]),
            "protocol": broker.PROTOCOL_VERSION,
        }))
        paired = json.loads(await websocket.recv())
        self.assertEqual(paired["type"], "paired")
        self.browser_socket = websocket
        return websocket

    async def receive(self, websocket, expected):
        for _ in range(12):
            payload = json.loads(await asyncio.wait_for(websocket.recv(), 5))
            if payload.get("type") == expected:
                return payload
        self.fail(f"did not receive {expected}")

    async def test_client_answers_a_relayed_session_query(self):
        chrome = await self.connect_browser()
        await chrome.send(json.dumps({"type": "browser_query", "id": "panel-1",
                                      "kind": "list_sessions", "limit": 25, "profileId": "work"}))
        result = await self.receive(chrome, "browser_query_result")
        self.assertEqual(result["id"], "panel-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["sessions"][0]["id"], "local-abc123")
        self.assertEqual(self.provider_calls, [(25, "work")])

    async def test_provider_failure_becomes_a_false_ok_answer(self):
        self.provider_result = RuntimeError("provider exploded")
        chrome = await self.connect_browser()
        await chrome.send(json.dumps({"type": "browser_query", "id": "panel-2", "kind": "list_sessions"}))
        result = await self.receive(chrome, "browser_query_result")
        self.assertEqual(result["id"], "panel-2")
        self.assertFalse(result["ok"])
        self.assertIn("session", result["error"])
        self.assertTrue(self.client.connected, "a provider failure must not drop the companion")

    async def test_unknown_query_kind_is_refused_by_the_client(self):
        # The broker already filters kinds; the companion must still refuse on its own.
        answer = await asyncio.to_thread(
            self.client.build_query_answer,
            {"type": "agent_query", "id": "forged-kind", "kind": "read_everything", "limit": 5},
        )
        self.assertEqual(answer["type"], "agent_query_result")
        self.assertEqual(answer["id"], "forged-kind")
        self.assertFalse(answer["ok"])
        self.assertIn("unsupported", answer["error"])
        self.assertEqual(self.provider_calls, [])


if __name__ == "__main__":
    unittest.main()
