# Chrome Web Store asset provenance

## Final files

- `store-icon-128.png` — 128×128 Store icon.
- `promo-small-440x280.png` — 440×280 small promotional tile.
- `promo-marquee-1400x560.png` — 1400×560 marquee promotional banner.
- `screenshot-product-1280x800.png` — 1280×800 verified live end-to-end product
  capture; SHA-256
  `8F5DEAA207A2F513D5D9B6C5EF9E88CEBC44C9344209670095A71953AC7D3585`.

The fast release gate reads each PNG's IHDR and refuses dimensions that do not
match the Chrome Web Store requirements.

## Promotional tile

The promotional tile was generated from `store-icon-128.png`, supplied only as
the existing brand reference, using the reproducible prompt below.
The selected landscape result was center-cropped by five source pixels and
downscaled to the exact 440×280 Store size.

Prompt:

```text
Use case: ads-marketing
Asset type: Chrome Web Store small promotional tile, final crop 11:7 landscape
Primary request: Create a polished promotional banner for the Hermes Connector Chrome extension using Image 1 only as the existing brand-mark reference. Present a crisp, faithful version of the circular cyan-to-magenta Hermes circuit mark as the visual anchor, with subtle flowing connection lines suggesting one local AI agent securely connecting to several browser tabs.
Scene/backdrop: deep near-black navy background with restrained cyan and magenta glow; clean premium technology aesthetic
Style/medium: precise high-end digital brand illustration, sharp geometric forms, readable at thumbnail size
Composition/framing: 11:7 landscape; brand mark on the left third; clear text hierarchy on the right; generous safe margins; no tiny UI mockups
Color palette: preserve the cyan, electric blue, purple, and magenta identity from Image 1
Text (verbatim): "HERMES CONNECTOR" and "LOCAL AI. YOUR TABS."
Typography: clean bold geometric sans-serif, high contrast, render both lines exactly once
Constraints: preserve the recognizable brand identity from Image 1; no browser or Google logos; no third-party marks; no people; no watermark; no extra text; no misspellings; no fine print; no fake interface screenshot
```

## Verified live product capture

The screenshot is not generated, composited, or backed by prewritten dashboard
content. It is an OS-level capture of a real headed Chrome for Testing window
running the 0.2.2 candidate extension, the matching candidate companion, and a
real local Hermes model session. The browser and Hermes profile are isolated;
the attached page is the public, non-sensitive `https://example.com/` test page.

Before capture, the acceptance test proves from Hermes' own session-scoped
agent log that `bridge_status`, `bridge_current_url`, and `bridge_read` each
completed successfully against the exact attached Chrome tab. It independently
requires Chrome to report `https://example.com/` and title `Example Domain`,
checks the model's four-line proof response, verifies the saved tab binding,
opens the real side panel through `Ctrl+Shift+H`, and captures only after the
proven transcript is visible and the panel reports `Ready · Hermes + Chrome`.

Reproduce the live acceptance and write a review copy outside the repository:

```powershell
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" `
  tests/e2e_real_hermes.py --headed `
  --capture "$env:TEMP\hermes-connector-real-e2e.png"
```

Visually review the temporary PNG before intentionally copying it to the Store
asset path. The deterministic fixture-only renderer remains available as
`python tests/capture_store_screenshot.py`; its default output is
`tests/artifacts/store-fixture-preview-1280x800.png`, so it cannot overwrite the
verified product screenshot.

## Marquee promotional banner

The marquee banner was generated using `promo-small-440x280.png` only as the
existing style and brand reference and the reproducible prompt below.
The selected result was downscaled to the exact 1400×560 Store size and saved
as a 24-bit RGB PNG.

Prompt:

```text
Use case: ads-marketing
Asset type: Chrome Web Store marquee promotional banner, final target 1400 x 560 pixels, wide 5:2 composition.
Input image: the provided 440 x 280 Hermes Connector promotional tile is a style and brand reference.
Primary request: create a premium wide promotional banner for the public Chrome extension Hermes Connector.
Scene/backdrop: deep near-black navy background with refined cyan, electric blue, violet, and magenta light trails; subtle depth and glow, uncluttered.
Subject: preserve the recognizable circular circuit-style C mark from the reference on the left, with elegant connection lines flowing toward a small group of browser-tab outlines on the right.
Composition/framing: wide cinematic layout; brand mark on the left third, headline centered-left, browser-tab symbols on the right; generous safe margins; strong readability at small size.
Style/medium: polished high-end technology product marketing, crisp vector-like geometry, restrained neon, professional rather than game-like.
Text (verbatim): "HERMES CONNECTOR"
Secondary text (verbatim): "LOCAL AI. YOUR TABS."
Small attribution (verbatim): "BY CORSEN AI"
Constraints: spell every text string exactly; no other words; no fake UI; no people; no robots; no Google or Chrome logo; no watermark; no gradients behind text that reduce contrast; preserve the existing cyan-to-magenta brand palette and visual identity; make the result suitable for a trustworthy developer tool listing.
```
