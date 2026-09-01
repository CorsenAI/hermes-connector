// Service worker: owns a direct WebSocket link to the local agent's loopback bridge, the pairing
// state, and the execution of agent-requested actions against the controlled tab. No native host.

import { DEFAULT_BRIDGE_URL, PROTOCOL_VERSION, OUT, IN, ACTION, STORE, DEFAULT_SETTINGS } from "./protocol.js";
import { buildSnapshot, clickRef, typeRef, scrollPage, readText, setOverlay,
  hoverRef, pressKey, selectOption, dragRefs, findText, refRect, focusRef } from "./page-actions.js";
import { attachTab, bindingList, detachTab, normalizeRegistry, removeTabEverywhere,
  removeScope, sameRegistry, scopeKey, setActiveTab } from "./bindings.js";
import * as cdp from "./cdp.js";

let ws = null;
let paired = false;
let pairedIntent = false;   // the user wants to stay paired; drives auto-reconnect + keepalive
let brokerState = { protocol: PROTOCOL_VERSION, browsers: [], agentProfiles: [] };
let companionDetected = false;
let reconnectTimer = null;
let pingTimer = null;       // 20s WebSocket keepalive while the socket is open (Chrome docs)
let actionQueue = Promise.resolve();  // serialize agent actions so they never race each other
let queueDepth = 0;         // bound the pending queue so a runaway/hostile agent can't OOM the worker
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const COMPANION_REINSTALL_NOTICE = Object.freeze({
  id: `companion-reinstall-${EXTENSION_VERSION}`,
  extensionVersion: EXTENSION_VERSION,
});
const LEGACY_DEFAULT_BRIDGE_URLS = new Set([
  "ws://127.0.0.1:8765",
  "ws://localhost:8765",
]);
let sessionGen = 0;         // bumped on disconnect/unpair -> already-queued actions are cancelled
const MAX_QUEUED = 32;
const MAX_UNPAIRED_PENDING_FRAMES = 8;
const MAX_UNPAIRED_PENDING_CHARS = 2_500_000;
const MAX_PAIRED_PENDING_FRAMES = 32;
const MAX_PAIRED_PENDING_CHARS = 8_000_000;
let desiredName = "Chrome"; // browser name to announce once the agent challenges us
let bindingTransaction = Promise.resolve(); // prevent concurrent read/modify/write updates from losing tabs
let authorizationGen = 0;   // binding/trusted-input revocations cancel in-flight action authority
const activationGeneration = new Map(); // windowId -> every active-tab change, including A→B→A
let activeTabEventGeneration = 0; // suppress stale async UI events after rapid activation/navigation
const attachedTabEventGeneration = new Map(); // tabId -> newest navigation/status event

chrome.tabs.onActivated.addListener(({ tabId, windowId }) => {
  if (Number.isInteger(windowId)) {
    activationGeneration.set(windowId, (activationGeneration.get(windowId) || 0) + 1);
  }
  scheduleActiveTabBroadcast(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!(Object.hasOwn(changeInfo || {}, "url") || Object.hasOwn(changeInfo || {}, "pendingUrl") ||
      Object.hasOwn(changeInfo || {}, "status"))) return;
  scheduleAttachedTabRefresh(tabId);
  if (tab && tab.active) scheduleActiveTabBroadcast(tabId, tab);
});

// Focusing another Chrome window changes the user-visible active tab without firing tabs.onActivated.
chrome.windows.onFocusChanged.addListener(() => scheduleActiveTabBroadcast(null));

// ---- mutual auth (challenge-response over the shared pairing code) -----------

async function getPairingCode() {
  const s = await chrome.storage.local.get(STORE.SETTINGS);
  return (s[STORE.SETTINGS] && s[STORE.SETTINGS].pairingCode) || "";
}

async function getIdentity() {
  const stored = (await chrome.storage.local.get(STORE.IDENTITY))[STORE.IDENTITY] || {};
  const browserId = stored.browserId || crypto.randomUUID();
  const browserName = stored.browserName || `Chrome ${browserId.slice(0, 6)}`;
  if (browserId !== stored.browserId || browserName !== stored.browserName) {
    await chrome.storage.local.set({ [STORE.IDENTITY]: { browserId, browserName } });
  }
  return { browserId, browserName };
}

async function loadBindings() {
  const stored = (await chrome.storage.local.get(STORE.BINDINGS))[STORE.BINDINGS];
  return normalizeRegistry(stored);
}

function sameBinding(left, right) {
  return !!left && !!right && left.profileId === right.profileId && left.sessionId === right.sessionId &&
    left.activeTabId === right.activeTabId && left.tabIds.length === right.tabIds.length &&
    left.tabIds.every((tabId, index) => tabId === right.tabIds[index]);
}

async function storeBindings(registry, sync = true, previous = null, shouldCommit = null) {
  const normalized = normalizeRegistry(registry);
  const before = previous === null ? null : normalizeRegistry(previous);
  // A debugger attachment is allowed only while its tab remains the explicit
  // active target of a stored Hermes scope. Detach immediately on removal,
  // transfer, revocation, or active-target change.
  await cdp.retainOnly(new Set(
    Object.values(normalized).map((binding) => binding.activeTabId)
  ));
  if (shouldCommit && !shouldCommit()) return before || normalized;
  // Validation and tab rendering are allowed to be read-only. Without this
  // guard, listTabs -> validateBindings wrote the same value and broadcast a
  // bindingsChanged event, whose side-panel listener immediately called
  // listTabs again. Besides spinning the UI, that loop could grow Chrome's
  // LevelDB log by hundreds of megabytes.
  if (before !== null && sameRegistry(before, normalized)) return normalized;
  if (shouldCommit && !shouldCommit()) return before || normalized;
  await chrome.storage.local.set({ [STORE.BINDINGS]: normalized });
  if (sync && paired) {
    if (before === null) {
      sendHost({ type: OUT.BINDING_SYNC, bindings: bindingList(normalized) });
    } else {
      for (const binding of Object.values(before)) {
        if (!normalized[binding.key]) sendHost({ type: OUT.BINDING_REMOVE,
          profileId: binding.profileId, sessionId: binding.sessionId });
      }
      for (const binding of Object.values(normalized)) {
        if (!sameBinding(before[binding.key], binding)) sendHost({ type: OUT.BINDING_UPDATE,
          profileId: binding.profileId, sessionId: binding.sessionId,
          tabIds: binding.tabIds, activeTabId: binding.activeTabId });
      }
    }
  }
  broadcast({ cmd: "bindingsChanged", bindings: normalized });
  return normalized;
}

function mutateBindings(mutator, sync = true, shouldCommit = null, onAuthorizationChange = null) {
  const operation = bindingTransaction.then(async () => {
    const current = await loadBindings();
    if (shouldCommit && !shouldCommit()) return current;
    const next = await mutator(current);
    if (shouldCommit && !shouldCommit()) return current;
    if (!sameRegistry(current, next)) {
      authorizationGen++;
      if (onAuthorizationChange) onAuthorizationChange(authorizationGen);
    }
    return storeBindings(next, sync, current, shouldCommit);
  });
  // Keep the transaction tail fulfilled so one rejected Chrome API call does not freeze later updates.
  bindingTransaction = operation.catch(() => {});
  return operation;
}

async function validateBindings(sync = true) {
  return mutateBindings(async (registry) => {
    let next = registry;
    for (const binding of Object.values(registry)) {
      for (const tabId of binding.tabIds) {
        try {
          const tab = await chrome.tabs.get(tabId);
          if (!isRetainableTab(tab)) next = removeTabEverywhere(next, tabId);
        } catch (_) {
          next = removeTabEverywhere(next, tabId);
        }
      }
    }
    return next;
  }, sync);
}

async function attachScopeTab(scope, tabId) {
  return mutateBindings((current) => attachTab(current, scope.profileId, scope.sessionId, tabId));
}

async function detachScopeTab(scope, tabId) {
  return mutateBindings((current) => detachTab(current, scope.profileId, scope.sessionId, tabId));
}

async function activateScopeTab(scope, tabId) {
  return mutateBindings((current) => setActiveTab(current, scope.profileId, scope.sessionId, tabId));
}
async function hmacHex(keyStr, msgStr) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(keyStr || ""),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(String(msgStr)));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function randHex(n) {
  const a = new Uint8Array(n); crypto.getRandomValues(a);
  return [...a].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Redact secret-bearing URL parts before a tab URL is sent to the agent — current_url, list_tabs
// and navigation results all pass through here. MUST stay in lockstep with the page-actions.js `SU`
// (snapshot/read_text): keyword denylist for named secrets (incl. AWS sig, SAML, OAuth state/code,
// tickets) + a high-entropy VALUE backstop for oddly-named ones. Overmatching a harmless param is
// fine; leaking one credential is not. Readable params (q, page, user, ids) are preserved.
function sanitizeUrl(u) {
  try {
    const url = new URL(String(u));
    const KEY = /(^|[_-])(token|access[_-]?token|refresh[_-]?token|id[_-]?token|auth|authorization|code|auth[_-]?code|session|session[_-]?id|sid|key|api[_-]?key|secret|client[_-]?secret|password|pwd|passwd|signature|sig|jwt|bearer|otp|pin|csrf|xsrf|state|nonce|ticket|credential|assertion|saml[_-]?response|saml[_-]?request|x[_-]?amz[_-]?signature|x[_-]?amz[_-]?credential|x[_-]?amz[_-]?security[_-]?token)($|[_-])/i;
    const looksSecret = (v) =>
      !!v && (
        /^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}$/.test(v) ||        // JWT
        /^[0-9a-f]{32,}$/i.test(v) ||                                                   // long hex
        (/^[A-Za-z0-9_\-+/]{40,}={0,2}$/.test(v) && /[0-9]/.test(v) && /[A-Za-z]/.test(v)));  // long base64-ish
    const scrub = (params) => {
      let any = false;
      for (const k of [...params.keys()]) {
        if (KEY.test(k) || looksSecret(params.get(k))) { params.set(k, "REDACTED"); any = true; }
      }
      return any;
    };
    url.username = ""; url.password = "";
    scrub(url.searchParams);
    if (url.hash && url.hash.includes("=")) {
      const h = new URLSearchParams(url.hash.replace(/^#/, ""));
      if (scrub(h)) url.hash = h.toString();
    }
    return url.href;
  } catch (_) { return String(u || "").slice(0, 500); }
}

// ---- direct WebSocket link to the local agent bridge ------------------------

function isLegacyDefaultBridgeUrl(value) {
  return LEGACY_DEFAULT_BRIDGE_URLS.has(String(value || "").trim().replace(/\/$/, "").toLowerCase());
}

async function ensureBridgeMigration() {
  const saved = await chrome.storage.local.get([STORE.SETTINGS, STORE.BRIDGE_MIGRATION]);
  const settings = saved[STORE.SETTINGS] || {};
  const current = String(settings.bridgeUrl || "").trim();
  const completed = saved[STORE.BRIDGE_MIGRATION];
  const migrationComplete = completed === true ||
    (!!completed && typeof completed === "object" && completed.completed === true);
  if (migrationComplete) {
    return { url: current || DEFAULT_BRIDGE_URL, migrated: false,
      customBridge: !!(typeof completed === "object" && completed.customBridge) };
  }
  const migrated = isLegacyDefaultBridgeUrl(current);
  // Record whether the address was user-configured BEFORE changing anything.
  // A legacy user may already have chosen port 8766 manually, so inspecting
  // only the final port during onInstalled would miss the required reboot note.
  const customBridge = !!current && !migrated;
  const updates = { [STORE.BRIDGE_MIGRATION]: { completed: true, customBridge } };
  if (migrated) updates[STORE.SETTINGS] = { ...settings, bridgeUrl: DEFAULT_BRIDGE_URL };
  try {
    await chrome.storage.local.set(updates);
  } catch (_) {
    // Even if local persistence is temporarily unavailable, never make the
    // first protocol-4 connection to the detached 0.2.0 default broker.
  }
  return { url: migrated ? DEFAULT_BRIDGE_URL : (current || DEFAULT_BRIDGE_URL),
    migrated, customBridge };
}

async function bridgeUrl() {
  return (await ensureBridgeMigration()).url;
}

function invalidateSession(sock = null) {
  sessionGen++;
  paired = false;
  brokerState = { protocol: PROTOCOL_VERSION, browsers: [], agentProfiles: [] };
  if (sock) sock._paired = false;
}

function clearSocketKeepalive() {
  clearInterval(pingTimer);
  pingTimer = null;
}

async function connectBridge(probeOnly = false) {
  // Resolve the URL BEFORE the open-socket check: with the await inside the check→assign gap, two
  // concurrent callers (alarm + panel) could both pass the check and leak a live duplicate socket.
  const url = await bridgeUrl();
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return ws;
  if (ws) {
    const stale = ws;
    invalidateSession(stale);
    clearSocketKeepalive();
    try { stale.close(); } catch (_) {}
  }
  let sock;
  try {
    sock = new WebSocket(url);
  } catch (e) {
    broadcast({ cmd: "hostError", error: String(e) });
    return null;
  }
  sock._probeOnly = probeOnly;
  ws = sock;
  // Every handler is scoped to ITS socket: after a settings change or reconnect replaces `ws`, a
  // late event from the old socket must not null out / unpair / reconnect over the live connection.
  sock.onopen = () => {
    if (ws !== sock) { try { sock.close(); } catch (_) {} return; }   // superseded while connecting
    // Chrome docs: exchange a message ~every 20s to keep the service worker (and this socket) alive.
    clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (ws === sock && sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: OUT.EVENT, name: "keepalive" }));
    }, 20000);
  };
  sock.onmessage = (ev) => {
    if (ws !== sock) return;
    // Size gate BEFORE JSON.parse: never parse an unbounded payload — a rogue local server could
    // otherwise OOM the worker with one giant frame, no pairing needed. Legit messages are tiny.
    if (typeof ev.data !== "string" || ev.data.length > 2000000) { try { sock.close(); } catch (_) {} return; }
    let m;
    try { m = JSON.parse(ev.data); } catch (_) {
      // Invalid frames are a protocol violation. Dropping them silently would
      // let a fake local endpoint bypass the bounded async queue and burn CPU.
      try { sock.close(); } catch (_) {}
      return;
    }
    const pendingFrames = (sock._pendingFrames || 0) + 1;
    const pendingChars = (sock._pendingChars || 0) + ev.data.length;
    const authenticated = sock._paired === true;
    const maxFrames = authenticated ? MAX_PAIRED_PENDING_FRAMES : MAX_UNPAIRED_PENDING_FRAMES;
    const maxChars = authenticated ? MAX_PAIRED_PENDING_CHARS : MAX_UNPAIRED_PENDING_CHARS;
    if (pendingFrames > maxFrames || pendingChars > maxChars) {
      // Never let an unauthenticated (or compromised local) endpoint build an
      // unbounded Promise/object backlog while async HMAC/storage work runs.
      try { sock.close(); } catch (_) {}
      return;
    }
    sock._pendingFrames = pendingFrames;
    sock._pendingChars = pendingChars;
    const frameChars = ev.data.length;
    // Preserve WebSocket frame order across async handshake work. Without this queue a
    // broker_state frame immediately following paired can overtake the HMAC/storage awaits and be
    // discarded as unauthenticated, leaving the panel with a stale readiness state.
    // Pass THIS socket so the handler can still bail if it is superseded across an await.
    sock._messageChain = (sock._messageChain || Promise.resolve())
      .then(() => onHostMessage(m, sock))
      .catch((e) => console.error("agent-bridge:", e))
      .finally(() => {
        sock._pendingFrames = Math.max(0, (sock._pendingFrames || 1) - 1);
        sock._pendingChars = Math.max(0, (sock._pendingChars || frameChars) - frameChars);
      });
  };
  sock.onclose = () => {
    if (ws !== sock) return;   // a newer connection owns the state now
    clearSocketKeepalive();
    ws = null;
    invalidateSession(sock);   // cancel any actions still queued from the dead session
    if (!sock._probeOnly) broadcast({ cmd: "disconnected", error: null });
    if (pairedIntent) scheduleReconnect();   // agent restarted / worker slept: self-heal
  };
  sock.onerror = () => {
    if (ws === sock && !sock._probeOnly) {
      broadcast({ cmd: "hostError", error: "cannot reach the local agent" });
    }
  };
  return sock;
}

function sendHost(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify(msg)); return true; }
  return false;
}

// Send only if `sock` is still the live connection — used in the async handshake so a reply never
// lands on a socket that was superseded mid-handshake.
function socketSend(sock, msg) {
  if (sock && sock === ws && sock.readyState === WebSocket.OPEN) { sock.send(JSON.stringify(msg)); return true; }
  return false;
}

function sessionSocketSend(sock, generation, msg) {
  if (generation !== sessionGen || !paired || !sock._paired) return false;
  return socketSend(sock, msg);
}

function actionAuthorized(sock, epoch) {
  return epoch.session === sessionGen && epoch.authorization === authorizationGen &&
    sock === ws && paired && sock._paired === true;
}

function actionSocketSend(sock, epoch, msg) {
  if (!actionAuthorized(sock, epoch)) return false;
  return socketSend(sock, msg);
}

function requireActionAuthorized(sock, epoch) {
  if (!actionAuthorized(sock, epoch)) throw new Error("tab authorization changed during the action");
}

function actionBindingMutation(sock, epoch, mutator) {
  const expected = epoch.authorization;
  return mutateBindings(
    mutator,
    true,
    () => actionAuthorized(sock, epoch),
    (nextGeneration) => {
      if (nextGeneration !== expected + 1) {
        throw new Error("concurrent tab authorization change");
      }
      epoch.authorization = nextGeneration;
    },
  );
}

function sendAuthorizationError(sock, epoch, actionId) {
  return sessionSocketSend(sock, epoch.session, {
    type: OUT.ACTION_RESULT,
    id: actionId,
    ok: false,
    error: "tab authorization changed while the browser action was running",
  });
}

// Reject empty / too-short / low-entropy pairing codes: HMAC over a guessable secret is forgeable,
// so a rogue local server could impersonate the agent. "1111111111111111" is 16 chars but 1 unique.
function weakCode(code) {
  if (!code || code.length < 16) return true;
  return new Set(code).size < 8;
}

async function helloNow(browserName) {
  const identity = await getIdentity();
  desiredName = browserName || identity.browserName;
  await connectBridge();   // the agent sends a challenge on connect; we answer it in onHostMessage()
}

async function reconnect() {
  const cur = (await chrome.storage.local.get(STORE.PAIRING))[STORE.PAIRING] || {};
  await helloNow(cur.browserName);
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => { reconnectTimer = null; if (pairedIntent) reconnect(); }, 1500);
}

// Keep the MV3 worker warm while paired so the WebSocket survives a long agent turn (Chrome 116+).
chrome.alarms.create("keepalive", { periodInMinutes: 0.5 });   // 0.5 = Chrome's minimum honored period
chrome.alarms.onAlarm.addListener((al) => {
  if (al.name !== "keepalive" || !pairedIntent) return;
  if (!ws || ws.readyState > WebSocket.OPEN) reconnect();   // CLOSING/CLOSED -> re-open
  else sendHost({ type: OUT.EVENT, name: "keepalive" });
});

// On worker startup, if a pairing was stored, restore the intent and reconnect.
chrome.storage.local.get(STORE.PAIRING).then((s) => {
  if (s[STORE.PAIRING]) { pairedIntent = true; reconnect(); }
});
validateBindings(false).catch(() => {});

async function onHostMessage(msg, sock) {
  // The handler does awaits (storage, crypto); across each one the connection can be replaced by a
  // reconnect or settings change. `alive()` guards every post-await step so a late message from an
  // old socket can't stomp the new connection's nonce / paired state. The challenge nonce is stored
  // ON the socket (sock._extNonce), not a global, so two connections never cross wires.
  const alive = () => ws === sock;
  const authenticated = () => alive() && paired && sock._paired === true;
  if (!alive()) return;
  switch (msg.type) {
    case IN.CHALLENGE: {
      // One challenge per connection: a rogue server can't flood challenges to burn HMAC/storage work.
      if (sock._challenged) break;
      sock._challenged = true;
      // Validate the nonce shape before spending crypto on it (bounded length, token charset).
      const nonce = String(msg.nonce || "");
      if (nonce.length < 8 || nonce.length > 512 || !/^[A-Za-z0-9_.:-]+$/.test(nonce)) {
        if (alive()) { try { sock.close(); } catch (_) {} }
        break;
      }
      if (msg.protocol !== PROTOCOL_VERSION) {
        pairedIntent = false;
        invalidateSession(sock);
        try { sock.close(); } catch (_) {}
        if (!sock._probeOnly) {
          broadcast({ cmd: "pairDenied", reason: "Connector companion and extension protocol versions differ." });
        }
        break;
      }
      companionDetected = true;
      broadcast({ cmd: "companionDetected", detected: true });
      // The broker challenged us: prove the browser role + stable browser identity, then require a
      // role-bound broker proof back. The shared code never travels in the clear.
      const code = await getPairingCode();
      if (!alive()) return;
      if (weakCode(code)) {
        // Refuse a missing/weak secret and close — never leave a half-open unauthenticated link idling.
        pairedIntent = false;
        invalidateSession(sock);
        sock._probeOnly = true;
        try { sock.close(); } catch (_) {}
        break;
      }
      const identity = await getIdentity();
      if (!alive()) return;
      const myNonce = randHex(16);
      sock._extNonce = myNonce;
      sock._browserId = identity.browserId;
      const proof = await hmacHex(code, `browser:${identity.browserId}:${nonce}`);
      if (!alive()) return;
      socketSend(sock, { type: OUT.HELLO, role: "browser", browserId: identity.browserId,
        browserName: desiredName || identity.browserName, proof, nonce: myNonce,
        extVersion: chrome.runtime.getManifest().version, protocol: PROTOCOL_VERSION });
      break;
    }
    case IN.PAIRED: {
      if (msg.protocol !== PROTOCOL_VERSION) {
        pairedIntent = false;
        invalidateSession(sock);
        try { sock.close(); } catch (_) {}
        broadcast({ cmd: "pairDenied", reason: "Connector companion and extension protocol versions differ." });
        break;
      }
      // Verify the agent proved it knows the SAME code — else this could be a rogue local server.
      const code = await getPairingCode();
      if (!alive()) return;
      const expected = await hmacHex(code,
        `broker:browser:${sock._browserId || ""}:${sock._extNonce || ""}`);
      if (!alive()) return;
      if (!sock._extNonce || !msg.proof || msg.proof !== expected) {
        // Identity proof failed (or PAIRED arrived with no prior challenge): cut the connection and
        // stop auto-retrying. The user fixes the code in ⚙ (saveSettings reconnects); a rogue server
        // just stays disconnected.
        pairedIntent = false;
        invalidateSession(sock);
        try { sock.close(); } catch (_) {}
        broadcast({ cmd: "pairDenied", reason: "agent identity check failed — wrong pairing code?" });
        break;
      }
      paired = !!msg.ok;
      sock._paired = paired;
      if (msg.brokerState && typeof msg.brokerState === "object") brokerState = msg.brokerState;
      if (paired) {
        const cur = (await chrome.storage.local.get(STORE.PAIRING))[STORE.PAIRING] || {};
        if (!alive()) return;
        await chrome.storage.local.set({ [STORE.PAIRING]: { ...cur, pairedAt: Date.now() } });
        await validateBindings(false);
        if (!alive()) return;
        const bindings = bindingList(await loadBindings());
        if (!authenticated()) return;
        socketSend(sock, { type: OUT.BINDING_SYNC, bindings });
      }
      broadcast({ cmd: "paired", ...msg });
      break;
    }
    case IN.PAIR_DENIED:
      if (!alive() || !sock._challenged) break;
      pairedIntent = false;
      invalidateSession(sock);
      broadcast({ cmd: "pairDenied", ...msg });
      try { sock.close(); } catch (_) {}
      break;
    case IN.PING:
      if (authenticated()) socketSend(sock, { type: OUT.EVENT, name: "pong", id: msg.id });
      break;
    case IN.BROKER_STATE:
      if (!authenticated()) break;
      if (msg.data && typeof msg.data === "object") brokerState = msg.data;
      broadcast({ cmd: "brokerState", state: brokerState });
      break;
    case IN.BINDING_REVOKED: {
      if (!authenticated()) break;
      const profileId = String(msg.profileId || "");
      const sessionId = String(msg.sessionId || "");
      scopeKey(profileId, sessionId);
      await mutateBindings(
        (current) => removeScope(current, profileId, sessionId), false, authenticated
      );
      if (!authenticated()) break;
      broadcast({ cmd: "bindingRevoked", profileId, sessionId,
        reason: msg.reason || "this session was attached in another Chrome profile" });
      break;
    }
    case IN.ACTION:
      // Only act once the agent has completed the pairing handshake, and run actions strictly one at
      // a time (a queue) so a fast burst can't fire a click before the prior snapshot/navigation ends.
      if (!authenticated()) {
        socketSend(sock, { type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: "not paired" });
        break;
      }
      if (queueDepth >= MAX_QUEUED) {
        socketSend(sock, { type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: "action queue full" });
        break;
      }
      const epoch = { session: sessionGen, authorization: authorizationGen }; queueDepth++;
      // ALWAYS decrement, even if the error path itself throws: `.then(dec, dec)` keeps the chain
      // fulfilled — one poisoned rejection would otherwise freeze the queue (and the counter) forever.
      const dec = () => { queueDepth--; return new Promise((r) => setTimeout(r, 60)); };  // rate-limit + settle
      actionQueue = actionQueue
        // Re-check right before executing: if the session dropped meanwhile, don't act on a stale page.
        .then(() => actionAuthorized(sock, epoch) ? handleAction(msg, sock, epoch)
          : sendAuthorizationError(sock, epoch, msg.id))
        .catch((e) => {
          try {
            if (!actionAuthorized(sock, epoch)) sendAuthorizationError(sock, epoch, msg.id);
            else actionSocketSend(sock, epoch,
              { type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: String(e) });
          } catch (_) {}
        })
        .then(dec, dec);
      break;
  }
}

// ---- action execution -------------------------------------------------------

function effectiveTabUrl(tab) {
  return String((tab && (tab.pendingUrl || tab.url)) || "").trim();
}

function urlControlReason(rawUrl) {
  let url;
  try { url = new URL(rawUrl); } catch (_) {
    return "This tab does not have a valid controllable URL.";
  }
  // Hermes deliberately supports opening a new empty tab before navigating it.
  // Permit exactly about:blank; every other browser-internal about: page remains blocked.
  if (url.href.toLowerCase() === "about:blank") return null;
  const protocol = url.protocol.toLowerCase();
  const blockedProtocols = {
    "chrome:": "Chrome internal pages cannot be controlled by extensions.",
    "chrome-search:": "Chrome internal pages cannot be controlled by extensions.",
    "chrome-untrusted:": "Chrome internal pages cannot be controlled by extensions.",
    "edge:": "Edge internal pages cannot be controlled by extensions.",
    "about:": "Browser internal pages cannot be controlled by extensions.",
    "devtools:": "Developer Tools pages cannot be controlled by extensions.",
    "view-source:": "View-source pages cannot be controlled by extensions.",
    "chrome-extension:": "Extension pages cannot be controlled by other extensions.",
    "edge-extension:": "Extension pages cannot be controlled by other extensions.",
    "file:": "Local file pages are not supported because Chrome file access requires a separate browser setting.",
  };
  if (blockedProtocols[protocol]) return blockedProtocols[protocol];
  if (!["http:", "https:"].includes(protocol)) {
    return `Pages using the ${protocol.replace(/:$/, "")} scheme cannot be controlled.`;
  }
  const hostname = url.hostname.toLowerCase();
  const pathname = url.pathname.toLowerCase();
  if (hostname === "chromewebstore.google.com" ||
      (hostname === "chrome.google.com" && (pathname === "/webstore" || pathname.startsWith("/webstore/")))) {
    return "Chrome Web Store pages cannot be controlled by extensions.";
  }
  return null;
}

function tabControlStatus(tab) {
  if (!tab || !Number.isInteger(tab.id)) {
    return { controllable: false, reason: "No active Chrome tab is available." };
  }
  const currentUrl = String(tab.url || "").trim();
  const pendingUrl = String(tab.pendingUrl || "").trim();
  if (!currentUrl && !pendingUrl) {
    return { controllable: false, reason: tab.status === "loading"
      ? "Wait for the active page to finish loading before attaching it."
      : "This tab has no controllable URL yet." };
  }
  const pendingReason = pendingUrl ? urlControlReason(pendingUrl) : null;
  if (pendingReason) return { controllable: false, reason: pendingReason };
  if (pendingUrl) {
    return { controllable: false,
      reason: "Wait for the active page to finish loading before attaching it." };
  }
  const currentReason = currentUrl ? urlControlReason(currentUrl) : null;
  if (currentReason) return { controllable: false, reason: currentReason };
  return { controllable: true, reason: null };
}

const SITE_ACCESS_GUIDANCE =
  "Chrome site access is off for this page. Open chrome://extensions, choose Hermes Connector > Details, then set Site access to On all sites.";

function hostPermissionPattern(rawUrl) {
  try {
    const url = new URL(String(rawUrl || ""));
    if (!["http:", "https:"].includes(url.protocol.toLowerCase())) return null;
    return `${url.protocol}//${url.hostname}/*`;
  } catch (_) {
    return null;
  }
}

async function siteAccessReason(rawUrl) {
  const origin = hostPermissionPattern(rawUrl);
  if (!origin) return null;
  try {
    if (await chrome.permissions.contains({ origins: [origin] })) return null;
  } catch (_) {}
  return SITE_ACCESS_GUIDANCE;
}

async function tabControlStatusWithSiteAccess(tab) {
  const control = tabControlStatus(tab);
  if (!control.controllable) return control;
  const reason = await siteAccessReason(effectiveTabUrl(tab));
  return reason ? { controllable: false, reason } : control;
}

function isControllableTab(tab) {
  return tabControlStatus(tab).controllable;
}

function isRetainableTab(tab) {
  if (!tab || !Number.isInteger(tab.id)) return false;
  const pendingUrl = String(tab.pendingUrl || "").trim();
  // Preserve the exact tab-id authorization while a safe navigation is pending, but keep actions
  // blocked through tabControlStatus until a controllable document is actually committed.
  if (pendingUrl) return !urlControlReason(pendingUrl);
  // Chrome can expose a freshly-created about:blank tab with an empty URL even
  // after status briefly says complete. Keeping that exact existing tab ID is
  // safe (all page actions remain blocked) and prevents a concurrent UI render
  // from revoking the NEW_TAB action before about:blank becomes observable.
  if (!String(tab.url || "").trim()) return true;
  return isControllableTab(tab);
}

function describeTab(tab, owner = null) {
  const control = tabControlStatus(tab);
  if (!tab) {
    return { tabId: null, windowId: null, index: null, title: "No active tab", url: "",
      active: false, owner: null, ...control };
  }
  return { tabId: tab.id, windowId: tab.windowId, index: tab.index,
    title: tab.title || "Untitled", url: sanitizeUrl(effectiveTabUrl(tab)),
    active: !!tab.active, owner, ...control };
}

async function describeTabWithSiteAccess(tab, owner = null) {
  const described = describeTab(tab, owner);
  if (!described.controllable || !tab) return described;
  const reason = await siteAccessReason(effectiveTabUrl(tab));
  return reason ? { ...described, controllable: false, reason } : described;
}

function scheduleActiveTabBroadcast(tabId, knownTab = null) {
  const eventGeneration = ++activeTabEventGeneration;
  Promise.resolve().then(async () => {
    let tab = knownTab;
    if (!tab && Number.isInteger(tabId)) {
      try { tab = await chrome.tabs.get(tabId); } catch (_) { tab = null; }
    }
    if (!tab) {
      try { [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true }); } catch (_) {}
    }
    if (eventGeneration !== activeTabEventGeneration) return;
    // An onUpdated lookup can finish after focus moved elsewhere. Never publish it as the active tab.
    if (tab && !tab.active) return;
    const described = await describeTabWithSiteAccess(tab || null);
    if (eventGeneration !== activeTabEventGeneration) return;
    broadcast({ cmd: "activeTabChanged", activeTab: described });
  }).catch(() => {});
}

function scheduleAttachedTabRefresh(tabId) {
  if (!Number.isInteger(tabId)) return;
  const eventGeneration = (attachedTabEventGeneration.get(tabId) || 0) + 1;
  attachedTabEventGeneration.set(tabId, eventGeneration);
  mutateBindings(async (registry) => {
    const attached = Object.values(registry).some((binding) => binding.tabIds.includes(tabId));
    if (!attached || attachedTabEventGeneration.get(tabId) !== eventGeneration) return registry;
    let tab;
    try { tab = await chrome.tabs.get(tabId); } catch (_) {
      return removeTabEverywhere(registry, tabId);
    }
    if (attachedTabEventGeneration.get(tabId) !== eventGeneration) return registry;
    return isRetainableTab(tab) ? registry : removeTabEverywhere(registry, tabId);
  }, true, () => attachedTabEventGeneration.get(tabId) === eventGeneration)
    .then((registry) => {
      if (attachedTabEventGeneration.get(tabId) !== eventGeneration) return;
      const retained = Object.values(registry).some((binding) => binding.tabIds.includes(tabId));
      if (retained) broadcast({ cmd: "attachedTabChanged", tabId });
    })
    .catch(() => {});
}

// Exact target only. An unbound or stale scope fails instead of falling back to whichever page the
// user most recently focused — the central wrong-tab guarantee of protocol v4.
async function getRetainableTargetTab(msg) {
  const scope = msg && msg.scope;
  if (!scope || !scope.profileId || !scope.sessionId) throw new Error("action has no Hermes session scope");
  if (!Number.isInteger(msg.targetTabId)) throw new Error("action has no explicit target tab");
  const registry = await loadBindings();
  const binding = registry[scopeKey(scope.profileId, scope.sessionId)];
  if (!binding || !binding.tabIds.includes(msg.targetTabId) || binding.activeTabId !== msg.targetTabId) {
    throw new Error("target tab is not attached as the active tab for this Hermes session");
  }
  let tab;
  try { tab = await chrome.tabs.get(msg.targetTabId); } catch (_) {
    await mutateBindings((current) => removeTabEverywhere(current, msg.targetTabId));
    throw new Error("attached target tab no longer exists");
  }
  if (!isRetainableTab(tab)) {
    throw new Error(`attached target tab cannot be retained: ${tabControlStatus(tab).reason}`);
  }
  return tab;
}

async function getTargetTab(msg) {
  const tab = await getRetainableTargetTab(msg);
  const control = tabControlStatus(tab);
  if (!control.controllable) throw new Error(`attached target tab cannot be controlled: ${control.reason}`);
  return tab;
}

async function inPage(tabId, func, args) {
  // Run in the extension's ISOLATED world, not the page's MAIN world: the page can't clobber the
  // globals/prototypes our helpers rely on (document.querySelector, JSON, HTMLInputElement…), so a
  // hostile site can't feed us fake DOM data. The isolated world persists window.__agentBridge across
  // calls (verified), so ref_N handles still resolve; and it has full DOM access.
  // chrome.scripting rejects `undefined` in args ("Value is unserializable"); pass null instead.
  const safe = (args || []).map((x) => (x === undefined ? null : x));
  const [res] = await chrome.scripting.executeScript({
    target: { tabId }, world: "ISOLATED", func, args: safe,
  });
  return res && res.result;
}

async function getSettings() {
  return { ...DEFAULT_SETTINGS, ...(await chrome.storage.local.get(STORE.SETTINGS))[STORE.SETTINGS] };
}

async function getScopeTabs(scope) {
  const registry = await validateBindings();
  const binding = registry[scopeKey(scope.profileId, scope.sessionId)];
  if (!binding) return { binding: null, tabs: [] };
  const tabs = [];
  for (const tabId of binding.tabIds) {
    try {
      const tab = await chrome.tabs.get(tabId);
      // Keep an explicitly authorized tab addressable while a safe HTTP(S)
      // navigation is pending. Page actions still fail closed in getTargetTab()
      // until the document is controllable, but list/switch/close and the
      // new-tab return index must not lose the exact tab during that interval.
      if (isRetainableTab(tab)) tabs.push(tab);
    } catch (_) {}
  }
  tabs.sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index));
  return { binding, tabs };
}

// Wait until the tab reports status "complete", or the timeout. IMPORTANT: create this promise
// (listener installed) BEFORE starting the navigation — a fast cached page can reach "complete"
// in the gap and leave a late listener waiting the full timeout for an event that already fired.
function waitComplete(tabId, ms) {
  return new Promise((resolve) => {
    const fin = (v) => { clearTimeout(to); chrome.tabs.onUpdated.removeListener(l); resolve(v); };
    const l = (id, info) => { if (id === tabId && info.status === "complete") fin(true); };
    const to = setTimeout(() => fin(false), ms);
    chrome.tabs.onUpdated.addListener(l);
  });
}

async function handleAction(msg, sock, epoch) {
  const a = msg.action || {};
  const pageIndependentAction = new Set([
    ACTION.NEW_TAB,
    ACTION.LIST_TABS,
    ACTION.SWITCH_TAB,
    ACTION.CLOSE_TAB,
    ACTION.CURRENT_URL,
    ACTION.WAIT,
  ]).has(a.kind);
  // Navigation is also safe from a freshly-created URL-less/about:blank tab:
  // it mutates only the exact authorized tab ID and validates the destination
  // before Chrome receives it. All DOM/input actions still require a fully
  // controllable committed document.
  const allowPendingTarget = pageIndependentAction || a.kind === ACTION.NAVIGATE;
  let tab;
  try {
    tab = await (allowPendingTarget ? getRetainableTargetTab(msg) : getTargetTab(msg));
    const accessError = await siteAccessReason(effectiveTabUrl(tab));
    if (accessError) throw new Error(accessError);
  } catch (error) {
    sessionSocketSend(sock, epoch.session,
      { type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: String(error.message || error) });
    return;
  }
  const settings = pageIndependentAction
    ? { trustedInput: false, showOverlay: false }
    : await getSettings();
  requireActionAuthorized(sock, epoch);
  // "Trusted input" mode: real browser input events via CDP only if the user enabled it. The required
  // manifest permission is present, but the debugger transport stays detached otherwise (no debugger banner).
  const useCdp = !!settings.trustedInput && await cdp.hasDebugger();
  const overlay = async (on) => { if (settings.showOverlay) { try { await inPage(tab.id, setOverlay, [on]); } catch (_) {} } };
  requireActionAuthorized(sock, epoch);
  await overlay(true);

  let data;
  try {
    switch (a.kind) {
    case ACTION.NAVIGATE: {
      const u = String(a.url || "");
      if (!/^https?:\/\//i.test(u)) { data = { ok: false, error: "only http/https URLs are allowed" }; break; }
      const policyError = urlControlReason(u);
      if (policyError) { data = { ok: false, error: policyError }; break; }
      const accessError = await siteAccessReason(u);
      if (accessError) { data = { ok: false, error: accessError }; break; }
      // Trusted-input mode: attach BEFORE navigating so a dialog fired during load (beforeunload,
      // onload alert) is auto-handled instead of freezing the page with nobody attached yet.
      if (useCdp) {
        try {
          await cdp.ensureAttached(tab.id, () => requireActionAuthorized(sock, epoch));
        } catch (_) {}
      }
      const fromUrl = tab.url;
      const loadedP = waitComplete(tab.id, 15000);   // listener FIRST, then navigate
      requireActionAuthorized(sock, epoch);
      await chrome.tabs.update(tab.id, { url: u });
      const loaded = await loadedP;
      // Report what ACTUALLY happened: the final URL after redirects, and whether the load finished.
      const t = await chrome.tabs.get(tab.id).catch(() => null);
      const finalUrl = (t && (t.pendingUrl || t.url)) || u;
      if (!loaded && t && t.url === fromUrl && t.status === "complete") {
        data = { ok: false, error: "navigation did not start (still on the previous page)" };
      } else {
        data = { url: sanitizeUrl(finalUrl), title: t && t.title, loaded };
      }
      break;
    }
    case ACTION.SNAPSHOT:
      requireActionAuthorized(sock, epoch);
      data = await inPage(tab.id, buildSnapshot, [a.maxChars]);
      break;
    case ACTION.READ_TEXT:
      requireActionAuthorized(sock, epoch);
      data = await inPage(tab.id, readText, [a.maxChars]);
      break;
    case ACTION.CLICK: {
      if (useCdp) {
        requireActionAuthorized(sock, epoch);
        const r = await inPage(tab.id, refRect, [a.ref]);
        requireActionAuthorized(sock, epoch);
        data = r.ok ? await cdp.click(tab.id, r.x, r.y,
          () => requireActionAuthorized(sock, epoch)) : r;
      } else { requireActionAuthorized(sock, epoch); data = await inPage(tab.id, clickRef, [a.ref]); }
      break;
    }
    case ACTION.TYPE: {
      if (useCdp) {
        // mustEdit: refuse to CDP-type into a non-editable target (button, checkbox, container…) —
        // Ctrl+A there would select the whole page and insertText would land who-knows-where.
        requireActionAuthorized(sock, epoch);
        const f = await inPage(tab.id, focusRef, [a.ref, true]);
        requireActionAuthorized(sock, epoch);
        if (!f.ok) data = f;
        else {
          data = await cdp.typeText(tab.id, a.text, () => requireActionAuthorized(sock, epoch));
          if (a.submit && data.ok !== false) {
            data = await cdp.key(tab.id, "Enter", () => requireActionAuthorized(sock, epoch));
          }
        }
      } else { requireActionAuthorized(sock, epoch); data = await inPage(tab.id, typeRef, [a.ref, a.text, !!a.submit]); }
      break;
    }
    case ACTION.SCROLL:
      requireActionAuthorized(sock, epoch);
      data = await inPage(tab.id, scrollPage, [a.ref, a.dy, a.to]);
      break;
    case ACTION.SCREENSHOT:
      // captureVisibleTab grabs the window's ACTIVE tab, which may differ from our target — focus
      // the target first so the screenshot is really of the page we act on.
      requireActionAuthorized(sock, epoch);
      if (!tab.active) { try { await chrome.tabs.update(tab.id, { active: true }); } catch (_) {} }
      requireActionAuthorized(sock, epoch);
      await new Promise((resolve) => setTimeout(resolve, 0));
      const beforeGeneration = activationGeneration.get(tab.windowId) || 0;
      let [activeBefore] = await chrome.tabs.query({ active: true, windowId: tab.windowId });
      await new Promise((resolve) => setTimeout(resolve, 0));
      if (!activeBefore || activeBefore.id !== tab.id ||
          (activationGeneration.get(tab.windowId) || 0) !== beforeGeneration) {
        throw new Error("the attached tab could not be made active for the screenshot");
      }
      requireActionAuthorized(sock, epoch);
      const captureGeneration = activationGeneration.get(tab.windowId) || 0;
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
      await new Promise((resolve) => setTimeout(resolve, 0));
      const [activeAfter] = await chrome.tabs.query({ active: true, windowId: tab.windowId });
      await new Promise((resolve) => setTimeout(resolve, 0));
      if (!activeAfter || activeAfter.id !== tab.id ||
          (activationGeneration.get(tab.windowId) || 0) !== captureGeneration) {
        throw new Error("the active tab changed during the screenshot; captured data was discarded");
      }
      requireActionAuthorized(sock, epoch);
      data = { dataUrl };
      break;
    case ACTION.CURRENT_URL:
      requireActionAuthorized(sock, epoch);
      data = { url: sanitizeUrl(effectiveTabUrl(tab)), title: tab.title };
      break;
    case ACTION.WAIT:
      await new Promise((r) => setTimeout(r, Math.min(a.ms || 0, 15000)));
      requireActionAuthorized(sock, epoch);
      data = { waited: a.ms };
      break;
    case ACTION.HOVER: {
      if (useCdp) {
        requireActionAuthorized(sock, epoch);
        const r = await inPage(tab.id, refRect, [a.ref]);
        requireActionAuthorized(sock, epoch);
        data = r.ok ? await cdp.hover(tab.id, r.x, r.y,
          () => requireActionAuthorized(sock, epoch)) : r;
      } else {
        requireActionAuthorized(sock, epoch);
        data = await inPage(tab.id, hoverRef, [a.ref]);
      }
      break;
    }
    case ACTION.KEY:
      if (useCdp) {
        // If a ref was given, it MUST focus successfully first — otherwise the trusted keystroke
        // would land on whatever was previously focused (wrong field/button). Abort on failure.
        if (a.ref) {
          requireActionAuthorized(sock, epoch);
          const f = await inPage(tab.id, focusRef, [a.ref]);
          requireActionAuthorized(sock, epoch);
          if (!f || f.ok !== true) { data = f || { ok: false, error: "could not focus ref: " + a.ref }; break; }
        }
        data = await cdp.key(tab.id, a.key, () => requireActionAuthorized(sock, epoch));
      } else {
        requireActionAuthorized(sock, epoch);
        data = await inPage(tab.id, pressKey, [a.key, a.ref]);
      }
      break;
    case ACTION.SELECT_OPTION:
      requireActionAuthorized(sock, epoch);
      data = await inPage(tab.id, selectOption, [a.ref, a.value, a.label]);
      break;
    case ACTION.DRAG:
      requireActionAuthorized(sock, epoch);
      data = await inPage(tab.id, dragRefs, [a.from, a.to]);
      break;
    case ACTION.FIND:
      requireActionAuthorized(sock, epoch);
      data = await inPage(tab.id, findText, [a.text]);
      break;
    // History moves wait for the load too (shorter cap: a same-document/bfcache move may emit no
    // "complete" at all) and report the REAL landing URL, so the agent never acts on the old page.
    case ACTION.BACK: {
      const p = waitComplete(tab.id, 5000);
      requireActionAuthorized(sock, epoch);
      await chrome.tabs.goBack(tab.id);
      const loaded = await p;
      const t = await chrome.tabs.get(tab.id).catch(() => null);
      data = { url: sanitizeUrl(t && t.url), title: t && t.title, loaded };
      break;
    }
    case ACTION.FORWARD: {
      const p = waitComplete(tab.id, 5000);
      requireActionAuthorized(sock, epoch);
      await chrome.tabs.goForward(tab.id);
      const loaded = await p;
      const t = await chrome.tabs.get(tab.id).catch(() => null);
      data = { url: sanitizeUrl(t && t.url), title: t && t.title, loaded };
      break;
    }
    case ACTION.RELOAD: {
      const p = waitComplete(tab.id, 15000);
      requireActionAuthorized(sock, epoch);
      await chrome.tabs.reload(tab.id);
      const loaded = await p;
      const t = await chrome.tabs.get(tab.id).catch(() => null);
      data = { url: sanitizeUrl(t && t.url), title: t && t.title, loaded };
      break;
    }
    case ACTION.NEW_TAB: {
      // Same scheme policy as navigate: the agent opens web pages, not chrome:// / file:// / js:.
      const nu = a.url ? String(a.url) : "about:blank";
      if (nu !== "about:blank" && !/^https?:\/\//i.test(nu)) {
        data = { ok: false, error: "only http/https URLs are allowed" };
        break;
      }
      const policyError = urlControlReason(nu);
      if (policyError) { data = { ok: false, error: policyError }; break; }
      const accessError = await siteAccessReason(nu);
      if (accessError) { data = { ok: false, error: accessError }; break; }
      requireActionAuthorized(sock, epoch);
      const t = await chrome.tabs.create({ url: nu, windowId: tab.windowId, active: true });
      let attached = false;
      try {
        requireActionAuthorized(sock, epoch);
        const bindings = await actionBindingMutation(
          sock, epoch,
          (current) => attachTab(current, msg.scope.profileId, msg.scope.sessionId, t.id),
        );
        const updated = bindings[scopeKey(msg.scope.profileId, msg.scope.sessionId)];
        attached = !!updated && updated.tabIds.includes(t.id);
        requireActionAuthorized(sock, epoch);
      } catch (error) {
        if (!attached) { try { await chrome.tabs.remove(t.id); } catch (_) {} }
        throw error;
      }
      const scoped = await getScopeTabs(msg.scope);
      data = { tabId: t.id, index: scoped.tabs.findIndex((item) => item.id === t.id) };
      break;
    }
    case ACTION.LIST_TABS: {
      requireActionAuthorized(sock, epoch);
      const scoped = await getScopeTabs(msg.scope);
      data = { tabs: await Promise.all(scoped.tabs.map(async (t, index) => {
        const control = await tabControlStatusWithSiteAccess(t);
        return {
          index,
          tabId: t.id,
          title: t.title,
          url: sanitizeUrl(effectiveTabUrl(t)),
          active: t.id === scoped.binding.activeTabId,
          controllable: control.controllable,
          ...(control.reason ? { reason: control.reason } : {}),
        };
      })) };
      break;
    }
    case ACTION.SWITCH_TAB: {
      const scoped = await getScopeTabs(msg.scope);
      const t = scoped.tabs[a.index];
      if (!t) { data = { ok: false, error: "no tab at index " + a.index }; }
      else {
        const accessError = await siteAccessReason(effectiveTabUrl(t));
        if (accessError) { data = { ok: false, error: accessError }; break; }
        requireActionAuthorized(sock, epoch);
        await actionBindingMutation(
          sock, epoch,
          (current) => setActiveTab(current, msg.scope.profileId, msg.scope.sessionId, t.id),
        );
        requireActionAuthorized(sock, epoch);
        await chrome.windows.update(t.windowId, { focused: true }).catch(() => {});
        requireActionAuthorized(sock, epoch);
        await chrome.tabs.update(t.id, { active: true });
        data = { switched: a.index, tabId: t.id };
      }
      break;
    }
    case ACTION.CLOSE_TAB: {
      const scoped = await getScopeTabs(msg.scope);
      const localIndex = a.index != null ? a.index : scoped.tabs.findIndex((item) => item.id === tab.id);
      const t = scoped.tabs[localIndex];
      if (t) {
        const accessError = await siteAccessReason(effectiveTabUrl(t));
        if (accessError) { data = { ok: false, error: accessError }; break; }
        requireActionAuthorized(sock, epoch);
        await actionBindingMutation(
          sock, epoch,
          (current) => detachTab(current, msg.scope.profileId, msg.scope.sessionId, t.id),
        );
        requireActionAuthorized(sock, epoch);
        await chrome.tabs.remove(t.id);
      }
      data = { closed: t ? localIndex : null, tabId: t ? t.id : null };
      break;
    }
    default:
      data = { ok: false, error: "unknown action: " + a.kind };
    }
  } finally {
    await overlay(false);
    // A detach/transfer or Trusted-input change can race an in-flight action
    // just before that action calls ensureAttached(). Reconcile again after
    // every action so a stale debugger transport and its dialog handler can
    // never survive outside the current explicit active targets.
    try {
      const latestSettings = await getSettings();
      if (!latestSettings.trustedInput) {
        await cdp.detachAll();
      } else {
        const latestBindings = await loadBindings();
        await cdp.retainOnly(new Set(
          Object.values(latestBindings).map((binding) => binding.activeTabId)
        ));
      }
    } catch (_) {
      try { await cdp.detach(tab.id); } catch (_) {}
    }
  }
  // Honest result: surface a real failure as ok:false instead of burying it under a top-level ok:true.
  if (data && data.ok === false) {
    if (!actionSocketSend(sock, epoch,
      { type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: data.error || "action failed" })) {
      sendAuthorizationError(sock, epoch, msg.id);
    }
  } else {
    if (!actionSocketSend(sock, epoch, { type: OUT.ACTION_RESULT, id: msg.id, ok: true, data })) {
      sendAuthorizationError(sock, epoch, msg.id);
    }
  }
}

// ---- UI (side panel) link ---------------------------------------------------

const panels = new Set();
function broadcast(msg) { chrome.runtime.sendMessage({ from: "bg", ...msg }).catch(() => {}); }

async function setUpdateBadge(active, title = "") {
  const text = active ? "UP" : "";
  await Promise.all([
    chrome.action.setBadgeText ? chrome.action.setBadgeText({ text }) : undefined,
    active && chrome.action.setBadgeBackgroundColor
      ? chrome.action.setBadgeBackgroundColor({ color: "#c27c0e" })
      : undefined,
    chrome.action.setTitle
      ? chrome.action.setTitle({ title: title || (active
        ? "Hermes Connector update requires attention"
        : "Open Hermes") })
      : undefined,
  ]);
}

chrome.storage.local.get(STORE.UPGRADE_NOTICE).then((stored) => {
  const notice = stored[STORE.UPGRADE_NOTICE] || null;
  return setUpdateBadge(!!notice, notice
    ? `Hermes Connector ${notice.extensionVersion}: reinstall the matching companion`
    : "");
}).catch(() => {});

if (chrome.runtime.onUpdateAvailable) {
  chrome.runtime.onUpdateAvailable.addListener((details) => {
    setUpdateBadge(true, `Hermes Connector ${details.version} is ready to install`).catch(() => {});
  });
}

chrome.runtime.onInstalled.addListener((details) => {
  if (chrome.runtime.getManifest().version !== COMPANION_REINSTALL_NOTICE.extensionVersion) return;
  (async () => {
    const migration = await ensureBridgeMigration();
    if (migration.migrated) {
      invalidateSession(ws);
      clearSocketKeepalive();
      if (ws) { try { ws.close(); } catch (_) {} ws = null; }
      if (pairedIntent) scheduleReconnect();
    }
    if (details.reason !== "update" || !details.previousVersion ||
        details.previousVersion === COMPANION_REINSTALL_NOTICE.extensionVersion) return;
    const notice = { ...COMPANION_REINSTALL_NOTICE, previousVersion: details.previousVersion,
      customBridge: migration.customBridge };
    await chrome.storage.local.set({ [STORE.UPGRADE_NOTICE]: notice });
    await setUpdateBadge(true,
      `Hermes Connector ${notice.extensionVersion}: reinstall the matching companion`);
    broadcast({ cmd: "upgradeNoticeChanged", notice });
  })().catch((error) => console.error("upgrade migration:", error));
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    switch (msg.cmd) {
      case "connect": {
        const cur = (await chrome.storage.local.get(STORE.PAIRING))[STORE.PAIRING] || {};
        const identity = await getIdentity();
        const browserName = msg.browserName || identity.browserName;
        await chrome.storage.local.set({ [STORE.PAIRING]: { ...cur },
          [STORE.IDENTITY]: { ...identity, browserName } });
        pairedIntent = true;
        helloNow(browserName);
        sendResponse({ ok: true });
        break;
      }
      case "unpair":
        pairedIntent = false;
        clearTimeout(reconnectTimer); reconnectTimer = null;
        sendHost({ type: OUT.BYE });
        invalidateSession(ws);
        clearSocketKeepalive();
        if (ws) ws.close();
        ws = null;
        brokerState = { protocol: PROTOCOL_VERSION, browsers: [], agentProfiles: [] };
        await cdp.detachAll();   // drop the debugger attachment + its banner
        await chrome.storage.local.remove(STORE.PAIRING);
        sendResponse({ ok: true });
        break;
      case "getState": {
        const st = await chrome.storage.local.get([
          STORE.IDENTITY, STORE.PAIRING, STORE.SETTINGS, STORE.BINDINGS, STORE.SELECTED_SCOPE,
          STORE.UPGRADE_NOTICE,
        ]);
        sendResponse({ paired, companionDetected, brokerState, identity: st[STORE.IDENTITY] || await getIdentity(),
          pairing: st[STORE.PAIRING] || null,
          bindings: normalizeRegistry(st[STORE.BINDINGS]),
          selectedScope: st[STORE.SELECTED_SCOPE] || null,
          upgradeNotice: st[STORE.UPGRADE_NOTICE] || null,
          settings: { ...DEFAULT_SETTINGS, ...(st[STORE.SETTINGS] || {}) } });
        break;
      }
      case "probeCompanion": {
        if (paired && ws && ws.readyState === WebSocket.OPEN) {
          companionDetected = true;
          broadcast({ cmd: "companionDetected", detected: true });
          sendResponse({ ok: true, detected: true });
          break;
        }
        companionDetected = false;
        const probe = await connectBridge(true);
        sendResponse({ ok: !!probe, detected: companionDetected });
        break;
      }
      case "dismissUpgradeNotice": {
        const saved = await chrome.storage.local.get(STORE.UPGRADE_NOTICE);
        const current = saved[STORE.UPGRADE_NOTICE] || null;
        const matches = current && current.id === String(msg.id || "");
        if (matches) {
          const companionCapabilityConfirmed = paired && brokerState &&
            Object.prototype.hasOwnProperty.call(brokerState, "agentBackends");
          if (!companionCapabilityConfirmed) {
            sendResponse({
              ok: false,
              error: `Companion ${chrome.runtime.getManifest().version} is not confirmed yet — reinstall it and restart Hermes`,
              upgradeNotice: current,
            });
            break;
          }
          await chrome.storage.local.remove(STORE.UPGRADE_NOTICE);
          await setUpdateBadge(false);
          broadcast({ cmd: "upgradeNoticeChanged", notice: null });
        }
        sendResponse({ ok: true, upgradeNotice: matches ? null : current });
        break;
      }
      case "selectScope": {
        const scope = { profileId: String(msg.profileId || ""), sessionId: String(msg.sessionId || "") };
        scopeKey(scope.profileId, scope.sessionId); // validate non-empty
        await chrome.storage.local.set({ [STORE.SELECTED_SCOPE]: scope });
        sendResponse({ ok: true, scope });
        break;
      }
      case "listTabs": {
        const registry = await validateBindings();
        const owners = new Map();
        for (const binding of Object.values(registry)) {
          for (const tabId of binding.tabIds) owners.set(tabId, {
            profileId: binding.profileId, sessionId: binding.sessionId,
            active: binding.activeTabId === tabId,
          });
        }
        let rawTabs;
        if (msg.includeAvailable) {
          // The user explicitly opened "Choose tabs": show local tab titles/URLs so they can choose.
          rawTabs = await chrome.tabs.query({});
        } else {
          // Normal rendering reads only this session's already-attached tabs, not the whole window.
          const key = scopeKey(String(msg.profileId || ""), String(msg.sessionId || ""));
          const binding = registry[key];
          const settled = await Promise.allSettled(
            (binding ? binding.tabIds : []).map((tabId) => chrome.tabs.get(tabId))
          );
          rawTabs = settled.filter((item) => item.status === "fulfilled").map((item) => item.value);
        }
        let activeChromeTab = null;
        try { [activeChromeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true }); } catch (_) {}
        // The explicit picker may explain why any local tab is unavailable. Normal rendering must
        // also retain an already-authorized tab while a safe navigation is pending so the user can
        // still see and revoke that authorization; actions remain blocked by `controllable:false`.
        const orderedTabs = rawTabs.filter((tab) => msg.includeAvailable || isRetainableTab(tab))
          .sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index));
        const tabs = await Promise.all(orderedTabs.map(
          (tab) => describeTabWithSiteAccess(tab, owners.get(tab.id) || null)
        ));
        const activeTab = await describeTabWithSiteAccess(activeChromeTab || null,
          activeChromeTab ? (owners.get(activeChromeTab.id) || null) : null);
        sendResponse({ ok: true, tabs, bindings: registry,
          activeTab });
        break;
      }
      case "attachActiveTab": {
        if (!paired) { sendResponse({ ok: false, error: "pair this Chrome profile before attaching tabs" }); break; }
        const scope = { profileId: String(msg.profileId || ""), sessionId: String(msg.sessionId || "") };
        scopeKey(scope.profileId, scope.sessionId);
        if (!Number.isInteger(msg.expectedTabId)) {
          sendResponse({ ok: false, error: "refresh the panel before attaching the current tab" });
          break;
        }
        const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
        if (!tab || tab.id !== msg.expectedTabId) {
          sendResponse({ ok: false, error: "the active Chrome tab changed; review it and press Attach current again" });
          break;
        }
        const control = await tabControlStatusWithSiteAccess(tab);
        if (!control.controllable) { sendResponse({ ok: false, error: control.reason }); break; }
        const bindings = await attachScopeTab(scope, tab.id);
        sendResponse({ ok: true, tabId: tab.id, bindings });
        break;
      }
      case "attachTab": {
        if (!paired) { sendResponse({ ok: false, error: "pair this Chrome profile before attaching tabs" }); break; }
        const scope = { profileId: String(msg.profileId || ""), sessionId: String(msg.sessionId || "") };
        scopeKey(scope.profileId, scope.sessionId);
        const tab = await chrome.tabs.get(msg.tabId);
        const control = await tabControlStatusWithSiteAccess(tab);
        if (!control.controllable) { sendResponse({ ok: false, error: control.reason }); break; }
        const bindings = await attachScopeTab(scope, tab.id);
        sendResponse({ ok: true, tabId: tab.id, bindings });
        break;
      }
      case "detachTab": {
        const scope = { profileId: String(msg.profileId || ""), sessionId: String(msg.sessionId || "") };
        const bindings = await detachScopeTab(scope, msg.tabId);
        sendResponse({ ok: true, bindings });
        break;
      }
      case "activateTab": {
        const scope = { profileId: String(msg.profileId || ""), sessionId: String(msg.sessionId || "") };
        const tab = await chrome.tabs.get(msg.tabId);
        const bindings = await activateScopeTab(scope, tab.id);
        await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
        await chrome.tabs.update(tab.id, { active: true });
        sendResponse({ ok: true, bindings });
        break;
      }
      case "saveIdentity": {
        const current = await getIdentity();
        const browserName = String(msg.browserName || "").trim().slice(0, 120);
        if (!browserName) { sendResponse({ ok: false, error: "browser name is required" }); break; }
        await chrome.storage.local.set({ [STORE.IDENTITY]: { ...current, browserName } });
        desiredName = browserName;
        invalidateSession(ws);
        clearSocketKeepalive();
        if (ws) { try { ws.close(); } catch (_) {} ws = null; }
        if (pairedIntent) scheduleReconnect();
        sendResponse({ ok: true, identity: { ...current, browserName } });
        break;
      }
      case "saveSettings": {
        const cur = (await chrome.storage.local.get(STORE.SETTINGS))[STORE.SETTINGS] || {};
        const next = { ...cur, ...msg.settings };
        if (!!cur.trustedInput !== !!next.trustedInput) authorizationGen++;
        await chrome.storage.local.set({ [STORE.SETTINGS]: next });
        // Trusted-input turned OFF -> detach the debugger now (removes Chrome's banner immediately).
        if (cur.trustedInput && !next.trustedInput) { try { await cdp.detachAll(); } catch (_) {} }
        // Bridge address or pairing code changed -> the live socket is stale. Drop it and reconnect so
        // the new value actually takes effect (a fresh challenge/HMAC handshake runs on reconnect).
        if (next.bridgeUrl !== cur.bridgeUrl || next.pairingCode !== cur.pairingCode) {
          invalidateSession(ws);
          clearSocketKeepalive();
          if (ws) { try { ws.close(); } catch (_) {} ws = null; }
          if (pairedIntent) scheduleReconnect();
        }
        sendResponse({ ok: true });
        break;
      }
      default:
        sendResponse({ ok: false, error: "unknown cmd" });
    }
  })().catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
  return true; // async response
});

chrome.tabs.onRemoved.addListener((tabId) => {
  mutateBindings((registry) => removeTabEverywhere(registry, tabId)).catch(() => {});
});

chrome.tabs.onReplaced.addListener((addedTabId, removedTabId) => {
  mutateBindings((registry) => {
    let next = normalizeRegistry(registry);
    for (const binding of Object.values(registry)) {
      if (!binding.tabIds.includes(removedTabId)) continue;
      next = detachTab(next, binding.profileId, binding.sessionId, removedTabId);
      next = attachTab(next, binding.profileId, binding.sessionId, addedTabId);
    }
    return next;
  }).catch(() => {});
});

chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {});
});
