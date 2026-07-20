# Chrome Web Store asset provenance

## Final files

- `store-icon-128.png` — 128×128 Store icon.
- `promo-small-440x280.png` — 440×280 small promotional tile.
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
