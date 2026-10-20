# PRODUCT_PLAN — Hermes Connector

> Durable product requirements and approved scope. Ideas are listed as *proposed* until the owner
> approves them; only *approved* items are built.

## Product (unchanged since 0.2.x)

Hermes Connector attaches exact Hermes profiles/sessions to user-selected tabs of a signed-in
Chrome profile through one authenticated loopback broker. The extension owns pairing and tab
bindings; Hermes owns chat, profiles, sessions and the agent turn. No remote code, no telemetry,
loopback only.

## Release 0.2.6 — "works with current Hermes without the web dashboard" (approved 2026-10-19)

Built first as 0.2.5 (GitHub prerelease only, never submitted to the Store) and renumbered 0.2.6
on 2026-10-20 after merging the fixes published on `main` since 0.2.4 (decision D-007).

Owner decision (2026-10-19): upgrade the product so the side panel keeps working with current
Hermes releases, then update the public pages and the Chrome Web Store listing.

### Problem

0.2.4 discovers Hermes sessions through (a) the Hermes web dashboard at a fixed loopback port
or (b) a Desktop headless `hermes serve` backend announced by the companion. Hermes 2026-10
routes Desktop through one gateway-hosted API that publishes no session token and never sets
`HERMES_SERVE_HEADLESS`, so (b) is dead; (a) depends on a dashboard process that is not restarted
automatically. Result: "Hermes dashboard unavailable", empty session list, no tab can be attached.

### Requirements

| ID | Requirement | Acceptance |
|---|---|---|
| R1 | The panel lists Hermes sessions whenever at least one Hermes process with the companion is running — dashboard or not. | Chromium acceptance: dashboard down, no headless backend, companion answers → dropdown filled, status "Chrome linked · choose a session". |
| R2 | Session discovery through the companion travels only over the existing paired broker socket (loopback, HMAC-authenticated), no new network listener, no new permission. | Broker tests: unauthenticated browser gets nothing; relay is bounded (size, timeout, one in flight per browser). |
| R3 | Only the fields the panel needs leave Hermes: `id`, `profile`, `title`, `display_name`, `source`, `last_active`, `is_active`. Never `cwd`, paths, costs or tokens. | Plugin unit test on the projection. |
| R4 | When a web dashboard is reachable, 0.2.4 behaviour is kept (embedded chat). Otherwise the conversation continues in Hermes Desktop/CLI and the panel says so. | Chromium acceptance keeps the existing "dashboard" scenarios green. |
| R5 | Clear status wording when nothing answers: say what to start (Hermes Desktop/CLI with the companion, or `hermes dashboard`). | Panel text review in the acceptance run. |
| R6 | Extension and companion stay version-locked (0.2.6 ↔ 0.2.6); an older companion triggers the existing upgrade notice. | Release gate (`tests/run_all.py`) version checks. |
| R7 | Public pages, README, PUBLISHING, store listing and ACCEPTANCE name 0.2.6 and the new companion download. | Release gate contract strings. |

### Out of scope (0.2.6)

- Embedding the Hermes chat without a web dashboard (would need an authenticated UI the gateway
  does not expose to extensions).
- Starting `hermes dashboard` from the companion.
- Any change to tab control, trusted input or permissions.

### Proposed (not approved)

- 0.3: companion-side session actions (new chat) once Hermes exposes a stable local API for them.
