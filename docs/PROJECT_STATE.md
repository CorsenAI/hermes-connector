# PROJECT_STATE — Hermes Connector

> Short-term memory. Rewritten at every completed step; never appended indefinitely.
> Last update: 2026-10-19 (chrome-extention-dev session).

## Where we are

- Public release on the Chrome Web Store: **0.2.4**. Current Hermes (October 2026) routes Desktop
  through one gateway-hosted API that publishes no session token and runs no headless backend,
  so 0.2.4's panel only works while `hermes dashboard` is running ("Hermes dashboard unavailable"
  otherwise). Reproduced live with the unmodified 0.2.4 extension.
- **0.2.5 is implemented, tested and packaged** on branch `feat/0.2.5-session-service`
  (3 commits on top of `main`/`bfd9bc2`): the panel asks a connected companion for the Hermes
  session list over the paired broker socket; the companion lists sessions in-process and
  forwards seven label/identity fields; dashboard mode and the legacy headless mode are unchanged;
  the panel names what to start instead of showing Chrome's "refused to connect" page.
- Proof: 94 Python tests, 27 JS tests, fast release gate, Chromium acceptance (16 checks incl.
  the three discovery scenarios), packaged pair acceptance, store-build check, and three green
  real-Hermes runs (`sessionListVia: companion`, `CONNECTOR_E2E_OK`). See `TEST_MATRIX.md`.
- Artifacts (reproducible): `dist/hermes-connector-0.2.5-chrome.zip`
  (SHA-256 `047cfd24…9a7f07`), `dist/hermes-connector-0.2.5-companion.zip`
  (SHA-256 `5779f58a…944e93`), `dist/release-0.2.5.json`. Unpacked copy for the owner's Chrome:
  `data/preview/hermes-connector-0.2.5/` (profile workspace, outside the repository).

## Next action

Owner decisions: (1) smoke-test 0.2.5 on his Chrome (unpacked preview + 0.2.5 companion on all
profiles — note the 0.2.4 Store extension in other Chrome profiles then shows the companion update
notice until the Store ships 0.2.5), (2) GO to merge into `main`, tag `v0.2.5`, publish the GitHub
prerelease with the two archives and `release-0.2.5.json`, push Pages, and upload the Chrome ZIP to
the Store item with deferred publishing.

## Blockers

None in the code. Publication requires the owner's accounts and explicit GO.

## Verified state

| Item | Value | How verified |
|---|---|---|
| Manifest / companion / broker version | 0.2.5 / 0.2.5 / 0.2.5 | release gate version lock |
| Branch / commits | `feat/0.2.5-session-service` — `4dcb79a`, `1886196`, `b4623be` (+ this docs commit) | `git log --oneline -4` |
| Automatic tests | green | `python tests/run_all.py` → "Fast release gate passed." |
| Chromium acceptance | green, 16 checks | `python tests/e2e_chromium.py` |
| Real Hermes acceptance | green ×3 | `python tests/e2e_real_hermes.py` |
| Store build | built, reproducible | `dist/release-0.2.5.json` |

## Latest changes

- 2026-10-19: companion session service (broker relay, in-process provider, pure source order,
  background query path, panel wording) — tests first, then code; docs/pages/listing/privacy
  updated; release archives built; real-Hermes acceptance adapted to current Hermes and green.
