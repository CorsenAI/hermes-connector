import assert from "node:assert/strict";
import test from "node:test";

import {
  attachTab,
  bindingList,
  detachTab,
  normalizeRegistry,
  removeTabEverywhere,
  removeScope,
  scopeKey,
  setActiveTab,
} from "../extension/src/bindings.js";

test("one session owns multiple tabs and an explicit active tab", () => {
  let registry = attachTab({}, "alpha", "session-1", 10);
  registry = attachTab(registry, "alpha", "session-1", 11);
  assert.deepEqual(registry[scopeKey("alpha", "session-1")].tabIds, [10, 11]);
  assert.equal(registry[scopeKey("alpha", "session-1")].activeTabId, 11);
  registry = setActiveTab(registry, "alpha", "session-1", 10);
  assert.equal(registry[scopeKey("alpha", "session-1")].activeTabId, 10);
});

test("attaching a tab to another session transfers ownership", () => {
  let registry = attachTab({}, "alpha", "session-1", 10);
  registry = attachTab(registry, "beta", "session-2", 10);
  assert.equal(registry[scopeKey("alpha", "session-1")], undefined);
  assert.deepEqual(registry[scopeKey("beta", "session-2")].tabIds, [10]);
});

test("detaching the active tab selects a remaining attached tab", () => {
  let registry = attachTab({}, "alpha", "session-1", 10);
  registry = attachTab(registry, "alpha", "session-1", 11);
  registry = detachTab(registry, "alpha", "session-1", 11);
  const binding = registry[scopeKey("alpha", "session-1")];
  assert.equal(binding.activeTabId, 10);
  assert.deepEqual(binding.tabIds, [10]);
});

test("closing a tab removes it from whichever session owns it", () => {
  let registry = attachTab({}, "alpha", "session-1", 10);
  registry = attachTab(registry, "beta", "session-2", 20);
  registry = removeTabEverywhere(registry, 10);
  assert.equal(registry[scopeKey("alpha", "session-1")], undefined);
  assert.ok(registry[scopeKey("beta", "session-2")]);
});

test("normalization drops empty and malformed bindings", () => {
  const registry = normalizeRegistry({
    bad: { profileId: "alpha", sessionId: "empty", tabIds: [] },
    good: { profileId: "alpha", sessionId: "ok", tabIds: [3, 3, "4"], activeTabId: 99 },
  });
  assert.deepEqual(bindingList(registry), [{
    profileId: "alpha",
    sessionId: "ok",
    tabIds: [3],
    activeTabId: 3,
  }]);
});

test("a session cannot activate an unattached tab", () => {
  const registry = attachTab({}, "alpha", "session-1", 10);
  assert.throws(() => setActiveTab(registry, "alpha", "session-1", 99), /not attached/);
});

test("a broker ownership revocation removes the complete local scope", () => {
  let registry = attachTab({}, "alpha", "session-1", 10);
  registry = attachTab(registry, "alpha", "session-1", 11);
  registry = removeScope(registry, "alpha", "session-1");
  assert.deepEqual(registry, {});
});
