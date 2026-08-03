# Test evidence — 2026-08-03 — 0.2.2 release candidate

## Why 0.2.2 was required

The public Store endpoint still served 0.2.0 while the 0.2.1 submission was
being evaluated. A deeper audit found that 0.2.1 was not ready to be treated as
the final corrective release:

- the side panel called the browser "paired" when only Chrome and the local
  broker were authenticated; it did not prove that the selected Hermes profile
  had loaded the Connector tools;
- successful Connector responses included `"error": null`, which Hermes' generic
  tool-result detector could misclassify as a failed browser call;
- switching Chrome tabs did not change the deliberately fixed Hermes target,
  but the panel did not explain that distinction and could leave users looking
  at a different page from the one Hermes controlled;
- internal, blank, loading, local-file, and Chrome Web Store pages did not all
  produce an early, plain-language refusal;
- the tab/session controls consumed too much side-panel height and reduced the
  actual Hermes chat;
- the first promotional video combined real extension chrome with a fixture
  page and a prewritten Hermes result. It was rejected and removed from public
  presentation rather than represented as live evidence.

0.2.2 makes readiness depend on pairing, the selected profile appearing in the
broker's authenticated `agentProfiles`, and a real active tab binding; removes
false `error` keys from successful tool
results, reports and refreshes the real active Chrome tab without silently
changing authorization, blocks restricted/pending pages before execution, and
moves secondary controls into compact accessible overlays. The installer now
verifies every installed companion file byte-for-byte and rolls back on any
post-publication verification failure.

## Why 0.2.1 was required (historical)

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

The 0.2.2 broker uses protocol 4 on the default port 8766. Extension tests
verify a one-shot migration of all legacy default 8765 URL forms before the
first connection, while preserving a genuinely custom port. This prevents the
detached 0.2.0 broker from silently serving a protocol-4 release after a normal Hermes restart;
an incompatible protocol is rejected rather than used as a fallback.
Broker persistence tests also verify that protocol 4 imports a validated
legacy owner only once, ignores a late write from a still-running protocol-3
broker, refuses fallback from a present invalid v4 snapshot, and uses distinct
complete temporary files for concurrent atomic saves.

## Multi-profile installation

The 0.2.2 source installer is tested without printing the pairing secret.
The shared home and every discovered named profile report
`hermes-connector` 0.2.2 enabled. The known conflicting legacy
`agent-bridge` payload is preserved but disabled only where its exact legacy
signature is detected.

The POSIX installer acceptance also passes under WSL with an isolated shared
home plus a named profile, including pipx-style Hermes shim resolution and a
Python 3.10+ check. A Windows PowerShell wrapper test verifies that a function
named `hermes` cannot break Python discovery. The same Windows gate executes
the normal-user `Install Hermes Connector.cmd` double-click path. Users must re-run the companion
installer after creating a new named profile.

## Store artwork and verified live capture

`store/screenshot-product-1280x800.png` is an exact 1280×800 OS-window capture
from the real 0.2.2 candidate. In an isolated profile, a real Hermes model called
`bridge_status`, `bridge_current_url`, and `bridge_read` against the exact
attached `https://example.com/` Chrome tab. The acceptance required
session-scoped `INFO … tool … completed` records for all three calls,
independently verified the exact Chrome URL/title and binding, then opened the
real side panel and captured only after that proven transcript was visible with
`Ready · Hermes + Chrome`. SHA-256:
`8F5DEAA207A2F513D5D9B6C5EF9E88CEBC44C9344209670095A71953AC7D3585`.

The icon, 440×280 tile, 1400×560 marquee, and live capture pass the metadata and
leakage gates. The old prewritten fixture renderer now writes only under
`tests/artifacts/` by default and cannot overwrite the public product capture.

The accepted 9.30-second 1920×1080 product video is generated from the same
proof-gated run after the transcript becomes visible. It shows the exact target,
the three real Connector tool calls, the real result, and the single authorized
tab popup without any marketing overlay or fake UI. Three decoded frames are
checked for valid contrast, the real Tabs open/close transition, and agreement
with the unobstructed final OS-window capture. SHA-256:
`DE91F39FC9E5CE225097F255CB620D324B47A436BD9BA034D1C608A4F01F239D`.

## Remaining external release evidence

- build the exact clean 0.2.2 archives and record their SHA-256 values;
- publish the matching GitHub 0.2.2 companion before changing the Store item;
- upload the 0.2.2 Chrome ZIP and verified replacement screenshot to the Store;
- complete a pre-submit pass from the exact extracted ZIP in the intended
  signed-in Chrome profile;
- after publication, confirm the existing Store ID serves 0.2.2 and smoke-test
  that Store-installed build.
