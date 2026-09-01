# Hermes Connector companion

This local Hermes plugin connects Hermes tool calls to the Hermes Connector
Chrome extension through one authenticated loopback broker.

The companion is required because a Chrome extension cannot register tools in
Hermes by itself. It works on Windows, macOS, and Linux and does not open a
network listener beyond `127.0.0.1`.

## Install

Extract the companion release archive. On Windows, double-click
`Install Hermes Connector.cmd` (or run `install.ps1` manually). On macOS or
Linux, run `./install.sh`. The installer uses `install.py` internally, copies
this directory to the shared Hermes home and every existing named profile, enables
`hermes-connector` in each scope, and prints the pairing code that must be
entered once in the extension. Re-run the installer after creating a new
Hermes profile.

Fully quit and reopen Hermes Desktop, or restart any already-running Hermes
dashboard, gateway, or chat process, after installation so it discovers the
newly enabled tools and announces its local backend.

The companion supervises the shared local broker. If that detached process is
terminated by a launcher restart or crashes, a running profile client starts it
again with a bounded cross-process launch lock.

The pairing code is stored under the local Hermes home in
`connector/credentials.json`. Treat it like a password. It is never included in
`bridge_status` or sent over the WebSocket.

To display it again locally:

```text
python <Hermes home>/plugins/hermes-connector/broker.py --show-code
```
