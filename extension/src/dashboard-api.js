// Read-only access to the local Hermes dashboard API.
//
// Hermes injects an ephemeral session token into the HTML it serves to its own
// dashboard. The Connector reads that token from the same loopback origin and
// keeps it in memory only. It is never persisted, logged, or sent to the broker.

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);
const TOKEN_RE = /window\.__HERMES_SESSION_TOKEN__\s*=\s*("(?:[^"\\]|\\.)*")/;
const DEFAULT_REQUEST_TIMEOUT_MS = 3_500;

export function normalizeLoopbackUrl(raw, fallback = "http://127.0.0.1:9119/") {
  let value = String(raw || "").trim();
  if (!value) value = fallback;
  if (!/^https?:\/\//i.test(value)) value = `http://${value}`;
  try {
    const parsed = new URL(value);
    if (!LOOPBACK_HOSTS.has(parsed.hostname) || parsed.protocol !== "http:") return null;
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

async function timedFetch(fetchImpl, input, options, timeoutMs) {
  const controller = new AbortController();
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error("Hermes local API request timed out"));
      controller.abort();
    }, timeoutMs);
  });
  try {
    return await Promise.race([
      Promise.resolve(fetchImpl(input, { ...options, signal: controller.signal })),
      timeout,
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function dashboardToken(baseUrl, fetchImpl, headless = false,
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS) {
  const pageUrl = headless
    ? new URL("/", normalizeLoopbackUrl(baseUrl)).href
    : makeDashboardUrl(baseUrl);
  const page = await timedFetch(fetchImpl, pageUrl, {
    cache: "no-store",
    credentials: "omit",
  }, timeoutMs);
  if (!page.ok) throw new Error(`Hermes dashboard ${page.status}`);
  const token = extractDashboardToken(await page.text());
  if (!token) throw new Error("Hermes dashboard did not provide a local session token");
  return token;
}

export async function listDashboardSessions(baseUrl, fetchImpl = fetch, options = {}) {
  const base = normalizeLoopbackUrl(baseUrl);
  if (!base) throw new Error("Hermes dashboard must use 127.0.0.1 or localhost");
  const requestedTimeout = Number(options.timeoutMs);
  const timeoutMs = Number.isFinite(requestedTimeout) && requestedTimeout > 0
    ? Math.min(requestedTimeout, 30_000)
    : DEFAULT_REQUEST_TIMEOUT_MS;
  const token = await dashboardToken(base, fetchImpl, options.headless === true, timeoutMs);
  const url = new URL("api/profiles/sessions", base);
  url.searchParams.set("limit", "200");
  url.searchParams.set("offset", "0");
  url.searchParams.set("min_messages", "0");
  url.searchParams.set("order", "recent");
  url.searchParams.set("profile", "all");
  const headers = new Headers();
  headers.set("Authorization", ["Bearer", token].join(" "));
  const response = await timedFetch(
    fetchImpl,
    url,
    { cache: "no-store", credentials: "omit", headers },
    timeoutMs,
  );
  if (!response.ok) throw new Error(`Hermes API ${response.status}`);
  const payload = await response.json();
  return Array.isArray(payload.sessions) ? payload.sessions : [];
}
