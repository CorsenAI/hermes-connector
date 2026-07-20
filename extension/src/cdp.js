// User-enabled "trusted input" mode via chrome.debugger (Chrome DevTools Protocol).
//
// OFF by default. The required manifest permission is present, but the debugger transport stays detached
// until the user turns the mode on. Then agent clicks/keys/hover become real browser input events, more reliable
// than synthetic DOM events. It also lets us auto-handle native JS dialogs
// (alert/confirm/prompt) so the agent never hangs on them. The cost is Chrome's yellow
// "… is debugging this browser" banner while attached (same as other agent extensions).

const attached = new Set();

// Per-tab record of auto-cancelled dialogs, so an action that triggered a confirm()/prompt() we
// dismissed can be reported as a FAILURE instead of a misleading success. `seq` increments on each
// cancelled dialog; an action snapshots it before dispatching and compares after.
const cancelledDialogs = new Map();   // tabId -> { seq, type, message }
function dialogSeq(tabId) { const r = cancelledDialogs.get(tabId); return r ? r.seq : 0; }
function dialogSince(tabId, beforeSeq) {
  const r = cancelledDialogs.get(tabId);
  return (r && r.seq > beforeSeq) ? r : null;
}

export async function hasDebugger() {
  try { return await chrome.permissions.contains({ permissions: ["debugger"] }); }
  catch (_) { return false; }
}

export async function ensureAttached(tabId) {
  if (attached.has(tabId)) return;
  await chrome.debugger.attach({ tabId }, "1.3");
  attached.add(tabId);
  try { await chrome.debugger.sendCommand({ tabId }, "Page.enable"); } catch (_) {}
  // CRITICAL: input events are dropped on a tab whose window isn't OS-focused unless we emulate
  // focus. Without this, CDP clicks/keys silently do nothing when the user isn't looking at the tab.
  try { await chrome.debugger.sendCommand({ tabId }, "Emulation.setFocusEmulationEnabled", { enabled: true }); } catch (_) {}
}

export async function detach(tabId) {
  if (!attached.has(tabId)) return;
  attached.delete(tabId);
  try { await chrome.debugger.detach({ tabId }); } catch (_) {}
}
export async function detachAll() { for (const id of [...attached]) await detach(id); }

// Auto-handle native JS dialogs so the page (and the agent) never blocks on them, BY TYPE:
//   alert       -> accept (it only has an OK button; dismissing it is the same thing)
//   beforeunload-> accept (the agent asked to leave the page; refusing would cancel its own navigation)
//   confirm     -> cancel (never auto-approve a possibly destructive question)
//   prompt      -> cancel (we have no meaningful text to type)
// This only fires on tabs we've attached to (i.e. only in trusted-input mode).
// Guard for development builds that omit the manifest permission: registering listeners only when the API
// exists keeps the service worker from crashing on load.
if (typeof chrome !== "undefined" && chrome.debugger && chrome.debugger.onEvent) {
  chrome.debugger.onEvent.addListener((source, method, params) => {
    if (method === "Page.javascriptDialogOpening" && source.tabId != null && attached.has(source.tabId)) {
      const t = (params && params.type) || "alert";
      const accept = t === "alert" || t === "beforeunload";
      chrome.debugger.sendCommand({ tabId: source.tabId }, "Page.handleJavaScriptDialog",
        { accept, promptText: "" }).catch(() => {});
      // Record a CANCELLED confirm/prompt so the action that opened it reports failure, not success.
      if (!accept) {
        const prev = cancelledDialogs.get(source.tabId);
        cancelledDialogs.set(source.tabId, {
          seq: (prev ? prev.seq : 0) + 1, type: t,
          message: String((params && params.message) || "").slice(0, 200) });
      }
    }
  });
  chrome.debugger.onDetach.addListener((source) => {
    if (source.tabId != null) { attached.delete(source.tabId); cancelledDialogs.delete(source.tabId); }
  });
}

const cmd = (tabId, method, params) => chrome.debugger.sendCommand({ tabId }, method, params || {});

// Give the dialog event (delivered over the same debugger channel) a tick to arrive after the input
// command resolves, so a confirm()/prompt() opened by the action is seen before we report a result.
const settle = () => new Promise((r) => setTimeout(r, 25));

export async function click(tabId, x, y) {
  await ensureAttached(tabId);
  const before = dialogSeq(tabId);
  const base = { x, y, button: "left" };
  await cmd(tabId, "Input.dispatchMouseEvent", { type: "mouseMoved", ...base, buttons: 0 });
  await cmd(tabId, "Input.dispatchMouseEvent", { type: "mousePressed", ...base, buttons: 1, clickCount: 1 });
  await cmd(tabId, "Input.dispatchMouseEvent", { type: "mouseReleased", ...base, buttons: 0, clickCount: 1 });
  await settle();
  // If the click opened a confirm()/prompt() we auto-cancelled, the action did NOT do what the page
  // asked — report failure with the dialog details rather than a misleading ok:true.
  const dlg = dialogSince(tabId, before);
  if (dlg) return { ok: false, error: "a " + dlg.type + " dialog was auto-cancelled", dialog: dlg, trusted: true };
  return { ok: true, trusted: true };
}

export async function hover(tabId, x, y) {
  await ensureAttached(tabId);
  await cmd(tabId, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  return { ok: true, trusted: true };
}

// Select-all uses Ctrl+A on Windows/Linux but Meta(Cmd)+A on macOS — the wrong modifier silently
// selects nothing and typing APPENDS instead of replacing. Resolve the platform once and cache it.
let platInfoP = null;
async function selectAllModifiers() {
  platInfoP = platInfoP || chrome.runtime.getPlatformInfo();
  return (await platInfoP).os === "mac" ? 4 /* Meta */ : 2 /* Control */;
}

export async function typeText(tabId, text) {
  await ensureAttached(tabId);
  const before = dialogSeq(tabId);
  // Select existing content first (Ctrl/Cmd+A) so insertText REPLACES it instead of appending —
  // otherwise typing into a field that already holds "old" produces "oldnew".
  const a = { code: "KeyA", key: "a", windowsVirtualKeyCode: 65, modifiers: await selectAllModifiers() };
  await cmd(tabId, "Input.dispatchKeyEvent", { type: "rawKeyDown", ...a });
  await cmd(tabId, "Input.dispatchKeyEvent", { type: "keyUp", ...a });
  await cmd(tabId, "Input.insertText", { text: String(text) });   // trusted text entry, replaces selection
  await settle();
  const dlg = dialogSince(tabId, before);
  if (dlg) return { ok: false, error: "a " + dlg.type + " dialog was auto-cancelled", dialog: dlg, trusted: true };
  return { ok: true, trusted: true };
}

const KEYS = {
  Enter: { code: "Enter", vk: 13 }, Tab: { code: "Tab", vk: 9 }, Escape: { code: "Escape", vk: 27 },
  Backspace: { code: "Backspace", vk: 8 }, Delete: { code: "Delete", vk: 46 },
  ArrowDown: { code: "ArrowDown", vk: 40 }, ArrowUp: { code: "ArrowUp", vk: 38 },
  ArrowLeft: { code: "ArrowLeft", vk: 37 }, ArrowRight: { code: "ArrowRight", vk: 39 },
  PageDown: { code: "PageDown", vk: 34 }, PageUp: { code: "PageUp", vk: 33 },
  Home: { code: "Home", vk: 36 }, End: { code: "End", vk: 35 },
};

export async function key(tabId, keyStr) {
  await ensureAttached(tabId);
  const before = dialogSeq(tabId);
  const parts = String(keyStr).split("+");
  const k = parts.pop();
  const mods = parts.map((p) => p.toLowerCase());
  let m = 0;
  if (mods.includes("alt")) m |= 1;
  if (mods.includes("control") || mods.includes("ctrl")) m |= 2;
  if (mods.includes("meta") || mods.includes("cmd")) m |= 4;
  if (mods.includes("shift")) m |= 8;
  const known = KEYS[k];
  const info = known
    ? { key: k, code: known.code, windowsVirtualKeyCode: known.vk }
    : (k.length === 1
        ? { key: k, code: "Key" + k.toUpperCase(), windowsVirtualKeyCode: k.toUpperCase().charCodeAt(0) }
        : { key: k, code: k });
  // A single char types text ONLY when no Alt/Ctrl/Meta is held — Shift IS allowed (Shift+A -> "A").
  // The old `m < 2` test wrongly made Alt+A printable (bit 1) and Shift+A non-printable (bit 8).
  const printable = k.length === 1 && !(m & 1) && !(m & 2) && !(m & 4);
  await cmd(tabId, "Input.dispatchKeyEvent", { type: printable ? "keyDown" : "rawKeyDown",
    modifiers: m, ...info, ...(printable ? { text: k } : {}) });
  await cmd(tabId, "Input.dispatchKeyEvent", { type: "keyUp", modifiers: m, ...info });
  await settle();
  const dlg = dialogSince(tabId, before);
  if (dlg) return { ok: false, error: "a " + dlg.type + " dialog was auto-cancelled", dialog: dlg, trusted: true };
  return { ok: true, trusted: true };
}
