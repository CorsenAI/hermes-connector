# Chrome Web Store listing — Hermes Connector 0.2.0

Upload: `dist/hermes-connector-0.2.0-chrome.zip`

Privacy policy: `https://corsenai.github.io/hermes-connector/privacy/`

Support: `https://corsenai.github.io/hermes-connector/support/`

Companion download: `https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.0/hermes-connector-0.2.0-companion.zip`

Source: `https://github.com/CorsenAI/hermes-connector`

## Upload assets

- Icon: `store/store-icon-128.png` (128×128)
- Small promo: `store/promo-small-440x280.png` (440×280)
- Marquee promo: `store/promo-marquee-1400x560.png` (1400×560)
- Product screenshot: `store/screenshot-product-1280x800.png` (1280×800)

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

Hermes Connector is a local AI browser automation bridge for Hermes Agent. It embeds your local Hermes dashboard in Chrome’s side panel and routes each selected Hermes session only to the tabs you explicitly attach.

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

PRIVATE BY ARCHITECTURE

• No Corsen AI relay, cloud account, analytics, advertising, tracking, or telemetry
• The pairing secret uses mutual authentication and is never sent over the connection
• The local Hermes dashboard runs inside an isolated side-panel frame
• All browser-control logic is bundled with the extension; no remote control code is downloaded or evaluated

DATA HANDLING

To provide browser automation, the extension handles visible website content, requested screenshots, and the URLs and titles of tabs you attach. Opening “Choose tabs” displays current tab titles and URLs locally so you can select them. This data goes to your local Hermes installation—not to Corsen AI.

If you configured Hermes to use a remote AI model provider, Hermes may send relevant content to that provider under your configuration and that provider’s terms.

Sensitive form values such as passwords, one-time codes, and payment fields are redacted from accessibility snapshots. Visible page text or screenshots can still contain sensitive information, so attach only tabs you are comfortable sharing with your Hermes configuration.

TRUSTED INPUT

Trusted input is disabled by default. When you enable it, Chrome’s debugger transport is used only for reliable input events and page-dialog handling in the selected attached tab. Chrome displays its debugging banner while attached.

REQUIREMENTS

• A local Hermes Agent installation and dashboard
• The matching Hermes Connector companion, available from the support and download page
• Chrome on a supported desktop system

Hermes Connector is an unofficial community extension by Corsen AI. It is not affiliated with or endorsed by Nous Research or Google.

Open-source project: https://github.com/CorsenAI/hermes-connector
Support and setup: https://corsenai.github.io/hermes-connector/support/
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
