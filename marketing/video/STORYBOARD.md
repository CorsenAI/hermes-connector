# Hermes Connector promo video

## Deliverables

- `hermes-connector-promo-1080p.mp4` — 1920×1080, 30 fps, H.264/AAC, 38.5 seconds.
- `hermes-connector-promo-vertical.mp4` — 1080×1920, 30 fps, H.264/AAC, 38.5 seconds.
- `hermes-connector-thumbnail-1280x720.png` — social/YouTube thumbnail.
- `hermes-connector-demo.gif` — silent short excerpt for GitHub or a landing page.
- `captions-en.srt` — English sidecar captions. The same core copy is burned into both videos.

## Storyboard and factual basis

| Time | Visual | On-screen message | Product evidence |
|---|---|---|---|
| 00:00–00:05 | Official marquee artwork | Your Hermes agent. Your real Chrome tabs. | Project positioning |
| 00:05–00:10 | Real Store product capture | One Hermes session. The exact tabs you choose. | Exact session/tab routing |
| 00:10–00:16 | Real side-panel crop | Your signed-in Chrome profile | Uses the user's normal Chrome profile and sessions |
| 00:16–00:21 | Real attach controls highlighted | Permission stays visible and scoped | Only explicitly attached tabs are accessible |
| 00:21–00:27 | Real UI, darkened for typography | Read. Navigate. Click. Type. | Supported browser actions |
| 00:27–00:32 | Official marquee artwork | Local-first by design | Loopback-only; no Corsen AI relay or telemetry |
| 00:32–00:38.5 | Official marquee artwork | Available on the Chrome Web Store | Public release CTA |

The video deliberately contains no adoption metrics, endorsements, benchmark claims, or simulated results. The interface imagery comes from `store/screenshot-product-1280x800.png`; the brand artwork comes from `store/promo-marquee-1400x560.png`.

## Suggested post copy

**YouTube title**

Hermes Connector — Connect Hermes Agent to Your Real Chrome Tabs

**X / LinkedIn copy**

Hermes Connector connects an exact Hermes session to only the Chrome tabs you choose — inside your normal signed-in profile. Local-first, explicit tab scope, and no Corsen AI relay or telemetry.

Chrome Web Store: https://chromewebstore.google.com/detail/cdhaldcgafmkcnpanlmmpaebabnlledm

Setup and source: https://corsenai.github.io/hermes-connector/

Unofficial community project by Corsen AI. Not affiliated with Nous Research or Google.

## Re-render

From PowerShell:

```powershell
.\marketing\video\render.ps1
```

The renderer uses local FFmpeg only. Its audio bed is synthesized at render time and contains no sampled or copyrighted music.
