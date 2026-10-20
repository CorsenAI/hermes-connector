import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHmac, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";

// Each scenario uses a fresh process: background.js AND its imported modules are
// isolated. Chrome/WebSocket are simulated; the production state machine, HMAC,
// bindings and CDP authorization code are executed without rewriting their source.
const scenarios = [
  ...["valid", "wrong-proof", "missing-proof", "no-challenge", "replay",
      "ok-false", "ok-string", "ok-number", "ok-object", "ok-missing"].map(kind => ({ kind })),
  ...["absent", "null", "valid", "missing", "empty", "false", "zero", "object",
      "revoked-focus", "revoked-attach"].map(ref => ({ kind: "key", ref })),
  ...[[0, 0], [1, 1], [1000, 1000], [14999, 14999], [15000, 15000],
      [50000, 15000], [-1, 0], [null, 0]].map(([value, expected]) => ({ kind: "wait", value, expected })),
  { kind: "wait", expected: 0 },
  ...["1000", false, {}, []].map(value => ({ kind: "wait-invalid", value })),
  { kind: "wait-invalid", overflow: true },
  { kind: "wait-revoked" },
  { kind: "queue-reconnect" },
];

if (!process.env.CONNECTOR_SECURITY_SCENARIO) {
  for (const [index, scenario] of scenarios.entries()) {
    test(`security ${index + 1}: ${JSON.stringify(scenario)}`, () => {
      const result = spawnSync(process.execPath, [fileURLToPath(import.meta.url)], {
        env: { ...process.env, CONNECTOR_SECURITY_SCENARIO: JSON.stringify(scenario) },
        encoding: "utf8", timeout: 15000, maxBuffer: 1024 * 1024,
      });
      assert.equal(result.error, undefined, String(result.error));
      assert.equal(result.signal, null, `child terminated: ${result.signal}`);
      assert.equal(result.status, 0, result.stdout + result.stderr);
      assert.match(result.stdout, /SCENARIO PASSED/);
    });
  }
} else {
  await exercise(JSON.parse(process.env.CONNECTOR_SECURITY_SCENARIO));
  console.log("SCENARIO PASSED");
}

async function until(read, label) {
  const deadline = Date.now() + 2500;
  while (Date.now() < deadline) {
    const value = read();
    if (value) return value;
    await sleep(2);
  }
  throw new Error(`timed out: ${label}`);
}

async function exercise(scenario) {
  const { PROTOCOL_VERSION, EXPECTED_BROKER_VERSION, DEFAULT_BRIDGE_URL } =
    await import("../extension/src/protocol.js");
  const version = JSON.parse(readFileSync(new URL("../extension/manifest.json", import.meta.url))).version;
  const secret = "0123456789abcdef".repeat(4);
  const events = () => {
    const listeners = [];
    return { listeners, addListener(fn) { listeners.push(fn); },
      removeListener(fn) { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); } };
  };
  const messages = events();
  const storage = {
    settings: { bridgeUrl: DEFAULT_BRIDGE_URL, pairingCode: secret,
      trustedInput: scenario.kind === "key", showOverlay: false },
    identity: { browserId: "security-browser", browserName: "Security fixture" },
    bindings: { ["profile\u001fsession"]: { key: "profile\u001fsession", profileId: "profile",
      sessionId: "session", tabIds: [7], activeTabId: 7 } },
  };
  const scripts = [], commands = [], pendingTimers = [];
  let releaseFocus, releaseAttach;
  const originalTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const originalInterval = globalThis.setInterval;
  const intervalHandles = new Set();
  globalThis.setInterval = (...args) => {
    const handle = originalInterval(...args);
    intervalHandles.add(handle);
    return handle;
  };
  if (!globalThis.crypto) globalThis.crypto = webcrypto;
  class FakeWebSocket {
    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
    static instances = [];
    constructor(url) {
      this.url = url; this.readyState = 0; this.sent = [];
      FakeWebSocket.instances.push(this);
      queueMicrotask(() => { if (this.readyState === 0) { this.readyState = 1; this.onopen?.({}); } });
    }
    send(raw) { this.sent.push(JSON.parse(raw)); }
    async emit(value, overflow = false) {
      const raw = JSON.stringify(value).replace(overflow ? '"NONFINITE"' : /$^/, "1e400");
      this.onmessage?.({ data: raw });
      await this._messageChain;
    }
    close() {
      if (this.readyState >= 2) return;
      this.readyState = 2;
      queueMicrotask(() => { this.readyState = 3; this.onclose?.({}); });
    }
  }
  globalThis.WebSocket = FakeWebSocket;
  globalThis.chrome = {
    action: { onClicked: events() },
    alarms: { create() {}, onAlarm: events() },
    runtime: { getManifest: () => ({ version }), onInstalled: events(), onMessage: messages,
      async sendMessage() {}, async getPlatformInfo() { return { os: "linux" }; } },
    permissions: { async contains(query) {
      return Array.isArray(query.origins) || query.permissions?.includes("debugger") === true;
    } },
    debugger: {
      async attach() {
        if (scenario.ref === "revoked-attach") await new Promise(resolve => { releaseAttach = resolve; });
      },
      async detach() {},
      async sendCommand(target, method, params) { commands.push({ target, method, params }); return {}; },
      onEvent: events(), onDetach: events(),
    },
    scripting: { async executeScript(details) {
      scripts.push(details);
      assert.equal(details.world, "ISOLATED");
      assert.equal(details.target.tabId, 7);
      assert.equal(details.func.name, "focusRef", "test must exercise the CDP keyboard path");
      if (scenario.ref === "revoked-focus") await new Promise(resolve => { releaseFocus = resolve; });
      return [{ result: details.args[0] === "ref_1" ? { ok: true } : { ok: false, error: "ref not found" } }];
    } },
    storage: { local: {
      async get(keys) {
        const result = {};
        for (const key of Array.isArray(keys) ? keys : [keys]) {
          if (Object.hasOwn(storage, key)) result[key] = structuredClone(storage[key]);
        }
        return result;
      },
      async set(values) { Object.assign(storage, structuredClone(values)); },
      async remove(key) { delete storage[key]; },
    } },
    tabs: {
      async get(id) { assert.equal(id, 7); return { id: 7, windowId: 1, index: 0,
        title: "Fixture", url: "https://example.test/", active: true }; },
      async query() { return [await this.get(7)]; },
      onActivated: events(), onRemoved: events(), onUpdated: events(), onReplaced: events(),
    },
    windows: { onFocusChanged: events() }, sidePanel: { async open() {} },
  };
  await import("../extension/src/background.js");
  assert.equal(messages.listeners.length, 1);
  const runtime = msg => new Promise((resolve, reject) => {
    const deadline = originalTimeout(() => reject(new Error(`runtime timeout: ${msg.cmd}`)), 2500);
    try {
      assert.equal(messages.listeners[0](msg, {}, reply => {
        originalClearTimeout(deadline); resolve(reply);
      }), true);
    } catch (error) { originalClearTimeout(deadline); reject(error); }
  });
  const unpair = async () => assert.equal((await runtime({ cmd: "unpair" })).ok, true);
  const connect = async () => {
    const count = FakeWebSocket.instances.length;
    assert.equal((await runtime({ cmd: "connect" })).ok, true);
    const socket = await until(() => FakeWebSocket.instances.length > count
      && FakeWebSocket.instances.at(-1), "new socket");
    await until(() => socket.readyState === 1, "socket open");
    return socket;
  };
  const challenge = async socket => {
    await socket.emit({ type: "challenge", nonce: "fixture-server-nonce", protocol: PROTOCOL_VERSION,
      brokerVersion: EXPECTED_BROKER_VERSION });
    const hello = await until(() => socket.sent.find(m => m.type === "hello"), "hello");
    return createHmac("sha256", secret).update(`broker:browser:${hello.browserId}:${hello.nonce}`).digest("hex");
  };
  const pairedMessage = proof => ({ type: "paired", ok: true, proof, protocol: PROTOCOL_VERSION,
    brokerVersion: EXPECTED_BROKER_VERSION, brokerState: { browsers: [], agentProfiles: [] } });
  const accept = async socket => {
    const proof = await challenge(socket);
    await socket.emit(pairedMessage(proof));
    assert.equal((await runtime({ cmd: "getState" })).paired, true);
    assert.ok(socket.sent.some(m => m.type === "binding_sync"));
    return proof;
  };
  const action = (socket, id, payload, overflow = false) => socket.emit({ type: "action", id,
    scope: { profileId: "profile", sessionId: "session" }, targetTabId: 7, action: payload }, overflow);
  const result = (socket, id) => until(() => socket.sent.find(m => m.type === "action_result" && m.id === id), id);
  const captureTimers = () => {
    globalThis.setTimeout = (fn, ms, ...args) => {
      const timer = { ms, fire: () => fn(...args) };
      pendingTimers.push(timer); return timer;
    };
  };
  const detach = async () => assert.equal((await runtime({ cmd: "detachTab", profileId: "profile",
    sessionId: "session", tabId: 7 })).ok, true);
  try {
    let socket = await connect();
    if (!scenario.kind.startsWith("wait") && !["key", "queue-reconnect"].includes(scenario.kind)) {
      let proof;
      if (scenario.kind === "replay") {
        proof = await accept(socket);
        await unpair();
        const previous = socket;
        socket = await connect();
        assert.notEqual(socket, previous);
        assert.notEqual(await challenge(socket), proof, "new connection must use a new nonce");
      } else if (scenario.kind === "no-challenge") {
        proof = createHmac("sha256", secret).update("broker:browser::").digest("hex");
      } else {
        proof = await challenge(socket);
      }
      const frame = pairedMessage(proof);
      if (scenario.kind === "wrong-proof") frame.proof = "0".repeat(64);
      if (scenario.kind === "missing-proof") delete frame.proof;
      if (scenario.kind === "ok-false") frame.ok = false;
      if (scenario.kind === "ok-string") frame.ok = "true";
      if (scenario.kind === "ok-number") frame.ok = 1;
      if (scenario.kind === "ok-object") frame.ok = {};
      if (scenario.kind === "ok-missing") delete frame.ok;
      await socket.emit(frame);
      const allowed = scenario.kind === "valid";
      assert.equal((await runtime({ cmd: "getState" })).paired, allowed);
      assert.equal(socket.sent.some(m => m.type === "binding_sync"), allowed);
      if (!allowed) {
        await until(() => socket.readyState === 3, "rejected socket closed");
        assert.equal(socket._paired, false);
        assert.equal(commands.length, 0);
      }
      return;
    }
    await accept(socket);
    if (scenario.kind === "key") {
      const ref = { null: null, valid: "ref_1", missing: "ref_missing", empty: "", false: false,
        zero: 0, object: {}, "revoked-focus": "ref_1" }[scenario.ref];
      const payload = { kind: "key", key: "Enter" };
      if (scenario.ref !== "absent" && scenario.ref !== "revoked-attach") payload.ref = ref;
      await action(socket, "key", payload);
      if (scenario.ref === "revoked-focus") {
        await until(() => releaseFocus, "focus started"); await detach(); releaseFocus();
      }
      if (scenario.ref === "revoked-attach") {
        await until(() => releaseAttach, "debugger attachment started"); await detach(); releaseAttach();
      }
      const reply = await result(socket, "key");
      const allowed = ["absent", "null", "valid"].includes(scenario.ref);
      assert.equal(reply.ok, allowed, JSON.stringify(reply));
      assert.equal(commands.filter(c => c.method === "Input.dispatchKeyEvent").length, allowed ? 2 : 0);
      assert.equal(scripts.length, ["valid", "missing", "revoked-focus"].includes(scenario.ref) ? 1 : 0);
      if (scenario.ref.startsWith("revoked")) assert.match(reply.error, /authorization changed/);
      return;
    }
    captureTimers();
    if (["wait", "wait-invalid"].includes(scenario.kind)) {
      const payload = { kind: "wait" };
      if (Object.hasOwn(scenario, "value")) payload.ms = scenario.value;
      if (scenario.overflow) payload.ms = "NONFINITE";
      await action(socket, "wait", payload, !!scenario.overflow);
      if (scenario.kind === "wait") {
        await until(() => pendingTimers.length, "wait timer");
        assert.equal(pendingTimers[0].ms, scenario.expected);
        assert.equal(socket.sent.some(m => m.type === "action_result"), false);
        pendingTimers.shift().fire();
        assert.equal((await result(socket, "wait")).ok, true);
      } else {
        const reply = await result(socket, "wait");
        assert.equal(reply.ok, false);
        assert.match(reply.error, /finite number/);
        assert.ok(pendingTimers.every(timer => timer.ms === 60), "only the fixed queue settle timer is allowed");
      }
      return;
    }
    await action(socket, "held", { kind: "wait", ms: 15000 });
    await until(() => pendingTimers.length, "held wait");
    assert.equal(pendingTimers[0].ms, 15000);
    if (scenario.kind === "wait-revoked") {
      await detach(); pendingTimers.shift().fire();
      const reply = await result(socket, "held");
      assert.equal(reply.ok, false); assert.match(reply.error, /authorization changed/);
      return;
    }
    for (let i = 0; i < 32; i++) await action(socket, `queued-${i}`, { kind: "current_url" });
    const full = await result(socket, "queued-31");
    assert.equal(full.ok, false); assert.match(full.error, /queue full/);
    assert.equal(pendingTimers.length, 1, "queued actions must not allocate extra wait timers");
    await unpair();
    const old = socket;
    socket = await connect();
    await accept(socket);
    // Drain the single wait and all 60 ms settle callbacks without real delays.
    for (let i = 0; i < 100; i++) {
      if (pendingTimers.length) pendingTimers.shift().fire();
      await sleep(1);
    }
    assert.equal(pendingTimers.length, 0);
    assert.equal(socket.sent.some(m => m.type === "action_result"), false,
      "old actions must not report into the replacement socket");
    assert.equal(old.sent.some(m => m.type === "action_result" && m.ok === true), false);
    await action(socket, "fresh", { kind: "current_url" });
    assert.equal((await result(socket, "fresh")).ok, true, "queue must recover after reconnect");
  } finally {
    globalThis.setTimeout = originalTimeout;
    await unpair();
    for (const handle of intervalHandles) clearInterval(handle);
    globalThis.setInterval = originalInterval;
  }
}
