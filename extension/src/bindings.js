// Pure helpers for the per-Hermes-session tab registry. Keeping mutations in
// this module makes wrong-tab safety testable without Chrome APIs.

export function scopeKey(profileId, sessionId) {
  if (!profileId || !sessionId) throw new Error("profileId and sessionId are required");
  return `${profileId}\u001f${sessionId}`;
}

export function normalizeBinding(raw) {
  if (!raw || typeof raw !== "object") throw new Error("invalid binding");
  const profileId = String(raw.profileId || "");
  const sessionId = String(raw.sessionId || "");
  const key = scopeKey(profileId, sessionId);
  const tabIds = [];
  for (const value of Array.isArray(raw.tabIds) ? raw.tabIds : []) {
    if (Number.isInteger(value) && value >= 0 && !tabIds.includes(value)) tabIds.push(value);
  }
  if (!tabIds.length) return null;
  const activeTabId = tabIds.includes(raw.activeTabId) ? raw.activeTabId : tabIds[0];
  return { key, profileId, sessionId, tabIds, activeTabId };
}

export function normalizeRegistry(raw) {
  const result = {};
  if (!raw || typeof raw !== "object") return result;
  for (const value of Object.values(raw)) {
    try {
      const binding = normalizeBinding(value);
      if (binding) result[binding.key] = binding;
    } catch (_) {}
  }
  return result;
}

export function attachTab(registry, profileId, sessionId, tabId) {
  if (!Number.isInteger(tabId) || tabId < 0) throw new Error("invalid tabId");
  const next = normalizeRegistry(registry);
  // One tab has one owner. This prevents two concurrent Hermes sessions from
  // believing they both control the same signed-in page.
  for (const [key, binding] of Object.entries(next)) {
    if (!binding.tabIds.includes(tabId)) continue;
    binding.tabIds = binding.tabIds.filter((id) => id !== tabId);
    if (!binding.tabIds.length) delete next[key];
    else if (binding.activeTabId === tabId) binding.activeTabId = binding.tabIds[0];
  }
  const key = scopeKey(profileId, sessionId);
  const binding = next[key] || { key, profileId, sessionId, tabIds: [], activeTabId: tabId };
  binding.tabIds.push(tabId);
  binding.activeTabId = tabId;
  next[key] = binding;
  return next;
}

export function detachTab(registry, profileId, sessionId, tabId) {
  const next = normalizeRegistry(registry);
  const key = scopeKey(profileId, sessionId);
  const binding = next[key];
  if (!binding) return next;
  binding.tabIds = binding.tabIds.filter((id) => id !== tabId);
  if (!binding.tabIds.length) delete next[key];
  else if (binding.activeTabId === tabId) binding.activeTabId = binding.tabIds[0];
  return next;
}

export function removeTabEverywhere(registry, tabId) {
  let next = normalizeRegistry(registry);
  for (const binding of Object.values(next)) {
    if (binding.tabIds.includes(tabId)) {
      next = detachTab(next, binding.profileId, binding.sessionId, tabId);
    }
  }
  return next;
}

export function setActiveTab(registry, profileId, sessionId, tabId) {
  const next = normalizeRegistry(registry);
  const key = scopeKey(profileId, sessionId);
  const binding = next[key];
  if (!binding || !binding.tabIds.includes(tabId)) throw new Error("tab is not attached to this session");
  binding.activeTabId = tabId;
  return next;
}

export function removeScope(registry, profileId, sessionId) {
  const next = normalizeRegistry(registry);
  delete next[scopeKey(profileId, sessionId)];
  return next;
}

export function bindingList(registry) {
  return Object.values(normalizeRegistry(registry)).map(({ profileId, sessionId, tabIds, activeTabId }) => ({
    profileId,
    sessionId,
    tabIds: [...tabIds],
    activeTabId,
  }));
}
