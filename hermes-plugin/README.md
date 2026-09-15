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
newly enabled tools and announces its local backend. Release 0.2.4 moves the
standard broker from protocol 4 / port 8766 to its version-checked protocol 5 /
port 8767 and retires only a verified older Connector broker for the same
Hermes home.

The companion supervises the shared local broker. If that detached process is
terminated by a launcher restart or crashes, a running profile client starts it
again with a bounded cross-process launch lock. On managed Windows installs,
the broker runs from Hermes' immutable base runtime instead of the replaceable
virtual-environment launcher so it cannot hold that launcher open during a
future Hermes update.

The pairing code is stored under the local Hermes home in
`connector/credentials.json`. Treat it like a password. It is never included in
`bridge_status` or sent over the WebSocket.

To display it again locally:

```text
python <Hermes home>/plugins/hermes-connector/broker.py --show-code
```

## Pairing code and captured output

`--show-code` intentionally writes the full pairing secret to standard output.
The installer consumes that output and normally displays the code once so it
can be pasted into Chrome. This is not a redacted diagnostic or a one-time
secret: terminal recordings, redirected output, installation logs and support
transcripts can retain a usable copy. Do not publish or share that output.
File permissions on `connector/credentials.json` do not protect such copies.

For an installation whose output will be recorded, suppress the code display:

```text
python install.py --no-show-code
```

Run this command from the extracted companion archive. When installing from a
source checkout, the equivalent is
`python scripts/install_companion.py --no-show-code`. Display the pairing code
separately only when needed, in a private terminal that is not being recorded.
The option suppresses display; it does not rotate or delete an existing secret.

An output warning or clearing a terminal line cannot retract a secret already
captured in a log. The explicit display command remains compatible with the
installer's captured subprocess output; this documentation does not remove
that exposure or resolve a clear-text-output scanning alert by itself.
