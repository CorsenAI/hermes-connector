// Functions injected into the page (ISOLATED world) via chrome.scripting.executeScript({ func }).
// The isolated world has full DOM access but its OWN copy of globals, so a hostile page can't
// clobber the helpers these functions rely on. Each MUST be fully self-contained: it runs in the
// page, cannot see module scope, and receives everything through its arguments. Returns are JSON.
//
// Ref ids (ref_N) are stable handles the agent uses to point at elements across calls. They are
// stored on window under a namespaced key so a later click/type can resolve the same live node.
//
// TWO policies are duplicated inline in several functions below because injected functions cannot
// share module scope. Keep them IDENTICAL when editing:
//   VIS(el) — authoritative visibility: element.checkVisibility with opacity + content-visibility
//             + visibility, so display:none / visibility:hidden / opacity:0 (incl. via an ancestor)
//             / a closed <details> / content-visibility:hidden are ALL treated as hidden. Hidden
//             text/nodes must never leave the page.
//   SU(u)  — redact secret-bearing URL parts (tokens, signatures, session ids, SAML, JWTs, AWS
//            sig, high-entropy values) from any href / page url before it reaches the agent.

// Build a compact accessibility snapshot: role + accessible name + a stable [ref_N] per element.
// Sensitive fields (passwords, one-time codes, card numbers) are redacted before they ever leave
// the page — the agent never sees their values.
export function buildSnapshot(maxChars) {
  const S = (window.__agentBridge = window.__agentBridge || {});
  S.counter = S.counter || 0;
  S.byId = S.byId || {};                 // ref -> WeakRef(el)
  S.byEl = S.byEl || new WeakMap();      // el -> ref

  // authoritative visibility (see file header). Includes both the standardized option names and the
  // older Chrome experimental aliases so it works across Chrome versions.
  const VIS = (el) => {
    try {
      if (el.checkVisibility) return el.checkVisibility({
        opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true,
        checkOpacity: true, checkVisibilityCSS: true });
    } catch (_) {}
    const s = getComputedStyle(el);
    return !(s.display === "none" || s.visibility === "hidden" || s.opacity === "0");
  };
  const onScreen = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 &&
      r.top < innerHeight && r.bottom > 0 && r.left < innerWidth && r.right > 0;
  };

  const SENSITIVE_AC = ["current-password", "new-password", "one-time-code",
    "cc-number", "cc-csc", "cc-exp", "cc-exp-month", "cc-exp-year"];
  const isSensitive = (el) => {
    const t = (el.getAttribute("type") || "").toLowerCase();
    if (t === "password" || t === "hidden") return true;
    const ac = (el.getAttribute("autocomplete") || "").toLowerCase();
    return SENSITIVE_AC.some((k) => ac.includes(k));
  };
  const roleOf = (el) => {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const map = { A: "link", BUTTON: "button", SELECT: "combobox", TEXTAREA: "textbox",
      H1: "heading", H2: "heading", H3: "heading", H4: "heading", H5: "heading", H6: "heading",
      NAV: "navigation", IMG: "image" };
    if (el.tagName === "INPUT") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (t === "checkbox" || t === "radio") return t;
      if (t === "submit" || t === "button") return "button";
      return "textbox";
    }
    return map[el.tagName] || "generic";
  };
  // Accessible name WITHOUT el.textContent: textContent happily includes display:none subtrees,
  // <style> bodies and prefetched secrets. Direct text nodes first (cheap, covers most elements),
  // else a small bounded walk over VISIBLE descendants only.
  const visText = (el) => {
    let out = "", seen = 0, n;
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(x) {
        if (++seen > 80) return NodeFilter.FILTER_REJECT;
        if (x.nodeType === 1) {
          if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"].includes(x.tagName)) return NodeFilter.FILTER_REJECT;
          if (x.getAttribute && x.getAttribute("aria-hidden") === "true") return NodeFilter.FILTER_REJECT;
          if (!VIS(x)) return NodeFilter.FILTER_REJECT;   // hidden subtree: never read it
          return NodeFilter.FILTER_SKIP;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    while ((n = tw.nextNode())) { out += n.nodeValue + " "; if (out.length >= 140) break; }
    return out;
  };
  // `deep` gates the visText walk: only interactive/named-role elements deserve descendant text
  // (an <a><span>label</span></a>) — running it on every generic wrapper div would multiply the
  // walk cost by the page size, and a container swallowing descendant text isn't its name anyway.
  const nameOf = (el, deep) => {
    if (isSensitive(el)) return "[redacted]";
    const lbl = el.getAttribute("aria-label") || el.getAttribute("placeholder") ||
      el.getAttribute("title") || el.getAttribute("alt");
    if (lbl) return lbl.trim().slice(0, 100);
    if (el.tagName === "INPUT" && (el.getAttribute("type") || "") === "submit") return el.value;
    const txt = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ").trim();
    return (txt || (deep ? visText(el) : "")).replace(/\s+/g, " ").trim().slice(0, 100);
  };
  const interactive = (el) => {
    if (["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "SUMMARY"].includes(el.tagName)) return true;
    if (el.getAttribute("onclick") != null || el.getAttribute("tabindex") != null) return true;
    const r = el.getAttribute("role");
    return r === "button" || r === "link" || el.getAttribute("contenteditable") === "true";
  };
  const refFor = (el) => {
    const existing = S.byEl.get(el);
    if (existing && S.byId[existing] && S.byId[existing].deref() === el) return existing;
    const ref = "ref_" + ++S.counter;
    S.byId[ref] = new WeakRef(el);
    S.byEl.set(el, ref);
    return ref;
  };

  // Redact secret-bearing URL parts before ANY url leaves the page (see file header). Keyword
  // denylist for named secrets + a high-entropy VALUE backstop for oddly-named ones. Overmatching a
  // harmless param is acceptable; leaking one credential is not. Non-secret readable params (q,
  // page, user, ids) are preserved so the agent keeps useful context.
  const SU = (u) => {
    try {
      const url = new URL(u, location.href);
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
      return url.href.slice(0, 400);
    } catch (_) { return String(u).slice(0, 200); }
  };

  const lines = [];
  const limit = Math.min(Math.max(1, maxChars || 20000), 100000);   // hard ceiling: never unbounded
  const MAX_DEPTH = 200;   // stop descending into pathologically deep DOMs (real pages are shallow)
  let count = 0, visited = 0;
  // Iterative DFS (explicit stack): a hostile page can nest elements thousands deep, and a recursive
  // walk would blow the JS call stack before any node cap kicked in.
  const stack = [{ el: document.body, depth: 0 }];
  while (stack.length) {
    const { el, depth } = stack.pop();
    // Bound BOTH emitted elements AND total nodes visited: a page with hundreds of thousands of
    // hidden nodes but few emitted ones could otherwise keep us calling getComputedStyle forever.
    if (count >= 8000 || ++visited > 25000) break;
    if (["SCRIPT", "STYLE", "META", "LINK", "NOSCRIPT", "TITLE", "TEMPLATE"].includes(el.tagName)) continue;
    if (el.getAttribute && el.getAttribute("aria-hidden") === "true") continue;
    // O(1) subtree prune (own computed style, no ancestor walk): display:none / opacity:0 /
    // content-visibility:hidden all hide the ENTIRE subtree and cannot be undone by a descendant,
    // so we skip this element AND never descend. This is the perf guard that also keeps the
    // authoritative VIS() call below cheap (it only runs on not-pruned candidates).
    let cs = null; try { cs = getComputedStyle(el); } catch (_) {}
    if (cs && (cs.display === "none" || cs.opacity === "0" || cs.contentVisibility === "hidden")) continue;
    let emitted = false;
    // Emission gate = authoritative VIS() (catches visibility:hidden, a closed <details>, and any
    // ancestor-driven case the O(1) prune above didn't) AND on-screen.
    if (VIS(el) && onScreen(el)) {
      const role = roleOf(el);
      const inter = interactive(el);
      const name = nameOf(el, inter || role !== "generic");
      const keep = inter || (role !== "generic") || name.length >= 2;
      if (keep) {
        count++;
        const ref = refFor(el);
        let line = "  ".repeat(Math.min(depth, 12)) + role;
        if (name) line += ' "' + name.replace(/"/g, '\\"') + '"';
        line += " [" + ref + "]";
        const href = el.getAttribute && el.getAttribute("href");
        if (href) line += ' href="' + SU(href) + '"';
        lines.push(line);
        emitted = true;
      }
    }
    if (depth < MAX_DEPTH) {
      const kids = el.children || [];
      for (let i = kids.length - 1; i >= 0; i--) stack.push({ el: kids[i], depth: emitted ? depth + 1 : depth });
    }
  }

  // prune dead refs
  for (const k of Object.keys(S.byId)) if (!S.byId[k].deref()) delete S.byId[k];

  let out = lines.join("\n");
  let truncated = false;
  if (out.length > limit) { out = out.slice(0, out.lastIndexOf("\n", limit)); truncated = true; }
  return { url: SU(location.href), title: document.title, content: out, truncated,
    viewport: { w: innerWidth, h: innerHeight } };
}

// NOTE: each exported function below is injected on its OWN via chrome.scripting.executeScript,
// so it cannot reference any other module-scope helper. Every one that resolves a ref defines the
// resolver inline as `RR`.

// Click a ref. Refuses a detached or disabled element (a synthetic el.click() on a disabled button
// fires no default action but would otherwise return a misleading ok:true).
export function clickRef(ref) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  const el = RR(ref);
  if (!el) return { ok: false, error: "ref not found: " + ref };
  if (!el.isConnected) return { ok: false, error: "element no longer in the page: " + ref };
  if (el.disabled) return { ok: false, error: "element is disabled: " + ref };
  el.scrollIntoView({ block: "center", inline: "center" });
  el.focus && el.focus();
  el.click();
  return { ok: true };
}

// Type into a ref. Refuses anything that is not a real, enabled, writable text field — a checkbox,
// button, disabled or readonly input, or detached node would otherwise have its .value overwritten
// and return a misleading ok:true without the intended effect.
export function typeRef(ref, text, submit) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  const el = RR(ref);
  if (!el) return { ok: false, error: "ref not found: " + ref };
  if (!el.isConnected) return { ok: false, error: "element no longer in the page: " + ref };
  const tag = el.tagName;
  const NON_TEXT = ["button", "submit", "checkbox", "radio", "file", "image", "reset", "range", "color", "hidden"];
  const type = (el.getAttribute && (el.getAttribute("type") || "text").toLowerCase()) || "text";
  if (el.isContentEditable) {
    if (el.getAttribute("contenteditable") === "false") return { ok: false, error: "not editable: " + ref };
    el.scrollIntoView({ block: "center" });
    el.focus();
    // Rich editors (Gmail, Notion, Slack, Discord, LinkedIn…): an <input> value setter throws
    // "Illegal invocation" on a <div>. Use the editing API + an InputEvent instead.
    try { document.execCommand("selectAll", false, null); document.execCommand("insertText", false, text); }
    catch (_) { el.textContent = text; }
    el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
  } else if (tag === "TEXTAREA" || (tag === "INPUT" && !NON_TEXT.includes(type))) {
    if (el.disabled) return { ok: false, error: "field is disabled: " + ref };
    if (el.readOnly) return { ok: false, error: "field is read-only: " + ref };
    el.scrollIntoView({ block: "center" });
    el.focus && el.focus();
    const proto = tag === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value");
    if (setter && setter.set) setter.set.call(el, text); else el.value = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  } else {
    return { ok: false, error: "not a text field (use click for checkboxes/buttons): " + ref };
  }
  if (submit) {
    const form = el.form;
    if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
    else el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }
  return { ok: true };
}

export function scrollPage(ref, dy, to) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  if (to === "bottom") { window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); return { ok: true, to }; }
  if (to === "top") { window.scrollTo({ top: 0, behavior: "smooth" }); return { ok: true, to }; }
  if (ref) {
    const el = RR(ref);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); return { ok: true }; }
    return { ok: false, error: "ref not found: " + ref };
  }
  window.scrollBy({ top: dy || window.innerHeight * 0.8, behavior: "smooth" });
  return { ok: true };
}

// Hover: reveal dropdown menus / tooltips that only appear on mouseover.
export function hoverRef(ref) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  const el = RR(ref);
  if (!el) return { ok: false, error: "ref not found: " + ref };
  if (!el.isConnected) return { ok: false, error: "element no longer in the page: " + ref };
  el.scrollIntoView({ block: "center" });
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  for (const type of ["pointerover", "mouseover", "pointerenter", "mouseenter", "mousemove"]) {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  }
  // synthetic events don't trigger the CSS :hover pseudo-class, so pure-CSS menus may not open.
  return { ok: true, synthetic: true };
}

// Press a key or combo ("Enter", "Escape", "Tab", "ArrowDown", "PageDown", "Control+a").
// Dispatches keyboard events to the target (a ref, else the focused element), and for
// navigation/scroll keys also performs the native scroll (synthetic key events don't scroll).
// If a ref is given but cannot be resolved, ABORT — never silently retarget document.body, which
// would send the key to the wrong place and return a misleading ok:true.
export function pressKey(key, ref) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  let target = null;
  if (ref) {
    target = RR(ref);
    if (!target) return { ok: false, error: "ref not found: " + ref };
    if (!target.isConnected) return { ok: false, error: "element no longer in the page: " + ref };
  } else {
    target = document.activeElement || document.body;
  }
  const parts = String(key).split("+");
  const k = parts.pop();
  const mods = parts.map((p) => p.toLowerCase());
  const code = k.length === 1 ? "Key" + k.toUpperCase() : k;
  const opt = { key: k, code, bubbles: true, cancelable: true,
    ctrlKey: mods.includes("control") || mods.includes("ctrl"),
    shiftKey: mods.includes("shift"), altKey: mods.includes("alt"),
    metaKey: mods.includes("meta") || mods.includes("cmd") };
  target.focus && target.focus();
  target.dispatchEvent(new KeyboardEvent("keydown", opt));
  target.dispatchEvent(new KeyboardEvent("keyup", opt));
  const H = window.innerHeight;
  const scroll = { PageDown: H * 0.9, PageUp: -H * 0.9, ArrowDown: 80, ArrowUp: -80,
    Home: -1e9, End: 1e9, " ": H * 0.9, Space: H * 0.9 };
  if (k in scroll) window.scrollBy({ top: scroll[k], behavior: "smooth" });
  // synthetic key events don't drive native behaviors (real Tab focus move, browser shortcuts);
  // flag it so the agent knows this was best-effort, not a guaranteed native keypress.
  return { ok: true, key, synthetic: true };
}

// Choose an option in a native <select>, by value or by visible label (loose match as fallback).
export function selectOption(ref, value, label) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  const el = RR(ref);
  if (!el) return { ok: false, error: "ref not found: " + ref };
  if (!el.isConnected) return { ok: false, error: "element no longer in the page: " + ref };
  if (el.tagName !== "SELECT") return { ok: false, error: "not a <select>: " + ref };
  if (el.disabled) return { ok: false, error: "select is disabled: " + ref };
  let m = null;
  for (const o of el.options) {
    if (value != null && o.value === value) { m = o; break; }
    if (label != null && o.textContent.trim() === String(label).trim()) { m = o; break; }
  }
  if (!m) {
    const needle = String(value != null ? value : label || "").toLowerCase();
    for (const o of el.options) if (o.textContent.trim().toLowerCase().includes(needle)) { m = o; break; }
  }
  if (!m) return { ok: false, error: "option not found" };
  el.value = m.value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true, selected: m.textContent.trim(), value: m.value };
}

// Best-effort HTML5 drag-and-drop from one element onto another.
export function dragRefs(from, to) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  const a = RR(from), b = RR(to);
  if (!a || !b) return { ok: false, error: "ref not found (from/to)" };
  if (!a.isConnected || !b.isConnected) return { ok: false, error: "element no longer in the page" };
  const dt = new DataTransfer();
  const rb = b.getBoundingClientRect(), ra = a.getBoundingClientRect();
  const fire = (el, type, x, y) => el.dispatchEvent(
    new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
  fire(a, "dragstart", ra.left + ra.width / 2, ra.top + ra.height / 2);
  fire(b, "dragenter", rb.left + rb.width / 2, rb.top + rb.height / 2);
  fire(b, "dragover", rb.left + rb.width / 2, rb.top + rb.height / 2);
  fire(b, "drop", rb.left + rb.width / 2, rb.top + rb.height / 2);
  fire(a, "dragend", rb.left + rb.width / 2, rb.top + rb.height / 2);
  // HTML5 drag events only; pointer/mouse-based or React-DnD widgets may ignore this. Best-effort.
  return { ok: true, synthetic: true };
}

// Find text on the page (case-insensitive), scroll to the first match, report how many.
// VISIBLE text only (see file header VIS): matching hidden content would leak text the user cannot
// see and scroll to nothing. Node budget + match cap so a pathological DOM can't hang the page.
export function findText(text) {
  const q = String(text || "").trim().toLowerCase();
  if (q.length < 2) return { ok: false, error: "search text too short" };
  const VIS = (el) => {
    try {
      if (el.checkVisibility) return el.checkVisibility({
        opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true,
        checkOpacity: true, checkVisibilityCSS: true });
    } catch (_) {}
    const s = getComputedStyle(el);
    return !(s.display === "none" || s.visibility === "hidden" || s.opacity === "0");
  };
  const skip = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, HEAD: 1 };
  let budget = 40000;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (--budget < 0) return NodeFilter.FILTER_REJECT;
      const p = n.parentElement;
      if (!p || skip[p.tagName] || !n.nodeValue) return NodeFilter.FILTER_REJECT;
      if (p.closest && p.closest('[aria-hidden="true"]')) return NodeFilter.FILTER_REJECT;
      if (!VIS(p)) return NodeFilter.FILTER_REJECT;   // hidden text: neither search nor count it
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let n, hits = 0, first = null;
  while ((n = walker.nextNode()) && hits < 500) {
    if (n.nodeValue.toLowerCase().includes(q)) { hits++; if (!first) first = n.parentElement; }
  }
  if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
  return { ok: true, matches: hits, scrolledToFirst: !!first, bounded: budget < 0 || hits >= 500 };
}

export function readText(maxChars) {
  const cap = Math.min(Math.max(1, maxChars || 20000), 100000);   // hard ceiling: never unbounded
  const VIS = (el) => {
    try {
      if (el.checkVisibility) return el.checkVisibility({
        opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true,
        checkOpacity: true, checkVisibilityCSS: true });
    } catch (_) {}
    const s = getComputedStyle(el);
    return !(s.display === "none" || s.visibility === "hidden" || s.opacity === "0");
  };
  // Redact secret-bearing URL parts (see file header SU). Keep IDENTICAL to buildSnapshot's SU.
  const SU = (u) => {
    try {
      const url = new URL(u, location.href);
      const KEY = /(^|[_-])(token|access[_-]?token|refresh[_-]?token|id[_-]?token|auth|authorization|code|auth[_-]?code|session|session[_-]?id|sid|key|api[_-]?key|secret|client[_-]?secret|password|pwd|passwd|signature|sig|jwt|bearer|otp|pin|csrf|xsrf|state|nonce|ticket|credential|assertion|saml[_-]?response|saml[_-]?request|x[_-]?amz[_-]?signature|x[_-]?amz[_-]?credential|x[_-]?amz[_-]?security[_-]?token)($|[_-])/i;
      const looksSecret = (v) =>
        !!v && (
          /^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}$/.test(v) ||
          /^[0-9a-f]{32,}$/i.test(v) ||
          (/^[A-Za-z0-9_\-+/]{40,}={0,2}$/.test(v) && /[0-9]/.test(v) && /[A-Za-z]/.test(v)));
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
      return url.href.slice(0, 400);
    } catch (_) { return String(u).slice(0, 200); }
  };
  // Walk text nodes; a HIDDEN parent (display:none, visibility:hidden, opacity:0, aria-hidden,
  // <template>, closed <details>) rejects the text so it never leaves the page. Streams up to the
  // cap instead of building the whole page's innerText (OOM on infinite scroll); a fixed node
  // budget bounds total work on pathological DOMs. Visibility is tested on each text node's PARENT
  // (SHOW_TEXT only) so checkVisibility's ancestor walk isn't repeated for every element.
  const skip = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, HEAD: 1, TITLE: 1, META: 1, LINK: 1 };
  const root = document.body || document.documentElement;
  let budget = 40000;
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (--budget < 0) return NodeFilter.FILTER_REJECT;
      const p = n.parentElement;
      if (!p || skip[p.tagName] || !n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      if (p.closest && p.closest('[aria-hidden="true"]')) return NodeFilter.FILTER_REJECT;
      if (!VIS(p)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const parts = []; let len = 0, node;
  while ((node = w.nextNode())) {
    const s = node.nodeValue.trim();
    parts.push(s); len += s.length + 1;
    if (len >= cap) break;
  }
  const t = parts.join(" ").replace(/\n{3,}/g, "\n\n");
  return { url: SU(location.href), text: t.slice(0, cap), truncated: len >= cap || budget < 0 };
}

// For CDP "trusted input" mode: return the viewport-center coordinates of a ref (after scrolling it
// into view) so the background can dispatch a real OS-level mouse event there. Refuses a detached
// or actually-hidden element — dispatching a real click at the coords of an invisible element would
// hit whatever is painted there instead.
export function refRect(ref) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  const el = RR(ref);
  if (!el) return { ok: false, error: "ref not found: " + ref };
  if (!el.isConnected) return { ok: false, error: "element no longer in the page: " + ref };
  const VIS = (x) => {
    try {
      if (x.checkVisibility) return x.checkVisibility({
        opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true,
        checkOpacity: true, checkVisibilityCSS: true });
    } catch (_) {}
    const s = getComputedStyle(x);
    return !(s.display === "none" || s.visibility === "hidden" || s.opacity === "0");
  };
  if (!VIS(el)) return { ok: false, error: "element is not visible: " + ref };
  el.scrollIntoView({ block: "center", inline: "center" });
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return { ok: false, error: "element has no box: " + ref };
  return { ok: true, x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
}

// Focus a ref before CDP types into it (so the trusted keystrokes land in the right field).
// With mustEdit, refuse anything that isn't an enabled, writable text field: focusing a button and
// then sending Ctrl+A + insertText would select the page and type into the void.
export function focusRef(ref, mustEdit) {
  const RR = (r) => { const S = window.__agentBridge || {}; const w = S.byId && S.byId[r]; return (w && w.deref()) || null; };
  const el = RR(ref);
  if (!el) return { ok: false, error: "ref not found: " + ref };
  if (!el.isConnected) return { ok: false, error: "element no longer in the page: " + ref };
  if (mustEdit) {
    const NON_TEXT = ["button", "submit", "checkbox", "radio", "file", "image", "reset", "range", "color", "hidden"];
    const tag = el.tagName;
    const editable = (el.isContentEditable && el.getAttribute("contenteditable") !== "false") ||
      (tag === "TEXTAREA" && !el.disabled && !el.readOnly) ||
      (tag === "INPUT" && !el.disabled && !el.readOnly &&
        !NON_TEXT.includes((el.getAttribute("type") || "text").toLowerCase()));
    if (!editable) return { ok: false, error: "not an editable text field: " + ref };
  }
  el.scrollIntoView({ block: "center" });
  el.focus && el.focus();
  return { ok: true };
}

// Minimal on-page affordance so the user always sees when the agent is acting.
export function setOverlay(active) {
  const ID = "__agent_bridge_overlay__";
  const existing = document.getElementById(ID);
  if (!active) { existing && existing.remove(); return; }
  if (existing) return;
  const box = document.createElement("div");
  box.id = ID;
  box.setAttribute("aria-hidden", "true");
  box.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483646;" +
    "box-shadow:inset 0 0 0 3px rgba(80,140,255,.9), inset 0 0 24px rgba(80,140,255,.45);" +
    "transition:opacity .2s;";
  document.documentElement.appendChild(box);
}
