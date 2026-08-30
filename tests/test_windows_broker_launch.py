"""Regression coverage for the Windows broker-launch defects reported in #5."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "hermes-plugin"
PACKAGE_NAME = "hermes_connector_windows_launch_tests"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(PLUGIN)]
sys.modules[PACKAGE_NAME] = PACKAGE

BROKER_SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.broker", PLUGIN / "broker.py"
)
broker = importlib.util.module_from_spec(BROKER_SPEC)
assert BROKER_SPEC and BROKER_SPEC.loader
sys.modules[BROKER_SPEC.name] = broker
BROKER_SPEC.loader.exec_module(broker)

CLIENT_SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.bridge_client", PLUGIN / "bridge_client.py"
)
bridge_client = importlib.util.module_from_spec(CLIENT_SPEC)
assert CLIENT_SPEC and CLIENT_SPEC.loader
sys.modules[CLIENT_SPEC.name] = bridge_client
CLIENT_SPEC.loader.exec_module(bridge_client)


class FakeProcess:
    returncode = None

    def poll(self):
        return self.returncode


class WindowsBrokerLaunchTests(unittest.TestCase):
    def test_windows_launch_uses_hidden_console_without_detached_process(self):
        with tempfile.TemporaryDirectory() as temp:
            client = bridge_client.BridgeClient("default", root=temp)
            captured = {}

            def fake_popen(command, **kwargs):
                captured["command"] = command
                captured["kwargs"] = kwargs
                return FakeProcess()

            log_stream = mock.MagicMock()
            with (
                mock.patch.object(bridge_client.sys, "platform", "win32"),
                mock.patch.object(
                    bridge_client.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200,
                    create=True,
                ),
                mock.patch.object(
                    bridge_client.subprocess, "CREATE_NO_WINDOW", 0x08000000,
                    create=True,
                ),
                mock.patch.object(
                    bridge_client.subprocess, "DETACHED_PROCESS", 0x00000008,
                    create=True,
                ),
                mock.patch.object(client, "_port_claimed", return_value=False),
                mock.patch.object(client, "_port_accepting", return_value=True),
                mock.patch.object(bridge_client, "_open_broker_log", return_value=log_stream),
                mock.patch.object(bridge_client.subprocess, "Popen", side_effect=fake_popen),
            ):
                client._ensure_broker_process()

            flags = captured["kwargs"]["creationflags"]
            self.assertEqual(flags, 0x08000200)
            self.assertFalse(flags & 0x00000008)
            self.assertIs(captured["kwargs"]["stdout"], log_stream)
            self.assertIs(captured["kwargs"]["stderr"], log_stream)
            log_stream.close.assert_called_once_with()
            self.assertEqual(Path(captured["command"][1]).name, "broker.py")
            self.assertIn("--serve", captured["command"])

    def test_readiness_probe_performs_valid_websocket_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.addCleanup(listener.close)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            requests: queue.Queue[bytes] = queue.Queue()

            def serve_once():
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(2)
                    request = bytearray()
                    while b"\r\n\r\n" not in request:
                        chunk = conn.recv(1024)
                        if not chunk:
                            break
                        request.extend(chunk)
                    requests.put(bytes(request))
                    headers = {}
                    for line in bytes(request).split(b"\r\n")[1:]:
                        if b":" in line:
                            name, value = line.split(b":", 1)
                            headers[name.strip().lower()] = value.strip()
                    key = headers[b"sec-websocket-key"]
                    accept = base64.b64encode(hashlib.sha1(
                        key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                    ).digest())
                    conn.sendall(
                        b"HTTP/1.1 101 Switching Protocols\r\n"
                        b"Upgrade: websocket\r\n"
                        b"Connection: Upgrade\r\n"
                        b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
                    )

            thread = threading.Thread(target=serve_once, daemon=True)
            thread.start()
            client = bridge_client.BridgeClient(
                "default", root=temp, host="127.0.0.1", port=port,
                auto_start_broker=False,
            )
            self.assertTrue(client._port_accepting())
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            request = requests.get(timeout=1)
            self.assertTrue(request.startswith(b"GET / HTTP/1.1\r\n"))
            self.assertIn(b"Upgrade: websocket\r\n", request)
            self.assertIn(b"Connection: Upgrade\r\n", request)
            self.assertIn(b"Sec-WebSocket-Version: 13\r\n", request)

    def test_concurrent_inherited_append_handles_preserve_all_records(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            log_path = temp_path / "broker.log"
            start_path = temp_path / "start"
            seed = [f"seed:{index:04d}" for index in range(40)]
            log_path.write_text("\n".join(seed) + "\n", encoding="utf-8")
            child = r'''
from pathlib import Path
import sys
import time
start = Path(sys.argv[1])
while not start.exists():
    time.sleep(0.001)
prefix = sys.argv[2]
count = int(sys.argv[3])
for index in range(count):
    stream = sys.stdout if index % 2 == 0 else sys.stderr
    stream.write(f"{prefix}:{index:04d}\n")
    stream.flush()
'''
            count = 400
            streams = [
                bridge_client._open_broker_log(log_path),
                bridge_client._open_broker_log(log_path),
            ]
            self.assertNotEqual(streams[0].fileno(), streams[1].fileno())
            processes = []
            try:
                for prefix, stream in zip(("writer-a", "writer-b"), streams):
                    processes.append(subprocess.Popen(
                        [sys.executable, "-c", child, str(start_path), prefix, str(count)],
                        stdin=subprocess.DEVNULL,
                        stdout=stream,
                        stderr=stream,
                        close_fds=True,
                        cwd=ROOT,
                    ))
            finally:
                for stream in streams:
                    stream.close()

            time.sleep(0.05)
            start_path.touch()
            for process in processes:
                self.assertEqual(process.wait(timeout=15), 0)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            expected = seed + [
                f"{prefix}:{index:04d}"
                for prefix in ("writer-a", "writer-b")
                for index in range(count)
            ]
            self.assertEqual(len(lines), len(expected))
            self.assertEqual(set(lines), set(expected))


if __name__ == "__main__":
    unittest.main()
