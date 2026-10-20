import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import test from "node:test";

// Background answers the panel's `listSessions` only over the authenticated broker socket and
// turns the companion's `browser_query_result` into the panel-facing reply (0.2.6 session service).

function eventTarget() {
  const listeners = [];
  return { listeners, addListener(l) { listeners.push(l); }, removeListener() {} };
}

async function waitFor(read, label, timeout = 1500) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = read();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`timed out waiting for ${label}`);
}

async function hmacHex(secret, message) {
  const encoder = new TextEncoder();
  const key = await webcrypto.subtle.importKey(
    "raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const signature = await webcrypto.subtle.sign("HMAC", key, encoder.encode(message));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

test("listSessions travels over the paired socket and resolves with the companion answer", async () => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
  const pairingCode = "fedcba9876543210".repeat(4);
  const storage = {
    settings: { bridgeUrl: "ws://127.0.0.1:8767", pairingCode, trustedInput: false, showOverlay: false },
    pairing: { pairedAt: 0 },
    identity: { browserId: "query-browser", browserName: "Query Chrome" },
    bindings: {},
  };
  const runtimeEvent = eventTarget();
  const simpleEvent = () => eventTarget();

  class FakeWebSocket {
    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
    static instances = [];
    constructor(url) {
      this.url = url; this.readyState = FakeWebSocket.CONNECTING; this.sent = [];
      FakeWebSocket.instances.push(this);
      queueMicrotask(() => {
        if (this.readyState !== FakeWebSocket.CONNECTING) return;
        this.readyState = FakeWebSocket.OPEN;
        if (this.onopen) this.onopen({});
      });
    }
    send(raw) { this.sent.push(JSON.parse(raw)); }
    emit(message) { if (this.onmessage) this.onmessage({ data: JSON.stringify(message) }); }
    close() {
      if (this.readyState >= FakeWebSocket.CLOSING) return;
      this.readyState = FakeWebSocket.CLOSING;
      queueMicrotask(() => { this.readyState = FakeWebSocket.CLOSED; if (this.onclose) this.onclose({}); });
    }
  }

  globalThis.WebSocket = FakeWebSocket;
  globalThis.chrome = {
    action: { onClicked: simpleEvent() },
    alarms: { create() {}, onAlarm: simpleEvent() },
    debugger: { async attach() {}, async detach() {}, async sendCommand() {}, onEvent: simpleEvent(), onDetach: simpleEvent() },
    permissions: { async contains() { return true; } },
    runtime: {
      getManifest() { return { version: "0.2.6" }; },
      onInstalled: simpleEvent(), onMessage: runtimeEvent,
      async sendMessage() {}, async getPlatformInfo() { return { os: "linux" }; },
    },
    scripting: { async executeScript() { return [{ result: null }]; } },
    sidePanel: { async open() {} },
    storage: {
      local: {
        async get(keys) {
          const names = Array.isArray(keys) ? keys : [keys];
          const result = {};
          for (const name of names) if (name != null && Object.hasOwn(storage, name)) result[name] = structuredClone(storage[name]);
          return result;
        },
        async set(values) { Object.assign(storage, structuredClone(values)); },
        async remove(key) { delete storage[key]; },
      },
    },
    tabs: {
      async get() { throw new Error("no tabs"); }, async query() { return []; },
      async update() {}, async remove() {}, async captureVisibleTab() { return ""; },
      onActivated: simpleEvent(), onRemoved: simpleEvent(), onReplaced: simpleEvent(), onUpdated: simpleEvent(),
    },
    windows: { async update() {}, onFocusChanged: simpleEvent() },
  };

  await import(`../extension/src/background.js?session-query=${Date.now()}`);
  const runtimeListener = runtimeEvent.listeners[0];
  const runtime = (message) => new Promise((resolve) => {
    assert.equal(runtimeListener(message, {}, resolve), true);
  });

  // Before pairing: no socket traffic, an honest refusal.
  const unpaired = await runtime({ cmd: "listSessions", limit: 50 });
  assert.deepEqual(unpaired, { ok: false, error: "not paired" });

  const socket = await waitFor(() => FakeWebSocket.instances[0], "socket");
  await waitFor(() => socket.readyState === FakeWebSocket.OPEN, "socket open");
  socket.emit({ type: "challenge", nonce: "query-server-nonce", protocol: 5, brokerVersion: "0.2.6" });
  const hello = await waitFor(() => socket.sent.find((m) => m.type === "hello"), "hello");
  const proof = await hmacHex(pairingCode, `broker:browser:${hello.browserId}:${hello.nonce}`);
  socket.emit({ type: "paired", ok: true, proof, protocol: 5, brokerVersion: "0.2.6",
    brokerState: { protocol: 5, browsers: [], agentProfiles: ["work"], agentBackends: [] } });
  await waitFor(() => socket.sent.find((m) => m.type === "binding_sync"), "binding sync");

  // Paired: the query goes out bounded and tagged, and concurrent callers share one in-flight query.
  const first = runtime({ cmd: "listSessions", limit: 5000, profileId: "work" });
  const second = runtime({ cmd: "listSessions", limit: 10 });
  const query = await waitFor(() => socket.sent.find((m) => m.type === "browser_query"), "browser_query");
  assert.equal(query.kind, "list_sessions");
  assert.equal(query.limit, 200, "the limit is clamped to the broker maximum");
  assert.equal(query.profileId, "work");
  assert.match(query.id, /^panel-/);
  assert.equal(socket.sent.filter((m) => m.type === "browser_query").length, 1, "one query in flight");

  // An answer for an unknown id is ignored; the real one resolves both callers.
  socket.emit({ type: "browser_query_result", id: "someone-else", ok: true, data: { sessions: [] } });
  const payload = { sessions: [{ id: "s-1", profile: "work", title: "Plan" }], source: "hermes-api" };
  socket.emit({ type: "browser_query_result", id: query.id, ok: true, data: payload });
  const [firstAnswer, secondAnswer] = await Promise.all([first, second]);
  assert.deepEqual(firstAnswer, { ok: true, data: payload });
  assert.deepEqual(secondAnswer, { ok: true, data: payload });

  // A companion error is surfaced, never thrown.
  const failing = runtime({ cmd: "listSessions" });
  const failingQuery = await waitFor(
    () => socket.sent.filter((m) => m.type === "browser_query")[1], "second browser_query",
  );
  socket.emit({ type: "browser_query_result", id: failingQuery.id, ok: false, error: "no Hermes companion is connected" });
  const failed = await failing;
  assert.equal(failed.ok, false);
  assert.match(failed.error, /no Hermes companion/);

  // Losing the session fails whatever is still pending instead of hanging until the timeout.
  const dangling = runtime({ cmd: "listSessions" });
  await waitFor(() => socket.sent.filter((m) => m.type === "browser_query")[2], "third browser_query");
  await runtime({ cmd: "unpair" });
  const reset = await dangling;
  assert.equal(reset.ok, false);
  assert.match(reset.error, /reset/);
});
