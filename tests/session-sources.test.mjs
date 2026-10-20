import assert from "node:assert/strict";
import test from "node:test";

import {
  COMPANION_QUERY_LIMIT, SOURCE_MODE, conversationNotice, discoverSessions,
  sessionServiceUnavailableMessage,
} from "../extension/src/session-sources.js";

const rows = [{ id: "s-1", profile: "work", title: "Hello" }, { id: "", profile: "x" }, null];

test("the configured dashboard wins when it answers", async () => {
  const calls = [];
  const result = await discoverSessions({
    dashboardUrl: "http://127.0.0.1:9119/",
    loadDashboard: async (url) => { calls.push(["dashboard", url]); return rows; },
    loadCompanion: async () => { calls.push(["companion"]); return rows; },
    loadHeadless: async () => { calls.push(["headless"]); return rows; },
    headlessBackends: [{ url: "http://127.0.0.1:5000/" }],
  });
  assert.equal(result.ok, true);
  assert.equal(result.mode, SOURCE_MODE.DASHBOARD);
  assert.equal(result.url, "http://127.0.0.1:9119/");
  assert.deepEqual(result.sessions, [rows[0]], "rows without an id are dropped");
  assert.deepEqual(calls, [["dashboard", "http://127.0.0.1:9119/"]]);
});

test("the companion replaces an unavailable dashboard before any headless backend", async () => {
  const calls = [];
  const result = await discoverSessions({
    dashboardUrl: "http://127.0.0.1:9119/",
    loadDashboard: async () => { throw new Error("connection refused"); },
    loadCompanion: async (limit) => { calls.push(["companion", limit]); return rows; },
    loadHeadless: async () => { calls.push(["headless"]); return rows; },
    headlessBackends: [{ url: "http://127.0.0.1:5000/" }],
  });
  assert.equal(result.ok, true);
  assert.equal(result.mode, SOURCE_MODE.COMPANION);
  assert.equal(result.url, "");
  assert.deepEqual(calls, [["companion", COMPANION_QUERY_LIMIT]]);
});

test("a legacy headless backend is still used when both newer sources fail", async () => {
  const result = await discoverSessions({
    dashboardUrl: "http://127.0.0.1:9119/",
    loadDashboard: async () => { throw new Error("down"); },
    loadCompanion: async () => { throw new Error("not paired"); },
    loadHeadless: async (url) => (url.endsWith(":5001/") ? rows : Promise.reject(new Error("old"))),
    headlessBackends: [{ url: "http://127.0.0.1:5000/" }, { url: "http://127.0.0.1:5001/" }],
  });
  assert.equal(result.ok, true);
  assert.equal(result.mode, SOURCE_MODE.DESKTOP);
  assert.equal(result.url, "http://127.0.0.1:5001/");
});

test("nothing answering yields every failure, never a throw", async () => {
  const result = await discoverSessions({
    dashboardUrl: "http://127.0.0.1:9119/",
    loadDashboard: async () => { throw new Error("refused"); },
    loadCompanion: async () => "not an array",
    loadHeadless: async () => { throw new Error("gone"); },
    headlessBackends: [{ url: "http://127.0.0.1:5000/" }],
  });
  assert.equal(result.ok, false);
  assert.deepEqual(result.errors, [
    "dashboard: refused", "companion: no session list", "desktop backend: gone",
  ]);
});

test("status wording names what to start", () => {
  const capable = { agentBackends: [], agentProfiles: [] };
  assert.match(sessionServiceUnavailableMessage({ paired: true, brokerState: {}, companionVersion: "0.2.6" }),
    /Companion 0\.2\.5 required/);
  assert.match(sessionServiceUnavailableMessage({ paired: false, brokerState: capable, companionVersion: "0.2.6" }),
    /pair the companion/);
  assert.match(sessionServiceUnavailableMessage({ paired: true, brokerState: capable, companionVersion: "0.2.6" }),
    /start Hermes/);
  assert.match(sessionServiceUnavailableMessage({ paired: true, companionVersion: "0.2.6",
    brokerState: { ...capable, agentProfiles: ["work"] } }), /did not answer/);
  assert.equal(conversationNotice(SOURCE_MODE.DASHBOARD), "");
  assert.match(conversationNotice(SOURCE_MODE.COMPANION), /companion/);
  assert.match(conversationNotice(SOURCE_MODE.DESKTOP), /Desktop/);
});
