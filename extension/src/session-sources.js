// Pure session-discovery policy for the side panel: which source lists Hermes sessions and what
// to tell the user when none does. No chrome.* / DOM access here so the order is unit-testable.
//
// Order (DECISIONS D-003):
//   1. the configured Web dashboard (embedded chat available),
//   2. the companion session service over the paired broker socket (conversation stays in Hermes),
//   3. a legacy Hermes Desktop headless backend advertised by the companion.

export const SOURCE_MODE = Object.freeze({
  DASHBOARD: "dashboard",
  COMPANION: "companion",
  DESKTOP: "desktop",
});

export const COMPANION_QUERY_LIMIT = 200;

function describe(error) {
  const text = error && error.message ? error.message : String(error || "unavailable");
  return text.slice(0, 160);
}

function normalizeRows(rows) {
  if (!Array.isArray(rows)) return [];
  return rows.filter((row) => row && typeof row === "object" && row.id);
}

// Each loader is an async function returning an array of session rows; it throws (or returns a
// non-array) when its source is unavailable. `headlessBackends` is the ordered list of
// { url } entries advertised in brokerState.agentBackends.
export async function discoverSessions({ loadDashboard, dashboardUrl, loadCompanion,
  loadHeadless, headlessBackends = [] }) {
  const errors = [];
  if (typeof loadDashboard === "function") {
    try {
      const rows = await loadDashboard(dashboardUrl);
      if (Array.isArray(rows)) {
        return { ok: true, mode: SOURCE_MODE.DASHBOARD, url: dashboardUrl, sessions: normalizeRows(rows) };
      }
      errors.push("dashboard: no session list");
    } catch (error) {
      errors.push(`dashboard: ${describe(error)}`);
    }
  }
  if (typeof loadCompanion === "function") {
    try {
      const rows = await loadCompanion(COMPANION_QUERY_LIMIT);
      if (Array.isArray(rows)) {
        return { ok: true, mode: SOURCE_MODE.COMPANION, url: "", sessions: normalizeRows(rows) };
      }
      errors.push("companion: no session list");
    } catch (error) {
      errors.push(`companion: ${describe(error)}`);
    }
  }
  if (typeof loadHeadless === "function") {
    for (const backend of headlessBackends) {
      if (!backend || !backend.url) continue;
      try {
        const rows = await loadHeadless(backend.url);
        if (Array.isArray(rows)) {
          return { ok: true, mode: SOURCE_MODE.DESKTOP, url: backend.url, sessions: normalizeRows(rows) };
        }
        errors.push("desktop backend: no session list");
      } catch (error) {
        errors.push(`desktop backend: ${describe(error)}`);
      }
    }
  }
  return { ok: false, errors };
}

// Status-line wording when no source answered. `brokerState` without an `agentBackends` key means
// the companion predates Desktop support entirely.
export function sessionServiceUnavailableMessage({ paired, brokerState, companionVersion }) {
  const stateKnown = brokerState && typeof brokerState === "object";
  const desktopCapable = stateKnown && Object.prototype.hasOwnProperty.call(brokerState, "agentBackends");
  if (paired && !desktopCapable) {
    return `Companion ${companionVersion} required for Hermes Desktop`;
  }
  if (!paired) return "Hermes sessions unavailable · pair the companion or start the Web dashboard";
  const profiles = Array.isArray(brokerState.agentProfiles) ? brokerState.agentProfiles : [];
  if (!profiles.length) return "Hermes sessions unavailable · start Hermes (companion) or hermes dashboard";
  return "Hermes sessions unavailable · the companion did not answer; retry or start hermes dashboard";
}

export function conversationNotice(mode) {
  switch (mode) {
    case SOURCE_MODE.DASHBOARD:
      return "";
    case SOURCE_MODE.DESKTOP:
      return "Hermes Desktop connected";
    case SOURCE_MODE.COMPANION:
      return "Hermes connected through the companion";
    default:
      return "";
  }
}
