# Research — Hermes session discovery for the Connector (2026-10-19)

Facts verified on the installed Hermes source (`~/.hermes/hermes-agent`, commit `ca069e12`,
fast-forwarded 2026-10-15) and on a live machine. Line numbers refer to that checkout.

## 1. Desktop no longer spawns per-profile headless backends

- `apps/desktop/src/store/gateway.ts:1312-1315` — when a profile "rides the primary backend",
  requests go `requestOnPrimaryGateway(...)`, traced as `primary-shared`.
- Desktop log on the live machine: `conn:local::<profile> via=primary-shared primary=local/<p>`
  for every profile; `hermes dashboard --status` → "No hermes dashboard or serve processes running".
- Consequence for 0.2.4: `bridge_client._headless_backend_metadata()` requires
  `HERMES_SERVE_HEADLESS == "1"`; no process has it → `agentBackends: []` in the broker state.

## 2. The gateway-hosted API withholds the SPA session token

- `gateway/run_api.py:64-67` — "Local clients authenticate with tickets minted on the owner-only
  control socket. The SPA session token is a bearer credential any loopback peer (any OS user)
  could read from GET /, so the gateway-hosted listener never publishes it."
  (`web.app.state.withhold_session_token = True`).
- `hermes_cli/web_server_dashboard.py:166-168` — `_serve_index` injects
  `window.__HERMES_SESSION_TOKEN__` only when neither the auth gate nor `withhold_session_token`
  applies. Measured: `GET /` on the gateway port returns the SPA without the token;
  `GET /api/profiles/sessions` without credentials → 401.
- Tickets are redeemed at the WebSocket subprotocol boundary (`run_api.py:242-325`), not usable
  by an extension's `fetch`.

## 3. `HERMES_SERVE_HEADLESS` only exists for `hermes serve`

- `hermes_cli/web_server_dashboard.py:118-141` — the headless branch (token-only root page) is
  mounted only when the environment variable is `"1"`, i.e. the standalone `hermes serve`
  backend. Desktop on current Hermes does not launch it.

## 4. The dashboard's aggregated session listing is plain Python

- `hermes_cli/web_routers/profiles.py:453-511` — `get_profiles_sessions(limit, offset,
  min_messages, archived, order, profile, ...)` "opens each profile's `state.db` directly" via
  `_profile_targets()` (→ `hermes_cli.profiles.profiles_to_serve(multiplex=True,
  include_standalone=True, include_parked=True)`) and `_read_profile_db(...)` (read-only
  `SessionDB`), tags rows with `profile`, sorts and windows them.
- Lower-level: `hermes_state.SessionDB(db_path, read_only=True).list_sessions_rich(limit=…,
  offset=0, order_by_last_active=True, compact_rows=True)`.

### Provider measurement (live machine, Hermes venv Python 3.14)

| Step | Result |
|---|---|
| `import hermes_cli.web_routers.profiles` (cold process) | 0.36 s |
| `get_profiles_sessions(limit=200, …, profile="all")` | 0.48 s, 200 rows, total 902, no errors |
| `profiles_to_serve(...)` | 24 targets |
| direct `SessionDB(read_only=True).list_sessions_rich(limit=3, …)` | 3 rows, titles present |

Row keys include `cwd`, `git_repo_root`, `git_branch`, `model`, token counts and costs → the
companion must project only the label/identity fields (D-002).

## 5. Plugin host API available to the companion

- `hermes_cli/plugins.py:228` — `PluginContext` exposes `register_tool`, `get_config/set_config`,
  `state`, `plugin_id`; `register(ctx)` receives `ctx.profile_name` (already used by the companion).
  No session-listing facade exists, hence the in-process provider.

## 6. Live reproduction of the 0.2.4 symptom (same day)

- Dashboard stopped → panel: "Hermes dashboard unavailable", default dropdown option only, iframe
  shows Chrome's "127.0.0.1 refused to connect".
- Dashboard started (`hermes dashboard --skip-build --no-open`) → unmodified 0.2.4 extension in a
  real Chromium: "Chrome linked · choose a session", 200 sessions, embedded chat loaded.
- Conclusion: the extension code works; its discovery dependencies do not hold on current Hermes.
