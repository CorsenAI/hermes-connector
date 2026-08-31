// Connector controls around the real Hermes dashboard. The extension owns only
// pairing and browser-tab bindings; Hermes owns chat, profiles, sessions, models,
// personality, and the agent turn itself.

import { listDashboardSessions, makeDashboardUrl, normalizeLoopbackUrl } from "./dashboard-api.js";

const DEFAULT_URL = "http://127.0.0.1:9119/";
const DEFAULT_BRIDGE = "ws://127.0.0.1:8766";

const dot = document.getElementById("dot");
const statusEl = document.getElementById("status");
const frame = document.getElementById("hermes");
const hint = document.getElementById("hint");
const cfg = document.getElementById("cfg");
const scopeSection = document.getElementById("scope");
const sessionSelect = document.getElementById("sessionSelect");
const attachActiveButton = document.getElementById("attachActive");
const manageTabsButton = document.getElementById("manageTabs");
const attachedTabs = document.getElementById("attachedTabs");
const tabPicker = document.getElementById("tabPicker");
const privacyButton = document.getElementById("privacyButton");
const privacyPopover = document.getElementById("privacyPopover");
const scopeInfo = document.getElementById("scopeInfo");
const setupNotice = document.getElementById("setupNotice");
const setupTitle = document.getElementById("setupTitle");
const companionDetection = document.getElementById("companionDetection");
const checkCompanionButton = document.getElementById("checkCompanion");
const downloadCompanion = document.getElementById("downloadCompanion");
const setupStepDownload = document.getElementById("setupStepDownload");
const setupStepInstall = document.getElementById("setupStepInstall");
const setupStepRestart = document.getElementById("setupStepRestart");
const setupStepPair = document.getElementById("setupStepPair");
const openSetupSettings = document.getElementById("openSetupSettings");
const upgradeNotice = document.getElementById("upgradeNotice");
const customPortUpgrade = document.getElementById("customPortUpgrade");
const dismissUpgradeNotice = document.getElementById("dismissUpgradeNotice");

let state = {};
let selectedScope = null;
let pickerOpen = false;
let platformOS = "unknown";
let tabsRenderGeneration = 0;
let sessionsLoadGeneration = 0;
let scopeSelectionGeneration = 0;
let dashboardGeneration = 0;
let scopePersistence = Promise.resolve();
let targetReadiness = null;

const setDot = (kind) => { dot.className = `dot ${kind}`; };
const keyFor = (scope) => scope ? `${scope.profileId}\u001f${scope.sessionId}` : "";
const copyScope = (scope) => scope ? Object.freeze({
  profileId: String(scope.profileId || ""),
  sessionId: String(scope.sessionId || ""),
}) : null;
const scopeIsCurrent = (scope) => !!scope && keyFor(scope) === keyFor(selectedScope);

function selectedBinding() {
  return selectedScope && state.bindings ? state.bindings[keyFor(selectedScope)] || null : null;
}

function selectedTargetReady() {
  const binding = selectedBinding();
  return !!binding && Number.isInteger(binding.activeTabId) &&
    Array.isArray(binding.tabIds) && binding.tabIds.includes(binding.activeTabId) &&
    !!targetReadiness && targetReadiness.scopeKey === keyFor(selectedScope) &&
    targetReadiness.tabId === binding.activeTabId && targetReadiness.controllable === true;
}

function selectedAgentReady() {
  const profiles = (state.brokerState && state.brokerState.agentProfiles) || [];
  return !!state.paired && !!selectedScope && profiles.includes(selectedScope.profileId);
}

function setupRequired() {
  return !String((state.settings && state.settings.pairingCode) || "").trim();
}

function persistScope(scope) {
  const operation = scopePersistence.then(async () => {
    if (!scope) {
      await chrome.storage.local.remove("selectedScope");
      return { ok: true };
    }
    return runtime({ cmd: "selectScope", ...scope });
  });
  scopePersistence = operation.catch(() => {});
  return operation;
}

function renderConnectionState(message = "", dotKind = "") {
  if (message) {
    if (dotKind) setDot(dotKind);
    statusEl.textContent = message;
    return;
  }
  if (setupRequired()) {
    setDot(state.companionDetected ? "warn" : "off");
    statusEl.textContent = state.companionDetected
      ? "companion detected — enter pairing code"
      : "setup required";
    return;
  }
  if (!state.paired) {
    setDot("off");
    statusEl.textContent = "Connector offline";
    return;
  }
  if (state.dashboardAvailable === false) {
    setDot("warn");
    statusEl.textContent = "Hermes dashboard unavailable";
    return;
  }
  if (!selectedScope) {
    setDot("warn");
    statusEl.textContent = "Chrome linked · choose a session";
    return;
  }
  if (!selectedAgentReady()) {
    setDot("warn");
    statusEl.textContent = `Chrome linked · start Hermes [${selectedScope.profileId}]`;
    return;
  }
  if (!selectedTargetReady()) {
    setDot("warn");
    const readinessMatchesScope = !!targetReadiness && !!selectedScope &&
      targetReadiness.scopeKey === keyFor(selectedScope);
    statusEl.textContent = readinessMatchesScope
      ? "Hermes linked · target loading"
      : "Hermes linked · attach a target";
    return;
  }
  setDot("on");
  statusEl.textContent = "Ready · Hermes + Chrome";
}

function modalElement() {
  if (cfg.classList.contains("open")) return cfg;
  if (!setupNotice.hidden) return setupNotice;
  if (!upgradeNotice.hidden) return upgradeNotice;
  return null;
}

function focusableElements(element) {
  return [...element.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter((item) => !item.hidden && item.getClientRects().length);
}

function syncModalState() {
  const blocked = !!modalElement();
  frame.inert = blocked;
  scopeSection.inert = blocked;
}

function focusFirst(element) {
  requestAnimationFrame(() => {
    const first = focusableElements(element)[0];
    if (first) first.focus();
  });
}

function positionPopover(element) {
  const bottom = scopeSection.getBoundingClientRect().bottom + 5;
  element.style.top = `${Math.max(38, Math.round(bottom))}px`;
}

function syncNoticeVisibility() {
  const setupWasHidden = setupNotice.hidden;
  const upgradeWasHidden = upgradeNotice.hidden;
  const settingsOpen = cfg.classList.contains("open");
  const needsSetup = setupRequired();
  setupNotice.hidden = settingsOpen || !needsSetup;
  upgradeNotice.hidden = settingsOpen || needsSetup || !state.upgradeNotice;
  customPortUpgrade.hidden = !state.upgradeNotice || !state.upgradeNotice.customBridge;
  syncModalState();
  if (setupWasHidden && !setupNotice.hidden) focusFirst(setupNotice);
  else if (upgradeWasHidden && !upgradeNotice.hidden) focusFirst(upgradeNotice);
  return needsSetup;
}

function renderUpgradeNotice(notice) {
  state.upgradeNotice = notice || null;
  syncNoticeVisibility();
}

function renderSetupNotice(settings) {
  state.settings = { ...(state.settings || {}), ...(settings || {}) };
  return syncNoticeVisibility();
}

function platformLabel() {
  return ({ win: "Windows", mac: "macOS", linux: "Linux", cros: "ChromeOS" })[platformOS] || "this computer";
}

function renderPlatformInstallStep() {
  switch (platformOS) {
    case "win":
      setupStepInstall.textContent =
        "Windows: double-click “Install Hermes Connector.cmd”, then leave the result window open to copy the code.";
      break;
    case "mac":
      setupStepInstall.textContent =
        "macOS: open Terminal in the extracted folder and run ./install.sh; keep Terminal open to copy the code.";
      break;
    case "linux":
      setupStepInstall.textContent =
        "Linux: open a terminal in the extracted folder and run ./install.sh; keep it open to copy the code.";
      break;
    case "cros":
      setupStepInstall.textContent =
        "ChromeOS is not supported by the local Hermes companion; use desktop Chrome on Windows, macOS, or Linux.";
      break;
    default:
      setupStepInstall.textContent =
        "Windows: run “Install Hermes Connector.cmd”. macOS/Linux: run ./install.sh in a terminal.";
  }
}

function renderCompanionDetection(detected, checking = false) {
  state.companionDetected = !!detected;
  checkCompanionButton.disabled = checking;
  checkCompanionButton.textContent = checking ? "Checking…" : "Check again";
  if (checking) {
    setupTitle.textContent = "Checking your local setup…";
    companionDetection.textContent =
      `Looking for the Hermes Connector companion from Chrome on ${platformLabel()}. This never sends data to the internet.`;
    if (!setupNotice.hidden) statusEl.textContent = "checking local companion";
    return;
  }
  if (detected) {
    setupTitle.textContent = "Companion already installed";
    companionDetection.textContent =
      `Good news: the companion is already reachable on ${platformLabel()}. Do not reinstall it for this Chrome profile.`;
    setupStepDownload.textContent = "Use the same private pairing code as your other Chrome profile.";
    setupStepInstall.textContent = "Paste the 64-character code below; it stays only on this computer.";
    setupStepRestart.textContent =
      "If you lost the code, running the installer again is safe and displays the existing code; then restart Hermes.";
    setupStepPair.textContent = "Choose a Hermes session and attach only the tabs it may use.";
    downloadCompanion.textContent = "Installer (only if you lost the code)";
    if (!setupNotice.hidden) statusEl.textContent = "companion detected — enter pairing code";
    return;
  }
  setupTitle.textContent = "Finish setup — about 2 minutes";
  companionDetection.textContent =
    `The companion is not reachable from Chrome on ${platformLabel()}. Start or restart Hermes and check again; install it only if it is still not detected.`;
  setupStepDownload.textContent = "Download and extract the Hermes Connector companion.";
  renderPlatformInstallStep();
  setupStepRestart.textContent = "Restart Hermes, then copy the private pairing code the installer displays.";
  setupStepPair.textContent = "Paste that code below, choose a Hermes session, and attach only the tabs it may use.";
  downloadCompanion.textContent = "Download companion 0.2.3";
  if (!setupNotice.hidden) statusEl.textContent = "setup required — companion not reachable";
}

async function probeCompanion() {
  renderCompanionDetection(false, true);
  const started = await runtime({ cmd: "probeCompanion" });
  if (!started || !started.ok) {
    renderCompanionDetection(false);
    return false;
  }
  const deadline = Date.now() + 2_500;
  do {
    const latest = await runtime({ cmd: "getState" });
    if (latest && latest.companionDetected) {
      renderCompanionDetection(true);
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 125));
  } while (Date.now() < deadline);
  renderCompanionDetection(false);
  return false;
}

async function runtime(message) {
  try {
    return await chrome.runtime.sendMessage(message);
  } catch (error) {
    return { ok: false, error: String(error.message || error) };
  }
}

// Only loopback addresses are allowed (and the manifest CSP enforces it too).
async function getUrl() {
  const stored = await chrome.storage.local.get("hermesUrl");
  return normalizeLoopbackUrl(stored.hermesUrl, DEFAULT_URL) || DEFAULT_URL;
}

async function dashboardUrl(scope = null) {
  return makeDashboardUrl(await getUrl(), scope);
}

async function showDashboard(scope = null, selectionGeneration = null) {
  const generation = ++dashboardGeneration;
  const url = await dashboardUrl(scope);
  if (generation !== dashboardGeneration) return false;
  if (selectionGeneration !== null && selectionGeneration !== scopeSelectionGeneration) return false;
  frame.src = url;
  hint.hidden = true;
  return true;
}

function updateScopeControls() {
  const ready = !!selectedScope;
  attachActiveButton.disabled = !ready || !state.paired;
  manageTabsButton.disabled = !ready;
  if (!ready) {
    scopeInfo.textContent = "Choose the Hermes project/session that should own browser tabs.";
    attachedTabs.replaceChildren();
    tabPicker.replaceChildren();
    tabPicker.hidden = true;
  }
  renderConnectionState();
}

function optionValue(profileId, sessionId) {
  return `${profileId}\u001f${sessionId}`;
}

function parseOption(value) {
  const split = String(value || "").indexOf("\u001f");
  if (split < 1) return null;
  const profileId = value.slice(0, split);
  const sessionId = value.slice(split + 1);
  return profileId && sessionId ? { profileId, sessionId } : null;
}

function sessionLabel(session) {
  const profile = session.profile || "default";
  const title = String(session.title || session.name || session.id || "Untitled session").trim();
  return `[${profile}] ${title}`;
}

async function loadSessions() {
  const generation = ++sessionsLoadGeneration;
  try {
    const url = await getUrl();
    if (generation !== sessionsLoadGeneration) return false;
    const sessions = await listDashboardSessions(url);
    if (generation !== sessionsLoadGeneration) return false;
    const currentScope = copyScope(selectedScope);
    const currentValue = currentScope ? optionValue(currentScope.profileId, currentScope.sessionId) : "";
    const options = [];
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = sessions.length ? "Choose a Hermes session…" : "No Hermes sessions yet";
    options.push(placeholder);
    const seen = new Set();
    for (const session of sessions) {
      if (!session || !session.id) continue;
      const profileId = String(session.profile || "default");
      const sessionId = String(session.id);
      const value = optionValue(profileId, sessionId);
      if (seen.has(value)) continue;
      seen.add(value);
      const option = document.createElement("option");
      option.value = value;
      option.textContent = sessionLabel({ ...session, profile: profileId });
      option.title = sessionId;
      options.push(option);
    }
    if (currentValue && !seen.has(currentValue)) {
      const option = document.createElement("option");
      option.value = currentValue;
      option.textContent = `[${currentScope.profileId}] ${currentScope.sessionId}`;
      options.push(option);
    }
    if (generation !== sessionsLoadGeneration) return false;
    sessionSelect.replaceChildren(...options);
    sessionSelect.value = currentValue;
    hint.hidden = true;
    state.dashboardAvailable = true;
    renderConnectionState();
    return true;
  } catch (_) {
    if (generation !== sessionsLoadGeneration) return false;
    hint.hidden = false;
    state.dashboardAvailable = false;
    renderConnectionState("Hermes dashboard unavailable", state.paired ? "warn" : "off");
    return false;
  }
}

async function selectScope(scope, navigate = true) {
  const generation = ++scopeSelectionGeneration;
  sessionsLoadGeneration++;
  tabsRenderGeneration++;
  const requestedScope = copyScope(scope);
  selectedScope = requestedScope;
  state.selectedScope = requestedScope;
  sessionSelect.value = requestedScope
    ? optionValue(requestedScope.profileId, requestedScope.sessionId)
    : "";
  updateScopeControls();
  if (!requestedScope) {
    const result = await persistScope(null);
    if (generation !== scopeSelectionGeneration) return false;
    if (!result || !result.ok) {
      scopeInfo.textContent = result && result.error ? result.error : "Could not clear this session";
      return false;
    }
    if (navigate) await showDashboard(null, generation);
    if (generation !== scopeSelectionGeneration) return false;
    await renderTabs();
    return true;
  }
  const result = await persistScope(requestedScope);
  if (generation !== scopeSelectionGeneration) return false;
  if (!result || !result.ok) {
    scopeInfo.textContent = result && result.error ? result.error : "Could not select this session";
    return false;
  }
  if (navigate) await showDashboard(requestedScope, generation);
  if (generation !== scopeSelectionGeneration) return false;
  await renderTabs();
  return true;
}

function tabRow(tab, binding, inPicker = false, scope = selectedScope) {
  const actionScope = copyScope(scope);
  const row = document.createElement("div");
  row.className = `tabRow${binding && binding.activeTabId === tab.tabId ? " current" : ""}`;
  const title = document.createElement("span");
  title.className = "tabTitle";
  title.textContent = `${inPicker ? "" : "Target · "}${tab.title || tab.url || `Tab ${tab.tabId}`}`;
  title.title = tab.url || "";
  row.appendChild(title);

  if (inPicker) {
    const button = document.createElement("button");
    button.className = "smallBtn";
    const sameOwner = tab.owner && actionScope &&
      tab.owner.profileId === actionScope.profileId && tab.owner.sessionId === actionScope.sessionId;
    button.textContent = sameOwner ? (tab.owner.active ? "Target" : "Use") : (tab.owner ? "Move here" : "Attach");
    button.disabled = (sameOwner && tab.owner.active) || tab.controllable === false ||
      (!sameOwner && !state.paired);
    if (tab.reason) button.title = tab.reason;
    button.onclick = async () => {
      if (!scopeIsCurrent(actionScope)) {
        scopeInfo.textContent = "Session changed; reopen Tabs before changing access.";
        return;
      }
      const command = sameOwner ? "activateTab" : "attachTab";
      const result = await runtime({ cmd: command, ...actionScope, tabId: tab.tabId });
      if (!result || !result.ok) {
        scopeInfo.textContent = result && result.error ? result.error : "Could not attach tab";
        return;
      }
      await renderTabs();
    };
    row.appendChild(button);
    if (sameOwner) {
      const remove = document.createElement("button");
      remove.className = "smallBtn";
      remove.textContent = "×";
      remove.title = "Revoke this tab from the selected Hermes session";
      remove.setAttribute("aria-label", `Revoke access to ${tab.title || tab.url || "this tab"}`);
      remove.onclick = async () => {
        if (!scopeIsCurrent(actionScope)) {
          scopeInfo.textContent = "Session changed; reopen Tabs before changing access.";
          return;
        }
        const result = await runtime({ cmd: "detachTab", ...actionScope, tabId: tab.tabId });
        if (!result || !result.ok) {
          scopeInfo.textContent = result && result.error ? result.error : "Could not revoke tab access";
          return;
        }
        await renderTabs();
      };
      row.appendChild(remove);
    }
  } else {
    if (binding.activeTabId !== tab.tabId) {
      const use = document.createElement("button");
      use.className = "smallBtn";
      use.textContent = "Use";
      use.onclick = async () => {
        if (!scopeIsCurrent(actionScope)) return;
        const result = await runtime({ cmd: "activateTab", ...actionScope, tabId: tab.tabId });
        if (!result || !result.ok) {
          scopeInfo.textContent = result && result.error ? result.error : "Could not switch browser target";
          return;
        }
        await renderTabs();
      };
      row.appendChild(use);
    }
    const remove = document.createElement("button");
    remove.className = "smallBtn";
    remove.textContent = "×";
    remove.title = "Detach this tab from the Hermes session";
    remove.onclick = async () => {
      if (!scopeIsCurrent(actionScope)) return;
      const result = await runtime({ cmd: "detachTab", ...actionScope, tabId: tab.tabId });
      if (!result || !result.ok) {
        scopeInfo.textContent = result && result.error ? result.error : "Could not revoke tab access";
        return;
      }
      await renderTabs();
    };
    row.appendChild(remove);
  }
  return row;
}

async function renderTabs() {
  const renderGeneration = ++tabsRenderGeneration;
  const renderScope = copyScope(selectedScope);
  targetReadiness = null;
  state.activeChromeTab = null;
  if (!renderScope) {
    updateScopeControls();
    return;
  }
  renderConnectionState();
  const includeAvailable = pickerOpen;
  const result = await runtime({ cmd: "listTabs", ...renderScope, includeAvailable });
  if (renderGeneration !== tabsRenderGeneration || !scopeIsCurrent(renderScope)) return;
  if (!result || !result.ok) {
    scopeInfo.textContent = result && result.error ? result.error : "Could not read Chrome tabs";
    return;
  }
  state.bindings = result.bindings || {};
  const binding = state.bindings[keyFor(renderScope)] || null;
  const byId = new Map((result.tabs || []).map((tab) => [tab.tabId, tab]));
  const current = result.activeTab || null;
  state.activeChromeTab = current;
  let target = binding ? byId.get(binding.activeTabId) : null;
  if (!target && binding) {
    target = current && current.tabId === binding.activeTabId ? current : {
      tabId: binding.activeTabId,
      title: `Attached tab ${binding.activeTabId}`,
      url: "",
      controllable: false,
      reason: "The attached target is still loading.",
    };
  }
  targetReadiness = target ? {
    scopeKey: keyFor(renderScope),
    tabId: target.tabId,
    controllable: target.controllable === true,
  } : null;
  attachedTabs.replaceChildren(...(target ? [tabRow(target, binding, false, renderScope)] : []));

  const usingCurrent = !!current && !!binding && current.tabId === binding.activeTabId;
  const currentOwnedHere = !!current && !!current.owner &&
    current.owner.profileId === renderScope.profileId && current.owner.sessionId === renderScope.sessionId;
  attachActiveButton.textContent = usingCurrent ? "Current target" :
    currentOwnedHere ? "Use current" : current && current.owner ? "Move current" : "Attach current";
  attachActiveButton.disabled = !state.paired || !current || current.controllable === false || usingCurrent;
  attachActiveButton.title = current && current.reason ? current.reason :
    "Attach the Chrome tab you are looking at to this exact Hermes session";

  const attachedCount = binding ? binding.tabIds.length : 0;
  manageTabsButton.textContent = pickerOpen ? "Close" : `Tabs${attachedCount ? ` (${attachedCount})` : ""}`;
  manageTabsButton.setAttribute("aria-expanded", String(pickerOpen));
  if (!target) {
    scopeInfo.textContent = current && current.controllable === false
      ? `No target · ${current.reason || "this Chrome page cannot be controlled"}`
      : "No target · Hermes browser actions are blocked until you attach a tab.";
  } else if (target.controllable === false) {
    scopeInfo.textContent = `Target retained · ${target.reason || "waiting for the attached page"}`;
  } else if (!current || current.tabId === target.tabId) {
    scopeInfo.textContent = selectedAgentReady()
      ? "Hermes is ready on the target shown above."
      : `Target saved · start or restart Hermes profile “${renderScope.profileId}”.`;
  } else if (current.controllable === false) {
    scopeInfo.textContent = `Hermes still targets “${target.title || target.url}” · ${current.reason || "current page cannot be attached"}`;
  } else {
    scopeInfo.textContent = `Hermes still targets “${target.title || target.url}” · press Use current to switch.`;
  }
  scopeInfo.title = scopeInfo.textContent;
  renderConnectionState();

  if (includeAvailable && pickerOpen) {
    positionPopover(tabPicker);
    tabPicker.hidden = false;
    const rows = (result.tabs || []).map((tab) => tabRow(tab, binding, true, renderScope));
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "tabTitle";
      empty.textContent = "No controllable web tabs are open.";
      rows.push(empty);
    }
    tabPicker.replaceChildren(...rows);
  } else {
    tabPicker.hidden = true;
    tabPicker.replaceChildren();
  }
}

// --- settings ---------------------------------------------------------------

async function setSettingsOpen(open) {
  cfg.classList.toggle("open", open);
  document.getElementById("gear").setAttribute("aria-expanded", String(open));
  syncNoticeVisibility();
  renderConnectionState();
  if (!open) {
    document.getElementById("gear").focus();
    return;
  }
  state = await runtime({ cmd: "getState" });
  const settings = state.settings || {};
  document.getElementById("browserName").value = (state.identity && state.identity.browserName) || "Chrome";
  document.getElementById("hermesUrl").value = await getUrl();
  document.getElementById("bridgeUrl").value = settings.bridgeUrl || DEFAULT_BRIDGE;
  document.getElementById("pairingCode").value = settings.pairingCode || "";
  document.getElementById("trustedInput").checked = !!settings.trustedInput;
  focusFirst(cfg);
}

document.getElementById("gear").onclick = async () => {
  await setSettingsOpen(!cfg.classList.contains("open"));
};
openSetupSettings.onclick = () => setSettingsOpen(true);
checkCompanionButton.onclick = () => probeCompanion();

document.getElementById("save").onclick = async () => {
  const url = normalizeLoopbackUrl(document.getElementById("hermesUrl").value, DEFAULT_URL);
  if (!url) { statusEl.textContent = "use a 127.0.0.1 / localhost address"; return; }
  const bridgeUrl = (document.getElementById("bridgeUrl").value || "").trim() || DEFAULT_BRIDGE;
  if (!/^wss?:\/\/(127\.0\.0\.1|localhost):\d+\/?$/.test(bridgeUrl)) {
    statusEl.textContent = "bridge must be ws://127.0.0.1:<port>";
    return;
  }
  const browserName = (document.getElementById("browserName").value || "").trim();
  const pairingCode = (document.getElementById("pairingCode").value || "").trim();
  if (!/^[0-9a-f]{64}$/i.test(pairingCode)) {
    statusEl.textContent = "paste the 64-character code printed by the companion installer";
    return;
  }
  const wantTrusted = document.getElementById("trustedInput").checked;
  let trustedInput = wantTrusted;
  if (wantTrusted && !await chrome.permissions.contains({ permissions: ["debugger"] })) {
    trustedInput = false;
    document.getElementById("trustedInput").checked = false;
    statusEl.textContent = "this build does not include trusted input";
  }
  await chrome.storage.local.set({ hermesUrl: url });
  const identityResult = await runtime({ cmd: "saveIdentity", browserName });
  const settingsResult = await runtime({ cmd: "saveSettings", settings: { bridgeUrl, pairingCode, trustedInput } });
  if (!identityResult.ok || !settingsResult.ok) {
    statusEl.textContent = identityResult.error || settingsResult.error || "Could not save settings";
    return;
  }
  state.settings = { ...(state.settings || {}), bridgeUrl, pairingCode, trustedInput };
  await setSettingsOpen(false);
  await showDashboard(selectedScope);
  await connect();
  await loadSessions();
};

// --- session/tab controls ---------------------------------------------------

sessionSelect.onchange = async () => {
  const scope = parseOption(sessionSelect.value);
  await selectScope(scope, true);
};

document.getElementById("refreshSessions").onclick = async () => {
  await loadSessions();
  await renderTabs();
};

attachActiveButton.onclick = async () => {
  const actionScope = copyScope(selectedScope);
  const expectedTabId = state.activeChromeTab && state.activeChromeTab.tabId;
  if (!actionScope || !state.paired || !Number.isInteger(expectedTabId)) return;
  const result = await runtime({ cmd: "attachActiveTab", ...actionScope, expectedTabId });
  if (!scopeIsCurrent(actionScope)) return;
  if (!result || !result.ok) {
    scopeInfo.textContent = result && result.error ? result.error : "Could not attach the active tab";
    return;
  }
  await renderTabs();
};

manageTabsButton.onclick = async () => {
  pickerOpen = !pickerOpen;
  privacyPopover.hidden = true;
  privacyButton.setAttribute("aria-expanded", "false");
  await renderTabs();
  if (pickerOpen) focusFirst(tabPicker);
};

privacyButton.onclick = () => {
  const open = privacyPopover.hidden;
  privacyPopover.hidden = !open;
  privacyButton.setAttribute("aria-expanded", String(open));
  if (open && pickerOpen) {
    pickerOpen = false;
    tabPicker.hidden = true;
    renderTabs();
  }
  if (open) {
    positionPopover(privacyPopover);
    privacyPopover.tabIndex = -1;
    privacyPopover.focus();
  }
};

document.addEventListener("keydown", (event) => {
  const modal = modalElement();
  if (event.key === "Tab" && modal) {
    const items = focusableElements(modal);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
    return;
  }
  if (event.key !== "Escape") return;
  if (cfg.classList.contains("open")) {
    event.preventDefault();
    setSettingsOpen(false);
    document.getElementById("gear").focus();
  } else if (!privacyPopover.hidden) {
    event.preventDefault();
    privacyPopover.hidden = true;
    privacyButton.setAttribute("aria-expanded", "false");
    privacyButton.focus();
  } else if (pickerOpen) {
    event.preventDefault();
    pickerOpen = false;
    renderTabs();
    manageTabsButton.focus();
  }
});

dismissUpgradeNotice.onclick = async () => {
  if (!state.upgradeNotice) return;
  const result = await runtime({
    cmd: "dismissUpgradeNotice",
    id: state.upgradeNotice.id,
  });
  if (result && result.ok) {
    renderUpgradeNotice(result.upgradeNotice);
    document.getElementById("gear").focus();
  }
};

// --- pairing status ---------------------------------------------------------

async function connect() {
  state = await runtime({ cmd: "getState" });
  renderConnectionState();
  const name = (state.identity && state.identity.browserName) || "Chrome";
  await runtime({ cmd: "connect", browserName: name });
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.from !== "bg") return;
  switch (message.cmd) {
    case "paired":
      state.paired = !!message.ok;
      targetReadiness = null;
      if (message.brokerState && typeof message.brokerState === "object") {
        state.brokerState = message.brokerState;
      }
      renderConnectionState(message.ok ? "" : "Pairing failed", message.ok ? "" : "err");
      renderTabs();
      break;
    case "pairDenied":
      state.paired = false;
      targetReadiness = null;
      state.brokerState = { agentProfiles: [], browsers: [] };
      setDot("err");
      statusEl.textContent = "pairing denied — check the code (⚙)";
      renderTabs().then(() => renderConnectionState("Pairing denied — check the code (⚙)", "err"));
      break;
    case "companionDetected":
      renderCompanionDetection(!!message.detected);
      break;
    case "disconnected":
      state.paired = false;
      targetReadiness = null;
      state.brokerState = { agentProfiles: [], browsers: [] };
      renderConnectionState("Connector broker not reachable", "off");
      renderTabs().then(() => renderConnectionState("Connector broker not reachable", "off"));
      break;
    case "hostError":
      setDot("err");
      statusEl.textContent = "Connector broker unreachable";
      break;
    case "brokerState":
      if (message.state) state.brokerState = message.state;
      renderConnectionState();
      renderTabs();
      break;
    case "upgradeNoticeChanged":
      renderUpgradeNotice(message.notice);
      break;
    case "bindingsChanged":
      renderTabs();
      break;
    case "activeTabChanged":
    case "attachedTabChanged":
      renderTabs();
      break;
    case "bindingRevoked":
      {
        const revokedScope = copyScope(selectedScope);
        const reason = message.reason || "This session moved to another Chrome profile.";
        renderTabs().then(() => {
          if (scopeIsCurrent(revokedScope) && message.profileId === revokedScope.profileId &&
              message.sessionId === revokedScope.sessionId) {
            scopeInfo.textContent = reason;
            scopeInfo.title = reason;
          }
        });
      }
      break;
  }
});

async function init() {
  try {
    const platform = await chrome.runtime.getPlatformInfo();
    platformOS = String((platform && platform.os) || "unknown");
  } catch (_) {}
  state = await runtime({ cmd: "getState" });
  renderUpgradeNotice(state.upgradeNotice);
  const needsSetup = renderSetupNotice(state.settings);
  selectedScope = copyScope(state.selectedScope);
  updateScopeControls();
  await showDashboard(selectedScope);
  if (needsSetup) {
    setDot("off");
    statusEl.textContent = "setup required";
    probeCompanion();
  } else {
    await connect();
  }
  await loadSessions();
  await renderTabs();
}

init();
setInterval(() => loadSessions(), 15_000);
