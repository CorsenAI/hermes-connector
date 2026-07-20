# Hermes Connector

Hermes Connector attaches exact Hermes profiles and sessions to user-selected
tabs in a real Google Chrome profile. The side panel embeds the real local
Hermes dashboard; it does not create a second chat or a hidden automation
browser.

Unofficial community project by Corsen AI. Not affiliated with or endorsed by
Nous Research or Google.

Public links: [download and setup](https://corsenai.github.io/hermes-connector/),
[support](https://corsenai.github.io/hermes-connector/support/), and
[privacy policy](https://corsenai.github.io/hermes-connector/privacy/).

## What it does

- Select a real Hermes profile/session from the local dashboard.
- Attach one or more chosen Chrome tabs to that session.
- Route every Hermes browser tool call to that exact session and active tab.
- Keep simultaneous projects isolated, even when requests are interleaved.
- Navigate, inspect, read, click, type, scroll, screenshot, hover, use keys,
  select options, drag, find, use history, and manage scoped tabs.
- Optionally use Chrome's debugger transport for trusted input and dialogs.
- Use the user's normal signed-in Chrome profile and existing site sessions.

There is no fallback to the globally active or most recently used tab. If a
Hermes session has no attached target, its browser action fails visibly.

## Components

```text
real Hermes session
  -> Hermes companion client
  -> authenticated loopback broker (127.0.0.1:8765)
  -> exact Chrome profile identity
  -> exact attached session/tab scope
  -> requested browser action
```

- `extension/`: reviewable Manifest V3 Chrome extension.
- `hermes-plugin/`: cross-platform Hermes companion and single local broker.
- `tests/`: protocol, routing, installer, packaging, UI-module, and live-browser
  acceptance tests.
- `docs/`: product contract, v2 architecture, and release acceptance gates.
- `store/`: Chrome Web Store copy and hostable privacy page.

## Install a release

Two artifacts are published together and must have the same version:

- `hermes-connector-<version>-chrome.zip`: upload to the Chrome Web Store or
  load unpacked during development.
- `hermes-connector-<version>-companion.zip`: install once into the local Hermes
  home.

Version 0.2.0 companion:
[download the versioned release artifact](https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.0/hermes-connector-0.2.0-companion.zip).

### 1. Install the companion

Extract the companion archive, then run:

Windows PowerShell:

```powershell
.\install.ps1
```

macOS or Linux:

```sh
./install.sh
```

The installer copies the plugin atomically, preserves the previous version,
enables `hermes-connector`, and prints a private pairing code. Restart any
already-running Hermes dashboard, gateway, or chat process afterward.

### 2. Install and pair Chrome

Install the Store extension. For local development, open
`chrome://extensions`, enable Developer mode, choose **Load unpacked**, and
select `extension/`.

Open the Hermes Connector side panel, then:

1. Open settings and name this Chrome profile.
2. Paste the pairing code printed by the companion installer.
3. Keep the default local dashboard and broker addresses unless Hermes uses
   different loopback ports.
4. Save, choose a real Hermes session, and attach the tabs it may control.
5. Enable **Trusted input** only when reliable native input/dialog handling is
   needed; Chrome displays its debugger banner while attached.

Only attached tabs can be read or controlled. Opening **Choose tabs** displays
tab titles and URLs locally so the user can select them.

## Build and verify

Fast, isolated release gate:

```powershell
.\scripts\package.ps1 -AllowDirty
```

Omit `-AllowDirty` for a real release; the builder refuses an uncommitted source
tree, runs all fast tests, produces deterministic allowlisted ZIPs, and records
SHA-256 hashes in `dist/release-<version>.json`.

Live extension acceptance using Chromium or Chrome for Testing:

```powershell
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" tests\e2e_chromium.py
```

The live test loads the actual service worker and exercises the real Chrome
APIs, companion broker, mutual pairing, exact two-profile routing, trusted
click/type, scoped tab management, and fail-closed behavior. It uses temporary
browser and Hermes homes and never touches the user's installed extension.

Two simultaneous real isolated Chrome profiles and cross-profile ownership
transfer:

```powershell
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" tests\e2e_multi_browser.py
```

## Privacy and security

- Loopback-only transport; no Corsen AI relay or telemetry.
- Persistent random browser identities, not account emails or scanned Chrome
  profile directories.
- Role-bound mutual HMAC authentication; the pairing secret is never put on the
  wire or exposed through Hermes tools.
- URL secret redaction, sensitive form-field redaction, bounded messages, and
  exact session/tab authorization.
- Page content goes to the user's local Hermes. A remote model receives it only
  if the user configured Hermes to use that provider.

See [PRIVACY.md](PRIVACY.md), [docs/PRODUCT-SPEC.md](docs/PRODUCT-SPEC.md), and
[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).
