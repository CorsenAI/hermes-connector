# Chrome Web Store listing — Hermes Connector 0.2.4

Upload: `dist/hermes-connector-0.2.4-chrome.zip`

Privacy policy: `https://corsenai.github.io/hermes-connector/privacy/`

Support: `https://corsenai.github.io/hermes-connector/support/`

Official website: `https://corsen.ai/`

Product, setup, and compatibility: `https://corsenai.github.io/hermes-connector/`

Promotional video: `https://www.youtube.com/watch?v=4akSq9cMmFw`

Companion download: `https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.4/hermes-connector-0.2.4-companion.zip`

Source: `https://github.com/CorsenAI/hermes-connector`

## Upload assets

- Icon: `store/store-icon-128.png` (128×128)
- Small promo: `store/promo-small-440x280.png` (440×280)
- Marquee promo: `store/promo-marquee-1400x560.png` (1400×560)
- Verified live E2E capture: `store/screenshot-product-1280x800.png` (1280×800).
  It remains an accurate capture of Web-dashboard mode with real Hermes model
  calls and the exact attached public `example.com` tab in an isolated profile.
- Desktop-mode product UI capture: `store/screenshot-desktop-1280x800.png`
  (1280×800). It shows the real 0.2.4 extension surface attached to public
  `example.com`, with isolated non-sensitive session metadata and no embedded
  Web-dashboard iframe.

## Item name

```text
Hermes Connector — by Corsen AI
```

## Summary

```text
Attach real Hermes sessions to chosen tabs in your signed-in Chrome profile. Local, unofficial, by Corsen AI.
```

## Category and language

```text
Developer Tools
English (United States)
```

## Detailed description

```text
Connect Hermes Agent to the Chrome tabs you choose.

Hermes Connector is a local AI browser automation bridge for Hermes Agent. It works directly with Hermes Desktop or embeds your local Web dashboard in Chrome’s side panel, and routes each selected Hermes session only to the tabs you explicitly attach.

Use your normal signed-in Chrome profile and existing website sessions—without a hidden automation profile and without guessing which tab an agent should control.

WHAT YOU CAN DO

• Choose a real local Hermes profile and session
• Attach one or more Chrome tabs to that exact session
• Let Hermes navigate, inspect, read, click, type, scroll, hover, select, drag, use keyboard shortcuts, take screenshots, search the page, and use browser history
• Open, list, switch, and close tabs only within the selected session’s scope
• Run multiple Hermes projects at the same time without crossing their tabs
• Automatically refuse browser actions when a session has no attached target

BUILT FOR PRECISE, LOCAL CONTROL

Hermes Connector links Chrome to the separately installed Hermes Connector companion on 127.0.0.1. Session-to-tab bindings are explicit, isolated, and revocable. If ownership of a tab moves to another Hermes session or Chrome profile, the previous owner is revoked.

LOCAL CONNECTOR, EXPLICIT CONTROL

• No Corsen AI relay, cloud account, analytics, advertising, tracking, or telemetry
• The pairing secret uses mutual authentication and is never sent over the connection
• Hermes Desktop stays in its own app; the optional local Web dashboard runs inside an isolated side-panel frame
• All browser-control logic is bundled with the extension; no remote control code is downloaded or evaluated

DATA HANDLING

To provide browser automation, the extension handles visible website content, requested screenshots, and the URLs and titles of tabs you attach. Opening “Tabs” displays current tab titles and URLs locally so you can select them. This data goes to your local Hermes installation—not to Corsen AI.

The extension handles two kinds of Authentication information: (1) one persistent local Connector pairing credential stored in Chrome local storage, for which only HMAC proofs—not the credential itself—travel to the companion; and (2) an ephemeral Hermes local session token read into memory and returned only to that same loopback Hermes API. The session token is never stored. Neither item is received by Corsen AI, and the extension does not read website cookies or login storage.

If you configured Hermes to use a remote AI model provider, Hermes may send relevant content to that provider under your configuration and that provider’s terms.

Sensitive form values such as passwords, one-time codes, and payment fields are redacted from accessibility snapshots. Visible page text or screenshots can still contain sensitive information, so attach only tabs you are comfortable sharing with your Hermes configuration.

TRUSTED INPUT

Trusted input is disabled by default. When you enable it, Chrome’s debugger transport is used only for reliable input events and page-dialog handling in the selected attached tab. Chrome displays its debugging banner while attached.

REQUIREMENTS

• A local Hermes Agent installation through Hermes Desktop or the Web dashboard
• The matching Hermes Connector companion, available from the support and download page
• Chrome on a supported desktop system

On first opening, the extension displays the exact companion download button,
plain-language Windows/macOS/Linux steps, an explanation of the local-only
component, and the pairing-code field. On Windows, the companion can be
installed by double-clicking “Install Hermes Connector.cmd”.

UPGRADING FROM AN OLDER VERSION

Chrome updates the extension automatically, but the local companion must be downloaded and installed again. Fully quit and restart Hermes Desktop, dashboards, gateways, and chats after installing companion 0.2.4. Hermes Desktop backends are then discovered automatically even though their local ports change at every launch; running `hermes dashboard` is no longer required for Desktop users. Companion 0.2.4 uses a version-checked protocol 5 broker on port 8767 and safely retires the verified older 8766 broker during upgrade. On Windows, it also keeps its detached broker outside Hermes' managed virtual-environment launcher so it does not block later Hermes Desktop or CLI updates. The update notice and toolbar badge remain visible until you confirm the matching companion is installed.

WATCH THE COMPLETE DEMO

See the full installation and live browser-control walkthrough:
https://www.youtube.com/watch?v=4akSq9cMmFw

Hermes Connector is an unofficial community extension by Corsen AI. It is not affiliated with or endorsed by Nous Research or Google.

OFFICIAL LINKS

Corsen AI official website: https://corsen.ai/
Product, setup, and compatible downloads: https://corsenai.github.io/hermes-connector/
Source code and releases: https://github.com/CorsenAI/hermes-connector
Support: https://corsenai.github.io/hermes-connector/support/
Privacy policy: https://corsenai.github.io/hermes-connector/privacy/
```

## Single purpose

```text
Connect user-selected Chrome tabs to the user's locally installed Hermes agent so that the exact selected Hermes session can read and perform requested browser actions in those tabs.
```

## Permission justifications

`<all_urls>`

```text
The user can explicitly attach a tab from any web origin. Broad host access is required to inspect and act on those selected pages and by Chrome for user-requested visible-tab screenshots. Tabs are not exposed to Hermes until the user attaches them.
```

`scripting`

```text
Runs packaged, fixed helper functions in attached tabs to create accessibility snapshots and perform the user's requested click, typing, scrolling, selection, and related page actions. No fetched code is injected or evaluated.
```

`storage`

```text
Stores a random local browser identity, loopback settings, the local Connector pairing credential, and exact Hermes session-to-tab bindings on the device.
```

`sidePanel`

```text
Displays the connector controls and Desktop-session status, or the isolated local Hermes Web dashboard, alongside the user's page.
```

`alarms`

```text
Keeps the authenticated local WebSocket available during an active Hermes task when the Manifest V3 service worker would otherwise suspend.
```

`debugger`

```text
Chrome does not allow this permission to be requested as optional. The extension does not attach the debugger unless the user enables Trusted input. It is then used only for reliable input events and page-dialog handling in the selected attached tab; Chrome shows its debugger banner while attached.
```

## Privacy practices

Data types to disclose:

- Website content.
- Web history.
- Authentication information — the persistent local Connector pairing credential
  and the ephemeral local Hermes session token. The pairing credential itself is
  never transmitted; the session token is never stored and is sent only to the
  same HTTP loopback Hermes API. Neither is received by Corsen AI.

Certifications:

- Data is used only for the single purpose and user-facing features.
- Data is not sold or used for advertising, profiling, or creditworthiness.
- Corsen AI does not receive or permit human access to locally processed data.
- Privacy policy and Store listing disclose the user-selected Hermes/model data
  path.
- Limited Use certification: yes.

Remote code:

```text
Yes. In Web-dashboard mode, a cross-origin iframe loads the user's own local Hermes dashboard from 127.0.0.1/localhost and remains isolated from extension APIs. In Hermes Desktop mode no remote UI or code is loaded: the extension reads authenticated session metadata from the Desktop backend's dynamically announced loopback API and keeps chat in Hermes Desktop. No fetched code is evaluated in the service worker, content-script, or extension-page context; all browser-control logic is bundled in the submitted ZIP.
```

## Reviewer note

```text
No account or remote credentials are required. Install Hermes Agent or Hermes
Desktop, then download companion 0.2.4 from the public v0.2.4 GitHub prerelease
and run the platform installer. Fully quit and restart Hermes Desktop (or restart
the dashboard/gateway/chat process), paste the locally printed pairing code into
extension settings, select a Hermes session, and attach a test tab. Desktop mode
automatically discovers the authenticated loopback backend and does not require
`hermes dashboard`. Unbound sessions fail closed; Trusted input is off by default.
The submitted source includes no minified or remotely fetched control code.
```
