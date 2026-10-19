# PROJECT_STATE — Hermes Connector

> Short-term memory. Rewritten at every completed step; never appended indefinitely.
> Last update: 2026-10-19 21:30 WEST (chrome-extention-dev session).

## Where we are

- Chrome Web Store: **0.2.4** is the public version. Current Hermes (October 2026) routes Desktop
  through one gateway-hosted API that publishes no session token and runs no headless backend,
  so 0.2.4's panel only lists sessions while `hermes dashboard` is running.
- **0.2.5 is published on GitHub as a pre-release** (2026-10-19 20:22 UTC):
  <https://github.com/CorsenAI/hermes-connector/releases/tag/v0.2.5> — tag `v0.2.5` →
  commit `4a54914` on branch `feat/0.2.5-session-service` (pushed). Assets:
  `hermes-connector-0.2.5-chrome.zip` (SHA-256 `047cfd24…9a7f07`),
  `hermes-connector-0.2.5-companion.zip` (`5779f58a…944e93`), `release-0.2.5.json` (`9adfee6a…`).
  Downloaded anonymously and compared: identical to `dist/`. "Latest" is still **v0.2.4**, so 0.2.4
  users and the public site are unchanged. GitHub's own "Release gate" workflow passed on the
  pushed branch.
- `main` is still `bfd9bc2` (0.2.4): the public site (GitHub Pages from `main`) keeps describing
  the version that the Store serves.
- The owner's machine still runs companion 0.2.4 on purpose (D-005, D-006): installing 0.2.5 there
  before the Store ships extension 0.2.5 would stop his Store-installed Chromes from working.

## Next action

1. **Store upload of `dist/hermes-connector-0.2.5-chrome.zip`** (no rebuild) with deferred
   publishing, listing texts from `store/LISTING.md`. Must be done from the owner's account in his
   own browser: Chrome forbids extensions on Web Store pages and Google rejects automated
   sign-in. Option offered: one-time Chrome Web Store API setup (service account) so later
   versions can be uploaded by the agent (see `docs/research/2026-10-19-chrome-web-store-api.md`).
2. After Google approves 0.2.5: mark the GitHub release as final + Latest, fast-forward `main` to
   the release branch (updates Pages), install companion 0.2.5 on the owner's Hermes with the
   installer (all profiles, including the 12 without a companion).

## Blockers

- Store upload needs the owner (see above). Nothing blocks in the code.

## Verified state

| Item | Value | How verified |
|---|---|---|
| Manifest / companion / broker version | 0.2.5 / 0.2.5 / 0.2.5 | release gate version lock |
| Release branch | `feat/0.2.5-session-service` at `4a54914` (= tag `v0.2.5`), pushed | `git ls-remote`, GitHub API `git/ref/tags/v0.2.5` |
| GitHub pre-release | published, 3 assets, prerelease=true, latest=v0.2.4 | anonymous GitHub API + sha256 of downloaded assets |
| Automatic tests | green | `python tests/run_all.py` → "Fast release gate passed." |
| Chromium acceptance | green, 16 checks | `python tests/e2e_chromium.py` |
| Real Hermes acceptance | green ×3 | `python tests/e2e_real_hermes.py` |
| GitHub CI on the pushed branch | Release gate: success | GitHub Actions API |

## Latest changes

- 2026-10-19: companion session service (broker relay, in-process provider, pure source order,
  background query path, panel wording); docs/pages/listing/privacy updated; release archives
  built; real-Hermes acceptance green; GitHub pre-release v0.2.5 published and verified.
