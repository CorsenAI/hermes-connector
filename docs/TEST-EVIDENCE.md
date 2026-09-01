# Test evidence

## 0.2.4 Hermes Desktop compatibility candidate — 2026-09-01

### Why 0.2.4 is required

The public 0.2.3 pair expects a separately running Hermes web dashboard at its
configured address. Hermes Desktop instead starts a headless local API on a
dynamic loopback port and does not expose the dashboard route embedded by the
side panel. As a result, the 0.2.3 companion can be paired and browser tools can
be installed while the panel still reports that `127.0.0.1` refused the
dashboard connection.

The 0.2.4 candidate makes the companion announce that same-process headless
backend through the authenticated local broker after Hermes Desktop binds its
port. The broker accepts only an explicit `http://127.0.0.1:<port>/` or
`http://localhost:<port>/` headless backend, ties the announcement to the
authenticated agent socket, and removes it on disconnect. The extension first
keeps the existing web-dashboard path, then falls back to an announced Desktop
backend. In Desktop mode it hides the unavailable dashboard frame, lists the
real sessions, and keeps session/tab controls in Chrome while the conversation
continues in Hermes Desktop.

The previous Windows launch path also kept
`hermes-agent\\venv\\Scripts\\python.exe` mapped after Desktop stopped its own
backend. Hermes' fail-closed updater therefore identified the Connector broker
as a foreign process and aborted. Companion 0.2.4 launches the detached broker
from the immutable managed base runtime with the companion dependencies exposed
explicitly, leaving the replaceable Hermes virtual environment free for update.
Because protocol 4 was shared by 0.2.1–0.2.3, a detached 0.2.3 broker could
also survive an upgrade, accept a 0.2.4 client, and silently omit the new
Desktop-backend messages. Release 0.2.4 therefore uses version-checked protocol
5 on port 8767, imports the validated v4 binding state exactly once, and stops
only a process whose executable arguments prove it is the prior Connector
broker for the same Hermes root and legacy port.

### Candidate validation completed so far

- the complete fast source gate passes on Windows: 76 Python tests pass with 6
  platform/privilege-specific cases skipped, and all 21 JavaScript tests pass;
  this includes delayed Desktop port discovery, strict loopback validation,
  authenticated advertisement, disconnect cleanup, session loading, the
  persistent 0.2.4 notice, request timeouts, loopback-only CSP, and Chrome Site
  access preflight, plus standard-port migration, exact broker-version checks,
  fail-closed v4-to-v5 state migration, and strict old-process matching;
- both Windows companion installers pass from isolated temporary Hermes homes
  and preserve the 0.2.4 payload version;
- the real isolated-Chrome acceptance passes a forced web-dashboard outage,
  automatic fallback to the advertised Desktop-style backend, session loading,
  exact tab routing, all browser actions, and restoration of dashboard mode;
- the two-profile real-Chrome acceptance passes concurrent routing, explicit
  transfer, and stale-owner revocation;
- the secondary 1280×800 Desktop-mode Store capture was reproduced from the
  actual extension UI with public `example.com` and isolated session data;
  SHA-256 `C2E875FC3EC6B02A30B2AEB4065BC5AA01D67DCCE469AD7D725C879C810570E9`.

### Exact packaged-pair and installed-runtime validation

Clean commit `f583074d0773fe81879aecd1e3b0e8145b35411d` produced protocol 5
archives with `sourceDirty: false`:

- Chrome ZIP: 60,222 bytes; SHA-256
  `335b35a7531722e58a84054ba102dceda9672699c7d60fc859f7d4c3bd072967`;
- companion ZIP: 32,635 bytes; SHA-256
  `3ec1c1c0428441d5f98fd9458bb099808dbb7b39ab9d34dea2dc5ecc29ff5cae`.

The packaged-pair acceptance loaded that exact Chrome ZIP in one and two
isolated real Chrome profiles and passed every routing/action gate. The exact
companion ZIP was then installed into the shared Windows Hermes home and all
16 discovered named profiles. Its strict cleanup stopped both processes in the
old venv-wrapper/base-runtime broker pair. The still-running old gateway
correctly demonstrated the documented respawn race; after fully restarting
Desktop and the gateway, only protocol 5 on `127.0.0.1:8767` remained.

The restarted CLI gateway launched the broker directly from Hermes' immutable
base runtime, with no venv wrapper process. Hermes' installed
`_scan_venv_blockers` reported `blocked: false`, zero processes, and no
Connector broker. With Hermes Desktop restarted as well, the same scan remained
clear. The live acceptance then loaded the exact packaged extension, proved one
dynamically announced Desktop backend, listed 86 real sessions, and rendered
“Hermes Desktop connected”. The harness read only counts, never session titles
or conversation content.

Finally, a real Hermes Desktop update was started while the new Connector was
active. Desktop released its backend, launched the detached updater, logged
`detached update finished OK`, and restarted itself with a ready backend. Unlike
the two earlier attempts with the old companion, the update log contained no
Connector venv holder and did not abort on a broker PID.

### Gates still open before distribution

- [ ] Re-run the complete release and packaged-pair gates from the final clean
  tagged commit.
- [x] Test an actual Hermes Desktop process after installing the exact packaged
  companion 0.2.4 and fully restarting Desktop.
- [x] Run Hermes' installed virtual-environment blocker scanner with the final
  broker active and confirm the Connector process is not reported.
- [x] Produce the deterministic clean Chrome/companion archives and release
  manifest; record their generated sizes and SHA-256 hashes here only after the
  build exists.
- [ ] Publish the matching GitHub `v0.2.4` prerelease assets before sending the
  Chrome package for review.
- [ ] Upload 0.2.4 to the existing Chrome Web Store item and keep publication
  deferred until review is approved.

The public Chrome Web Store release remains 0.2.3 throughout these candidate
gates. Users must keep companion 0.2.3 until Chrome itself explicitly reports
extension 0.2.4.

## 0.2.3 release candidate — 2026-08-31

### Why 0.2.3 is required

The 0.2.2 companion launched its Windows broker with
`CREATE_NO_WINDOW | DETACHED_PROCESS`, even though Windows ignores
`CREATE_NO_WINDOW` in that combination. It also inherited independently opened
`broker.log` handles whose MSVCRT append positions could race between processes,
and used a raw TCP readiness probe that could leave invalid WebSocket handshake
noise in the log.

The reconciled fix on `main` removes `DETACHED_PROCESS`, keeps
`CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`, opens the Windows log with
kernel-enforced `FILE_APPEND_DATA` semantics, and performs a protocol-valid
WebSocket upgrade for readiness. The 0.2.3 release bump also makes Chrome show a
new companion-reinstallation notice to users upgrading from 0.2.2.

### Local release-candidate validation

The fast gate passes on Windows with Python 3.11 and Node.js 24:

- the 64-test Python suite is green (58 passed and six platform/privilege skips),
  including the native two-process Windows append test, the explicit
  no-`DETACHED_PROCESS` launch assertion, and the valid WebSocket readiness probe;
- 19 JavaScript tests pass, including the 0.2.2-to-0.2.3 upgrade notice;
- both the PowerShell installer and normal-user double-click `.cmd` path install
  companion 0.2.3 and verify the installed payload version;
- the real single-browser Chrome acceptance passes every advertised action,
  upgrade notice, exact routing, and fail-closed check;
- the real two-browser acceptance passes concurrent isolated profiles,
  ownership transfer, and stale-owner revocation.

The public product screenshot and video remain identified as 0.2.2 captures.
The 0.2.3 patch does not change the depicted product UI, so their provenance is
preserved rather than relabelled.

### Clean packaged artifacts

The deterministic clean build reports `sourceDirty: false`. Its publishable
archives are:

- `hermes-connector-0.2.3-chrome.zip` — 57,590 bytes — SHA-256
  `039d0b569f623a70e8c1f180a3372595d7f733d3160bc195dc1c52864edfc3e7`;
- `hermes-connector-0.2.3-companion.zip` — 28,220 bytes — SHA-256
  `32fbae02a31874af223cdd06bcce7e02443fa366a0327cc06419aec6db9f55f6`.

The exact extracted Chrome and companion ZIP pair passes both the single-browser
and two-browser real Chrome acceptance suites. The published
`release-0.2.3.json` records the tagged source commit, a clean source tree, and
the same deterministic archive hashes.

### Completed 0.2.3 distribution status — 2026-09-01

- [x] The final tagged commit passed the release gate on Windows, macOS, and
  Ubuntu.
- [x] The public GitHub `v0.2.3` release is normal and marked Latest; its
  matching companion and release manifest are published.
- [x] The existing Chrome Web Store item publicly serves 0.2.3. The official
  update endpoint reports 0.2.3, and the distributed CRX matches the release
  code; Google adds only `update_url` and verified-content metadata.
- [x] Public Pages serves the 0.2.3 setup, companion, upgrade, and compatibility
  cutover documentation.
- [ ] A final Store-installed smoke test in the intended signed-in Chrome
  profile, including the 0.2.2-to-0.2.3 companion reinstall notice, remains to
  be performed.

## Historical evidence — 2026-08-03 — 0.2.2 release candidate

### Why 0.2.2 was required

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

### Why 0.2.1 was required (historical)

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

### Fast release gate

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

### Real Chrome extension acceptance

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

### Broker recovery

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

### Multi-profile installation

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

### Store artwork and verified live capture

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

### Completed 0.2.2 distribution evidence

GitHub release v0.2.2 and its three version-matched artifacts were published,
the existing Chrome Web Store item was updated to 0.2.2, and the public Pages
documentation was aligned with that Store pair. The later Windows reliability
fix is intentionally distributed as 0.2.3 rather than replacing 0.2.2 assets.
