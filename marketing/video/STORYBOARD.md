# Hermes Connector verified product video

## Accepted replacement

`hermes-connector-real-e2e-1080p.mp4` is the approved horizontal product demo.

- Duration: 9.30 seconds
- Canvas: 1920×1080, 30 fps, H.264, no audio
- SHA-256:
  `DE91F39FC9E5CE225097F255CB620D324B47A436BD9BA034D1C608A4F01F239D`
- Candidate: Hermes Connector 0.2.2, protocol 4
- Public test page: `https://example.com/`
- Isolated capture profile: `connector-demo`

The video contains no generated interface, prewritten dashboard response,
marketing overlay, account data, pairing code, notification, or private tab.
The 1920×1080 edition only scales the continuous 1280×800 Chrome-window
recording, adds dark side padding, and applies short start/end fades.

## Proof gate

`tests/e2e_real_hermes.py` creates a complete isolated Hermes home and named
profile without copying the user's `.env` or real Connector credential, installs the
candidate companion, starts the candidate extension in an isolated real Chrome
for Testing profile, opens `example.com`, and attaches that exact tab. A real
Hermes model must then call all three tools:

1. `bridge_status`
2. `bridge_current_url`
3. `bridge_read`

The test rejects the run unless Hermes' own session-scoped agent log records a
successful `INFO … tool … completed` line for each call. It independently asks
Chrome for the exact `https://example.com/` URL/title, validates the model proof
response and binding, then starts the real dashboard, opens the actual Chrome
side panel, requires the proven transcript to be visible, and requires
`Ready · Hermes + Chrome`.

Recording starts after that proof gate. The demo therefore shows an already
verified result; it does not claim that inference occurs in real time during
the nine-second clip.

After recording, the test decodes start, Tabs-open, and end frames. It rejects
black/blank frames, a missing UI transition, or an end frame that differs too
far from the unobstructed final OS-window capture.

## Visible sequence

- The real `example.com` page and its exact Hermes target are visible together.
- The real transcript shows three Connector tool calls and the model result.
- `Tabs (1)` opens briefly and shows `Example Domain` as the only authorized
  target, then closes so the chat regains the full panel height.

There are no hidden state-changing cuts in the raw recording.

## Reproduction

```powershell
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" `
  tests/e2e_real_hermes.py --headed `
  --capture "$env:TEMP\hermes-connector-video-proof.png" `
  --record "marketing\video\.build\hermes-connector-real-e2e-clean.mkv"
```

The public MP4 is rendered from that raw MKV with Lanczos scaling to
1728×1080, 96-pixel side padding on each side, H.264 NVENC, and no overlay.

## Rejected legacy draft

The earlier `Project Atlas` promo was rejected because it combined real
extension chrome with fixture HTML, a prewritten Hermes response, oversized
copy over the product UI, and unsupported visual claims. Its GIF, thumbnail,
captions, overlays, and renderer were removed so they cannot be republished by
mistake. Git history retains the audit trail.
