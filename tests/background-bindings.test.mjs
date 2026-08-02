import assert from "node:assert/strict";
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

test("read-only tab rendering does not write or rebroadcast unchanged bindings", async () => {
  const runtimeMessages = [];
  const debuggerAttachments = [];
  const debuggerDetachments = [];
  const runtimeEvent = eventTarget();
  const storage = {
    settings: { bridgeUrl: "ws://127.0.0.1:8765/" },
    bindings: {
      "profile\u001fsession": {
        key: "profile\u001fsession",
        profileId: "profile",
        sessionId: "session",
        tabIds: [7],
        activeTabId: 7,
      },
    },
  };
  let bindingWrites = 0;
  const simpleEvent = () => eventTarget();
  const installedEvent = eventTarget();
  globalThis.chrome = {
    action: { onClicked: simpleEvent() },
    alarms: { create() {}, onAlarm: simpleEvent() },
    debugger: {
      async attach({ tabId }) { debuggerAttachments.push(tabId); },
      async detach({ tabId }) { debuggerDetachments.push(tabId); },
      async sendCommand() {},
      onEvent: simpleEvent(),
      onDetach: simpleEvent(),
    },
    permissions: { async contains() { return false; } },
    runtime: {
      getManifest() { return { version: "0.2.1" }; },
      onInstalled: installedEvent,
      onMessage: runtimeEvent,
      async sendMessage(message) { runtimeMessages.push(message); },
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
        async set(values) {
          if (Object.hasOwn(values, "bindings")) bindingWrites += 1;
          Object.assign(storage, structuredClone(values));
        },
        async remove(key) { delete storage[key]; },
      },
    },
    tabs: {
      async get(tabId) {
        if (tabId !== 7) throw new Error("missing tab");
        return { id: 7, windowId: 1, index: 0, title: "Fixture", url: "https://example.test/", active: true };
      },
      async query() { return []; },
      onActivated: simpleEvent(),
      onRemoved: simpleEvent(),
      onReplaced: simpleEvent(),
      onUpdated: simpleEvent(),
    },
    windows: { async update() {} },
  };

  const cdp = await import("../extension/src/cdp.js");
  await import(`../extension/src/background.js?regression=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(installedEvent.listeners.length, 1);
  const onInstalled = installedEvent.listeners[0];
  onInstalled({ reason: "install" });
  onInstalled({ reason: "update", previousVersion: "0.2.1" });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(storage.upgradeNotice, undefined);
  onInstalled({ reason: "update", previousVersion: "0.2.0" });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(storage.upgradeNotice.id, "companion-reinstall-0.2.1");
  assert.equal(storage.upgradeNotice.customBridge, false);
  assert.equal(storage.settings.bridgeUrl, "ws://127.0.0.1:8766");
  assert.deepEqual(storage.bridgeMigration021, { completed: true, customBridge: false });
  assert.equal(runtimeMessages.filter((item) => item.cmd === "upgradeNoticeChanged").length, 1);

  delete storage.bridgeMigration021;
  storage.settings.bridgeUrl = "ws://localhost:8765/";
  onInstalled({ reason: "install" });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(storage.settings.bridgeUrl, "ws://127.0.0.1:8766");
  assert.deepEqual(storage.bridgeMigration021, { completed: true, customBridge: false });

  delete storage.bridgeMigration021;
  storage.settings.bridgeUrl = "ws://127.0.0.1:8766";
  onInstalled({ reason: "install" });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.deepEqual(storage.bridgeMigration021, { completed: true, customBridge: true });

  delete storage.bridgeMigration021;
  storage.settings.bridgeUrl = "ws://127.0.0.1:9900";
  onInstalled({ reason: "install" });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(storage.settings.bridgeUrl, "ws://127.0.0.1:9900");
  assert.deepEqual(storage.bridgeMigration021, { completed: true, customBridge: true });

  await chrome.storage.local.remove("upgradeNotice");
  onInstalled({ reason: "update", previousVersion: "0.1.9" });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(storage.upgradeNotice.previousVersion, "0.1.9");
  assert.equal(storage.upgradeNotice.customBridge, true);

  assert.equal(runtimeEvent.listeners.length, 1);
  const listener = runtimeEvent.listeners[0];
  const send = (message) => new Promise((resolve) => {
    assert.equal(listener(message, {}, resolve), true);
  });

  let noticeResult = await send({ cmd: "dismissUpgradeNotice", id: "future-notice" });
  assert.equal(noticeResult.upgradeNotice.id, "companion-reinstall-0.2.1");
  noticeResult = await send({ cmd: "dismissUpgradeNotice", id: "companion-reinstall-0.2.1" });
  assert.equal(noticeResult.upgradeNotice, null);
  assert.equal(storage.upgradeNotice, undefined);

  bindingWrites = 0;
  runtimeMessages.length = 0;
  for (let index = 0; index < 3; index += 1) {
    const result = await send({ cmd: "listTabs", profileId: "profile", sessionId: "session" });
    assert.equal(result.ok, true);
  }
  assert.equal(bindingWrites, 0);
  assert.equal(runtimeMessages.filter((item) => item.cmd === "bindingsChanged").length, 0);

  await cdp.ensureAttached(7);
  assert.deepEqual(debuggerAttachments, [7]);
  await send({ cmd: "detachTab", profileId: "profile", sessionId: "session", tabId: 7 });
  assert.equal(bindingWrites, 1);
  assert.deepEqual(debuggerDetachments, [7]);
  assert.equal(runtimeMessages.filter((item) => item.cmd === "bindingsChanged").length, 1);

  await send({ cmd: "detachTab", profileId: "profile", sessionId: "session", tabId: 7 });
  assert.equal(bindingWrites, 1);
  assert.deepEqual(debuggerDetachments, [7]);
  assert.equal(runtimeMessages.filter((item) => item.cmd === "bindingsChanged").length, 1);
});
