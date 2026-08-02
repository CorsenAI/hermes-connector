import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import test from "node:test";

function eventTarget() {
  const listeners = [];
  return {
    listeners,
    addListener(listener) { listeners.push(listener); },
    removeListener(listener) {
      const index = listeners.indexOf(listener);
      if (index >= 0) listeners.splice(index, 1);
    },
  };
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

test("actions stay bound to their authenticated socket and current tab authorization", async () => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
  const pairingCode = "0123456789abcdef".repeat(4);
  const scopeKey = "profile\u001fsession";
  const storage = {
    settings: {
      bridgeUrl: "ws://127.0.0.1:8765/",
      pairingCode,
      trustedInput: false,
      showOverlay: false,
    },
    pairing: { pairedAt: 0 },
    identity: { browserId: "test-browser", browserName: "Test Chrome" },
    bindings: {
      [scopeKey]: {
        key: scopeKey,
        profileId: "profile",
        sessionId: "session",
        tabIds: [7],
        activeTabId: 7,
      },
    },
  };
  const runtimeEvent = eventTarget();
  const simpleEvent = () => eventTarget();
  const activatedEvent = simpleEvent();
  let activeTabId = 7;
  let captureResolve = null;

  class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;
    static instances = [];

    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.CONNECTING;
      this.sent = [];
      FakeWebSocket.instances.push(this);
      queueMicrotask(() => {
        if (this.readyState !== FakeWebSocket.CONNECTING) return;
        this.readyState = FakeWebSocket.OPEN;
        if (this.onopen) this.onopen({});
      });
    }

    send(raw) { this.sent.push(JSON.parse(raw)); }

    emit(message) {
      if (this.onmessage) this.onmessage({ data: JSON.stringify(message) });
    }

    close() {
      if (this.readyState >= FakeWebSocket.CLOSING) return;
      this.readyState = FakeWebSocket.CLOSING;
      queueMicrotask(() => {
        this.readyState = FakeWebSocket.CLOSED;
        if (this.onclose) this.onclose({});
      });
    }
  }

  globalThis.WebSocket = FakeWebSocket;
  globalThis.chrome = {
    action: { onClicked: simpleEvent() },
    alarms: { create() {}, onAlarm: simpleEvent() },
    debugger: {
      async attach() {}, async detach() {}, async sendCommand() {},
      onEvent: simpleEvent(), onDetach: simpleEvent(),
    },
    permissions: { async contains() { return false; } },
    runtime: {
      getManifest() { return { version: "0.2.1" }; },
      onInstalled: simpleEvent(),
      onMessage: runtimeEvent,
      async sendMessage() {},
      async getPlatformInfo() { return { os: "win" }; },
    },
    scripting: { async executeScript() { return [{ result: null }]; } },
    sidePanel: { async open() {} },
    storage: {
      local: {
        async get(keys) {
          const names = Array.isArray(keys) ? keys : [keys];
          const result = {};
          for (const name of names) {
            if (name != null && Object.hasOwn(storage, name)) result[name] = structuredClone(storage[name]);
          }
          return result;
        },
        async set(values) { Object.assign(storage, structuredClone(values)); },
        async remove(key) { delete storage[key]; },
      },
    },
    tabs: {
      async get(tabId) {
        if (tabId !== 7) throw new Error("missing tab");
        return { id: 7, windowId: 1, index: 0, title: "Fixture", url: "https://example.test/", active: activeTabId === 7 };
      },
      async query() {
        return [{ id: activeTabId, windowId: 1, index: activeTabId === 7 ? 0 : 1,
          title: "Fixture", url: "https://example.test/", active: true }];
      },
      async update(tabId, values) { if (values.active) activeTabId = tabId; },
      async remove() {},
      async captureVisibleTab() {
        return new Promise((resolve) => { captureResolve = resolve; });
      },
      onActivated: activatedEvent,
      onRemoved: simpleEvent(), onReplaced: simpleEvent(), onUpdated: simpleEvent(),
    },
    windows: { async update() {} },
  };

  await import(`../extension/src/background.js?session-security=${Date.now()}`);
  assert.equal(runtimeEvent.listeners.length, 1);
  const runtimeListener = runtimeEvent.listeners[0];
  const runtime = (message) => new Promise((resolve) => {
    assert.equal(runtimeListener(message, {}, resolve), true);
  });

  async function authenticate(socket, nonce) {
    await waitFor(() => socket.readyState === FakeWebSocket.OPEN, "socket open");
    socket.emit({ type: "challenge", nonce, protocol: 4 });
    const hello = await waitFor(
      () => socket.sent.find((message) => message.type === "hello"), "browser hello",
    );
    const proof = await hmacHex(
      pairingCode, `broker:browser:${hello.browserId}:${hello.nonce}`,
    );
    socket.emit({ type: "paired", ok: true, proof, protocol: 4, brokerState: {} });
    await waitFor(
      () => socket.sent.find((message) => message.type === "binding_sync"), "binding sync",
    );
  }

  const first = await waitFor(() => FakeWebSocket.instances[0], "initial socket");
  assert.equal(first.url, "ws://127.0.0.1:8766");
  assert.equal(storage.settings.bridgeUrl, "ws://127.0.0.1:8766");
  assert.deepEqual(storage.bridgeMigration021, { completed: true, customBridge: false });
  await authenticate(first, "first-server-nonce");
  first.emit({
    type: "action", id: "old-wait", scope: { profileId: "profile", sessionId: "session" },
    targetTabId: 7, action: { kind: "wait", ms: 120 },
  });
  first.emit({
    type: "action", id: "old-url", scope: { profileId: "profile", sessionId: "session" },
    targetTabId: 7, action: { kind: "current_url" },
  });
  await new Promise((resolve) => setTimeout(resolve, 15));
  await runtime({ cmd: "unpair" });
  await runtime({ cmd: "connect", browserName: "Test Chrome" });

  const second = await waitFor(() => FakeWebSocket.instances[1], "replacement socket");
  await authenticate(second, "second-server-nonce");
  await new Promise((resolve) => setTimeout(resolve, 260));
  assert.equal(
    second.sent.some((message) => message.type === "action_result" &&
      ["old-wait", "old-url"].includes(message.id)),
    false,
    "an old action result must never cross into a replacement authenticated socket",
  );

  second.emit({
    type: "action", id: "aba-screenshot", scope: { profileId: "profile", sessionId: "session" },
    targetTabId: 7, action: { kind: "screenshot" },
  });
  await waitFor(() => captureResolve, "screenshot capture");
  activeTabId = 8;
  for (const listener of activatedEvent.listeners) listener({ tabId: 8, windowId: 1 });
  activeTabId = 7;
  for (const listener of activatedEvent.listeners) listener({ tabId: 7, windowId: 1 });
  captureResolve("data:image/png;base64,wrong-tab");
  const discarded = await waitFor(
    () => second.sent.find((message) => message.type === "action_result" && message.id === "aba-screenshot"),
    "discarded ABA screenshot",
  );
  assert.equal(discarded.ok, false);
  assert.equal(Object.hasOwn(discarded, "data"), false);
  assert.match(discarded.error, /active tab changed/);

  second.emit({
    type: "action", id: "revoked-wait", scope: { profileId: "profile", sessionId: "session" },
    targetTabId: 7, action: { kind: "wait", ms: 100 },
  });
  await new Promise((resolve) => setTimeout(resolve, 10));
  await runtime({ cmd: "detachTab", profileId: "profile", sessionId: "session", tabId: 7 });
  const revoked = await waitFor(
    () => second.sent.find((message) => message.type === "action_result" && message.id === "revoked-wait"),
    "revoked action error",
  );
  assert.equal(revoked.ok, false);
  assert.equal(Object.hasOwn(revoked, "data"), false);
  assert.match(revoked.error, /authorization changed/);

  await runtime({ cmd: "unpair" });
});
