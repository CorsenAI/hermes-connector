# Test evidence — 2026-08-02 — 0.2.1 hotfix

## Why 0.2.1 was required

The public 0.2.0 package was installable, but final use exposed production
paths that the isolated release tests had not covered:

- `listTabs` validated and stored an unchanged binding registry, broadcast
  `bindingsChanged`, and caused the open side panel to request `listTabs`
  again. Two used Chrome profiles accumulated approximately 606 MiB and
  1.66 GiB of local extension LevelDB journals before the loop was found.
- The companion installer copied and enabled the plugin only in the shared
  Hermes home. Named Hermes profiles have independent plugin payloads and
  activation lists, so their real sessions did not receive Connector tools.
- A `BridgeClient` attempted to start the detached broker only once. If that
  broker later exited or was killed with a launcher, the reconnect loop never
  started a replacement.

The data growth was local Chrome storage churn, not network transmission or a
publisher data leak.

## Fast release gate

Command:

```text
<Hermes venv Python> tests/run_all.py
```

The gate passes on Windows with Python 3.11 and Node.js 24. It covers protocol
routing and authentication, exact session/tab ownership, plugin context,
installer behavior, deterministic archives, extension syntax, metadata,
whole-tracked-tree leakage checks, canonical line endings, and JavaScript
registry/dashboard modules.

New regression evidence includes:

- three unchanged `listTabs` requests produce zero binding-storage writes and
  zero `bindingsChanged` broadcasts in the real background module under a
  Chrome API mock;
- one real detach produces exactly one write/event, and repeating the no-op
  detach produces none;
- semantic registry comparison detects active-tab, tab-order, and scope
  changes without depending on object-key order;
- the reconnect loop supervises a missing broker, while a cross-process launch
  marker and per-client throttle serialize normal launch races and retain the
  marker through unusually slow starts;
- the installer copies the plugin to the shared home and every existing named
  profile as one rollback-capable transaction, and migrates only the exact
  known legacy `agent-bridge` signature.
- browser actions and results remain pinned to the authenticated socket and
  current binding epoch; disconnect, detach, transfer, or Trusted-input changes
  cancel stale authority without forwarding page data;
- the broker rejects a late result if its scope moved to another Chrome profile
  and immediately cancels pending work when the same browser identity reconnects;
- installer locks, plugin targets, plugin parents, and config targets reject
  symlink/reparse redirection, and an interruption between payload swaps restores
  the previous installation.

## Real Chrome extension acceptance

Commands:

```text
<Hermes venv Python> tests/e2e_chromium.py
<Hermes venv Python> tests/e2e_multi_browser.py
```

Both pass against real unpacked Manifest V3 extension code and real Chrome
APIs. The single-browser run verifies the service worker, real side panel,
authenticated dashboard-session loading, mutual broker authentication,
post-pair tab attachment, two exact Hermes sessions, every advertised action,
trusted input/dialog handling, scoped tabs, and fail-closed unbound sessions.
It also verifies that first launch shows the companion explanation, exact
versioned download, and open pairing settings, while configured users do not
see that setup prompt.
It also sends three unchanged real `listTabs` messages and observes zero
`bindingsChanged` events after the UI settles. The real panel also displays and
persistently dismisses the companion-reinstallation notice intended for users
whose Store extension auto-updates from 0.2.0.

The two-browser run verifies two concurrent isolated Chrome profiles, stable
browser identities, exact routing, explicit ownership transfer, stale-owner
revocation, and fail-closed behavior after displacement.

## Broker recovery

An isolated live recovery probe started a real detached broker, killed the
exact broker process owning its random test port, kept the same `BridgeClient`
alive, and observed a distinct replacement broker plus a restored authenticated
connection. All temporary processes and data were removed afterward.

The 0.2.1 broker uses protocol 4 on the new default port 8766. Extension tests
verify a one-shot migration of all legacy default 8765 URL forms before the
first connection, while preserving a genuinely custom port. This prevents the
detached 0.2.0 broker from silently serving 0.2.1 after a normal Hermes restart;
an incompatible protocol is rejected rather than used as a fallback.
Broker persistence tests also verify that protocol 4 imports a validated
legacy owner only once, ignores a late write from a still-running protocol-3
broker, refuses fallback from a present invalid v4 snapshot, and uses distinct
complete temporary files for concurrent atomic saves.

## Multi-profile installation

The 0.2.1 source installer was run locally without printing the pairing secret.
The shared home and every discovered named profile report
`hermes-connector` 0.2.1 enabled. The known conflicting legacy
`agent-bridge` payload is preserved but disabled only where its exact legacy
signature is detected.

The POSIX installer acceptance also passes under WSL with an isolated shared
home plus a named profile, including pipx-style Hermes shim resolution and a
Python 3.10+ check. A Windows PowerShell wrapper test verifies that a function
named `hermes` cannot break Python discovery. The same Windows gate executes
the normal-user `Install Hermes Connector.cmd` double-click path. Users must re-run the companion
installer after creating a new named profile.

## Store artwork

`store/screenshot-product-1280x800.png` was recaptured from the real 0.2.1
extension panel at exactly 1280×800 with isolated fixture data. The icon,
440×280 tile, 1400×560 marquee, and screenshot pass the metadata and leakage
gates.

## Remaining external release evidence

- build the exact clean 0.2.1 archives and record their SHA-256 values;
- publish the matching GitHub 0.2.1 companion before changing the Store item;
- upload the 0.2.1 Chrome ZIP and updated screenshot to the Store;
- complete a pre-submit pass from the exact extracted ZIP in the intended
  signed-in Chrome profile;
- after publication, confirm the existing Store ID serves 0.2.1 and smoke-test
  that Store-installed build.
