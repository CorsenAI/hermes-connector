# Chrome Web Store release runbook

This runbook reflects the multiplexed loopback-broker architecture in protocol
v3. There is no native-messaging host.

## 1. Produce release artifacts

From a clean release commit:

```powershell
.\scripts\package.ps1
```

The command must pass all tests and produce:

- `dist/hermes-connector-<version>-chrome.zip`
- `dist/hermes-connector-<version>-companion.zip`
- `dist/release-<version>.json`

Verify both SHA-256 values against the release manifest. Upload only the
`-chrome.zip` file to the Chrome Web Store. Publish the matching companion ZIP
separately under the same release version.

## 2. Required public surfaces

- Privacy: `https://corsenai.github.io/hermes-connector/privacy/`
- Support and installation: `https://corsenai.github.io/hermes-connector/support/`
- Companion 0.2.0: `https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.0/hermes-connector-0.2.0-companion.zip`
- Source: `https://github.com/CorsenAI/hermes-connector`
- Support email: `hello@corsen.ai`

The public pages are deployed from `docs/` in the source repository. Publish
the companion archive and release manifest under the matching GitHub release
before submitting the Store item.
- Ensure the Corsen AI developer account has 2-Step Verification enabled.
- Do not submit until the privacy page, companion download, and review
  instructions are public.

## 3. Listing assets

Google currently requires:

- a 128×128 PNG icon inside the extension ZIP (96×96 artwork with transparent
  padding is recommended);
- one 440×280 small promotional image;
- at least one actual-product screenshot, preferably 1280×800 (640×400 is also
  accepted), full bleed and square-cornered;
- up to five screenshots; an optional 1400×560 marquee image.

Use real extension UI and real but non-sensitive test content. Do not include
personal accounts, emails, tokens, local paths, or private conversations.

Prepared assets:

- `store/store-icon-128.png` — 128×128;
- `store/promo-small-440x280.png` — 440×280;
- `store/screenshot-product-1280x800.png` — 1280×800 real headed-Chrome
  capture with isolated test data.

Generation/capture provenance and the reproducible screenshot command are in
`store/ASSETS.md`.

## 4. Privacy practices fields

Single purpose:

> Connect user-selected Chrome tabs to the user's locally installed Hermes
> agent so that the exact selected Hermes session can read and perform requested
> browser actions in those tabs.

Declare the data the extension handles even though processing is local:

- **Website content**: visible text, accessibility structure, element labels,
  and requested screenshots from attached tabs.
- **Web history**: URLs and titles of attached tabs; current tab titles/URLs are
  shown locally only after the user opens Choose tabs.

Certify that the data is not sold, is not used for advertising,
creditworthiness, or unrelated purposes, and is used only for the stated
single purpose. The extension publisher does not receive the data. The local
Hermes installation may forward content to a remote model only when the user
has configured that provider, as disclosed in the listing and privacy policy.

Remote code declaration:

> Yes. A cross-origin iframe loads the user's own local Hermes dashboard from a
> loopback address. The iframe is isolated from extension APIs. No fetched code
> is evaluated by the extension service worker, content scripts, or extension
> page context; all browser-control logic is included in the submitted ZIP.

This disclosure matches Manifest V3's isolated-iframe exemption and avoids
misrepresenting the real embedded Hermes UI.

## 5. Permission justifications

- `<all_urls>`: the user may explicitly attach a tab from any web origin;
  Chrome also requires broad host access for requested visible-tab screenshots.
- `scripting`: inject packaged, fixed helper functions into attached tabs to
  inspect and perform requested actions.
- `storage`: retain local random browser identity, settings, pairing preference,
  and exact session/tab bindings.
- `sidePanel`: display connector controls and the isolated local Hermes
  dashboard alongside the current page.
- `alarms`: keep the loopback WebSocket available while a Hermes task is active
  despite Manifest V3 service-worker suspension.
- `debugger`: Chrome does not permit this permission as optional. The extension
  attaches only after the user enables Trusted input, for reliable input and
  dialog handling in the selected tab; Chrome shows its debugger banner.

## 6. Reviewer instructions

Provide Google with the public companion URL and these exact steps:

1. Install the companion in an isolated Hermes home and restart Hermes.
2. Copy the pairing code printed by the installer.
3. Open the extension side panel, paste the code, and save.
4. Choose a real/local test Hermes session and attach a test tab.
5. Ask Hermes to call `bridge_snapshot`, `bridge_click`, or `bridge_type`.
6. Confirm an unbound session is refused and another attached session remains
   isolated.

Mention that the dashboard iframe and companion are required for the main UI to
be functional during review. Sensitive permissions can trigger manual review,
so use deferred publishing and answer reviewer questions promptly.

## 7. Final release gates

- [x] Clean committed/tagged source; Store and companion versions match.
- [x] Fast gate and isolated live Chromium test pass from the packaged source.
- [x] Clean companion install tested on Windows, macOS, and Linux, or the Store
      copy is limited to verified platforms.
- [ ] Final end-to-end pass in the intended signed-in Google Chrome profile.
- [ ] Privacy URL, support URL, companion URL, listing, and dashboard
      declarations are mutually consistent.
- [x] 128×128 icon, 440×280 promo, and one real 1280×800 screenshot are ready
      and contain no personal data.
- [ ] Final artwork uploaded in the Chrome Web Store dashboard.
- [ ] Submit for review with deferred publishing; publish only after approval
      and final artifact/hash verification.

Official references: Chrome Web Store documentation for
[images](https://developer.chrome.com/docs/webstore/images/),
[privacy fields](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy),
[user data](https://developer.chrome.com/docs/webstore/program-policies/user-data-faq),
[Manifest V3](https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements),
and [optional permissions](https://developer.chrome.com/docs/extensions/reference/api/permissions).
