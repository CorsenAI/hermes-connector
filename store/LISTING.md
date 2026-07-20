# Chrome Web Store listing — Hermes Connector 0.2.0

Upload: `dist/hermes-connector-0.2.0-chrome.zip`

Privacy policy: `https://corsenai.github.io/hermes-connector/privacy/`

Support: `https://corsenai.github.io/hermes-connector/support/`

Companion download: `https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.0/hermes-connector-0.2.0-companion.zip`

Source: `https://github.com/CorsenAI/hermes-connector`

## Upload assets

- Icon: `store/store-icon-128.png` (128×128)
- Small promo: `store/promo-small-440x280.png` (440×280)
- Product screenshot: `store/screenshot-product-1280x800.png` (1280×800)

## Item name

```text
Hermes Connector — by Corsen AI
```

## Summary

```text
Attach exact local Hermes sessions to chosen tabs and let them read, click, type, navigate, and manage scoped tabs.
```

## Category and language

```text
Developer Tools
English (United States)
```

## Detailed description

```text
Hermes Connector brings your own locally installed Hermes agent into Chrome's side panel and lets the exact Hermes session you select act in the tabs you explicitly attach.

Use your normal signed-in Chrome profile and existing site sessions—no hidden automation profile and no guessing which tab should be controlled.

Core capabilities:
• Choose a real local Hermes profile and session
• Attach one or more tabs to that exact session
• Navigate, inspect, read, click, type, scroll, screenshot, hover, use keys, select, drag, find, and use browser history
• Open, list, switch, and close tabs only inside the session's own scope
• Run simultaneous Hermes projects without crossing their tabs
• Refuse browser actions when a session has no attached target

Local architecture:
• The extension connects to the separately installed Hermes Connector companion on 127.0.0.1
• There is no Corsen AI relay, account, analytics, tracking, or telemetry
• The pairing secret uses mutual authentication and is never sent over the connection
• The real local Hermes dashboard is embedded in an isolated side-panel frame

Data disclosure:
To perform its user-facing function, the extension handles visible website content, requested screenshots, and the URLs/titles of tabs you attach. Opening “Choose tabs” displays current tab titles and URLs locally so you can select them. This data is sent to your local Hermes installation, not to Corsen AI. If you configured Hermes to use a remote model provider, Hermes may send the content to that provider under your configuration and the provider's terms.

Sensitive field values such as passwords, one-time-code inputs, and payment fields are redacted from accessibility snapshots. Visible page text or screenshots can still contain sensitive information, so attach only tabs you are comfortable sharing with your Hermes configuration.

Trusted input is off by default. When enabled, it uses Chrome's debugger transport for reliable input and dialogs; Chrome displays its debugging banner while attached.

Requirements:
• A local Hermes Agent installation and dashboard
• The matching Hermes Connector companion (same version), available from the support/download page

Unofficial community extension by Corsen AI. Not affiliated with or endorsed by Nous Research or Google.
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
Stores a random local browser identity, loopback settings, pairing preference, and exact Hermes session-to-tab bindings on the device.
```

`sidePanel`

```text
Displays the connector controls and the isolated local Hermes dashboard alongside the user's page.
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

Certifications:

- Data is used only for the single purpose and user-facing features.
- Data is not sold or used for advertising, profiling, or creditworthiness.
- Corsen AI does not receive or permit human access to locally processed data.
- Privacy policy and Store listing disclose the user-selected Hermes/model data
  path.
- Limited Use certification: yes.

Remote code:

```text
Yes. A cross-origin iframe loads the user's own local Hermes dashboard from 127.0.0.1/localhost. That iframe is isolated from extension APIs. No fetched code is evaluated in the service worker, content-script, or extension-page context; all browser-control logic is bundled in the submitted ZIP.
```

## Reviewer note

```text
The extension requires the matching public companion and a local Hermes dashboard. Install the companion, paste its locally printed pairing code into extension settings, select a Hermes session, and attach a test tab. The extension will fail closed for any session without an exact binding. The submitted source includes no minified or remotely fetched control code.
```
