# DECISIONS — Hermes Connector

> Append-only. One entry per structural decision, dated, with its proof. A changed decision gets a
> new entry that supersedes the old one. Earlier design history: `ARCHITECTURE-V2.md`.

## D-001 — Session discovery moves into the companion (broker relay)

- **Date**: 2026-10-19
- **Status**: ratified
- **Decision**: the paired extension asks the broker for the Hermes session list
  (`browser_query` → `agent_query` → `agent_query_result` → `browser_query_result`); the broker
  relays to one connected companion, which reads the session store in-process and answers.
- **Why**: current Hermes (source `ca069e12`) serves Desktop through the gateway-hosted API, which
  withholds the SPA session token by design (`gateway/run_api.py`: "the gateway-hosted listener
  never publishes it") and never sets `HERMES_SERVE_HEADLESS` (`hermes_cli/web_server_dashboard.py`
  only enters the headless branch for `hermes serve`). Both 0.2.4 discovery paths therefore depend on
  processes that do not exist by default. The companion already runs inside every Hermes process
  and already owns an authenticated loopback channel to the extension.
- **Proof / source**: `docs/research/2026-10-19-hermes-session-service.md`; live reproduction of
  0.2.4 with and without a dashboard (same document).
- **Consequence**: new message kinds on the existing protocol 5 socket (additive; an old broker
  ignores them and the panel falls back). Extension and companion versions bump together to 0.2.5
  (exact broker release handshake). No new permission, no new listener.

## D-002 — Projection of session rows

- **Date**: 2026-10-19
- **Status**: ratified
- **Decision**: the companion forwards only `id`, `profile`, `title`, `display_name`, `source`,
  `last_active`, `is_active` (strings/numbers/booleans, title capped at 200 chars, at most 200 rows).
- **Why**: Hermes session rows carry `cwd`, git roots, token counts and costs. The panel needs a
  label and an identity; nothing else should reach the browser.
- **Proof / source**: row keys observed on the live store (research document).
- **Consequence**: plugin unit test on the projection; the dashboard path is unchanged (Hermes'
  own API decides what it returns there).

## D-003 — Source order in the panel

- **Date**: 2026-10-19
- **Status**: ratified
- **Decision**: configured web dashboard first (embedded chat), then the companion session
  service (conversation stays in Hermes Desktop/CLI), then the legacy advertised headless backend.
- **Why**: the dashboard mode is the richest experience and is unchanged; the companion path is
  the one that always exists; the headless path only exists on older Hermes releases and costs
  nothing to keep.
- **Proof / source**: `extension/src/session-sources.js` (pure module) + its unit test; Chromium
  acceptance scenarios.
- **Consequence**: status text "Hermes dashboard unavailable" is replaced by wording that names
  what to start.

## D-004 — Session provider inside the companion

- **Date**: 2026-10-19
- **Status**: ratified
- **Decision**: the provider first calls Hermes' own aggregated listing
  (`hermes_cli.web_routers.profiles.get_profiles_sessions`, the function behind
  `GET /api/profiles/sessions`), and falls back to a direct read-only `SessionDB` listing per
  profile (`hermes_cli.profiles.profiles_to_serve` + `hermes_state.SessionDB(read_only=True)`).
  Every path is wrapped: any failure yields a bounded error, never an exception into Hermes.
- **Why**: measured on the live install: import 0.36 s, call 0.48 s for 200 rows over 24 profiles.
  Both are internal Hermes APIs; wrapping and the fallback limit the blast radius of a future change.
- **Proof / source**: research document, "provider measurement".
- **Consequence**: the provider runs in a worker thread with a timeout so the broker socket loop
  is never blocked; the plugin's unit tests inject a fake provider.

## D-005 — Development on an isolated Hermes home and a distinct broker port

- **Date**: 2026-10-19
- **Status**: ratified
- **Decision**: 0.2.5 is never installed into the machine's shared Hermes home or profiles while
  0.2.4 is in use there; acceptance runs use a temporary Hermes home and `HERMES_BRIDGE_PORT`.
- **Why**: the exact broker release handshake makes 0.2.4 and 0.2.5 companions stop each other's
  broker on the shared port (`bridge_client._connect_forever`): mixing versions on one home would
  break the owner's working Connector.
- **Proof / source**: `hermes-plugin/bridge_client.py` (incompatible release → `stop_broker_processes`).
- **Consequence**: the live acceptance (`tests/e2e_real_hermes.py`) remains the only path that
  touches a real Hermes, on a temporary home.

## D-006 — 0.2.5 publication order: GitHub pre-release first, Latest unchanged

- **Date**: 2026-10-19
- **Status**: ratified (owner asked the agent to publish)
- **Decision**: v0.2.5 is published as a GitHub **pre-release** (tag `v0.2.5` on the release
  branch, `make_latest=false`) before the Store upload; `main`, Pages and "Latest" stay on 0.2.4
  until Google approves extension 0.2.5, then the release is promoted and `main` fast-forwarded.
- **Why**: the 0.2.5 panel links to the v0.2.5 companion download, which must exist when Google
  reviews the package; 0.2.4 users must keep seeing the 0.2.4 instructions and download.
- **Proof / source**: GitHub API after publication — `releases/tags/v0.2.5` prerelease=true with
  3 assets; `releases/latest` = v0.2.4; downloaded assets' SHA-256 equal `dist/`.
- **Consequence**: publication credentials are a short-lived token limited to public repositories,
  created in the owner's attached tab and stored only in the profile `.env` (never printed); it
  expires 2026-10-26.
