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

test("active-tab reporting rejects restricted pages without changing the scoped target", async () => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
  const pairingCode = "0123456789abcdef".repeat(4);
  const bindingKey = "profile\u001fsession";
  const storage = {
    settings: {
      bridgeUrl: "ws://127.0.0.1:8766",
      pairingCode,
      trustedInput: false,
      showOverlay: false,
    },
    bridgeMigration021: { completed: true, customBridge: false },
    pairing: { pairedAt: 0 },
    identity: { browserId: "test-browser", browserName: "Test Chrome" },
    bindings: {
      [bindingKey]: {
        key: bindingKey,
        profileId: "profile",
        sessionId: "session",
        tabIds: [7],
        activeTabId: 7,
      },
    },
  };
  const tabs = new Map([
    [7, { id: 7, windowId: 1, index: 0, title: "Attached", url: "https://attached.test/",
      status: "complete", active: false }],
    [8, { id: 8, windowId: 1, index: 1, title: "Store", url: "https://chromewebstore.google.com/detail/example",
      status: "complete", active: true }],
  ]);
  let activeTabId = 8;
  let bindingWrites = 0;
  let scriptingCalls = 0;
  const withheldOrigins = new Set();
  const runtimeMessages = [];
  const runtimeEvent = eventTarget();
  const activatedEvent = eventTarget();
  const updatedEvent = eventTarget();
  const windowFocusEvent = eventTarget();
  const simpleEvent = () => eventTarget();

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
    emit(message) { if (this.onmessage) this.onmessage({ data: JSON.stringify(message) }); }
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
    permissions: {
      async contains(query) {
        if (!Array.isArray(query && query.origins)) return false;
        return query.origins.every((origin) => !withheldOrigins.has(origin));
      },
    },
    runtime: {
      getManifest() { return { version: "0.2.4" }; },
      onInstalled: simpleEvent(),
      onMessage: runtimeEvent,
      async sendMessage(message) { runtimeMessages.push(message); },
      async getPlatformInfo() { return { os: "win" }; },
    },
    scripting: {
      async executeScript() { scriptingCalls += 1; return [{ result: null }]; },
    },
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
        async set(values) {
          if (Object.hasOwn(values, "bindings")) bindingWrites += 1;
          Object.assign(storage, structuredClone(values));
        },
        async remove(key) { delete storage[key]; },
      },
    },
    tabs: {
      async get(tabId) {
        const tab = tabs.get(tabId);
        if (!tab) throw new Error("missing tab");
        return structuredClone({ ...tab, active: tabId === activeTabId });
      },
      async query(queryInfo) {
        if (queryInfo && queryInfo.active) {
          const tab = tabs.get(activeTabId);
          return tab ? [structuredClone({ ...tab, active: true })] : [];
        }
        return [...tabs.values()].map((tab) => structuredClone({ ...tab, active: tab.id === activeTabId }));
      },
      async update(tabId, values) { if (values.active) activeTabId = tabId; },
      onActivated: activatedEvent,
      onRemoved: simpleEvent(),
      onReplaced: simpleEvent(),
      onUpdated: updatedEvent,
    },
    windows: { async update() {}, onFocusChanged: windowFocusEvent },
  };

  await import(`../extension/src/background.js?active-tab=${Date.now()}`);
  const socket = await waitFor(() => FakeWebSocket.instances[0], "initial socket");
  await waitFor(() => socket.readyState === FakeWebSocket.OPEN, "socket open");
  socket.emit({ type: "challenge", nonce: "server-nonce", protocol: 5, brokerVersion: "0.2.4" });
  const hello = await waitFor(() => socket.sent.find((message) => message.type === "hello"), "browser hello");
  const proof = await hmacHex(pairingCode, `broker:browser:${hello.browserId}:${hello.nonce}`);
  socket.emit({ type: "paired", ok: true, proof, protocol: 5,
    brokerVersion: "0.2.4", brokerState: {} });
  await waitFor(() => socket.sent.find((message) => message.type === "binding_sync"), "binding sync");

  assert.equal(runtimeEvent.listeners.length, 1);
  const runtimeListener = runtimeEvent.listeners[0];
  const runtime = (message) => new Promise((resolve) => {
    assert.equal(runtimeListener(message, {}, resolve), true);
  });

  withheldOrigins.add("https://attached.test/*");
  socket.emit({
    type: "action",
    id: "site-access-revoked",
    scope: { profileId: "profile", sessionId: "session" },
    targetTabId: 7,
    action: { kind: "snapshot" },
  });
  const deniedControl = await waitFor(
    () => socket.sent.find((message) => message.type === "action_result" &&
      message.id === "site-access-revoked"),
    "withheld site-access action error",
  );
  assert.equal(deniedControl.ok, false);
  assert.match(deniedControl.error, /Details.*Site access.*On all sites/);
  assert.equal(scriptingCalls, 0, "withheld host access must fail before page injection");
  withheldOrigins.delete("https://attached.test/*");

  withheldOrigins.add("https://blocked-destination.test/*");
  socket.emit({
    type: "action",
    id: "site-access-navigation",
    scope: { profileId: "profile", sessionId: "session" },
    targetTabId: 7,
    action: { kind: "navigate", url: "https://blocked-destination.test/private" },
  });
  const deniedNavigation = await waitFor(
    () => socket.sent.find((message) => message.type === "action_result" &&
      message.id === "site-access-navigation"),
    "withheld navigation destination error",
  );
  assert.equal(deniedNavigation.ok, false);
  assert.match(deniedNavigation.error, /Details.*Site access.*On all sites/);
  withheldOrigins.delete("https://blocked-destination.test/*");

  let result = await runtime({ cmd: "listTabs", profileId: "profile", sessionId: "session" });
  assert.equal(result.ok, true);
  assert.equal(result.tabs.length, 1);
  assert.equal(result.tabs[0].tabId, 7);
  assert.equal(result.tabs[0].controllable, true);
  assert.equal(result.activeTab.tabId, 8);
  assert.equal(result.activeTab.controllable, false);
  assert.match(result.activeTab.reason, /Chrome Web Store/);
  assert.equal(result.bindings[bindingKey].activeTabId, 7);
  assert.equal(bindingWrites, 0);

  Object.assign(tabs.get(8), { url: "about:blank", pendingUrl: undefined,
    status: "complete", active: true });
  result = await runtime({ cmd: "listTabs", profileId: "profile", sessionId: "session" });
  assert.equal(result.activeTab.controllable, true,
    "the supported empty new-tab target must remain attachable");

  Object.assign(tabs.get(8), { url: "https://withheld.test/private", pendingUrl: undefined,
    status: "complete", active: true });
  withheldOrigins.add("https://withheld.test/*");
  result = await runtime({ cmd: "listTabs", profileId: "profile", sessionId: "session" });
  assert.equal(result.activeTab.controllable, false);
  assert.match(result.activeTab.reason, /Details.*Site access.*On all sites/);
  const withheldAttach = await runtime({ cmd: "attachActiveTab", profileId: "profile",
    sessionId: "session", expectedTabId: 8 });
  assert.equal(withheldAttach.ok, false);
  assert.match(withheldAttach.error, /Details.*Site access.*On all sites/);
  assert.equal(storage.bindings[bindingKey].activeTabId, 7);
  withheldOrigins.delete("https://withheld.test/*");

  const restricted = [
    [{ url: "", pendingUrl: "", status: "loading" }, /finish loading/],
    [{ url: "", pendingUrl: "https://next.test/", status: "loading" }, /finish loading/],
    [{ url: "about:blank", pendingUrl: "https://next.test/", status: "loading" }, /finish loading/],
    [{ url: "https://old.test/", pendingUrl: "https://next.test/", status: "loading" }, /finish loading/],
    [{ url: "https://old.test/", pendingUrl: "chrome://settings", status: "loading" }, /Chrome internal/],
    [{ url: "edge://settings", status: "complete" }, /Edge internal/],
    [{ url: "about:config", status: "complete" }, /Browser internal/],
    [{ url: "devtools://devtools/bundled/inspector.html", status: "complete" }, /Developer Tools/],
    [{ url: "view-source:https://example.test/", status: "complete" }, /View-source/],
    [{ url: "file:///C:/Users/example/document.html", status: "complete" }, /file access requires/],
    [{ url: "https://chromewebstore.google.com/detail/example", status: "complete" }, /Chrome Web Store/],
    [{ url: "https://chrome.google.com/webstore/detail/example", status: "complete" }, /Chrome Web Store/],
  ];
  for (const [values, reason] of restricted) {
    Object.assign(tabs.get(8), { pendingUrl: undefined, ...values });
    result = await runtime({ cmd: "listTabs", profileId: "profile", sessionId: "session" });
    assert.equal(result.activeTab.controllable, false, values.url || "loading tab");
    assert.match(result.activeTab.reason, reason);
    const attached = await runtime({ cmd: "attachActiveTab", profileId: "profile", sessionId: "session",
      expectedTabId: 8 });
    assert.equal(attached.ok, false);
    assert.match(attached.error, reason);
    assert.equal(storage.bindings[bindingKey].activeTabId, 7);
  }
  assert.equal(bindingWrites, 0, "rejected pages must not change tab authorization");

  const staleConsent = await runtime({ cmd: "attachActiveTab", profileId: "profile",
    sessionId: "session", expectedTabId: 7 });
  assert.equal(staleConsent.ok, false);
  assert.match(staleConsent.error, /active Chrome tab changed/);
  assert.equal(storage.bindings[bindingKey].activeTabId, 7,
    "a focus change after rendering must not authorize a different tab");

  runtimeMessages.length = 0;
  Object.assign(tabs.get(8), { url: "https://active.test/?token=secret-value", pendingUrl: undefined,
    status: "complete", active: true });
  for (const listener of activatedEvent.listeners) listener({ tabId: 8, windowId: 1 });
  const activated = await waitFor(
    () => runtimeMessages.find((message) => message.cmd === "activeTabChanged"),
    "active-tab activation event",
  );
  assert.equal(activated.activeTab.tabId, 8);
  assert.equal(activated.activeTab.controllable, true);
  assert.equal(activated.activeTab.url, "https://active.test/?token=REDACTED");

  runtimeMessages.length = 0;
  for (const listener of windowFocusEvent.listeners) listener(1);
  const focused = await waitFor(
    () => runtimeMessages.find((message) => message.cmd === "activeTabChanged"),
    "active-tab window-focus event",
  );
  assert.equal(focused.activeTab.tabId, 8);

  runtimeMessages.length = 0;
  Object.assign(tabs.get(8), { url: "https://chromewebstore.google.com/detail/changed", status: "loading" });
  for (const listener of updatedEvent.listeners) {
    listener(8, { url: tabs.get(8).url, status: "loading" }, structuredClone(tabs.get(8)));
  }
  const navigated = await waitFor(
    () => runtimeMessages.find((message) => message.cmd === "activeTabChanged"),
    "active-tab URL event",
  );
  assert.equal(navigated.activeTab.controllable, false);
  assert.match(navigated.activeTab.reason, /Chrome Web Store/);

  const eventCount = runtimeMessages.length;
  for (const listener of updatedEvent.listeners) {
    listener(7, { url: "https://inactive.test/" }, { ...tabs.get(7), active: false });
  }
  await waitFor(
    () => runtimeMessages.slice(eventCount)
      .find((message) => message.cmd === "attachedTabChanged" && message.tabId === 7),
    "inactive attached-tab refresh",
  );
  assert.equal(runtimeMessages.slice(eventCount)
    .some((message) => message.cmd === "activeTabChanged"), false,
  "inactive URL changes must not impersonate the active Chrome tab");

  Object.assign(tabs.get(8), { url: "https://valid.test/", status: "complete" });
  const attached = await runtime({ cmd: "attachActiveTab", profileId: "profile", sessionId: "session",
    expectedTabId: 8 });
  assert.equal(attached.ok, true);
  assert.equal(storage.bindings[bindingKey].activeTabId, 8);
  assert.deepEqual(storage.bindings[bindingKey].tabIds, [7, 8]);

  Object.assign(tabs.get(8), { url: "", pendingUrl: "https://next.test/", status: "loading" });
  result = await runtime({ cmd: "listTabs", profileId: "profile", sessionId: "session" });
  assert.equal(result.activeTab.controllable, false);
  assert.match(result.activeTab.reason, /finish loading/);
  assert.equal(result.tabs.length, 2);
  const pendingTarget = result.tabs.find((tab) => tab.tabId === 8);
  assert.ok(pendingTarget, "a retained pending target must remain visible for revocation");
  assert.equal(pendingTarget.controllable, false);
  assert.match(pendingTarget.reason, /finish loading/);
  assert.equal(result.bindings[bindingKey].activeTabId, 8,
    "a safe pending navigation must not silently revoke the exact tab-id authorization");

  runtimeMessages.length = 0;
  Object.assign(tabs.get(7), { url: "https://attached.test/", pendingUrl: "https://slow.test/",
    status: "loading", active: false });
  for (const listener of updatedEvent.listeners) {
    listener(7, { pendingUrl: tabs.get(7).pendingUrl, status: "loading" },
      structuredClone(tabs.get(7)));
  }
  await waitFor(
    () => runtimeMessages.find((message) => message.cmd === "attachedTabChanged" && message.tabId === 7),
    "inactive attached-tab loading event",
  );
  result = await runtime({ cmd: "listTabs", profileId: "profile", sessionId: "session" });
  const inactivePending = result.tabs.find((tab) => tab.tabId === 7);
  assert.ok(inactivePending, "an inactive attached tab must remain visible while loading");
  assert.equal(inactivePending.controllable, false);

  Object.assign(tabs.get(7), { url: "https://chromewebstore.google.com/detail/unsafe",
    pendingUrl: undefined, status: "complete", active: false });
  for (const listener of updatedEvent.listeners) {
    listener(7, { url: tabs.get(7).url, status: "complete" }, structuredClone(tabs.get(7)));
  }
  await waitFor(
    () => !storage.bindings[bindingKey].tabIds.includes(7),
    "inactive restricted target revocation",
  );
  assert.deepEqual(storage.bindings[bindingKey].tabIds, [8],
    "unsafe navigation must revoke an inactive attached tab without the panel being open");

  await runtime({ cmd: "unpair" });
});
