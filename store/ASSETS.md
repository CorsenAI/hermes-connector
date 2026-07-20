# Chrome Web Store asset provenance

## Final files

- `store-icon-128.png` — 128×128 Store icon.
- `promo-small-440x280.png` — 440×280 small promotional tile.
- `promo-marquee-1400x560.png` — 1400×560 marquee promotional banner.
- `screenshot-product-1280x800.png` — 1280×800 actual-product screenshot.

The fast release gate reads each PNG's IHDR and refuses dimensions that do not
match the Chrome Web Store requirements.

## Promotional tile

The promotional tile was generated with OpenAI's built-in image generation
tool. `store-icon-128.png` was supplied only as the existing brand reference.
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

## Product screenshot

The screenshot is not generated or composited. It is an OS-level capture of a
real headed Chrome for Testing window running the unpacked extension and its
actual side panel. The test harness supplies an isolated browser profile,
loopback companion, authenticated dashboard fixture, two non-sensitive Hermes
sessions, and a release-workspace fixture tab. It opens the extension via the
real `Ctrl+Shift+H` action gesture and verifies `browser paired`, the selected
session, and one exact attachment before capture.

On Windows, run the capture with a Python environment containing `websockets`
and Pillow:

```powershell
python tests/capture_store_screenshot.py
```

The script refuses to overwrite the final screenshot unless `--force` is
provided.

## Marquee promotional banner

The marquee banner was generated with OpenAI's built-in image generation tool,
using `promo-small-440x280.png` only as the existing style and brand reference.
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
