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
        self.expressions: list[str] = []

    def call(self, method: str, _params=None) -> dict:
        self.calls.append(method)
        return {}

    def evaluate(self, expression: str) -> dict:
        self.expressions.append(expression)
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


class CompanionConfirmationTests(unittest.TestCase):
    def test_waits_for_pairing_and_capability_in_the_same_response(self):
        cdp = FakeCdp([
            {"paired": False, "capability": True},
            {"paired": True, "capability": False},
            {"paired": True, "capability": True},
        ])
        result = live.wait_for_companion_confirmation(cdp, timeout=1, poll_interval=0)
        self.assertEqual(result, {"paired": True, "capability": True})
        self.assertEqual(cdp.evaluations, 3)
        self.assertTrue(all("cmd:'getState'" in expression for expression in cdp.expressions))
        self.assertTrue(all("dismissUpgradeNotice" not in expression for expression in cdp.expressions))

    def test_does_not_treat_truthy_non_booleans_as_authentication(self):
        cdp = FakeCdp([
            {"paired": "false", "capability": True},
            {"paired": True, "capability": "false"},
            {"paired": True, "capability": True, "unrelated": "must not be returned"},
        ])
        result = live.wait_for_companion_confirmation(cdp, timeout=1, poll_interval=0)
        self.assertEqual(cdp.evaluations, 3)
        self.assertEqual(result, {"paired": True, "capability": True})

    def test_unpaired_companion_times_out_instead_of_dismissing(self):
        cdp = FakeCdp([{"paired": False, "capability": True}])
        with self.assertRaisesRegex(RuntimeError, "paired=False; capability=True"):
            live.wait_for_companion_confirmation(cdp, timeout=0, poll_interval=0)
        self.assertEqual(cdp.evaluations, 1)

    def test_missing_capability_times_out_instead_of_accepting_pairing_alone(self):
        cdp = FakeCdp([{"paired": True}])
        with self.assertRaisesRegex(RuntimeError, "paired=True; capability=False"):
            live.wait_for_companion_confirmation(cdp, timeout=0, poll_interval=0)
        self.assertEqual(cdp.evaluations, 1)


if __name__ == "__main__":
    unittest.main()
