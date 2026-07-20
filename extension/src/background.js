// Service worker: owns a direct WebSocket link to the local agent's loopback bridge, the pairing
// state, and the execution of agent-requested actions against the controlled tab. No native host.

import { DEFAULT_BRIDGE_URL, PROTOCOL_VERSION, OUT, IN, ACTION, STORE, DEFAULT_SETTINGS } from "./protocol.js";
import { buildSnapshot, clickRef, typeRef, scrollPage, readText, setOverlay,
  hoverRef, pressKey, selectOption, dragRefs, findText, refRect, focusRef } from "./page-actions.js";
import { attachTab, bindingList, detachTab, normalizeRegistry, removeTabEverywhere,
  removeScope, scopeKey, setActiveTab } from "./bindings.js";
import * as cdp from "./cdp.js";

let ws = null;
let paired = false;
let pairedIntent = false;   // the user wants to stay paired; drives auto-reconnect + keepalive
let brokerState = { protocol: PROTOCOL_VERSION, browsers: [], agentProfiles: [] };
let reconnectTimer = null;
let pingTimer = null;       // 20s WebSocket keepalive while the socket is open (Chrome docs)
let actionQueue = Promise.resolve();  // serialize agent actions so they never race each other
let queueDepth = 0;         // bound the pending queue so a runaway/hostile agent can't OOM the worker
let sessionGen = 0;         // bumped on disconnect/unpair -> already-queued actions are cancelled
const MAX_QUEUED = 32;
let desiredName = "Chrome"; // browser name to announce once the agent challenges us
let bindingTransaction = Promise.resolve(); // prevent concurrent read/modify/write updates from losing tabs

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

async function storeBindings(registry, sync = true, previous = null) {
  const normalized = normalizeRegistry(registry);
  await chrome.storage.local.set({ [STORE.BINDINGS]: normalized });
  if (sync && paired) {
    if (previous === null) {
      sendHost({ type: OUT.BINDING_SYNC, bindings: bindingList(normalized) });
    } else {
      const before = normalizeRegistry(previous);
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

function mutateBindings(mutator, sync = true) {
  const operation = bindingTransaction.then(async () => {
    const current = await loadBindings();
    const next = await mutator(current);
    return storeBindings(next, sync, current);
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
          if (!isControllableTab(tab)) next = removeTabEverywhere(next, tabId);
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

async function bridgeUrl() {
  const s = await chrome.storage.local.get(STORE.SETTINGS);
  return (s[STORE.SETTINGS] && s[STORE.SETTINGS].bridgeUrl) || DEFAULT_BRIDGE_URL;
}

async function connectBridge() {
  // Resolve the URL BEFORE the open-socket check: with the await inside the check→assign gap, two
  // concurrent callers (alarm + panel) could both pass the check and leak a live duplicate socket.
  const url = await bridgeUrl();
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return ws;
  let sock;
  try {
    sock = new WebSocket(url);
  } catch (e) {
    broadcast({ cmd: "hostError", error: String(e) });
    return null;
  }
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
    let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
    // onHostMessage is async — a sync try/catch would miss post-await errors, so catch the promise.
    // Pass THIS socket so the handler can bail if it's superseded across an await (connection race).
    Promise.resolve(onHostMessage(m, sock)).catch((e) => console.error("agent-bridge:", e));
  };
  sock.onclose = () => {
    if (ws !== sock) return;   // a newer connection owns the state now
    clearInterval(pingTimer); pingTimer = null;
    ws = null;
    paired = false;
    sessionGen++;   // cancel any actions still queued from the dead session
    broadcast({ cmd: "disconnected", error: null });
    if (pairedIntent) scheduleReconnect();   // agent restarted / worker slept: self-heal
  };
  sock.onerror = () => { if (ws === sock) broadcast({ cmd: "hostError", error: "cannot reach the local agent" }); };
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
      // The broker challenged us: prove the browser role + stable browser identity, then require a
      // role-bound broker proof back. The shared code never travels in the clear.
      const code = await getPairingCode();
      if (!alive()) return;
      if (weakCode(code)) {
        // Refuse a missing/weak secret and close — never leave a half-open unauthenticated link idling.
        pairedIntent = false;
        try { sock.close(); } catch (_) {}
        broadcast({ cmd: "pairDenied", reason: "Enter the private pairing code printed by the companion installer (⚙ button)." });
        break;
      }
      if (msg.protocol !== PROTOCOL_VERSION) {
        pairedIntent = false;
        try { sock.close(); } catch (_) {}
        broadcast({ cmd: "pairDenied", reason: "Connector companion and extension protocol versions differ." });
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
        paired = false; pairedIntent = false;
        try { sock.close(); } catch (_) {}
        broadcast({ cmd: "pairDenied", reason: "agent identity check failed — wrong pairing code?" });
        break;
      }
      paired = !!msg.ok;
      if (msg.brokerState && typeof msg.brokerState === "object") brokerState = msg.brokerState;
      if (paired) {
        const cur = (await chrome.storage.local.get(STORE.PAIRING))[STORE.PAIRING] || {};
        if (!alive()) return;
        await chrome.storage.local.set({ [STORE.PAIRING]: { ...cur, pairedAt: Date.now() } });
        await validateBindings(false);
        if (!alive()) return;
        sendHost({ type: OUT.BINDING_SYNC, bindings: bindingList(await loadBindings()) });
      }
      broadcast({ cmd: "paired", ...msg });
      break;
    }
    case IN.PAIR_DENIED:
      paired = false; pairedIntent = false;
      await chrome.storage.local.remove(STORE.PAIRING);   // don't keep retrying a refused pairing
      broadcast({ cmd: "pairDenied", ...msg });
      break;
    case IN.PING:
      sendHost({ type: OUT.EVENT, name: "pong", id: msg.id });
      break;
    case IN.BROKER_STATE:
      if (msg.data && typeof msg.data === "object") brokerState = msg.data;
      broadcast({ cmd: "brokerState", state: brokerState });
      break;
    case IN.BINDING_REVOKED: {
      const profileId = String(msg.profileId || "");
      const sessionId = String(msg.sessionId || "");
      scopeKey(profileId, sessionId);
      await mutateBindings((current) => removeScope(current, profileId, sessionId), false);
      broadcast({ cmd: "bindingRevoked", profileId, sessionId,
        reason: msg.reason || "this session was attached in another Chrome profile" });
      break;
    }
    case IN.ACTION:
      // Only act once the agent has completed the pairing handshake, and run actions strictly one at
      // a time (a queue) so a fast burst can't fire a click before the prior snapshot/navigation ends.
      if (!paired) {
        sendHost({ type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: "not paired" });
        break;
      }
      if (queueDepth >= MAX_QUEUED) {
        sendHost({ type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: "action queue full" });
        break;
      }
      const gen = sessionGen; queueDepth++;
      // ALWAYS decrement, even if the error path itself throws: `.then(dec, dec)` keeps the chain
      // fulfilled — one poisoned rejection would otherwise freeze the queue (and the counter) forever.
      const dec = () => { queueDepth--; return new Promise((r) => setTimeout(r, 60)); };  // rate-limit + settle
      actionQueue = actionQueue
        // Re-check right before executing: if the session dropped meanwhile, don't act on a stale page.
        .then(() => (gen === sessionGen && paired) ? handleAction(msg)
          : sendHost({ type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: "disconnected" }))
        .catch((e) => { try { sendHost({ type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: String(e) }); } catch (_) {} })
        .then(dec, dec);
      break;
  }
}

// ---- action execution -------------------------------------------------------

function isControllableTab(t) {
  if (!t || !Number.isInteger(t.id)) return false;
  const url = t.pendingUrl || t.url || "";
  if (url === "about:blank") return true;
  return !/^(chrome|edge|about|devtools|view-source):/.test(url) &&
    !/^chrome-extension:\/\//.test(url);
}

// Exact target only. An unbound or stale scope fails instead of falling back to whichever page the
// user most recently focused — the central wrong-tab guarantee of protocol v3.
async function getTargetTab(msg) {
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
  if (!isControllableTab(tab)) throw new Error("attached target tab cannot be controlled");
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
      if (isControllableTab(tab)) tabs.push(tab);
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

async function handleAction(msg) {
  const a = msg.action || {};
  let tab;
  try {
    tab = await getTargetTab(msg);
  } catch (error) {
    sendHost({ type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: String(error.message || error) });
    return;
  }
  const settings = await getSettings();
  // "Trusted input" mode: real browser input events via CDP only if the user enabled it. The required
  // manifest permission is present, but the debugger transport stays detached otherwise (no debugger banner).
  const useCdp = !!settings.trustedInput && await cdp.hasDebugger();
  const overlay = async (on) => { if (settings.showOverlay) { try { await inPage(tab.id, setOverlay, [on]); } catch (_) {} } };
  await overlay(true);

  let data;
  try {
    switch (a.kind) {
    case ACTION.NAVIGATE: {
      const u = String(a.url || "");
      if (!/^https?:\/\//i.test(u)) { data = { ok: false, error: "only http/https URLs are allowed" }; break; }
      // Trusted-input mode: attach BEFORE navigating so a dialog fired during load (beforeunload,
      // onload alert) is auto-handled instead of freezing the page with nobody attached yet.
      if (useCdp) { try { await cdp.ensureAttached(tab.id); } catch (_) {} }
      const fromUrl = tab.url;
      const loadedP = waitComplete(tab.id, 15000);   // listener FIRST, then navigate
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
      data = await inPage(tab.id, buildSnapshot, [a.maxChars]);
      break;
    case ACTION.READ_TEXT:
      data = await inPage(tab.id, readText, [a.maxChars]);
      break;
    case ACTION.CLICK: {
      if (useCdp) {
        const r = await inPage(tab.id, refRect, [a.ref]);
        data = r.ok ? await cdp.click(tab.id, r.x, r.y) : r;
      } else data = await inPage(tab.id, clickRef, [a.ref]);
      break;
    }
    case ACTION.TYPE: {
      if (useCdp) {
        // mustEdit: refuse to CDP-type into a non-editable target (button, checkbox, container…) —
        // Ctrl+A there would select the whole page and insertText would land who-knows-where.
        const f = await inPage(tab.id, focusRef, [a.ref, true]);
        if (!f.ok) data = f;
        else { data = await cdp.typeText(tab.id, a.text); if (a.submit) await cdp.key(tab.id, "Enter"); }
      } else data = await inPage(tab.id, typeRef, [a.ref, a.text, !!a.submit]);
      break;
    }
    case ACTION.SCROLL:
      data = await inPage(tab.id, scrollPage, [a.ref, a.dy, a.to]);
      break;
    case ACTION.SCREENSHOT:
      // captureVisibleTab grabs the window's ACTIVE tab, which may differ from our target — focus
      // the target first so the screenshot is really of the page we act on.
      if (!tab.active) { try { await chrome.tabs.update(tab.id, { active: true }); } catch (_) {} }
      data = { dataUrl: await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" }) };
      break;
    case ACTION.CURRENT_URL:
      data = { url: sanitizeUrl(tab.url), title: tab.title };
      break;
    case ACTION.WAIT:
      await new Promise((r) => setTimeout(r, Math.min(a.ms || 0, 15000)));
      data = { waited: a.ms };
      break;
    case ACTION.HOVER: {
      if (useCdp) {
        const r = await inPage(tab.id, refRect, [a.ref]);
        data = r.ok ? await cdp.hover(tab.id, r.x, r.y) : r;
      } else data = await inPage(tab.id, hoverRef, [a.ref]);
      break;
    }
    case ACTION.KEY:
      if (useCdp) {
        // If a ref was given, it MUST focus successfully first — otherwise the trusted keystroke
        // would land on whatever was previously focused (wrong field/button). Abort on failure.
        if (a.ref) {
          const f = await inPage(tab.id, focusRef, [a.ref]);
          if (!f || f.ok !== true) { data = f || { ok: false, error: "could not focus ref: " + a.ref }; break; }
        }
        data = await cdp.key(tab.id, a.key);
      } else data = await inPage(tab.id, pressKey, [a.key, a.ref]);
      break;
    case ACTION.SELECT_OPTION:
      data = await inPage(tab.id, selectOption, [a.ref, a.value, a.label]);
      break;
    case ACTION.DRAG:
      data = await inPage(tab.id, dragRefs, [a.from, a.to]);
      break;
    case ACTION.FIND:
      data = await inPage(tab.id, findText, [a.text]);
      break;
    // History moves wait for the load too (shorter cap: a same-document/bfcache move may emit no
    // "complete" at all) and report the REAL landing URL, so the agent never acts on the old page.
    case ACTION.BACK: {
      const p = waitComplete(tab.id, 5000);
      await chrome.tabs.goBack(tab.id);
      const loaded = await p;
      const t = await chrome.tabs.get(tab.id).catch(() => null);
      data = { url: sanitizeUrl(t && t.url), title: t && t.title, loaded };
      break;
    }
    case ACTION.FORWARD: {
      const p = waitComplete(tab.id, 5000);
      await chrome.tabs.goForward(tab.id);
      const loaded = await p;
      const t = await chrome.tabs.get(tab.id).catch(() => null);
      data = { url: sanitizeUrl(t && t.url), title: t && t.title, loaded };
      break;
    }
    case ACTION.RELOAD: {
      const p = waitComplete(tab.id, 15000);
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
      const t = await chrome.tabs.create({ url: nu, windowId: tab.windowId, active: true });
      await attachScopeTab(msg.scope, t.id);
      const scoped = await getScopeTabs(msg.scope);
      data = { tabId: t.id, index: scoped.tabs.findIndex((item) => item.id === t.id) };
      break;
    }
    case ACTION.LIST_TABS: {
      const scoped = await getScopeTabs(msg.scope);
      data = { tabs: scoped.tabs.map((t, index) => ({
        index,
        tabId: t.id,
        title: t.title,
        url: sanitizeUrl(t.url),
        active: t.id === scoped.binding.activeTabId,
      })) };
      break;
    }
    case ACTION.SWITCH_TAB: {
      const scoped = await getScopeTabs(msg.scope);
      const t = scoped.tabs[a.index];
      if (!t) { data = { ok: false, error: "no tab at index " + a.index }; }
      else {
        await chrome.windows.update(t.windowId, { focused: true }).catch(() => {});
        await chrome.tabs.update(t.id, { active: true });
        await activateScopeTab(msg.scope, t.id);
        data = { switched: a.index, tabId: t.id };
      }
      break;
    }
    case ACTION.CLOSE_TAB: {
      const scoped = await getScopeTabs(msg.scope);
      const localIndex = a.index != null ? a.index : scoped.tabs.findIndex((item) => item.id === tab.id);
      const t = scoped.tabs[localIndex];
      if (t) {
        await detachScopeTab(msg.scope, t.id);
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
  }
  // Honest result: surface a real failure as ok:false instead of burying it under a top-level ok:true.
  if (data && data.ok === false) {
    sendHost({ type: OUT.ACTION_RESULT, id: msg.id, ok: false, error: data.error || "action failed" });
  } else {
    sendHost({ type: OUT.ACTION_RESULT, id: msg.id, ok: true, data });
  }
}

// ---- UI (side panel) link ---------------------------------------------------

const panels = new Set();
function broadcast(msg) { chrome.runtime.sendMessage({ from: "bg", ...msg }).catch(() => {}); }

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
        sendHost({ type: OUT.BYE });
        if (ws) ws.close();
        ws = null; paired = false;
        brokerState = { protocol: PROTOCOL_VERSION, browsers: [], agentProfiles: [] };
        cdp.detachAll();   // drop the debugger attachment + its banner
        await chrome.storage.local.remove(STORE.PAIRING);
        sendResponse({ ok: true });
        break;
      case "getState": {
        const st = await chrome.storage.local.get([
          STORE.IDENTITY, STORE.PAIRING, STORE.SETTINGS, STORE.BINDINGS, STORE.SELECTED_SCOPE,
        ]);
        sendResponse({ paired, brokerState, identity: st[STORE.IDENTITY] || await getIdentity(),
          pairing: st[STORE.PAIRING] || null,
          bindings: normalizeRegistry(st[STORE.BINDINGS]),
          selectedScope: st[STORE.SELECTED_SCOPE] || null,
          settings: { ...DEFAULT_SETTINGS, ...(st[STORE.SETTINGS] || {}) } });
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
        const tabs = rawTabs.filter(isControllableTab)
          .sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index))
          .map((tab) => ({ tabId: tab.id, windowId: tab.windowId, index: tab.index,
            title: tab.title || "Untitled", url: sanitizeUrl(tab.url || tab.pendingUrl),
            active: tab.active, owner: owners.get(tab.id) || null }));
        sendResponse({ ok: true, tabs, bindings: registry });
        break;
      }
      case "attachActiveTab": {
        if (!paired) { sendResponse({ ok: false, error: "pair this Chrome profile before attaching tabs" }); break; }
        const scope = { profileId: String(msg.profileId || ""), sessionId: String(msg.sessionId || "") };
        scopeKey(scope.profileId, scope.sessionId);
        const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
        if (!isControllableTab(tab)) { sendResponse({ ok: false, error: "the active tab cannot be controlled" }); break; }
        const bindings = await attachScopeTab(scope, tab.id);
        sendResponse({ ok: true, tabId: tab.id, bindings });
        break;
      }
      case "attachTab": {
        if (!paired) { sendResponse({ ok: false, error: "pair this Chrome profile before attaching tabs" }); break; }
        const scope = { profileId: String(msg.profileId || ""), sessionId: String(msg.sessionId || "") };
        scopeKey(scope.profileId, scope.sessionId);
        const tab = await chrome.tabs.get(msg.tabId);
        if (!isControllableTab(tab)) { sendResponse({ ok: false, error: "the tab cannot be controlled" }); break; }
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
        if (ws) { try { ws.close(); } catch (_) {} ws = null; paired = false; }
        if (pairedIntent) scheduleReconnect();
        sendResponse({ ok: true, identity: { ...current, browserName } });
        break;
      }
      case "saveSettings": {
        const cur = (await chrome.storage.local.get(STORE.SETTINGS))[STORE.SETTINGS] || {};
        const next = { ...cur, ...msg.settings };
        await chrome.storage.local.set({ [STORE.SETTINGS]: next });
        // Trusted-input turned OFF -> detach the debugger now (removes Chrome's banner immediately).
        if (cur.trustedInput && !next.trustedInput) { try { await cdp.detachAll(); } catch (_) {} }
        // Bridge address or pairing code changed -> the live socket is stale. Drop it and reconnect so
        // the new value actually takes effect (a fresh challenge/HMAC handshake runs on reconnect).
        if (next.bridgeUrl !== cur.bridgeUrl || next.pairingCode !== cur.pairingCode) {
          sessionGen++;
          if (ws) { try { ws.close(); } catch (_) {} ws = null; }
          paired = false;
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
