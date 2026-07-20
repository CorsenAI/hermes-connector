# Privacy Policy — Hermes Connector (unofficial · by Corsen AI)

_Last updated: 2026-07-20_

Hermes Connector lets a Hermes agent running on your computer read and control
Chrome tabs that you explicitly attach. Corsen AI does not operate a relay,
analytics service, account system, or telemetry endpoint for the extension.

## Data the extension handles

To provide its single browser-control purpose, the extension can handle:

- website content from attached tabs, including visible text, accessibility
  structure, element labels, and screenshots you request;
- browsing activity for attached tabs, including their URL and title; when you
  open **Choose tabs**, current tab titles and URLs are displayed locally so you
  can choose which tabs to attach;
- text and navigation instructions sent by your locally configured Hermes agent;
- Hermes profile and session identifiers and titles read from your local Hermes
  dashboard;
- a random browser identifier, tab bindings, the loopback addresses you choose,
  and pairing settings stored in `chrome.storage.local`.

The extension does not read browser cookies or authentication storage. Password,
one-time-code, and payment-field values are redacted from accessibility
snapshots. Visible page text and screenshots can still contain sensitive
information, so attach only tabs you are comfortable sharing with your Hermes
configuration.

## Where data goes

The extension communicates with the separately installed Hermes Connector
companion over an authenticated loopback WebSocket (`ws://127.0.0.1` or
`ws://localhost`) and loads the user-selected local Hermes dashboard over HTTP
loopback. Page data is sent only to that local Hermes installation to perform
the requested action. It is not sent to Corsen AI.

What Hermes does after receiving page content depends on the user's Hermes
configuration. A local model can keep processing on-device. If the user has
configured Hermes to use a remote model or another service, Hermes may transmit
the content to that chosen provider under the provider's terms. Corsen AI does
not select or receive that transmission.

## Storage and retention

The extension stores its random browser identifier, local addresses, pairing
preference, and profile/session-to-tab bindings in Chrome local storage until
the user clears extension data or removes the extension. The extension does not
persist page snapshots, page text, screenshots, or form content. The local
Hermes companion persists the pairing credential and browser-binding preference
under the user's Hermes home. Hermes itself may retain chats or tool results
according to the user's Hermes settings.

## Publisher access and use

Corsen AI does not receive, sell, rent, monetize, or use this data for
advertising, profiling, creditworthiness, or any purpose unrelated to the
extension's single browser-control function. Corsen AI personnel cannot access
locally processed data. There is no telemetry.

Hermes Connector's use of information received from Chrome APIs adheres to the
Chrome Web Store User Data Policy, including the Limited Use requirements.

## Security

The companion binds only to loopback. The extension and companion use a
persistent high-entropy secret with role-bound mutual HMAC authentication; the
secret is not sent over the WebSocket. Each Hermes profile/session is routed
only to tabs explicitly attached to that exact scope. An unbound session is
rejected instead of falling back to another tab.

## Permissions

- `<all_urls>` and `scripting`: read and act on any web origin, because the user
  may attach a tab from any site; `<all_urls>` is also required by Chrome for a
  requested visible-tab screenshot.
- `storage`: retain local pairing, identity, settings, and tab bindings.
- `sidePanel`: provide the connector controls and local Hermes dashboard.
- `alarms`: keep the local WebSocket available during an active task.
- `debugger`: Chrome does not allow this permission to be requested as optional.
  The extension does not attach the debugger unless the user enables **Trusted
  input**; it is then used for reliable clicks, typing, keys, hover, and dialogs
  in the selected tab. Chrome displays its debugging banner while attached.

## User control

Tabs are inaccessible to Hermes Connector until the user attaches them to a
specific Hermes session. The user can detach a tab, disable Trusted input,
clear extension storage, disable the companion plugin, or uninstall the
extension at any time.

## Contact

Questions about this policy: hello@corsen.ai.

Hermes Connector is an unofficial community extension and is not affiliated
with or endorsed by Nous Research or Google.
