import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { makeDashboardUrl, normalizeLoopbackUrl } from "../extension/src/dashboard-api.js";

const SOURCE = readFileSync(new URL("../extension/src/sidepanel.js", import.meta.url), "utf8");
const BASE_URL = "http://127.0.0.1:9119/";
const SCOPE = Object.freeze({ profileId: "research", sessionId: "session-a" });

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function element() {
  const attributes = new Map();
  return {
    hidden: false, disabled: false, value: "", textContent: "", style: {}, children: [],
    classList: { contains() { return false; }, toggle() {} },
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.get(name) ?? null; },
    removeAttribute(name) { attributes.delete(name); },
    replaceChildren(...children) { this.children = children; },
    appendChild(child) { this.children.push(child); },
    addEventListener() {}, focus() {},
    querySelectorAll() { return []; },
    getClientRects() { return []; },
    getBoundingClientRect() { return { bottom: 0 }; },
  };
}

// Evaluate the actual panel module in a fresh context. Only imports and the
// automatic startup call are replaced; navigation and polling run unchanged.
// The iframe double records every src assignment, including identical values.
function loadPanel({ getStorage, sessions, source = SOURCE } = {}) {
  const elements = new Map();
  const writes = [];
  const intervals = [];
  const storage = { hermesUrl: BASE_URL };
  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const frame = getElement("hermes");
  Object.defineProperty(frame, "src", {
    get() {
      const value = frame.getAttribute("src");
      return value === null ? "" : new URL(value, BASE_URL).href;
    },
    set(value) {
      writes.push(String(value));
      frame.setAttribute("src", value);
    },
  });
  const context = vm.createContext({
    console, URL, setTimeout, clearTimeout,
    document: {
      getElementById: getElement,
      createElement: element,
      addEventListener() {},
    },
    chrome: {
      storage: { local: {
        async get(key) { return getStorage ? getStorage(key) : { ...storage }; },
        async set(values) { Object.assign(storage, values); },
        async remove(key) { delete storage[key]; },
      } },
      runtime: {
        onMessage: { addListener() {} },
        getManifest() { return { version: "0.2.4" }; },
        async sendMessage() { return { ok: true, tabs: [], bindings: {} }; },
      },
    },
    fetch() { throw new Error("Unexpected network request in panel unit test"); },
    makeDashboardUrl, normalizeLoopbackUrl,
    DEFAULT_BRIDGE_URL: "ws://127.0.0.1:8767/",
    async listDashboardSessions(...args) {
      return sessions ? sessions(...args) : [{ id: SCOPE.sessionId, profile: SCOPE.profileId }];
    },
    setInterval(callback, delay) { intervals.push({ callback, delay }); return intervals.length; },
    requestAnimationFrame(callback) { callback(); },
  });
  const imports = source.match(/^import .*;$/gm) || [];
  assert.equal(imports.length, 2, "review the harness when panel imports change");
  assert.equal((source.match(/^init\(\);$/gm) || []).length, 1);
  const executable = source.replace(/^import .*;$/gm, "").replace(/^init\(\);$/m, "");
  vm.runInContext(executable + `\n;globalThis.panelTest = {
    showDashboard, loadSessions, setSessionSource,
    setScope(scope) {
      selectedScope = copyScope(scope);
      return ++scopeSelectionGeneration;
    },
  };`, context, { filename: "sidepanel.js", timeout: 1000 });
  return { ...context.panelTest, elements, frame, writes, intervals, storage };
}

test("identical dashboard URLs are assigned only once", async () => {
  const panel = loadPanel();
  for (let i = 0; i < 5; i++) assert.equal(await panel.showDashboard(SCOPE), true);
  assert.deepEqual(panel.writes, [makeDashboardUrl(BASE_URL, SCOPE)]);
});

test("the real 15-second poll preserves the loaded dashboard", async () => {
  const panel = loadPanel();
  panel.setScope(SCOPE);
  assert.equal(await panel.loadSessions(), true);
  const poll = panel.intervals.find(({ delay }) => delay === 15_000);
  assert.ok(poll, "the session refresh timer must remain registered");
  for (let i = 0; i < 4; i++) assert.equal(await poll.callback(), true);
  assert.equal(panel.writes.length, 1);
  assert.equal(panel.elements.get("sessionSelect").children.length, 2);
});

test("changing session, profile, or clearing selection still navigates", async () => {
  const panel = loadPanel();
  const scopes = [SCOPE, { ...SCOPE, sessionId: "session-b" },
    { ...SCOPE, profileId: "another-profile" }, null];
  for (const scope of scopes) {
    assert.equal(await panel.showDashboard(scope), true);
    assert.equal(await panel.showDashboard(scope), true);
  }
  assert.deepEqual(panel.writes, scopes.map((scope) => makeDashboardUrl(BASE_URL, scope)));
});

test("a changed configured loopback endpoint navigates exactly once", async () => {
  const panel = loadPanel();
  await panel.showDashboard(SCOPE);
  panel.storage.hermesUrl = "http://localhost:9220/";
  await panel.showDashboard(SCOPE);
  await panel.showDashboard(SCOPE);
  assert.deepEqual(panel.writes, [makeDashboardUrl(BASE_URL, SCOPE),
    makeDashboardUrl(panel.storage.hermesUrl, SCOPE)]);
});

test("equivalent endpoint formatting does not cause another navigation", async () => {
  const panel = loadPanel();
  await panel.showDashboard(SCOPE);
  panel.storage.hermesUrl = "  127.0.0.1:9119  ";
  await panel.showDashboard(SCOPE);
  assert.equal(panel.writes.length, 1);
});

test("scope identifiers remain encoded rather than becoming URL parameters", async () => {
  const panel = loadPanel();
  const scope = { profileId: "profile & other", sessionId: "session?resume=other#fragment" };
  await panel.showDashboard(scope);
  await panel.showDashboard(scope);
  const url = new URL(panel.frame.src);
  assert.equal(url.searchParams.get("profile"), scope.profileId);
  assert.equal(url.searchParams.get("resume"), scope.sessionId);
  assert.equal(url.hash, "");
  assert.equal(panel.writes.length, 1);
});

test("a late dashboard response cannot replace a newer navigation", async () => {
  const pending = deferred();
  let reads = 0;
  const panel = loadPanel({ getStorage: () => ++reads === 1
    ? pending.promise : { hermesUrl: BASE_URL } });
  const oldNavigation = panel.showDashboard(SCOPE);
  const nextScope = { ...SCOPE, sessionId: "session-b" };
  assert.equal(await panel.showDashboard(nextScope), true);
  pending.resolve({ hermesUrl: BASE_URL });
  assert.equal(await oldNavigation, false);
  assert.deepEqual(panel.writes, [makeDashboardUrl(BASE_URL, nextScope)]);
});

test("a superseded selection cannot navigate even without a newer request", async () => {
  const pending = deferred();
  const panel = loadPanel({ getStorage: () => pending.promise });
  const generation = panel.setScope(SCOPE);
  const oldNavigation = panel.showDashboard(SCOPE, generation);
  panel.setScope({ ...SCOPE, sessionId: "session-b" });
  pending.resolve({ hermesUrl: BASE_URL });
  assert.equal(await oldNavigation, false);
  assert.deepEqual(panel.writes, []);
});

test("desktop mode unloads the iframe and returning to dashboard restores it", async () => {
  const panel = loadPanel();
  await panel.showDashboard(SCOPE);
  panel.setSessionSource("desktop", BASE_URL);
  assert.equal(await panel.showDashboard(SCOPE), true);
  assert.equal(panel.frame.hidden, true);
  assert.equal(panel.frame.getAttribute("src"), null);
  assert.equal(panel.elements.get("desktopMode").hidden, false);
  panel.setSessionSource("dashboard", BASE_URL);
  await panel.showDashboard(SCOPE);
  await panel.showDashboard(SCOPE);
  assert.equal(panel.frame.hidden, false);
  assert.equal(panel.elements.get("desktopMode").hidden, true);
  assert.deepEqual(panel.writes, Array(2).fill(makeDashboardUrl(BASE_URL, SCOPE)));
});

test("a late dashboard response cannot resurrect an iframe in desktop mode", async () => {
  const pending = deferred();
  const panel = loadPanel({ getStorage: () => pending.promise });
  const oldNavigation = panel.showDashboard(SCOPE);
  panel.setSessionSource("desktop", BASE_URL);
  await panel.showDashboard(SCOPE);
  pending.resolve({ hermesUrl: BASE_URL });
  assert.equal(await oldNavigation, false);
  assert.equal(panel.frame.hidden, true);
  assert.equal(panel.frame.getAttribute("src"), null);
  assert.deepEqual(panel.writes, []);
});

test("a temporary session API failure does not reload the existing iframe", async () => {
  let fail = false;
  const panel = loadPanel({ sessions: () => {
    if (fail) throw new Error("Fixture temporarily unavailable");
    return [{ id: SCOPE.sessionId, profile: SCOPE.profileId }];
  } });
  panel.setScope(SCOPE);
  assert.equal(await panel.loadSessions(), true);
  fail = true;
  assert.equal(await panel.loadSessions(), false);
  assert.equal(panel.elements.get("hint").hidden, false);
  fail = false;
  assert.equal(await panel.loadSessions(), true);
  assert.equal(panel.elements.get("hint").hidden, true);
  assert.equal(panel.writes.length, 1);
});

test("the iframe double reproduces the original unconditional reload defect", async () => {
  const guard = "if (frame.src !== url) frame.src = url;";
  assert.ok(SOURCE.includes(guard));
  const panel = loadPanel({ source: SOURCE.replace(guard, "frame.src = url;") });
  panel.setScope(SCOPE);
  await panel.loadSessions();
  await panel.loadSessions();
  assert.equal(panel.writes.length, 2, "identical src assignments must not be silently deduplicated by the fixture");
});
