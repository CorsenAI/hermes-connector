# PROJECT_STATE — Hermes Connector

> Short-term memory. Rewritten at every completed step; never appended indefinitely.
> Last update: 2026-10-20 (Claude Code session, chrome-extention-dev profile).

## Where we are

- Chrome Web Store: **0.2.4** is the public version (needs `hermes dashboard` with current Hermes).
- **0.2.5 is superseded.** Its GitHub prerelease (2026-10-19) was built from a local `main` frozen
  at 0.2.4 and lacked the 26 commits published on `origin/main` since (security fixes in shipped
  extension code). It was never submitted to the Store and is left in place, marked superseded.
- **0.2.6 = 0.2.5 session service + `origin/main`** (D-007), branch `release/0.2.6`. All gates
  green except the real-model acceptance, which Hermes' one-gateway-per-user rule blocks on this
  machine while the owner's live gateway runs (TEST_MATRIX T-124). Archives in `dist/`:
  `hermes-connector-0.2.6-chrome.zip` (`08e2645a…eb414b5`),
  `hermes-connector-0.2.6-companion.zip` (`80fc7bc4…36aeb6`), `release-0.2.6.json`,
  `release-notes-0.2.6.md`.
- `main` (local and GitHub) = `8f54e7a`; the release branch contains it, so `main` can be
  fast-forwarded at the Store cutover.
- The owner's machine runs companion 0.2.4 on purpose (D-005): companion 0.2.6 would stop the
  owner's Store-installed 0.2.4 Chromes until the Store ships 0.2.6.

## Next action

1. Publish GitHub prerelease `v0.2.6` (owner approved 2026-10-20): push `release/0.2.6` + tag,
   3 assets, `make_latest=false`; prepend a "superseded by 0.2.6" note to the `v0.2.5` release.
   Verify anonymously (hashes, Latest still v0.2.4, companion URL HTTP 200).
2. Owner uploads `dist/hermes-connector-0.2.6-chrome.zip` in the Developer Dashboard (Package >
   upload new package), texts from `store/LISTING.md`, submit with deferred publishing.
3. After approval: publish on the Store, promote `v0.2.6` to Latest, fast-forward `main`
   (Pages), install companion 0.2.6 on the owner's Hermes (all profiles), owner smoke test (T-116).

## Blockers

- Store upload needs the owner's browser (Chrome forbids extensions on Web Store pages).
