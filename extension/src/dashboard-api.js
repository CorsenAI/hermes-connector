// Read-only access to the local Hermes dashboard API.
//
// Hermes injects an ephemeral session token into the HTML it serves to its own
// dashboard. The Connector reads that token from the same loopback origin and
// keeps it in memory only. It is never persisted, logged, or sent to the broker.

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);
const TOKEN_RE = /window\.__HERMES_SESSION_TOKEN__\s*=\s*("(?:[^"\\]|\\.)*")/;

export function normalizeLoopbackUrl(raw, fallback = "http://127.0.0.1:9119/") {
  let value = String(raw || "").trim();
  if (!value) value = fallback;
  if (!/^https?:\/\//i.test(value)) value = `http://${value}`;
  try {
    const parsed = new URL(value);
    if (!LOOPBACK_HOSTS.has(parsed.hostname) || !/^https?:$/.test(parsed.protocol)) return null;
    parsed.username = "";
    parsed.password = "";
    parsed.pathname = "/";
    parsed.search = "";
    parsed.hash = "";
    return parsed.href;
  } catch (_) {
    return null;
  }
}

export function extractDashboardToken(html) {
  const match = TOKEN_RE.exec(String(html || ""));
  if (!match) return null;
  try {
    const token = JSON.parse(match[1]);
    return typeof token === "string" && token.length >= 16 && token.length <= 2048
      ? token
      : null;
  } catch (_) {
    return null;
  }
}

export function makeDashboardUrl(baseUrl, scope = null) {
  const base = normalizeLoopbackUrl(baseUrl);
  if (!base) throw new Error("Hermes dashboard must use 127.0.0.1 or localhost");
  const url = new URL("chat", base);
  if (scope) {
    url.searchParams.set("resume", String(scope.sessionId || ""));
    url.searchParams.set("profile", String(scope.profileId || ""));
  }
  return url.href;
}

async function dashboardToken(baseUrl, fetchImpl) {
  const page = await fetchImpl(makeDashboardUrl(baseUrl), {
    cache: "no-store",
    credentials: "omit",
  });
  if (!page.ok) throw new Error(`Hermes dashboard ${page.status}`);
  const token = extractDashboardToken(await page.text());
  if (!token) throw new Error("Hermes dashboard did not provide a local session token");
  return token;
}

export async function listDashboardSessions(baseUrl, fetchImpl = fetch) {
  const base = normalizeLoopbackUrl(baseUrl);
  if (!base) throw new Error("Hermes dashboard must use 127.0.0.1 or localhost");
  const token = await dashboardToken(base, fetchImpl);
  const url = new URL("api/profiles/sessions", base);
  url.searchParams.set("limit", "200");
  url.searchParams.set("offset", "0");
  url.searchParams.set("min_messages", "0");
  url.searchParams.set("order", "recent");
  url.searchParams.set("profile", "all");
  const headers = new Headers();
  headers.set("Authorization", ["Bearer", token].join(" "));
  const response = await fetchImpl(url, { cache: "no-store", credentials: "omit", headers });
  if (!response.ok) throw new Error(`Hermes API ${response.status}`);
  const payload = await response.json();
  return Array.isArray(payload.sessions) ? payload.sessions : [];
}
