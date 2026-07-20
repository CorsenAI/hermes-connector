"""Hermes plugin contract tests: real call context must reach the broker."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hermes-plugin"
PACKAGE_NAME = "hermes_connector_plugin_test"
SPEC = importlib.util.spec_from_file_location(
    PACKAGE_NAME,
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
plugin = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[PACKAGE_NAME] = plugin
SPEC.loader.exec_module(plugin)


class FakeBridgeClient:
    instances = []

    def __init__(self, profile_id):
        self.profile_id = profile_id
        self.calls = []
        self.started = False
        self.stopped = False
        FakeBridgeClient.instances.append(self)

    def start(self):
        self.started = True
        return self

    def request(self, action, timeout=30, session_id=None, task_id=None):
        self.calls.append({
            "action": action,
            "timeout": timeout,
            "session_id": session_id,
            "task_id": task_id,
        })
        return {"ok": True, "data": {"routed": True}}

    def stop(self):
        self.stopped = True

    def refresh_status(self):
        return {"connected": True, "profile": self.profile_id}


class FakeContext:
    profile_name = "real-profile"

    def __init__(self):
        self.tools = {}

    def register_tool(self, name, handler, **metadata):
        self.tools[name] = {"handler": handler, **metadata}


class PluginRoutingTests(unittest.TestCase):
    def setUp(self):
        FakeBridgeClient.instances.clear()
        plugin.bridge_client.BridgeClient = FakeBridgeClient
        plugin.BRIDGE = None
        self.context = FakeContext()
        plugin.register(self.context)
        self.client = FakeBridgeClient.instances[-1]

    def test_register_uses_plugin_context_profile(self):
        self.assertTrue(self.client.started)
        self.assertEqual(self.client.profile_id, "real-profile")

    def test_tool_forwards_real_session_and_task_context(self):
        result = self.context.tools["bridge_open"]["handler"](
            {"url": "https://example.com"},
            session_id="session-from-hermes",
            task_id="task-from-hermes",
        )
        self.assertEqual(json.loads(result)["ok"], True)
        self.assertEqual(self.client.calls, [{
            "action": {"kind": "navigate", "url": "https://example.com"},
            "timeout": 30,
            "session_id": "session-from-hermes",
            "task_id": "task-from-hermes",
        }])

    def test_obsolete_disk_profile_tools_are_not_registered(self):
        self.assertNotIn("bridge_list_chrome", self.context.tools)
        self.assertNotIn("bridge_pin", self.context.tools)
        self.assertIn("bridge_tab", self.context.tools)

    def test_reregister_stops_the_previous_companion_client(self):
        first = self.client
        replacement_context = FakeContext()
        plugin.register(replacement_context)
        self.assertTrue(first.stopped)
        self.assertTrue(FakeBridgeClient.instances[-1].started)
        self.assertEqual(
            replacement_context.tools["bridge_status"]["toolset"],
            "hermes-connector",
        )


if __name__ == "__main__":
    unittest.main()
