"""Deterministic checks for live Chromium synchronization helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hermes_connector_e2e_helpers", ROOT / "tests" / "e2e_chromium.py"
)
live = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(live)


class FakeCdp:
    def __init__(self, values: list[dict]):
        self.values = values
        self.calls: list[str] = []
        self.evaluations = 0

    def call(self, method: str, _params=None) -> dict:
        self.calls.append(method)
        return {}

    def evaluate(self, _expression: str) -> dict:
        index = min(self.evaluations, len(self.values) - 1)
        self.evaluations += 1
        return self.values[index]


class ExtensionApiReadinessTests(unittest.TestCase):
    def test_retries_until_the_expected_extension_apis_are_ready(self):
        cdp = FakeCdp([
            {"ready": False, "runtimeId": "extension-id", "namespaces": ["runtime"]},
            {"ready": False, "runtimeId": "extension-id", "namespaces": ["runtime", "storage"]},
            {"ready": True, "runtimeId": "extension-id", "namespaces": ["runtime", "storage", "tabs"]},
        ])

        result = live.wait_for_extension_apis(
            cdp, "extension-id", timeout=1, poll_interval=0
        )

        self.assertTrue(result["ready"])
        self.assertEqual(cdp.evaluations, 3)
        self.assertEqual(
            cdp.calls,
            ["Runtime.enable", "Runtime.runIfWaitingForDebugger"],
        )

    def test_timeout_reports_the_observed_context(self):
        cdp = FakeCdp([
            {"ready": False, "runtimeId": "wrong-id", "namespaces": ["runtime"]}
        ])

        with self.assertRaisesRegex(
            RuntimeError,
            "expected_extension_id=expected-id.*runtime_id=wrong-id.*runtime",
        ):
            live.wait_for_extension_apis(
                cdp, "expected-id", timeout=0.004, poll_interval=0.001
            )


if __name__ == "__main__":
    unittest.main()
