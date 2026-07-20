// Shared message protocol between the extension and the multiplexed local broker. The extension
// connects directly to loopback (no native host). Hermes plugin processes connect as separate
// authenticated agent clients, so several profiles/sessions can share several Chrome instances.
//
// Direction legend:
//   ext  -> agent : requests/answers the extension originates (pairing, profile choice, chat)
//   agent -> ext  : commands the agent originates (navigate, snapshot, click, ...)

// Where the local agent's bridge listens. Overridable in settings if the user changed the port.
export const DEFAULT_BRIDGE_URL = "ws://127.0.0.1:8765";

// v3: role-bound mutual auth + stable browserId + exact profile/session/tab routing.
export const PROTOCOL_VERSION = 3;

// Direct-connection flow: the extension opens a WebSocket to the local agent. The agent's bridge
// authenticates the caller by Origin (only this extension's chrome-extension:// origin is accepted;
// the browser sets Origin and extensions cannot spoof it, so a malicious web page is rejected).

// Messages the extension sends toward the agent (over the bridge).
export const OUT = {
  HELLO: "hello",                 // { role:"browser", browserId, browserName, proof, nonce }
  ACTION_RESULT: "action_result", // { id, ok, data?, error? }
  BINDING_SYNC: "binding_sync",   // { bindings:[{profileId,sessionId,tabIds,activeTabId}] }
  BINDING_UPDATE: "binding_update",
  BINDING_REMOVE: "binding_remove",
  EVENT: "event",                 // { name, ... } page/agent lifecycle notifications
  BYE: "bye",
};

// Messages the agent sends toward the extension (over the bridge).
export const IN = {
  CHALLENGE: "challenge",         // { nonce } — prove you know the pairing code (mutual auth)
  PAIRED: "paired",               // { ok, browserId, browserName, proof, brokerState }
  PAIR_DENIED: "pair_denied",     // { reason }
  BROKER_STATE: "broker_state",   // { data:{browsers,agentProfiles,...} }
  BINDING_REVOKED: "binding_revoked", // another Chrome profile explicitly claimed this scope
  ACTION: "action",               // { id, scope, targetTabId, action:{ kind, ...args } }
  PING: "ping",                   // { id }
};

// Action kinds the agent may request. Kept small and explicit so the store review and
// the user both see exactly what the tool can do.
export const ACTION = {
  NAVIGATE: "navigate",           // { url }
  SNAPSHOT: "snapshot",           // { maxChars? } -> accessibility tree with ref ids
  READ_TEXT: "read_text",         // { maxChars? } -> visible text
  CLICK: "click",                 // { ref }
  TYPE: "type",                   // { ref, text, submit? }
  SCROLL: "scroll",               // { ref?, dy?, to? }  to = "top"|"bottom"
  SCREENSHOT: "screenshot",       // {} -> data url (visible tab)
  CURRENT_URL: "current_url",     // {}
  WAIT: "wait",                   // { ms }
  // --- human-like extras ---
  HOVER: "hover",                 // { ref } — reveal menus/tooltips
  KEY: "key",                     // { key, ref? } — "Enter","Escape","Tab","ArrowDown","PageDown","Control+a"
  SELECT_OPTION: "select_option", // { ref, value?, label? } — choose in a <select>
  DRAG: "drag",                   // { from, to } — drag one element onto another
  FIND: "find",                   // { text } — find text on the page and scroll to it
  BACK: "back", FORWARD: "forward", RELOAD: "reload", // history
  NEW_TAB: "new_tab",             // { url? }
  LIST_TABS: "list_tabs",         // {}
  SWITCH_TAB: "switch_tab",       // { index }
  CLOSE_TAB: "close_tab",         // { index? }
};

// storage.local keys
export const STORE = {
  IDENTITY: "identity",           // { browserId, browserName }
  PAIRING: "pairing",             // { pairedAt }
  SETTINGS: "settings",           // { bridgeUrl, pairingCode, trustedInput, showOverlay }
  BINDINGS: "bindings",           // scopeKey -> { profileId, sessionId, tabIds, activeTabId }
  SELECTED_SCOPE: "selectedScope",// { profileId, sessionId }
};

export const DEFAULT_SETTINGS = {
  showOverlay: true,
  trustedInput: false,  // OFF by default: synthetic in-page events, no debugger banner. When ON (the
                        // manifest-declared `debugger` permission is then attached) clicks/keys become real
                        // OS-level events (isTrusted) via CDP and native dialogs are auto-handled.
};
