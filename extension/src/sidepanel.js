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
const sessionSelect = document.getElementById("sessionSelect");
const attachActiveButton = document.getElementById("attachActive");
const manageTabsButton = document.getElementById("manageTabs");
const attachedTabs = document.getElementById("attachedTabs");
const tabPicker = document.getElementById("tabPicker");
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

const setDot = (kind) => { dot.className = `dot ${kind}`; };
const keyFor = (scope) => scope ? `${scope.profileId}\u001f${scope.sessionId}` : "";

function renderUpgradeNotice(notice) {
  state.upgradeNotice = notice || null;
  upgradeNotice.hidden = !state.upgradeNotice;
  customPortUpgrade.hidden = !state.upgradeNotice || !state.upgradeNotice.customBridge;
}

function renderSetupNotice(settings) {
  const required = !String((settings && settings.pairingCode) || "").trim();
  setupNotice.hidden = !required;
  return required;
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
  downloadCompanion.textContent = "Download companion 0.2.1";
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

async function showDashboard(scope = null) {
  frame.src = await dashboardUrl(scope);
}

function updateScopeControls() {
  const ready = !!selectedScope;
  attachActiveButton.disabled = !ready;
  manageTabsButton.disabled = !ready;
  if (!ready) {
    scopeInfo.textContent = "Choose the Hermes project/session that should own browser tabs.";
    attachedTabs.replaceChildren();
    tabPicker.replaceChildren();
    tabPicker.hidden = true;
  }
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
  const currentValue = selectedScope ? optionValue(selectedScope.profileId, selectedScope.sessionId) : "";
  try {
    const sessions = await listDashboardSessions(await getUrl());
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
      option.textContent = `[${selectedScope.profileId}] ${selectedScope.sessionId}`;
      options.push(option);
    }
    sessionSelect.replaceChildren(...options);
    sessionSelect.value = currentValue;
    if (statusEl.textContent === "Hermes sessions unavailable") statusEl.textContent = "browser paired";
  } catch (_) {
    statusEl.textContent = "Hermes sessions unavailable";
  }
}

async function selectScope(scope, navigate = true) {
  selectedScope = scope;
  updateScopeControls();
  if (!scope) return;
  const result = await runtime({ cmd: "selectScope", ...scope });
  if (!result || !result.ok) {
    scopeInfo.textContent = result && result.error ? result.error : "Could not select this session";
    return;
  }
  if (navigate) await showDashboard(scope);
  await renderTabs();
}

function tabRow(tab, binding, inPicker = false) {
  const row = document.createElement("div");
  row.className = `tabRow${binding && binding.activeTabId === tab.tabId ? " current" : ""}`;
  const title = document.createElement("span");
  title.className = "tabTitle";
  title.textContent = tab.title || tab.url || `Tab ${tab.tabId}`;
  title.title = tab.url || "";
  row.appendChild(title);

  if (inPicker) {
    const button = document.createElement("button");
    button.className = "smallBtn";
    const sameOwner = tab.owner && selectedScope &&
      tab.owner.profileId === selectedScope.profileId && tab.owner.sessionId === selectedScope.sessionId;
    button.textContent = sameOwner ? (tab.owner.active ? "Current" : "Use") : (tab.owner ? "Move here" : "Attach");
    button.disabled = sameOwner && tab.owner.active;
    button.onclick = async () => {
      const command = sameOwner ? "activateTab" : "attachTab";
      const result = await runtime({ cmd: command, ...selectedScope, tabId: tab.tabId });
      if (!result.ok) scopeInfo.textContent = result.error || "Could not attach tab";
      await renderTabs();
    };
    row.appendChild(button);
  } else {
    if (binding.activeTabId !== tab.tabId) {
      const use = document.createElement("button");
      use.className = "smallBtn";
      use.textContent = "Use";
      use.onclick = async () => {
        await runtime({ cmd: "activateTab", ...selectedScope, tabId: tab.tabId });
        await renderTabs();
      };
      row.appendChild(use);
    }
    const remove = document.createElement("button");
    remove.className = "smallBtn";
    remove.textContent = "×";
    remove.title = "Detach this tab from the Hermes session";
    remove.onclick = async () => {
      await runtime({ cmd: "detachTab", ...selectedScope, tabId: tab.tabId });
      await renderTabs();
    };
    row.appendChild(remove);
  }
  return row;
}

async function renderTabs() {
  if (!selectedScope) {
    updateScopeControls();
    return;
  }
  const result = await runtime({ cmd: "listTabs", ...selectedScope, includeAvailable: pickerOpen });
  if (!result || !result.ok) {
    scopeInfo.textContent = result && result.error ? result.error : "Could not read Chrome tabs";
    return;
  }
  const binding = (result.bindings || {})[keyFor(selectedScope)] || null;
  const byId = new Map((result.tabs || []).map((tab) => [tab.tabId, tab]));
  const rows = [];
  for (const tabId of binding ? binding.tabIds : []) {
    const tab = byId.get(tabId);
    if (tab) rows.push(tabRow(tab, binding));
  }
  attachedTabs.replaceChildren(...rows);
  scopeInfo.textContent = binding
    ? `${binding.tabIds.length} attached tab${binding.tabIds.length === 1 ? "" : "s"} · green = current target`
    : "No tab attached. Hermes will refuse browser actions until you attach one.";

  if (pickerOpen) {
    tabPicker.hidden = false;
    tabPicker.replaceChildren(...(result.tabs || []).map((tab) => tabRow(tab, binding, true)));
  } else {
    tabPicker.hidden = true;
    tabPicker.replaceChildren();
  }
}

// --- settings ---------------------------------------------------------------

async function setSettingsOpen(open) {
  const cfg = document.getElementById("cfg");
  cfg.classList.toggle("open", open);
  if (!open) return;
  state = await runtime({ cmd: "getState" });
  const settings = state.settings || {};
  document.getElementById("browserName").value = (state.identity && state.identity.browserName) || "Chrome";
  document.getElementById("hermesUrl").value = await getUrl();
  document.getElementById("bridgeUrl").value = settings.bridgeUrl || DEFAULT_BRIDGE;
  document.getElementById("pairingCode").value = settings.pairingCode || "";
  document.getElementById("trustedInput").checked = !!settings.trustedInput;
}

document.getElementById("gear").onclick = async () => {
  const cfg = document.getElementById("cfg");
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
  document.getElementById("cfg").classList.remove("open");
  renderSetupNotice({ pairingCode });
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
  if (!selectedScope) return;
  const result = await runtime({ cmd: "attachActiveTab", ...selectedScope });
  if (!result.ok) scopeInfo.textContent = result.error || "Could not attach the active tab";
  await renderTabs();
};

manageTabsButton.onclick = async () => {
  pickerOpen = !pickerOpen;
  manageTabsButton.textContent = pickerOpen ? "Hide tabs" : "Choose tabs";
  await renderTabs();
};

dismissUpgradeNotice.onclick = async () => {
  if (!state.upgradeNotice) return;
  const result = await runtime({
    cmd: "dismissUpgradeNotice",
    id: state.upgradeNotice.id,
  });
  if (result && result.ok) renderUpgradeNotice(result.upgradeNotice);
};

// --- pairing status ---------------------------------------------------------

async function connect() {
  state = await runtime({ cmd: "getState" });
  if (state && state.paired) {
    setDot("on");
    statusEl.textContent = "browser paired";
  }
  const name = (state.identity && state.identity.browserName) || "Chrome";
  await runtime({ cmd: "connect", browserName: name });
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.from !== "bg") return;
  switch (message.cmd) {
    case "paired":
      setDot(message.ok ? "on" : "off");
      statusEl.textContent = message.ok ? "browser paired" : "pairing failed";
      break;
    case "pairDenied":
      setDot("err");
      statusEl.textContent = "pairing denied — check the code (⚙)";
      break;
    case "companionDetected":
      renderCompanionDetection(!!message.detected);
      break;
    case "disconnected":
      setDot("off");
      statusEl.textContent = "Connector broker not reachable";
      break;
    case "hostError":
      setDot("err");
      statusEl.textContent = "Connector broker unreachable";
      break;
    case "brokerState":
      if (message.state) state.brokerState = message.state;
      break;
    case "upgradeNoticeChanged":
      renderUpgradeNotice(message.notice);
      break;
    case "bindingsChanged":
      renderTabs();
      break;
    case "bindingRevoked":
      if (selectedScope && message.profileId === selectedScope.profileId &&
          message.sessionId === selectedScope.sessionId) {
        scopeInfo.textContent = message.reason || "This session moved to another Chrome profile.";
      }
      renderTabs();
      break;
  }
});

frame.addEventListener("load", () => { hint.hidden = true; });

async function init() {
  try {
    const platform = await chrome.runtime.getPlatformInfo();
    platformOS = String((platform && platform.os) || "unknown");
  } catch (_) {}
  state = await runtime({ cmd: "getState" });
  renderUpgradeNotice(state.upgradeNotice);
  const setupRequired = renderSetupNotice(state.settings);
  selectedScope = state.selectedScope || null;
  updateScopeControls();
  await showDashboard(selectedScope);
  if (setupRequired) {
    setDot("off");
    statusEl.textContent = "setup required";
    await setSettingsOpen(true);
    probeCompanion();
  } else {
    await connect();
  }
  await loadSessions();
  await renderTabs();
}

init();
setInterval(() => loadSessions(), 15_000);
