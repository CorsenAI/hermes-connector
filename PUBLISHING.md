# Chrome Web Store release runbook

This runbook reflects the multiplexed loopback-broker architecture in protocol
v5. There is no native-messaging host.

## 1. Produce release artifacts

From a clean release commit:

```powershell
.\scripts\package.ps1
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" tests\e2e_packaged_release.py
```

The first command must pass all fast tests and produce the three artifacts
below. The second command safely extracts that exact Chrome ZIP and runs both
live-browser acceptance suites against it:

- `dist/hermes-connector-<version>-chrome.zip`
- `dist/hermes-connector-<version>-companion.zip`
- `dist/release-<version>.json`

Verify both SHA-256 values against the release manifest. Upload only the
`-chrome.zip` file to the Chrome Web Store. Publish the matching companion ZIP
separately under the same release version.

## 2. Required public surfaces

- Chrome Web Store: `https://chromewebstore.google.com/detail/hermes-connector-%E2%80%94-by-cor/cdhaldcgafmkcnpanlmmpaebabnlledm`
- Corsen AI official website: `https://corsen.ai/`
- Product and setup: `https://corsenai.github.io/hermes-connector/`
- Privacy: `https://corsenai.github.io/hermes-connector/privacy/`
- Support and installation: `https://corsenai.github.io/hermes-connector/support/`
- Complete video demo: `https://youtu.be/4akSq9cMmFw`
- 0.2.4 release details: `https://github.com/CorsenAI/hermes-connector/releases/tag/v0.2.4`
- Companion 0.2.4: `https://github.com/CorsenAI/hermes-connector/releases/download/v0.2.4/hermes-connector-0.2.4-companion.zip`
- Source: `https://github.com/CorsenAI/hermes-connector`
- Support email: `hello@corsen.ai`

The public pages are deployed from `docs/` in the source repository. Publish
the companion archive and release manifest under a public matching GitHub
**prerelease** before submitting the Store item. Keep that release marked as a
prerelease—not Latest—while Google still distributes the previous Store
version. Promote it to a normal Latest release only at the Store cutover.
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
- up to five screenshots; an optional 1400×560 marquee image;
- an optional public YouTube promotional video shown directly on the listing.

Use real extension UI and real but non-sensitive test content. Do not include
personal accounts, emails, tokens, local paths, or private conversations.

Prepared assets:

- `store/store-icon-128.png` — 128×128;
- `store/promo-small-440x280.png` — 440×280;
- `store/screenshot-product-1280x800.png` — 1280×800 real headed-Chrome
  capture with an isolated real Hermes model, exact attached `example.com` tab,
  and verified `bridge_status` → `bridge_current_url` → `bridge_read` calls.
- `store/screenshot-desktop-1280x800.png` — 1280×800 headed-Chrome Desktop-mode
  product UI capture with the public `example.com` tab and isolated session
  metadata.

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
  shown locally only after the user opens Tabs.
- **Authentication information**: the persistent local Connector pairing
  credential stored in Chrome local storage, plus the ephemeral local Hermes
  session token read into memory. Only HMAC proofs—not the pairing credential—go
  to the companion. The session token is never stored and is returned only to
  the same HTTP loopback Hermes API. Neither is received by Corsen AI.

Certify that the data is not sold, is not used for advertising,
creditworthiness, or unrelated purposes, and is used only for the stated
single purpose. The extension publisher does not receive the data. The local
Hermes installation may forward content to a remote model only when the user
has configured that provider, as disclosed in the listing and privacy policy.

Remote code declaration:

> Yes. In Web-dashboard mode, a cross-origin iframe loads the user's own local
> Hermes dashboard from a loopback address and remains isolated from extension
> APIs. In Hermes Desktop mode, no remote UI or code is loaded: the extension
> reads authenticated session metadata from Desktop's dynamically announced
> loopback API. No fetched code is evaluated by the extension service worker,
> content scripts, or extension page context; all browser-control logic is
> included in the submitted ZIP.

This disclosure matches Manifest V3's isolated-iframe exemption and avoids
misrepresenting the real embedded Hermes UI.

## 5. Permission justifications

- `<all_urls>`: the user may explicitly attach a tab from any web origin;
  Chrome also requires broad host access for requested visible-tab screenshots.
- `scripting`: inject packaged, fixed helper functions into attached tabs to
  inspect and perform requested actions.
- `storage`: retain local random browser identity, settings, the Connector pairing credential,
  and exact session/tab bindings.
- `sidePanel`: display connector controls and Desktop-session status, or the
  isolated local Hermes Web dashboard, alongside the current page.
- `alarms`: keep the loopback WebSocket available while a Hermes task is active
  despite Manifest V3 service-worker suspension.
- `debugger`: Chrome does not permit this permission as optional. The extension
  attaches only after the user enables Trusted input, for reliable input and
  dialog handling in the selected tab; Chrome shows its debugger banner.

## 6. Reviewer instructions

Provide Google with the public companion URL and these exact steps:

1. Install the companion in an isolated Hermes home and fully restart Hermes
   Desktop, or restart the Web dashboard process.
2. Copy the pairing code printed by the installer.
3. Open the extension side panel, paste the code, and save.
4. Choose a real/local test Hermes session and attach a test tab. With Hermes
   Desktop, confirm the panel shows “Hermes Desktop connected” without running
   `hermes dashboard`.
5. Ask Hermes to call `bridge_snapshot`, `bridge_click`, or `bridge_type`.
6. Confirm an unbound session is refused and another attached session remains
   isolated.

Mention that the companion is required. Hermes Desktop keeps chat in the
Desktop app; Web-dashboard mode uses the isolated iframe. Sensitive permissions
can trigger manual review, so use deferred publishing and answer reviewer
questions promptly.

## 7. Completed 0.2.4 release gates — 2026-09-02

- [x] Clean committed/tagged 0.2.4 source; Store and companion versions match.
- [x] Fast gate, isolated Chromium, and packaged-pair acceptance pass.
- [x] Real Hermes Desktop `serve --port 0` discovery is verified without a
      separately launched Web dashboard.
- [x] Desktop and CLI both launch the broker from the update-safe managed base
      runtime; Hermes' installed blocker scanner does not report that broker.
- [x] Installing 0.2.4 retires only the verified legacy v4/8766 broker and the
      v5 state imports the prior v4 bindings exactly once.
- [x] Exact companion 0.2.4 ZIP is installed on Windows and Desktop is fully
      restarted before the signed-in Chrome smoke test.
- [x] Public GitHub `v0.2.4` release serves the companion, Chrome ZIP, and
      release manifest before Store review begins.
- [x] Store listing, reviewer note, privacy text, support page, and new Desktop
      screenshot describe the same tested behavior.
- [x] Upload only `dist/hermes-connector-0.2.4-chrome.zip` to the existing Store
      item, complete review, and publish the approved version publicly.

The existing Chrome Web Store item publicly serves 0.2.4. The matching GitHub
release is normal and marked Latest, and Pages publishes the matching 0.2.4
setup, companion, upgrade, and compatibility guidance.

## 8. Historical 0.2.3 release gates

- [x] Clean committed/tagged source; Store and companion versions match.
- [x] Fast gate and isolated live Chromium test pass from the packaged source.
- [x] Clean companion install tested on Windows, macOS, and Linux, or the Store
      copy is limited to verified platforms.
- [x] Pre-submit end-to-end pass in the intended signed-in Google Chrome
      profile using the exact extracted release ZIP.
- [x] Official website, product, GitHub, video, privacy, support, companion,
      listing, and dashboard declarations are mutually consistent.
- [x] 128×128 icon, 440×280 promo, and one real 1280×800 screenshot are ready
      and contain no personal data.
- [x] Final artwork uploaded in the Chrome Web Store dashboard.
- [x] Submit for review with deferred publishing; publish only after approval
      and final artifact/hash verification.

## 9. Historical 0.2.3 approval, public cutover, and verification

The existing Chrome Web Store item now publicly serves 0.2.3. The public
GitHub `v0.2.3` release is normal and marked Latest, its original tag and three
verified assets are unchanged, and Pages publishes the matching 0.2.3 setup
and compatibility documentation. Release gates are green on Windows, macOS,
and Ubuntu for both public branches.

- [x] Google approved the submission prepared under deferred publishing.
- [x] The documentation cutover makes 0.2.3 the public/current pair, moves
      0.2.2 to legacy, and updates the compatibility tables plus homepage
      JSON-LD version/download URL to 0.2.3.
- [x] Run the complete release gate on the prepared cutover commit.
- [x] Publish the approved 0.2.3 package from the existing Chrome Web Store
      item without creating a new item or changing the extension ID.
- [x] Publish the documentation cutover and wait for the matching GitHub Pages
      deployment.
- [x] Promote GitHub v0.2.3 from prerelease to a normal release and mark it
      Latest.
- [x] Confirm both that the public Store endpoint serves version 0.2.3 for the
      existing extension ID and that Pages serves the cutover documentation.
- [ ] Smoke-test the Store-installed build in the intended signed-in Chrome
      profile and confirm an upgraded 0.2.2 profile receives the companion
      reinstall notice.

Official references: Chrome Web Store documentation for
[images](https://developer.chrome.com/docs/webstore/images/),
[privacy fields](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy),
[user data](https://developer.chrome.com/docs/webstore/program-policies/user-data-faq),
[Manifest V3](https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements),
and [optional permissions](https://developer.chrome.com/docs/extensions/reference/api/permissions).
