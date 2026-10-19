# PROJECT_STATE — Hermes Connector

> Short-term memory. Rewritten at every completed step; never appended indefinitely.
> Last update: 2026-10-19 (chrome-extention-dev session).

## Where we are

- Public release on the Chrome Web Store: **0.2.4** (extension + companion), `main` at `bfd9bc2`.
- 0.2.4 lists Hermes sessions only through the Hermes **web dashboard** (`/chat` token +
  `/api/profiles/sessions`) or through a Desktop **headless `hermes serve` backend** advertised by
  the companion. Current Hermes (source `ca069e12`, 2026-10-15) runs Desktop through one
  gateway-hosted API that never publishes the token and never sets `HERMES_SERVE_HEADLESS`, so the
  second path is dead and the first depends on a dashboard process that nobody restarts after a
  reboot. Panel symptom: "Hermes dashboard unavailable", empty session list, no tab can be attached.
- Live reproduction (unmodified 0.2.4, real Chromium, 2026-10-19): the panel works as soon as a
  dashboard listens on 127.0.0.1:9119 (200 sessions, embedded chat). Not an extension-code defect,
  but an architecture dependency that no longer holds on current Hermes.
- Work branch for the fix: `feat/0.2.5-session-service` (from `main`). Baseline release gate green
  on this machine (`python tests/run_all.py`: Python suite OK, JS 21/21).

## Next action

Implement the companion **session service** (PRODUCT_PLAN.md §0.2.5) test-first: broker relay
tests in `tests/test_broker.py`, then `hermes-plugin/broker.py` + `bridge_client.py`, then the
extension (`session-sources.js` pure module + `background.js` + `sidepanel.js`), then the
Chromium acceptance scenario.

## Blockers

None for the code. Publication (GitHub release/Pages, Chrome Web Store upload) needs the owner's
explicit GO and his accounts.

## Verified state

| Item | Value | How verified |
|---|---|---|
| Manifest version | 0.2.4 (target 0.2.5) | `extension/manifest.json` |
| Commit | `bfd9bc2` (main) | `git log --oneline -1` |
| Automatic tests | green | `python tests/run_all.py` → "Fast release gate passed." |
| Manual Chrome check | 0.2.4 panel verified live against a running dashboard | diagnostics kept outside the repository |
| Store build | not built for 0.2.5 | — |

## Latest changes

- 2026-10-19: project copied from the delivered tree; worktree metadata pruned; uncommitted
  `archive/connector-real-fix` work stashed for triage; branch `feat/0.2.5-session-service` created.
