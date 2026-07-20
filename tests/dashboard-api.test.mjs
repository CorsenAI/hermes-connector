import assert from "node:assert/strict";
import test from "node:test";

import {
  extractDashboardToken,
  listDashboardSessions,
  makeDashboardUrl,
  normalizeLoopbackUrl,
} from "../extension/src/dashboard-api.js";

test("dashboard addresses are restricted to loopback", () => {
  assert.equal(normalizeLoopbackUrl("127.0.0.1:9119/chat?x=1"), "http://127.0.0.1:9119/");
  assert.equal(normalizeLoopbackUrl("http://localhost:8000/anything"), "http://localhost:8000/");
  assert.equal(normalizeLoopbackUrl("https://example.com"), null);
  assert.equal(normalizeLoopbackUrl("file:///tmp/dashboard"), null);
});

test("dashboard session token is parsed without evaluating page script", () => {
  const html = '<script>window.__HERMES_SESSION_TOKEN__="temporary-token-123456";</script>';
  assert.equal(extractDashboardToken(html), "temporary-token-123456");
  assert.equal(extractDashboardToken('<script>alert("no token")</script>'), null);
  assert.equal(extractDashboardToken('window.__HERMES_SESSION_TOKEN__="short"'), null);
});

test("selected Hermes scope becomes the real dashboard resume URL", () => {
  const url = new URL(makeDashboardUrl("http://127.0.0.1:9119", {
    profileId: "work",
    sessionId: "session-42",
  }));
  assert.equal(url.pathname, "/chat");
  assert.equal(url.searchParams.get("profile"), "work");
  assert.equal(url.searchParams.get("resume"), "session-42");
});

test("sessions API uses the ephemeral dashboard token only in memory", async () => {
  const calls = [];
  const fakeFetch = async (input, options = {}) => {
    const url = String(input);
    calls.push({ url, options });
    if (url.endsWith("/chat")) {
      return new Response(
        '<script>window.__HERMES_SESSION_TOKEN__="temporary-token-123456";</script>',
        { status: 200 },
      );
    }
    return Response.json({ sessions: [{ id: "s1", profile: "p1" }] });
  };
  const sessions = await listDashboardSessions("http://localhost:9119", fakeFetch);
  assert.deepEqual(sessions, [{ id: "s1", profile: "p1" }]);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.headers.get("Authorization"), "Bearer temporary-token-123456");
});
