# Architecture v2: multiplexed local broker

This document replaces the single `Bridge` / single `controlledTabId` design.

## Components

### Chrome extension instance

Each Chrome profile has one persistent `browserId`, one WebSocket connection to
the local broker, and a local registry of attached tabs per Hermes scope. The
extension executes browser actions and is authoritative for whether a `tabId`
still exists.

### Local broker

One broker per Hermes installation owns `127.0.0.1:8767`. It accepts two
authenticated client roles:

- `browser`: Chrome extension instances;
- `agent`: Hermes plugin instances from any profile or process.

The broker persists the pairing secret and the preferred `browserId` for each
Hermes scope. Runtime tab membership is synchronised by the owning extension.
It multiplexes requests and responses; it never executes browser actions.

### Hermes companion client

Every Hermes process loads the same plugin but connects as a client instead of
trying to bind the browser port. The plugin obtains its profile from
`PluginContext.profile_name` and receives `session_id` / `task_id` in each tool
handler call. Those identifiers accompany every action request.

Named Hermes profiles have independent plugin directories and activation
lists. The companion installer deploys the same payload into the shared home
and every existing profile while all instances still share one root pairing
secret and broker. Deployment and activation roll back across every discovered
profile if any scope fails. Re-running the installer covers profiles created
later.

### Real Hermes session UI

The side panel lists the real profile/session to select and manages its attached
Chrome tabs. Three sources, in order (0.2.6):

1. **Web dashboard** — when a local `hermes dashboard` answers at the configured
   loopback address, the panel reads its sessions API and embeds
   `/chat?resume=<sessionId>` under the matching Hermes profile (unchanged).
2. **Companion session service** — the panel sends `browser_query`
   (`kind: list_sessions`) over its paired broker socket; the broker relays it as
   `agent_query` to one connected companion (preferring the profile the user is
   looking at), which lists sessions in-process from Hermes' own session store and
   answers `agent_query_result`; the broker returns `browser_query_result`. The
   companion forwards only `id`, `profile`, `title`, `display_name`, `source`,
   `last_active`, `is_active` (at most 200 rows). The conversation stays in Hermes
   Desktop or the Hermes CLI.
3. **Legacy headless Desktop backend** — older Hermes releases started a headless
   API on a dynamic loopback port that the companion announced through
   `brokerState.agentBackends`; the panel still reads it when nothing else answers.

When no source answers, the panel says so and names what to start; it never
renders a connection error page.

## Route

```text
Hermes tool call
  { profileId, sessionId, taskId, action }
        |
        v
local broker -- exact scope binding --> browserId
        |
        v
Chrome extension -- exact scope tab set --> active tabId
        |
        v
action_result follows the same request route back to the calling Hermes process
```

No exact binding means no action. There is no fallback to the globally active,
last-used, or first controllable tab.

```text
Side panel (paired browser)            local broker                 companion (any profile)
  browser_query {id, list_sessions} --> pick one companion ---------> agent_query {brokerId, limit}
  browser_query_result {id, ok, data} <-- only the routed companion <-- agent_query_result {brokerId, ok, data}
```

Queries are bounded: one relay timeout, at most four in flight per browser, an
answer accepted only from the companion that received the question, and a
disconnect on either side fails the pending query instead of leaving it hanging.

## Security boundaries

- The broker binds only to loopback.
- Web pages are rejected by Origin. Browser and agent roles use role-bound HMAC
  challenges so a proof cannot be replayed as another role.
- The pairing secret is generated once, stored outside the repository with
  restrictive filesystem permissions, and never transmitted.
- Agent requests can target only bindings registered by a paired browser.
- Browser results are accepted only from the browser that owns the routed
  request.
- URLs and snapshots retain the existing credential redaction and size limits.
- The manifest includes `chrome.debugger` because Chrome does not permit it as an optional permission, but
  debugger attachment remains an explicit user choice through the Trusted input setting.

## Lifecycle

- The companion ensures the single broker is running, then reconnects with
  bounded backoff. A running client restarts a missing broker through a
  throttled cross-process launch lock instead of reconnecting forever to an
  empty port.
- A service-worker restart preserves `browserId` and validates stored tab IDs.
- Binding validation is silent when the normalized registry is unchanged; only
  real changes write storage, synchronize the broker, and notify the panel.
- A full Chrome restart preserves browser identity and session preference. Any
  tab that cannot be proven to be the same restored tab must be attached again.
- Broker or Hermes restarts do not rotate the pairing code.
- A headless Hermes Desktop process advertises its bound loopback port only
  after the server has started. The broker validates the exact loopback URL,
  ties it to the authenticated agent socket, and removes it on disconnect.
- Version 0.2.4 migrates only the standard protocol-3/4 addresses (8765/8766)
  to protocol 5 on 8767; an explicitly configured custom port is preserved.
  The exact broker version is checked during both handshake phases, so an older
  detached broker cannot silently serve the new extension or companion.
- The 0.2.4 installer and each newly loaded Desktop or CLI companion can stop
  only a process whose command line proves it is an installed broker for the
  same Hermes root and legacy port. The Windows broker then launches from the
  immutable base runtime rather than the replaceable venv shim, keeping future
  Hermes updates unblocked.
- Protocol 5 stores ownership in `broker-state-v5.json`. It validates and
  snapshots protocol-4 preferences once when that file is absent, then never
  reads mutable v4 state again. Unique atomic staging files prevent two
  overlapping broker launches from corrupting the protocol-5 snapshot.

## Cross-browser ownership

An explicit attachment in another Chrome profile transfers the complete Hermes
scope to that browser. The broker sends `binding_revoked` to the old profile,
which removes its local stale binding. A later full-state sync from an old or
reconnecting profile is restoration only and cannot silently steal a scope
back; the user must explicitly attach it again to transfer ownership.
