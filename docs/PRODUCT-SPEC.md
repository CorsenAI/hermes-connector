# Hermes Connector product contract

Status: source of truth for the public Chrome extension. Other Corsen AI and
Hermes integrations are out of scope.

## Product promise

Hermes Connector attaches real Hermes sessions to tabs in the user's real,
signed-in Google Chrome profile. The side panel either shows the real Hermes
Web dashboard or works beside Hermes Desktop; the extension does not implement
a second, fake chat.

## Required user flow

1. Install Hermes Connector from the Chrome Web Store in each Chrome profile
   that should be controllable.
2. On first opening, follow the extension's built-in explanation and exact
   download link, then run the companion installer once for the local Hermes installation. It
   installs and enables the plugin in the shared home and every existing named
   profile; run it again after creating a new profile.
3. Pair locally with a persistent high-entropy code. No cloud relay is used.
4. Open the side panel and choose a real Hermes profile and session.
5. Attach one or more Chrome tabs to that session and choose its active tab.
6. Chat in the embedded Web dashboard, or continue in Hermes Desktop while the
   panel shows session and tab controls. Browser tools invoked by that exact
   Hermes session act only in its attached tabs.
7. Keep other Hermes sessions/projects isolated, each with its own tabs. A
   single session may open and control additional tabs inside its own scope.

## Identity and routing

- Every installed extension instance owns a random, stable `browserId`. This is
  the actual connected Chrome profile; routing never depends on scanning profile
  directories or account email addresses.
- A browser scope is identified by `profileId + sessionId` and maps to exactly
  one `browserId`, one or more `tabId` values, and one active `tabId`.
- Every action carries the originating Hermes profile and session. There is no
  process-global target tab.
- If a scope has no valid attached tab, the action fails visibly. The extension
  must never guess another active/recent tab.
- New tabs opened by a scoped action are automatically added to that same scope.
- Tab switching and closing operate only on tabs attached to the scope.

## Public-release requirements

- Google Chrome Manifest V3, using the user's normal signed-in profile.
- Windows, macOS, and Linux companion support.
- Loopback-only transport with mutual authentication and no secret on the wire.
- No telemetry or external relay by default.
- No personal paths, emails, tokens, test profiles, machine names, or generated-
  by markers in distributed files.
- Real product screenshots, Corsen AI branding, a public privacy URL, accurate
  permission explanations, and a reproducible Store ZIP.
- The Chrome package and companion package use the same protocol version and are
  tested together from clean installations.
- A Store auto-update that requires a new local companion must display a
  persistent, dismissible reinstall notice; Chrome cannot update that local
  component itself.
- Read-only tab rendering and binding validation must not write extension
  storage or broadcast a binding change when the normalized registry is
  unchanged.
- A first-time user must see the companion purpose, exact download, operating-
  system steps, private-code step, Hermes restart, and tab-attachment flow
  inside the extension without needing to discover repository documentation.

## Explicit non-goals for version 1

- Chromium automation profiles or a hidden throwaway browser.
- Remote browser control over the network.
- Automatic access to a tab that the user did not attach.
- Reimplementing Hermes chat, sessions, models, or personalities in the
  extension.
