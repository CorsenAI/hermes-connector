# Hermes Connector launch kit

Use this kit after the refreshed public page is live. Adapt the opening line to
the community instead of posting identical text everywhere.

## Canonical positioning

**Hermes Connector is a Chrome browser extension for Hermes Agent that routes
each Hermes session only to the tabs the user explicitly chooses.**

Proof points that can be stated publicly:

- Works with the user's real, signed-in Google Chrome profile.
- Keeps exact Hermes profile, session, Chrome profile, and tab bindings.
- Can navigate, inspect, read, click, type, scroll, capture screenshots, and
  manage tabs inside the selected scope.
- Uses an authenticated loopback companion; Corsen AI runs no relay and
  receives no browsing telemetry.
- Fails closed when a Hermes session has no attached tab.
- Available from the Chrome Web Store; Hermes Agent and the matching local
  companion are required.

Do not claim that the project is official, endorsed by Nous Research, the
first, perfectly secure, or universally compatible.

## Canonical links

- Chrome Web Store: https://chromewebstore.google.com/detail/hermes-connector-%E2%80%94-by-cor/cdhaldcgafmkcnpanlmmpaebabnlledm
- Complete video demo: https://youtu.be/4akSq9cMmFw
- Product and setup: https://corsenai.github.io/hermes-connector/
- Source: https://github.com/CorsenAI/hermes-connector
- Support: https://corsenai.github.io/hermes-connector/support/
- Privacy: https://corsenai.github.io/hermes-connector/privacy/

## YouTube

Published video: https://youtu.be/4akSq9cMmFw

Title:

```text
Hermes Agent in Your Real Chrome Tabs — Hermes Connector Demo
```

Description:

```text
Hermes Connector is a Chrome browser extension for Hermes Agent. It connects an
exact local Hermes profile and session to only the Chrome tabs you choose, so
multiple browser projects can stay isolated while Hermes navigates, reads,
clicks, types, and captures screenshots in your real signed-in profile.

Install from the Chrome Web Store:
https://chromewebstore.google.com/detail/hermes-connector-%E2%80%94-by-cor/cdhaldcgafmkcnpanlmmpaebabnlledm

Setup and companion download:
https://corsenai.github.io/hermes-connector/

Open source:
https://github.com/CorsenAI/hermes-connector

Hermes Connector is an unofficial community project by Corsen AI. It is not
affiliated with or endorsed by Nous Research or Google. A local Hermes Agent
installation and the matching companion are required.
```

Suggested chapters for a longer tutorial:

```text
00:00 What Hermes Connector does
00:20 Install the Chrome extension
00:40 Install the local companion
01:10 Pair a Chrome profile
01:35 Choose a Hermes session
02:00 Attach only the tabs Hermes may control
02:30 Run and verify a browser task
03:00 Privacy and Trusted input
```

Tags: `Hermes Agent`, `Hermes browser extension`, `Chrome extension`,
`browser automation`, `local AI`, `AI agent`.

## X / Twitter

```text
Hermes Agent can now work in the Chrome tabs you explicitly choose.

Hermes Connector binds an exact Hermes session to selected tabs in your real,
signed-in Chrome profile — with local transport, isolated projects, and no
Corsen AI relay or browsing telemetry.

Chrome Web Store + setup:
https://corsenai.github.io/hermes-connector/

Open source:
https://github.com/CorsenAI/hermes-connector

Unofficial community project by Corsen AI.
```

Attach the short landscape video. If posting a thread, use the second post for
the companion requirement and the third for the security model; do not hide
those details below a promotional claim.

## LinkedIn

```text
We built Hermes Connector because browser automation becomes dangerous and
confusing when an agent can silently fall back to the wrong active tab.

Hermes Connector is a Chrome browser extension for Hermes Agent that creates an
explicit binding between a Hermes profile/session and only the tabs selected by
the user. That means two projects can run in separate Chrome profiles without
crossing their browser scope.

The extension works with the user's real signed-in Chrome profile, while an
authenticated loopback companion handles local routing. Corsen AI operates no
relay and receives no browsing telemetry. If a session has no attached target,
the browser action fails visibly.

It is now available on the Chrome Web Store, with the complete implementation,
privacy model, and acceptance tests published on GitHub:
https://corsenai.github.io/hermes-connector/

Hermes Connector is an unofficial community project and requires a local
Hermes Agent installation plus the matching companion.
```

Recommended media: landscape video first, real product screenshot second,
architecture/security graphic third.

## Reddit or community forum

Suggested title:

```text
I built an open-source Chrome connector that isolates Hermes sessions to chosen tabs
```

Body:

```text
I wanted Hermes to use my normal signed-in Chrome profile without guessing the
globally active tab or mixing two concurrent projects. I built Hermes Connector
to bind an exact Hermes profile/session to only the tabs the user explicitly
attaches.

It can navigate, read, click, type, scroll, capture screenshots, and manage tabs
inside that scope. If nothing is attached, it fails closed. Communication with
the companion stays on authenticated loopback, and Corsen AI runs no relay or
telemetry endpoint.

The extension is on the Chrome Web Store. It also needs a one-time local
companion install alongside Hermes Agent; the setup page explains the complete
flow for Windows, macOS, and Linux.

Demo/setup: https://corsenai.github.io/hermes-connector/
Source and security details: https://github.com/CorsenAI/hermes-connector

This is an unofficial community project by Corsen AI. I would especially value
feedback on onboarding clarity, multi-profile behavior, and the permission
explanations.
```

Post only where project showcases are permitted. Answer technical questions in
the thread; do not cross-post repeatedly or ask for artificial stars/reviews.

## Discord / Telegram community

```text
Released: Hermes Connector, an open-source Chrome browser extension for Hermes
Agent. It binds each Hermes session to only the tabs you choose in your real
signed-in Chrome profile, with local authenticated routing and fail-closed tab
scope. Chrome Web Store, setup, source, and security notes:
https://corsenai.github.io/hermes-connector/

Unofficial community project by Corsen AI. Hermes Agent + companion required.
```

## Verification after publishing

- Confirm the first frame and caption explain the product without audio.
- Confirm every link opens the intended public page in a private window.
- Confirm the companion requirement appears in the post itself.
- Reply to installation questions with the support URL, not copied shell
  commands that may become stale.
- Track Chrome Web Store impressions, listing visitors, installs, and
  uninstallations separately from GitHub stars and video views.
- Ask for honest feedback; never incentivize ratings, reviews, stars, or forks.

## High-fit distribution order

1. Submit the repository to
   [Awesome Hermes Agent](https://github.com/0xNyk/awesome-hermes-agent/issues/new?template=resource-submission.yml)
   as a beta plugin. That project requires a resource-submission issue rather
   than an unsolicited pull request.
2. Share one technical announcement in the official Nous Research Discord
   `#plugins-skills-and-skins` channel. Do not repeat it across unrelated
   channels or ping maintainers.
3. Add one project comment to the next pinned `Showcase Thursday` thread in
   `r/hermesagent`. Link the source and demo rather than posting a marketplace
   advertisement.
4. Recommend the repository through
   [The Hermes Bible submission form](https://www.hermesbible.com/submit),
   emphasizing exact tab control, Store distribution, and the local companion.
5. Submit to
   [Hermes Atlas](https://github.com/ksimback/hermes-ecosystem/issues/new?template=suggest-repo.yml)
   only after the repository has received at least one authentic star. Its
   automated inclusion rules currently reject zero-star repositories.

For every submission, disclose that the project is unofficial and that Hermes
Agent plus the local companion are required. One useful, contextual submission
per platform is enough.
