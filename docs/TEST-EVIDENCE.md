# Test evidence — 2026-07-20

Checked acceptance gates are backed by the following commands and results on
Windows with Chromium 149, Python 3.11, and Node.js 24.

## Fast release gate

```text
python tests/run_all.py
```

Result: 17 Python tests and 11 JavaScript tests passed. Coverage includes
role-bound authentication, two-browser routing, explicit ownership transfer,
simultaneous-transfer serialization, stale-owner revocation, profile
impersonation rejection, fail-closed unbound sessions, plugin context and
reload lifecycle propagation, atomic companion installation, deterministic
archive contents and executable POSIX installer mode, permission metadata,
dashboard-token parsing, tab registry behavior, and leakage checks.

## Real extension / real Chrome APIs

```text
python tests/e2e_chromium.py
```

Result: passed with the unpacked extension's actual Manifest V3 service worker,
side-panel page, `chrome.tabs`, `chrome.scripting`, `chrome.debugger`, and
loopback WebSocket. Verified authenticated dashboard session loading, post-pair
tab attachment, two Hermes profiles routed to exact tabs, all advertised action
kinds, PNG screenshot capture, scoped tab management, rejected restricted
navigation, rejected unbound session, cancelled confirm dialog, and debugger
detach. The core routing scenario also passed five consecutive runs after the
binding transaction fix.

## Two real Chrome profiles

```text
python tests/e2e_multi_browser.py
```

Result: two isolated Chromium user-data directories ran concurrently with
distinct stable browser IDs and names. Each Hermes profile reached only its own
Chrome profile. Explicitly attaching one session in the other Chrome profile
rerouted it, revoked the old browser's binding, and left the displaced session
unbound instead of guessing a tab.

## Hermes dashboard and installer

- The dashboard authentication module successfully listed sessions from the
  running local Hermes dashboard without persisting or logging its temporary
  token.
- The companion installer was run against an isolated `HERMES_HOME`; Hermes
  reported `hermes-connector` version 0.2.0 enabled. No live user plugin or
  configuration was changed by this test.
- The same fast gate passed under Ubuntu 24.04 in WSL (Python 3.12 and Node.js
  22), and `tests/e2e_installer_posix.sh` performed a real isolated Linux copy
  through `scripts/install.sh` before removing its temporary home.

## Chrome Web Store artwork

- `store/promo-small-440x280.png` is an exact 440×280 brand promotional tile.
- `store/screenshot-product-1280x800.png` is an exact 1280×800 OS-level capture
  of the real unpacked extension side panel in headed Chrome. The capture proves
  a paired browser, authenticated Hermes session, and one exact attached tab.
  It uses an isolated browser profile, loopback broker, dashboard token, and
  non-sensitive fixture content.
- `tests/capture_store_screenshot.py` reproduces the screenshot and refuses to
  overwrite an existing asset unless `--force` is passed.
- The fast release gate validates the icon, promo, and screenshot PNG headers
  and exact required dimensions.

## Final packaged artifacts

The exact `dist/hermes-connector-0.2.0-chrome.zip` was extracted and loaded in
real Chrome after the public-tree cleanup. It passed both the complete
single-browser acceptance and the two-simultaneous-profile transfer/revocation
acceptance. The exact companion ZIP was extracted and installed into a fresh
isolated Hermes home without printing its pairing secret; Hermes reported
`hermes-connector` version 0.2.0 enabled.

The release manifest records clean tagged source and these SHA-256 values:

```text
hermes-connector-0.2.0-chrome.zip
06c42c6a98590523b2467074cddaeedb7c62010a799244596ebbc74a40428365

hermes-connector-0.2.0-companion.zip
bc6286dae03a8343885fea86672cce86578cc7970551d254552afcfddb3f43c5
```

The Chrome archive contains exactly 12 allowlisted runtime files. The companion
archive contains exactly 11 files and records `install.sh` with mode 0755.

## Public release verification

- The public `main` and `v0.2.0` GitHub Actions runs passed the fast gate on
  `windows-latest`, `ubuntu-latest`, and `macos-latest`. The two POSIX jobs also
  exercised `tests/e2e_installer_posix.sh` through the real shell installer.
- The project, privacy, and support pages each returned HTTPS 200 from
  `https://corsenai.github.io/hermes-connector/`; their published HTML contains
  no analytics script.
- Both assets downloaded from the public GitHub Release matched the byte counts
  and SHA-256 values recorded above.

## Gates still requiring external evidence

- final use in the user's intended signed-in Google Chrome profile;
- Chrome Web Store submission and reviewer approval.
