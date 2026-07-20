# Hermes Connector companion

This local Hermes plugin connects Hermes tool calls to the Hermes Connector
Chrome extension through one authenticated loopback broker.

The companion is required because a Chrome extension cannot register tools in
Hermes by itself. It works on Windows, macOS, and Linux and does not open a
network listener beyond `127.0.0.1`.

## Install

Use `install.py` from the companion release archive. It copies this directory
to the active Hermes home, enables `hermes-connector`, and prints the pairing
code that must be entered once in the extension.

Restart any already-running Hermes dashboard, gateway, or chat process after
installation so it discovers the newly enabled tools.

The pairing code is stored under the local Hermes home in
`connector/credentials.json`. Treat it like a password. It is never included in
`bridge_status` or sent over the WebSocket.

To display it again locally:

```text
python <Hermes home>/plugins/hermes-connector/broker.py --show-code
```
