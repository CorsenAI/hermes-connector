# Hermes Connector — Chrome browser extension for Hermes Agent

Hermes Connector is an open-source Chrome browser extension for Hermes Agent
that connects an exact Hermes profile and session to the signed-in Chrome tabs
you choose. Hermes can then read and control those tabs without using a hidden
automation browser or guessing which tab belongs to which task.

![Hermes Connector — local AI, your tabs](store/promo-marquee-1400x560.png)

[**Install version 0.2.2 from the Chrome Web Store**](https://chromewebstore.google.com/detail/hermes-connector-%E2%80%94-by-cor/cdhaldcgafmkcnpanlmmpaebabnlledm)
· [Download companion 0.2.2](https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.2/hermes-connector-0.2.2-companion.zip)
· [Setup and support](https://corsenai.github.io/hermes-connector/support/)
· [Privacy policy](https://corsenai.github.io/hermes-connector/privacy/)

> Unofficial community project by Corsen AI. Not affiliated with or endorsed
> by Nous Research or Google.

## Current release

The public Chrome Web Store release is **0.2.2**. The extension and local
companion must have exactly the same version.

| Chrome extension | Matching companion | Protocol / default broker | Status |
| --- | --- | --- | --- |
| 0.2.2 | [Companion 0.2.2](https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.2/hermes-connector-0.2.2-companion.zip) | Protocol 4 / `127.0.0.1:8766` | Current public release |
| 0.2.1 | [Companion 0.2.1](https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.1/hermes-connector-0.2.1-companion.zip) | Protocol 4 / `127.0.0.1:8766` | Legacy released/sideloaded pair |
| 0.2.0 | [Companion 0.2.0](https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.0/hermes-connector-0.2.0-companion.zip) | Protocol 3 / `127.0.0.1:8765` | Legacy pair; see disk-recovery note |

Do not mix versions. Check `chrome://extensions` before installing a companion.
The complete compatibility, upgrade, and version 0.2.0 LevelDB recovery guide
is available on the [support page](https://corsenai.github.io/hermes-connector/support/).

## What it does

Hermes Connector embeds the real local Hermes dashboard in Chrome's side panel.
You decide which tabs each Hermes session may access, and the connector keeps
that scope exact even when several projects, sessions, or Chrome profiles run at
the same time.

With an attached tab, Hermes can:

- inspect and read the visible page;
- navigate, click, type, scroll, hover, select, drag, and use keyboard actions;
- find text, use browser history, and take requested screenshots;
- open, list, switch, and close tabs inside the session's authorized scope;
- keep concurrent Hermes projects isolated from one another.

There is no fallback to the globally active or most recently used tab. If a
Hermes session has no attached target, its browser action fails visibly.

## Install version 0.2.2

### 1. Install the Chrome extension

Install Hermes Connector from the
[Chrome Web Store](https://chromewebstore.google.com/detail/hermes-connector-%E2%80%94-by-cor/cdhaldcgafmkcnpanlmmpaebabnlledm),
then verify that `chrome://extensions` shows version **0.2.2**.

### 2. Install the matching companion

Download and extract
[`hermes-connector-0.2.2-companion.zip`](https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.2/hermes-connector-0.2.2-companion.zip).

On Windows, double-click `Install Hermes Connector.cmd`, or run:

```powershell
.\install.ps1
```

On macOS or Linux, run:

```sh
./install.sh
```

Restart every running Hermes dashboard, gateway, or chat process. Re-run the
installer after creating a new named Hermes profile.

### 3. Pair Chrome and choose the tabs

In the Hermes Connector side panel:

1. Give this Chrome profile a recognizable name.
2. Paste the private pairing code printed by the installer.
3. Select the Hermes profile and session you want to use.
4. Choose **Attach active tab** or **Choose tabs**.
5. Ask Hermes to work with the selected page.

Tab titles and URLs are displayed locally when you open **Choose tabs**, so you
make the authorization decision yourself.

## Architecture

```text
Hermes profile and session
  -> Hermes Connector companion
  -> authenticated broker on 127.0.0.1:8766
  -> exact local Chrome profile identity
  -> explicitly attached tabs
  -> requested browser action
```

The extension and companion use role-bound mutual HMAC authentication. The
pairing secret is not transmitted over the loopback connection.

## Privacy and security

Hermes Connector is designed to keep authority visible and local:

- no Corsen AI relay, cloud account, advertising, analytics, tracking, or telemetry;
- loopback-only connector transport on `127.0.0.1`;
- explicit tab attachment and exact session-to-tab authorization;
- separate persistent identities for separate Chrome profiles;
- role-bound mutual HMAC authentication without sending the pairing secret;
- sensitive form-field and URL-secret redaction in browser snapshots;
- bounded protocol messages and fail-closed routing;
- Trusted input disabled by default, with Chrome's debugger banner visible when enabled.

Page content is sent to the user's local Hermes installation. A remote model
provider receives it only if the user configured Hermes to use that provider.
Attach only tabs you are comfortable sharing with that configuration.

Read [PRIVACY.md](PRIVACY.md), [docs/PRODUCT-SPEC.md](docs/PRODUCT-SPEC.md), and
[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).

## Build and verify

Run the isolated test gate:

```powershell
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" tests\run_all.py
```

Run live extension acceptance:

```powershell
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" tests\e2e_chromium.py
```

Run two-profile isolation and ownership-transfer acceptance:

```powershell
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" tests\e2e_multi_browser.py
```

For a release, `scripts/package.ps1` refuses an uncommitted source tree, runs
the fast tests, produces deterministic allowlisted ZIPs, and records SHA-256
hashes in `dist/release-<version>.json`. Explicit `-AllowDirty` development
builds are isolated under `dist/dev/` and must not be uploaded to the Store.

## Support

- [Chrome Web Store listing](https://chromewebstore.google.com/detail/hermes-connector-%E2%80%94-by-cor/cdhaldcgafmkcnpanlmmpaebabnlledm)
- [Setup, version compatibility, and troubleshooting](https://corsenai.github.io/hermes-connector/support/)
- [Privacy policy](https://corsenai.github.io/hermes-connector/privacy/)
- [Source code and releases](https://github.com/CorsenAI/hermes-connector)

Hermes Connector is released under the [MIT License](LICENSE).
