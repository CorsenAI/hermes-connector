# Architecture v2: multiplexed local broker

This document replaces the single `Bridge` / single `controlledTabId` design.

## Components

### Chrome extension instance

Each Chrome profile has one persistent `browserId`, one WebSocket connection to
the local broker, and a local registry of attached tabs per Hermes scope. The
extension executes browser actions and is authoritative for whether a `tabId`
still exists.

### Local broker

One broker per Hermes installation owns `127.0.0.1:8765`. It accepts two
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

### Real Hermes dashboard

The side panel embeds the local dashboard. A small connector bar uses Hermes'
existing read-only multi-profile sessions API to select the real profile/session
and manage its attached Chrome tabs. Selecting a session opens the dashboard at
`/chat?resume=<sessionId>` under the matching Hermes profile.

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
  bounded backoff.
- A service-worker restart preserves `browserId` and validates stored tab IDs.
- A full Chrome restart preserves browser identity and session preference. Any
  tab that cannot be proven to be the same restored tab must be attached again.
- Broker or Hermes restarts do not rotate the pairing code.

## Cross-browser ownership

An explicit attachment in another Chrome profile transfers the complete Hermes
scope to that browser. The broker sends `binding_revoked` to the old profile,
which removes its local stale binding. A later full-state sync from an old or
reconnecting profile is restoration only and cannot silently steal a scope
back; the user must explicitly attach it again to transfer ownership.
