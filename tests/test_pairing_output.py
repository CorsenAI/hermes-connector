"""Verify intentional pairing-code display without using installed credentials."""
from contextlib import redirect_stderr, redirect_stdout
import asyncio
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from test_broker import broker

ROOT = Path(__file__).resolve().parents[1]


class PairingOutputTests(unittest.TestCase):
    def test_explicit_display_preserves_installer_stdout_contract(self):
        secret = "0123456789abcdef" * 4
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            broker, "load_or_create_secret", return_value=secret
        ) as load, redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(broker.main(["--show-code", "--root", temp]), 0)
            load.assert_called_once_with(temp)
        self.assertEqual(out.getvalue(), secret + "\n")
        self.assertEqual(err.getvalue(), "")

    def test_captured_subprocess_output_is_stable_and_local(self):
        with tempfile.TemporaryDirectory() as temp:
            command = [sys.executable, str(ROOT / "hermes-plugin" / "broker.py"),
                       "--show-code", "--root", temp]
            first = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
            second = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
            self.assertRegex(first.stdout, r"\A[0-9a-f]{64}\n\Z")
            self.assertEqual(second.stdout, first.stdout)
            self.assertEqual(first.stderr + second.stderr, "")

    def test_serve_and_show_code_cannot_be_combined(self):
        with mock.patch.object(broker, "load_or_create_secret") as load, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                broker.main(["--serve", "--show-code"])
            self.assertEqual(raised.exception.code, 2)
            load.assert_not_called()


class BrokerStartupOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_startup_does_not_print_pairing_secret(self):
        secret = "0123456789abcdef" * 4
        server = types.SimpleNamespace(host="127.0.0.1", port=8767, secret=secret,
                                       start=mock.AsyncMock(), close=mock.AsyncMock())
        args = types.SimpleNamespace(root="unused-test-root", host=server.host, port=server.port)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(broker, "BrokerServer", return_value=server), \
                redirect_stdout(out), redirect_stderr(err):
            task = asyncio.create_task(broker._run_from_args(args))
            try:
                await asyncio.sleep(0)
                server.start.assert_awaited_once()
                self.assertEqual(out.getvalue(), "Hermes Connector broker listening on ws://127.0.0.1:8767\n")
                self.assertNotIn(secret, out.getvalue() + err.getvalue())
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            server.close.assert_awaited_once()
