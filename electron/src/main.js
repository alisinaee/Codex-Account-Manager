"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { app, BrowserWindow, Menu, Notification, Tray, clipboard, dialog, ipcMain, nativeImage, screen, shell } = require("electron");

const { createApiClient } = require("./api-client");
const { ensureBackendRunning, fetchCurrentUsage, getDefaultBackendState, runServiceCommand } = require("./backend");
const { shouldInvalidateDesktopStateForRequest } = require("./desktop-state-cache");
const { downloadBackendExportArchive } = require("./export-download");
const { APP_ID, APP_NAME, getIconPath, getWindowIconPath, resolveDesktopIdentity } = require("./icons");
const { buildApplicationMenuTemplate, shouldQuitOnWindowAllClosed } = require("./menu");
const { notificationsEnabled, sendUsageNotification } = require("./notifications");
const {
  formatRuntimeDiagnostics,
  installPythonCore,
  installPythonRuntime,
  loadStoredRuntimeState,
  normalizeRuntimeStatus,
  resolveRuntimeStatus,
  saveStoredRuntimeState,
} = require("./runtime");
const { applyTrayState, createTray, statusBarEnabled } = require("./tray");
const {
  PROJECT_RELEASES_API_URL,
  PROJECT_RELEASES_URL,
  buildCoreInstallSpecForVersion,
  buildUnifiedUpdateStatus,
  clearPendingUpdateState,
  downloadReleaseAsset,
  fetchGitHubReleaseNotes,
  loadPendingUpdateState,
  savePendingUpdateState,
  selectReleaseAsset,
  shouldResumePendingCoreSync,
  withVersionPrefix,
} = require("./update-manager");
const { buildUsageSummary } = require("./usage");
const { applyWindowsTaskbarUsage, ensureWindowsNotificationShortcut } = require("./windows-integration");
const { usageHexColor } = require("./usage-thresholds");

const desktopIdentity = resolveDesktopIdentity(process.env);
const DESKTOP_APP_ID = desktopIdentity.appId || APP_ID;
const DESKTOP_APP_NAME = desktopIdentity.appName || APP_NAME;
const STARTUP_DEBUG_ENABLED = process.env.CAM_ELECTRON_STARTUP_DEBUG === "1";
let pendingQuitContext = null;

function startupDebugLog(event, details = {}) {
  if (!STARTUP_DEBUG_ENABLED) {
    return;
  }
  const payload = {
    ts: new Date().toISOString(),
    event,
    pid: process.pid,
    ppid: process.ppid,
    appName: DESKTOP_APP_NAME,
    appId: DESKTOP_APP_ID,
    ...details,
  };
  console.error(`[cam-main] ${JSON.stringify(payload)}`);
}

function markQuitContext(reason, details = {}) {
  pendingQuitContext = {
    reason: String(reason || "").trim() || "unknown",
    details: details && typeof details === "object" ? details : {},
  };
  startupDebugLog("quit-context", pendingQuitContext);
}

function requestAppQuit(reason, details = {}) {
  markQuitContext(reason, details);
  app.isQuitting = true;
  app.quit();
}

if (desktopIdentity.isDevShell) {
  app.setPath("userData", path.join(app.getPath("appData"), DESKTOP_APP_NAME));
}

startupDebugLog("process-start", {
  execPath: process.execPath,
  cwd: process.cwd(),
  argv: process.argv,
  userDataPath: app.getPath("userData"),
  launchContext: process.env.CAM_ELECTRON_APP_LAUNCH_CONTEXT || "",
  isDevShell: desktopIdentity.isDevShell,
});

app.setName(DESKTOP_APP_NAME);
app.name = DESKTOP_APP_NAME;
if (typeof app.setAppUserModelId === "function") {
  app.setAppUserModelId(DESKTOP_APP_ID);
}
const hasSingleInstanceLock = app.requestSingleInstanceLock();
startupDebugLog("single-instance-lock", { acquired: hasSingleInstanceLock });
if (!hasSingleInstanceLock) {
  markQuitContext("single-instance-lock-failed");
  startupDebugLog("single-instance-lock-failed", {});
  app.quit();
}

process.on("uncaughtException", (error) => {
  startupDebugLog("uncaught-exception", {
    message: String(error?.message || error),
    stack: String(error?.stack || ""),
  });
});
process.on("unhandledRejection", (reason) => {
  startupDebugLog("unhandled-rejection", {
    reason: String(reason?.stack || reason?.message || reason || ""),
  });
});
process.on("exit", (code) => {
  startupDebugLog("process-exit", { code });
});

let mainWindow = null;
let splashWindow = null;
let tray = null;
let miniMeterWindow = null;
let backendState = getDefaultBackendState();
let apiClient = null;
let desktopState = null;
let latestUsagePayload = null;
let refreshTimer = null;
let miniMeterPersistTimer = null;
let miniMeterSuppressMovePersist = false;
let runtimeState = normalizeRuntimeStatus({
  phase: "checking_runtime",
  python: {},
  core: {},
  uiService: getDefaultBackendState(),
});
let runtimeProgress = [];
let updateProgress = [];
let updateStatusCache = null;
let updateRunPromise = null;
let pendingUpdateState = null;
let registeredIpcChannels = [];
let devBackendRestarted = false;
const MINI_METER_BASE_FONT_SIZE = 14;
const ZOOM_FACTOR_MIN = 0.5;
const ZOOM_FACTOR_MAX = 3.0;
const ZOOM_FACTOR_STEP = 0.1;
const WINDOWS_NOTIFICATION_LAUNCH_ARG_PATTERNS = [
  "--notification-launch-id=",
  "--notification-app-user-model-id=",
  "--notification-",
];
let pendingOpenProfilesFromNotification = false;
let lastAutoSwitchWarningDueAt = null;
let autoSwitchStopInFlight = false;

function windowsMiniMeterEnabled(config = {}) {
  return Boolean(config?.ui?.windows_mini_meter_enabled);
}

function windowsMiniMeterDragEnabled(config = {}) {
  return Boolean(config?.ui?.windows_mini_meter_drag_enabled);
}

function windowsMiniMeterFontSize(config = {}) {
  const raw = Number(config?.ui?.windows_mini_meter_font_size);
  if (!Number.isFinite(raw)) return 14;
  return Math.max(10, Math.min(24, Math.round(raw)));
}

function windowsMiniMeterDisplayMode(config = {}) {
  const raw = String(config?.ui?.windows_mini_meter_display_mode || "primary").trim().toLowerCase();
  return raw === "primary" ? "primary" : "follow_focus";
}

function windowsMiniMeterDisplayTarget(config = {}) {
  const rawTarget = String(config?.ui?.windows_mini_meter_display_target || "").trim().toLowerCase();
  if (rawTarget === "primary" || rawTarget === "follow_focus") return rawTarget;
  if (/^display:-?\d+$/.test(rawTarget)) return rawTarget;
  return windowsMiniMeterDisplayMode(config);
}

function windowsMiniMeterSize(config = {}) {
  const fontSize = windowsMiniMeterFontSize(config);
  const valueColumnWidth = Math.round(fontSize * 2.35);
  const metricColumnWidth = Math.round(fontSize * 1.3);
  const horizontalPadding = Math.round(fontSize * 0.6);
  const verticalPadding = Math.round(fontSize * 0.5);
  const rowHeight = Math.round(fontSize * 1.06);
  const rowGap = Math.round(fontSize * 0.14);
  return {
    width: Math.max(60, Math.min(138, valueColumnWidth + metricColumnWidth + (horizontalPadding * 2))),
    height: Math.max(44, Math.min(96, (rowHeight * 2) + rowGap + (verticalPadding * 2))),
  };
}

function windowsMiniMeterPosition(config = {}) {
  const x = Number(config?.ui?.windows_mini_meter_x);
  const y = Number(config?.ui?.windows_mini_meter_y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x: Math.round(x), y: Math.round(y) };
}

function buildWindowsMiniMeterHtml() {
  return [
    "<!doctype html>",
    "<html><head><meta charset=\"utf-8\" />",
    "<style>",
    "html, body { margin:0; width:100%; height:100%; overflow:hidden; background:transparent; font-family:'Segoe UI', Arial, sans-serif; }",
    ".meter { box-sizing:border-box; width:100%; height:100%; padding:calc(var(--meter-font-size) * 0.24) calc(var(--meter-font-size) * 0.30); border-radius:calc(var(--meter-font-size) * 0.5); background:rgba(10,12,15,0.90); border:1px solid rgba(255,255,255,0.10); display:flex; flex-direction:column; justify-content:center; gap:calc(var(--meter-font-size) * 0.14); --meter-font-size:14px; }",
    ".meter.draggable { -webkit-app-region: drag; cursor:move; }",
    ".row { display:flex; align-items:center; font-size:var(--meter-font-size); line-height:1.05; font-weight:700; letter-spacing:0.1px; text-shadow:0 0 4px rgba(0,0,0,0.45); }",
    ".five { color:#22c55e; }",
    ".week { color:#22c55e; }",
    ".value { min-width:calc(var(--meter-font-size) * 2.35); margin-right:calc(var(--meter-font-size) * 0.18); }",
    "</style></head><body>",
    "<div class=\"meter\" id=\"meter\">",
    "<div class=\"row five\"><span class=\"value\" id=\"five\">--</span><span>5H</span></div>",
    "<div class=\"row week\"><span class=\"value\" id=\"week\">--</span><span>W</span></div>",
    "</div>",
    "<script>",
    "window.__updateMeter = (payload) => {",
    "  const five = document.getElementById('five');",
    "  const week = document.getElementById('week');",
    "  const fiveValue = payload && payload.fiveHour != null ? payload.fiveHour : '--';",
    "  const weekValue = payload && payload.weekly != null ? payload.weekly : '--';",
    "  const fiveTone = payload && payload.fiveTone ? payload.fiveTone : '';",
    "  const weekTone = payload && payload.weekTone ? payload.weekTone : '';",
    "  if (five) five.textContent = String(fiveValue);",
    "  if (week) week.textContent = String(weekValue);",
    "  if (five) five.style.color = fiveTone || '#adaaaa';",
    "  if (week) week.style.color = weekTone || '#adaaaa';",
    "};",
    "window.__setMeterOptions = (payload) => {",
    "  const root = document.getElementById('meter');",
    "  if (!root) return;",
    "  const font = payload && payload.fontSize != null ? payload.fontSize : 14;",
    "  const drag = Boolean(payload && payload.dragEnabled);",
    "  root.style.setProperty('--meter-font-size', `${font}px`);",
    "  root.classList.toggle('draggable', drag);",
    "};",
    "</script></body></html>",
  ].join("");
}

function listDesktopDisplays() {
  if (!screen || typeof screen.getAllDisplays !== "function") {
    return [];
  }
  const displays = screen.getAllDisplays();
  const primaryId = screen.getPrimaryDisplay?.()?.id;
  return displays.map((display, index) => {
    const id = Number(display?.id);
    const bounds = display?.bounds || {};
    const workArea = display?.workArea || {};
    const isPrimary = id === primaryId;
    return {
      id,
      index: index + 1,
      isPrimary,
      label: isPrimary ? `Display ${index + 1} (Primary)` : `Display ${index + 1}`,
      bounds: {
        x: Number(bounds.x) || 0,
        y: Number(bounds.y) || 0,
        width: Number(bounds.width) || 0,
        height: Number(bounds.height) || 0,
      },
      workArea: {
        x: Number(workArea.x) || 0,
        y: Number(workArea.y) || 0,
        width: Number(workArea.width) || 0,
        height: Number(workArea.height) || 0,
      },
    };
  }).filter((item) => Number.isFinite(item.id));
}

function resolveWindowsMiniMeterDisplay(config = {}) {
  const saved = windowsMiniMeterPosition(config);
  if (saved) {
    return screen?.getDisplayNearestPoint?.(saved) || screen?.getPrimaryDisplay?.() || null;
  }
  const target = windowsMiniMeterDisplayTarget(config);
  if (target === "primary") {
    return screen?.getPrimaryDisplay?.() || null;
  }
  if (target.startsWith("display:")) {
    const targetId = Number(target.split(":")[1]);
    if (Number.isFinite(targetId) && typeof screen?.getAllDisplays === "function") {
      const found = screen.getAllDisplays().find((display) => Number(display?.id) === targetId);
      if (found) return found;
    }
    return screen?.getPrimaryDisplay?.() || null;
  }
  const cursor = screen?.getCursorScreenPoint?.() || { x: 0, y: 0 };
  return screen?.getDisplayNearestPoint?.(cursor) || screen?.getPrimaryDisplay?.() || null;
}

function applyWindowsMiniMeterSize(config = {}) {
  if (process.platform !== "win32" || !miniMeterWindow || miniMeterWindow.isDestroyed()) {
    return;
  }
  const nextSize = windowsMiniMeterSize(config);
  const bounds = miniMeterWindow.getBounds();
  if (bounds.width === nextSize.width && bounds.height === nextSize.height) {
    return;
  }
  miniMeterSuppressMovePersist = true;
  miniMeterWindow.setBounds({ ...bounds, width: nextSize.width, height: nextSize.height });
  miniMeterSuppressMovePersist = false;
}

function positionWindowsMiniMeter(config = {}) {
  if (process.platform !== "win32" || !miniMeterWindow || miniMeterWindow.isDestroyed()) {
    return;
  }
  const display = resolveWindowsMiniMeterDisplay(config);
  const workArea = display?.workArea;
  if (!workArea) {
    return;
  }
  const bounds = miniMeterWindow.getBounds();
  const saved = windowsMiniMeterPosition(config);
  const marginRight = 12;
  const marginBottom = 8;
  const anchoredX = workArea.x + Math.max(0, workArea.width - bounds.width - marginRight);
  const anchoredY = workArea.y + Math.max(0, workArea.height - bounds.height - marginBottom);
  const minX = workArea.x;
  const maxX = workArea.x + Math.max(0, workArea.width - bounds.width);
  const minY = workArea.y;
  const maxY = workArea.y + Math.max(0, workArea.height - bounds.height);
  const x = saved ? Math.max(minX, Math.min(maxX, saved.x)) : anchoredX;
  const y = saved ? Math.max(minY, Math.min(maxY, saved.y)) : anchoredY;
  miniMeterSuppressMovePersist = true;
  miniMeterWindow.setBounds({ ...bounds, x, y });
  miniMeterSuppressMovePersist = false;
}

function updateWindowsMiniMeterOptions(config = {}) {
  if (!miniMeterWindow || miniMeterWindow.isDestroyed()) {
    return;
  }
  const dragEnabled = windowsMiniMeterDragEnabled(config);
  const fontSize = windowsMiniMeterFontSize(config);
  miniMeterWindow.setMovable(Boolean(dragEnabled));
  miniMeterWindow.setFocusable(Boolean(dragEnabled));
  miniMeterWindow.setIgnoreMouseEvents(!dragEnabled, { forward: !dragEnabled });
  const script = `window.__setMeterOptions(${JSON.stringify({ dragEnabled, fontSize })});`;
  miniMeterWindow.webContents.executeJavaScript(script).catch(() => {});
}

async function persistWindowsMiniMeterPosition(bounds = {}) {
  if (!apiClient || !desktopState || !windowsMiniMeterDragEnabled(desktopState?.config || {})) {
    return;
  }
  const x = Number(bounds?.x);
  const y = Number(bounds?.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return;
  }
  const currentX = Number(desktopState?.config?.ui?.windows_mini_meter_x);
  const currentY = Number(desktopState?.config?.ui?.windows_mini_meter_y);
  if (Math.round(currentX) === Math.round(x) && Math.round(currentY) === Math.round(y)) {
    return;
  }
  try {
    const nextConfig = await requestWithTokenRefresh("/api/ui-config", {
      method: "POST",
      body: JSON.stringify({
        ui: {
          windows_mini_meter_x: Math.round(x),
          windows_mini_meter_y: Math.round(y),
        },
      }),
    });
    if (desktopState) {
      desktopState = {
        ...desktopState,
        config: {
          ...(desktopState.config || {}),
          ...(nextConfig || {}),
          ui: {
            ...(desktopState.config?.ui || {}),
            ...(nextConfig?.ui || {}),
          },
        },
      };
    }
  } catch (_) {
    // Ignore temporary persistence failures for drag updates.
  }
}

function queuePersistWindowsMiniMeterPosition() {
  if (!miniMeterWindow || miniMeterWindow.isDestroyed() || miniMeterSuppressMovePersist) {
    return;
  }
  if (miniMeterPersistTimer) {
    clearTimeout(miniMeterPersistTimer);
  }
  const bounds = miniMeterWindow.getBounds();
  miniMeterPersistTimer = setTimeout(() => {
    miniMeterPersistTimer = null;
    persistWindowsMiniMeterPosition(bounds).catch(() => {});
  }, 420);
}

function ensureWindowsMiniMeterWindow() {
  if (process.platform !== "win32" || miniMeterWindow || app.isQuitting) {
    return miniMeterWindow;
  }
  const html = buildWindowsMiniMeterHtml();
  const initialSize = windowsMiniMeterSize(desktopState?.config || {});
  miniMeterWindow = new BrowserWindow({
    width: initialSize.width,
    height: initialSize.height,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    fullscreenable: false,
    maximizable: false,
    minimizable: false,
    resizable: false,
    movable: true,
    show: false,
    skipTaskbar: true,
    hasShadow: false,
    focusable: true,
    backgroundColor: "#00000000",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  miniMeterWindow.setAlwaysOnTop(true, "pop-up-menu");
  miniMeterWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  miniMeterWindow.setMenuBarVisibility(false);
  miniMeterWindow.once("ready-to-show", () => {
    applyWindowsMiniMeterSize(desktopState?.config || {});
    positionWindowsMiniMeter(desktopState?.config || {});
    updateWindowsMiniMeterOptions(desktopState?.config || {});
    miniMeterWindow?.showInactive?.();
  });
  miniMeterWindow.on("move", () => queuePersistWindowsMiniMeterPosition());
  miniMeterWindow.on("closed", () => {
    miniMeterWindow = null;
  });
  miniMeterWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`).catch(() => {});
  return miniMeterWindow;
}

function destroyWindowsMiniMeterWindow() {
  if (miniMeterPersistTimer) {
    clearTimeout(miniMeterPersistTimer);
    miniMeterPersistTimer = null;
  }
  if (!miniMeterWindow || miniMeterWindow.isDestroyed()) {
    miniMeterWindow = null;
    return;
  }
  miniMeterWindow.destroy();
  miniMeterWindow = null;
}

function updateWindowsMiniMeterWindow(summary = {}) {
  if (!miniMeterWindow || miniMeterWindow.isDestroyed()) {
    return;
  }
  const fiveHourRaw = Number(summary?.fiveHourPercent);
  const weeklyRaw = Number(summary?.weeklyPercent);
  const fiveHour = Number.isFinite(fiveHourRaw) ? `${Math.round(fiveHourRaw)}%` : "--";
  const weekly = Number.isFinite(weeklyRaw) ? `${Math.round(weeklyRaw)}%` : "--";
  const fiveTone = Number.isFinite(fiveHourRaw) ? usageHexColor(fiveHourRaw) : "";
  const weekTone = Number.isFinite(weeklyRaw) ? usageHexColor(weeklyRaw) : "";
  const script = `window.__updateMeter(${JSON.stringify({ fiveHour, weekly, fiveTone, weekTone })});`;
  miniMeterWindow.webContents.executeJavaScript(script).catch(() => {});
}

function syncWindowsMiniMeter({ summary, config }) {
  if (process.platform !== "win32") {
    return false;
  }
  if (!windowsMiniMeterEnabled(config || {})) {
    destroyWindowsMiniMeterWindow();
    return false;
  }
  ensureWindowsMiniMeterWindow();
  applyWindowsMiniMeterSize(config || {});
  positionWindowsMiniMeter(config || {});
  updateWindowsMiniMeterOptions(config || {});
  updateWindowsMiniMeterWindow(summary || {});
  miniMeterWindow?.showInactive?.();
  return true;
}

function emitToRenderer(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function setRuntimeState(next) {
  runtimeState = normalizeRuntimeStatus(next, {
    minCoreVersion: process.env.CAM_ELECTRON_MIN_CORE_VERSION || "0.0.20",
  });
  if (runtimeState.core.commandPath) {
    saveStoredRuntimeState({
      commandPath: runtimeState.core.commandPath,
      version: runtimeState.core.version,
      pythonPath: runtimeState.python.path,
    }, { appLike: app });
  }
  emitToRenderer("desktop:runtime-status", runtimeState);
  return runtimeState;
}

function pushRuntimeProgress(progress) {
  runtimeProgress = [...runtimeProgress, { ts: Date.now(), ...progress }];
  emitToRenderer("desktop:runtime-progress", runtimeProgress[runtimeProgress.length - 1]);
}

function pushUpdateProgress(progress) {
  updateProgress = [...updateProgress, { ts: Date.now(), ...progress }];
  emitToRenderer("desktop:update-progress", updateProgress[updateProgress.length - 1]);
}

function updaterReleaseApiUrl() {
  return String(process.env.CAM_ELECTRON_RELEASES_API_URL || "").trim() || PROJECT_RELEASES_API_URL;
}

function updaterReleaseRepoUrl() {
  return String(process.env.CAM_ELECTRON_RELEASES_REPO_URL || "").trim() || PROJECT_RELEASES_URL;
}

function updaterDevModeEnabled() {
  return desktopIdentity.isDevShell
    || Boolean(String(process.env.CAM_ELECTRON_RELEASES_API_URL || "").trim())
    || Boolean(String(process.env.CAM_ELECTRON_RELEASES_REPO_URL || "").trim());
}

function shouldSimulateDesktopInstaller({ updateStatus, asset } = {}) {
  return Boolean(
    asset?.simulate_open
      || updateStatus?.release_notes?.simulation_mode
      || updateStatus?.latest_release?.simulation_mode,
  );
}

async function collectRuntimeDiagnostics() {
  let backendLogs = [];
  let fetchError = "";
  if (apiClient && runtimeState?.uiService?.running) {
    try {
      const payload = await requestWithTokenRefresh("/api/debug/logs?tail=240", {});
      backendLogs = Array.isArray(payload?.logs) ? payload.logs : [];
    } catch (error) {
      fetchError = String(error?.message || error);
    }
  }
  return {
    runtimeState,
    runtimeProgress,
    backendState,
    backendLogs,
    fetchError,
  };
}

async function loadReleaseNotesForDesktop({ force = false } = {}) {
  const cacheAgeMs = Number(process.env.CAM_ELECTRON_RELEASE_CACHE_MS || 300000);
  if (!force && updateStatusCache?.release_notes?.fetched_at) {
    const ageMs = Date.now() - Date.parse(updateStatusCache.release_notes.fetched_at);
    if (Number.isFinite(ageMs) && ageMs >= 0 && ageMs < cacheAgeMs) {
      return updateStatusCache.release_notes;
    }
  }

  try {
    return await fetchGitHubReleaseNotes({
      apiUrl: updaterReleaseApiUrl(),
      repoUrl: updaterReleaseRepoUrl(),
    });
  } catch (error) {
    if (apiClient) {
      try {
        const path = force ? "/api/release-notes?force=true" : "/api/release-notes";
        const payload = await requestWithTokenRefresh(path, {});
        return {
          ...payload,
          source: payload?.source || "backend-fallback",
        };
      } catch (_) {}
    }
    return {
      status: "error",
      status_text: String(error?.message || error || "Unable to load release notes."),
      source: "desktop",
      repo_url: updaterReleaseRepoUrl(),
      fetched_at: new Date().toISOString(),
      error: String(error?.message || error || ""),
      system_python: updateStatusCache?.release_notes?.system_python || null,
      releases: updateStatusCache?.release_notes?.releases || [],
    };
  }
}

async function getUnifiedUpdateStatus({ force = false } = {}) {
  const releaseNotes = await loadReleaseNotesForDesktop({ force });
  const status = buildUnifiedUpdateStatus({
    appVersion: app.getVersion(),
    runtimeState,
    releaseNotes,
    pendingUpdate: pendingUpdateState,
    updaterDevMode: updaterDevModeEnabled(),
    platform: process.platform,
  });
  updateStatusCache = status;
  return status;
}

function pendingUpdateDownloadDir() {
  return path.join(app.getPath("userData"), "updates");
}

function pendingCoreInstallSpec() {
  return String(pendingUpdateState?.coreInstallSpec || "").trim();
}

async function syncCoreToAppVersion({ targetVersion = app.getVersion(), coreInstallSpec = "" } = {}) {
  if (!runtimeState.python.available || !runtimeState.python.supported) {
    throw new Error("Python 3.11+ must be installed before the core can be updated.");
  }
  pushUpdateProgress({
    phase: "syncing_python_core",
    label: `Sync Python core to ${targetVersion}`,
    status: "running",
    percent: 5,
    targetVersion: `v${targetVersion}`,
    detail: `Preparing Python core ${targetVersion}.`,
  });
  await installPythonCore(runtimeState, {
    packageName: process.env.CAM_ELECTRON_CORE_INSTALL_SPEC
      || String(coreInstallSpec || "").trim()
      || pendingCoreInstallSpec()
      || buildCoreInstallSpecForVersion(targetVersion),
    onProgress: (event) => {
      pushUpdateProgress({
        phase: "syncing_python_core",
        label: event.label || "Sync Python core",
        status: event.status || "running",
        percent: event.status === "done" ? 90 : null,
        targetVersion: `v${targetVersion}`,
        detail: event.message || "",
      });
    },
  });
  await checkRuntime({ activateBackend: true });
}

function persistPendingUpdateState(nextPending) {
  pendingUpdateState = nextPending && typeof nextPending === "object" ? nextPending : null;
  if (pendingUpdateState) {
    savePendingUpdateState(pendingUpdateState, { appLike: app, fsImpl: fs });
    return;
  }
  clearPendingUpdateState({ appLike: app, fsImpl: fs });
}

async function runSystemPythonStep({ updateStatus, systemPythonSelection = "skip" } = {}) {
  const pythonStatus = updateStatus?.system_python || {};
  if (!pythonStatus.update_available) {
    return { awaitingUser: false, performed: false };
  }
  const required = Boolean(pythonStatus.required);
  const selected = required || String(systemPythonSelection || "").trim().toLowerCase() === "update";
  if (!selected) {
    return { awaitingUser: false, performed: false, skipped: true };
  }

  const targetVersion = updateStatus?.target_version || updateStatus?.current_version || `v${app.getVersion()}`;
  pushUpdateProgress({
    phase: "updating_system_python",
    label: required ? "Install System Python" : "Update System Python",
    status: "running",
    percent: 10,
    targetVersion,
    detail: required ? "Preparing a supported System Python runtime." : "Preparing the optional System Python update.",
  });

  if (process.platform === "win32") {
    await installPythonRuntime(runtimeState, {
      onProgress: (event) => {
        pushUpdateProgress({
          phase: "updating_system_python",
          label: event.label || (required ? "Install System Python" : "Update System Python"),
          status: event.status || "running",
          percent: event.status === "done" ? 90 : null,
          targetVersion,
          detail: event.message || "",
        });
      },
    });
    await checkRuntime({ activateBackend: true });
    persistPendingUpdateState({
      ...(pendingUpdateState || {}),
      targetVersion,
      systemPythonRequired: required,
      systemPythonSelected: selected,
      systemPythonSkipped: false,
      awaitingSystemPythonInstall: false,
      systemPythonCompleted: true,
    });
    return { awaitingUser: false, performed: true };
  }

  const installUrl = String(pythonStatus.install_url || "").trim();
  persistPendingUpdateState({
    ...(pendingUpdateState || {}),
    targetVersion,
    systemPythonRequired: required,
    systemPythonSelected: selected,
    systemPythonSkipped: false,
    awaitingSystemPythonInstall: true,
    systemPythonCompleted: false,
    systemPythonInstallUrl: installUrl,
  });
  if (installUrl) {
    await shell.openExternal(installUrl);
  }
  pushUpdateProgress({
    phase: "awaiting_system_python",
    label: required ? "Install System Python" : "Optional System Python update",
    status: "awaiting-user",
    percent: 100,
    targetVersion,
    detail: required
      ? "Install Python 3.11+ from the opened page, then relaunch the app to continue the update."
      : "Install the optional System Python update from the opened page, then relaunch the app if you want to use it.",
  });
  return { awaitingUser: true, performed: false };
}

async function runUnifiedUpdateFlow(options = {}) {
  updateProgress = [];
  const initialStatus = await getUnifiedUpdateStatus({ force: true });
  const normalizedPythonSelection = String(options?.systemPythonSelection || "").trim().toLowerCase() === "update" ? "update" : "skip";
  pushUpdateProgress({
    phase: "checking_updates",
    label: "Checking updates",
    status: "running",
    percent: 5,
    targetVersion: initialStatus.target_version || initialStatus.latest_version || initialStatus.current_version,
    detail: initialStatus.status_text || "Checking desktop and core versions.",
  });

  if (!initialStatus.update_available) {
    pushUpdateProgress({
      phase: "ready",
      label: "Up to date",
      status: "done",
      percent: 100,
      targetVersion: initialStatus.current_version,
      detail: "Desktop app and Python core are already aligned.",
    });
    return initialStatus;
  }

  if (initialStatus.desktop_update_needed) {
    const asset = selectReleaseAsset({
      release: initialStatus.latest_release,
      platform: process.platform,
      arch: process.arch,
    });
    if (!asset) {
      throw new Error("No compatible desktop installer asset was found for this release.");
    }
    pushUpdateProgress({
      phase: "downloading_desktop_update",
      label: `Downloading ${asset.name}`,
      status: "running",
      percent: 10,
      targetVersion: initialStatus.latest_version,
      detail: "Downloading the desktop installer.",
    });
    const filePath = await downloadReleaseAsset({
      asset,
      destinationDir: pendingUpdateDownloadDir(),
      fsImpl: fs,
      onProgress: (progress) => {
        pushUpdateProgress({
          ...progress,
          label: `Downloading ${asset.name}`,
          targetVersion: initialStatus.latest_version,
        });
      },
    });
    persistPendingUpdateState({
      targetVersion: initialStatus.latest_version,
      awaitingDesktopInstall: true,
      assetName: asset.name,
      assetPath: filePath,
      downloadedAt: new Date().toISOString(),
      simulatedDesktopInstaller: shouldSimulateDesktopInstaller({ updateStatus: initialStatus, asset }),
      coreInstallSpec: String(initialStatus.core_install_spec || "").trim(),
      systemPythonRequired: Boolean(initialStatus.system_python?.required),
      systemPythonSelected: Boolean(initialStatus.system_python?.required) || normalizedPythonSelection === "update",
      systemPythonSkipped: Boolean(initialStatus.system_python?.optional) && normalizedPythonSelection !== "update",
      awaitingSystemPythonInstall: false,
      systemPythonCompleted: false,
      systemPythonInstallUrl: String(initialStatus.system_python?.install_url || "").trim(),
    });
    if (shouldSimulateDesktopInstaller({ updateStatus: initialStatus, asset })) {
      if (typeof shell.showItemInFolder === "function") {
        shell.showItemInFolder(filePath);
      }
      pushUpdateProgress({
        phase: "awaiting_installer",
        label: "Simulation asset downloaded",
        status: "awaiting-user",
        percent: 100,
        targetVersion: initialStatus.latest_version,
        detail: "Local simulation feed downloaded the desktop asset. Replace it with a real installer if you want a full install test, then relaunch the app manually to continue.",
      });
      return getUnifiedUpdateStatus({ force: false });
    }
    const openResult = await shell.openPath(filePath);
    if (openResult) {
      throw new Error(openResult);
    }
    pushUpdateProgress({
      phase: "awaiting_installer",
      label: "Installer opened",
      status: "awaiting-user",
      percent: 100,
      targetVersion: initialStatus.latest_version,
      detail: "Finish installing the new desktop app from the opened DMG, then relaunch this app to complete the Python core sync.",
    });
    return getUnifiedUpdateStatus({ force: false });
  }

  if (initialStatus.system_python?.update_available) {
    if (initialStatus.system_python?.required || normalizedPythonSelection === "update") {
      persistPendingUpdateState({
        ...(pendingUpdateState || {}),
        targetVersion: initialStatus.target_version || initialStatus.current_version,
        awaitingDesktopInstall: false,
        systemPythonRequired: Boolean(initialStatus.system_python?.required),
        systemPythonSelected: initialStatus.system_python?.required || normalizedPythonSelection === "update",
        systemPythonSkipped: false,
        awaitingSystemPythonInstall: false,
        systemPythonCompleted: false,
        systemPythonInstallUrl: String(initialStatus.system_python?.install_url || "").trim(),
        coreInstallSpec: String(initialStatus.core_install_spec || "").trim(),
      });
      const pythonStep = await runSystemPythonStep({
        updateStatus: initialStatus,
        systemPythonSelection: normalizedPythonSelection,
      });
      if (pythonStep.awaitingUser) {
        return getUnifiedUpdateStatus({ force: false });
      }
    } else {
      persistPendingUpdateState({
        ...(pendingUpdateState || {}),
        targetVersion: initialStatus.target_version || initialStatus.current_version,
        awaitingDesktopInstall: false,
        systemPythonRequired: false,
        systemPythonSelected: false,
        systemPythonSkipped: true,
        awaitingSystemPythonInstall: false,
        systemPythonCompleted: false,
        systemPythonInstallUrl: String(initialStatus.system_python?.install_url || "").trim(),
        coreInstallSpec: String(initialStatus.core_install_spec || "").trim(),
      });
    }
  }

  const postPythonStatus = await getUnifiedUpdateStatus({ force: true });

  if (postPythonStatus.core_update_needed) {
    await syncCoreToAppVersion({
      targetVersion: app.getVersion(),
      coreInstallSpec: postPythonStatus.core_install_spec,
    });
    persistPendingUpdateState(null);
    const finalStatus = await getUnifiedUpdateStatus({ force: true });
    pushUpdateProgress({
      phase: "ready",
      label: "Update complete",
      status: "done",
      percent: 100,
      targetVersion: finalStatus.current_version,
      detail: "Desktop app and Python core are now aligned.",
    });
    return finalStatus;
  }

  pushUpdateProgress({
    phase: "ready",
    label: "Update complete",
    status: "done",
    percent: 100,
    targetVersion: postPythonStatus.current_version,
    detail: postPythonStatus.system_python?.update_available
      ? "Selected update steps completed."
      : "Desktop app and Python core are aligned.",
  });
  return postPythonStatus;
}

async function maybeResumePendingUpdate() {
  pendingUpdateState = loadPendingUpdateState({ appLike: app, fsImpl: fs });
  if (pendingUpdateState?.awaitingSystemPythonInstall) {
    if (!runtimeState?.python?.available || !runtimeState?.python?.supported) {
      return;
    }
    persistPendingUpdateState({
      ...pendingUpdateState,
      awaitingSystemPythonInstall: false,
      systemPythonCompleted: true,
    });
  }
  if (!shouldResumePendingCoreSync({
    pendingUpdate: pendingUpdateState,
    appVersion: app.getVersion(),
    runtimeState,
  })) {
    if (pendingUpdateState && pendingUpdateState.targetVersion && String(pendingUpdateState.targetVersion).trim() === app.getVersion()) {
      if (!pendingUpdateState.awaitingSystemPythonInstall) {
        persistPendingUpdateState(null);
      }
    }
    return;
  }
  try {
    await syncCoreToAppVersion({
      targetVersion: app.getVersion(),
      coreInstallSpec: pendingCoreInstallSpec(),
    });
    persistPendingUpdateState(null);
    await getUnifiedUpdateStatus({ force: true });
    pushUpdateProgress({
      phase: "ready",
      label: "Update complete",
      status: "done",
      percent: 100,
      targetVersion: `v${app.getVersion()}`,
      detail: "Resumed pending update and synced the Python core.",
    });
  } catch (error) {
    pushUpdateProgress({
      phase: "syncing_python_core",
      label: "Python core sync failed",
      status: "failed",
      percent: 100,
      targetVersion: `v${app.getVersion()}`,
      error: String(error?.message || error),
      detail: String(error?.message || error),
    });
  }
}

function isInvalidSessionTokenError(error) {
  const message = String(error?.message || "");
  return /invalid session token/i.test(message);
}

async function refreshBackendClient() {
  if (process.env.CAM_ELECTRON_SKIP_BACKEND === "1") {
    return;
  }
  backendState = await ensureBackendRunning({ command: runtimeState.core.commandPath || undefined });
  apiClient = createApiClient({ state: backendState });
}

async function requestWithTokenRefresh(path, options = {}) {
  try {
    return await apiClient.request(String(path || ""), options || {});
  } catch (error) {
    if (!isInvalidSessionTokenError(error)) {
      throw error;
    }
    await refreshBackendClient();
    return apiClient.request(String(path || ""), options || {});
  }
}

function getLoadUrl() {
  const useDevServer = process.env.CAM_ELECTRON_USE_DEV_SERVER === "1";
  if (!useDevServer) {
    return null;
  }
  if (process.env.CAM_ELECTRON_RENDERER_URL) {
    return process.env.CAM_ELECTRON_RENDERER_URL;
  }
  if (process.env.CAM_ELECTRON_BASE_URL) {
    return process.env.CAM_ELECTRON_BASE_URL;
  }
  return null;
}

function isWindowsNotificationLaunchArg(value = "") {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return WINDOWS_NOTIFICATION_LAUNCH_ARG_PATTERNS.some((prefix) => normalized.startsWith(prefix));
}

function wasLaunchedFromWindowsNotification(argv = []) {
  if (process.platform !== "win32") {
    return false;
  }
  if (!Array.isArray(argv)) {
    return false;
  }
  return argv.some((arg) => isWindowsNotificationLaunchArg(arg));
}

function focusMainWindow() {
  if (!mainWindow) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
}

function setRendererView(view) {
  if (mainWindow) {
    mainWindow.webContents.send("desktop:navigate", view);
    focusMainWindow();
  }
}

function openProfilesFromNotification() {
  pendingOpenProfilesFromNotification = false;
  if (!mainWindow || mainWindow.isDestroyed()) {
    createSplashWindow();
    createMainWindow();
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (mainWindow.webContents.isLoadingMainFrame()) {
    mainWindow.webContents.once("did-finish-load", () => setRendererView("profiles"));
    focusMainWindow();
    return;
  }
  setRendererView("profiles");
}

function openAutoSwitchWarningDialog() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createSplashWindow();
    createMainWindow();
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  const sendDialog = () => {
    mainWindow.webContents.send("desktop:auto-switch-stopped", {
      title: "Auto-switch disabled",
      message: "Auto-switch has been disabled. Enable it again from Auto Switch rules when you want automatic switching to resume.",
    });
    setRendererView("autoswitch");
  };
  if (mainWindow.webContents.isLoadingMainFrame()) {
    mainWindow.webContents.once("did-finish-load", sendDialog);
    focusMainWindow();
    return;
  }
  sendDialog();
}

function openAutoSwitchPendingDialog(remainingSec = 30) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createSplashWindow();
    createMainWindow();
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  const safeRemainingSec = Math.max(0, Number.isFinite(Number(remainingSec)) ? Math.floor(Number(remainingSec)) : 30);
  const sendDialog = () => {
    mainWindow.webContents.send("desktop:auto-switch-pending", {
      title: "Auto-switch is pending",
      message: `Auto-switch starts in about ${safeRemainingSec} seconds. Stop it now if you want to cancel this switch flow.`,
      remainingSec: safeRemainingSec,
    });
    setRendererView("autoswitch");
  };
  if (mainWindow.webContents.isLoadingMainFrame()) {
    mainWindow.webContents.once("did-finish-load", sendDialog);
    focusMainWindow();
    return;
  }
  sendDialog();
}

async function stopAutoSwitchFromNotificationAction() {
  if (autoSwitchStopInFlight || !apiClient) {
    return;
  }
  autoSwitchStopInFlight = true;
  try {
    await requestWithTokenRefresh("/api/auto-switch/stop", {
      method: "POST",
      body: JSON.stringify({}),
    });
    desktopState = await apiClient.getDesktopState();
    syncDesktopUsageCache(desktopState);
    latestUsagePayload = desktopState?.usage || latestUsagePayload;
    applyTrayFromLatestUsage();
  } catch (error) {
    startupDebugLog("auto-switch-stop-action-failed", {
      message: String(error?.message || error),
    });
  } finally {
    autoSwitchStopInFlight = false;
  }
  openAutoSwitchWarningDialog();
}

function maybeNotifyPendingAutoSwitch(nextDesktopState) {
  const autoState = nextDesktopState?.autoSwitch || {};
  const config = nextDesktopState?.config || {};
  const dueAt = Number(autoState?.pending_switch_due_at || 0);
  if (!dueAt || !Number.isFinite(dueAt)) {
    lastAutoSwitchWarningDueAt = null;
    return;
  }
  const nowSec = Date.now() / 1000;
  const remainingSec = Math.max(0, Math.floor(dueAt - nowSec));
  if (remainingSec > 30) {
    return;
  }
  if (!notificationsEnabled(config)) {
    return;
  }
  if (!nextDesktopState?.usage) {
    return;
  }
  const dueKey = String(Math.floor(dueAt));
  if (lastAutoSwitchWarningDueAt === dueKey) {
    return;
  }
  lastAutoSwitchWarningDueAt = dueKey;
  sendUsageNotification(
    Notification,
    nextDesktopState.usage,
    () => openAutoSwitchPendingDialog(remainingSec),
    getIconPath(),
    {
      body: `Auto switch starts in ${remainingSec} seconds`,
      actions: [{ type: "button", text: "Stop switch" }],
      onAction: (actionIndex) => {
        if (Number(actionIndex) === 0) {
          stopAutoSwitchFromNotificationAction().catch(() => {});
        }
      },
    },
  );
}

function cycleRendererView(step = 1) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send("desktop:cycle-view", Number(step) < 0 ? -1 : 1);
  focusMainWindow();
}

function requestRendererRefresh() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send("desktop:refresh-requested");
  focusMainWindow();
}

function syncDesktopUsageCache(nextState) {
  if (!nextState || typeof nextState !== "object") {
    return;
  }
  latestUsagePayload = nextState.usage || null;
  applyTrayFromLatestUsage();
}

function toggleRendererSidebar() {
  if (mainWindow) {
    mainWindow.webContents.send("desktop:toggle-sidebar");
    focusMainWindow();
  }
}

function clampZoomFactor(value) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(ZOOM_FACTOR_MAX, Math.max(ZOOM_FACTOR_MIN, value));
}

function setMainWindowZoomFactor(nextFactor) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const clamped = clampZoomFactor(nextFactor);
  const rounded = Math.round(clamped * 100) / 100;
  mainWindow.webContents.setZoomFactor(rounded);
}

function adjustMainWindowZoom(delta) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const current = Number(mainWindow.webContents.getZoomFactor() || 1);
  setMainWindowZoomFactor(current + delta);
}

function getInputModifierSet(input = {}) {
  const modifiers = Array.isArray(input.modifiers) ? input.modifiers : [];
  return new Set(modifiers.map((value) => String(value || "").toLowerCase()));
}

function hasPrimaryModifier(input = {}) {
  const modifierSet = getInputModifierSet(input);
  if (process.platform === "darwin") {
    return Boolean(input.meta || modifierSet.has("meta") || modifierSet.has("command") || modifierSet.has("cmd"));
  }
  return Boolean(input.control || modifierSet.has("control") || modifierSet.has("ctrl"));
}

function hasAltModifier(input = {}) {
  const modifierSet = getInputModifierSet(input);
  return Boolean(input.alt || modifierSet.has("alt"));
}

function getInputType(input = {}) {
  return String(input.type || "").toLowerCase();
}

function getWheelDeltaY(input = {}) {
  const deltaY = Number(input.deltaY);
  if (Number.isFinite(deltaY) && deltaY !== 0) return deltaY;
  const wheelDelta = Number(input.wheelDelta);
  if (Number.isFinite(wheelDelta) && wheelDelta !== 0) return -wheelDelta;
  return 0;
}

function isZoomInShortcutInput(input = {}) {
  const key = String(input.key || "").toLowerCase();
  const code = String(input.code || "");
  const keyCode = Number(input.keyCode);
  return key === "+"
    || key === "="
    || key === "plus"
    || key === "add"
    || code === "Equal"
    || code === "NumpadAdd"
    || keyCode === 187
    || keyCode === 107
    || keyCode === 61
    || keyCode === 171;
}

function isZoomOutShortcutInput(input = {}) {
  const key = String(input.key || "").toLowerCase();
  const code = String(input.code || "");
  const keyCode = Number(input.keyCode);
  return key === "-"
    || key === "_"
    || key === "subtract"
    || code === "Minus"
    || code === "NumpadSubtract"
    || keyCode === 189
    || keyCode === 109;
}

function isZoomResetShortcutInput(input = {}) {
  const key = String(input.key || "");
  const code = String(input.code || "");
  const keyCode = Number(input.keyCode);
  return key === "0" || code === "Digit0" || code === "Numpad0" || keyCode === 48 || keyCode === 96;
}

function buildSplashHtml(iconUrl) {
  return [
    "<!doctype html>",
    "<html><head><meta charset=\"utf-8\" />",
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />",
    "<style>",
    "html, body { margin:0; width:100%; height:100%; overflow:hidden; }",
    "body { display:flex; align-items:center; justify-content:center; background:radial-gradient(circle at 32% 20%, #132238, #081019 62%); font-family:'Segoe UI', Arial, sans-serif; color:#d9ecff; }",
    ".card { width:100%; height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:16px; }",
    ".icon-wrap { width:78px; height:78px; border-radius:18px; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.14); display:flex; align-items:center; justify-content:center; box-shadow:0 16px 36px rgba(0,0,0,0.32); }",
    ".icon { width:54px; height:54px; object-fit:contain; }",
    ".title { font-size:20px; font-weight:700; letter-spacing:0.3px; text-shadow:0 1px 4px rgba(0,0,0,0.35); }",
    ".subtitle { font-size:13px; color:rgba(217,236,255,0.78); letter-spacing:0.2px; }",
    ".loader { width:180px; height:5px; border-radius:999px; background:rgba(255,255,255,0.14); overflow:hidden; }",
    ".bar { width:35%; height:100%; border-radius:999px; background:linear-gradient(90deg, #34d399, #22c55e, #16a34a); animation:slide 1.05s ease-in-out infinite; }",
    "@keyframes slide { 0% { transform:translateX(-110%); } 100% { transform:translateX(390%); } }",
    "</style></head><body>",
    "<div class=\"card\">",
    `<div class="icon-wrap"><img class="icon" src="${iconUrl}" alt="App icon" /></div>`,
    `<div class="title">${APP_NAME}</div>`,
    "<div class=\"subtitle\">Launching desktop runtime...</div>",
    "<div class=\"loader\"><div class=\"bar\"></div></div>",
    "</div>",
    "</body></html>",
  ].join("");
}

function createSplashWindow() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    return splashWindow;
  }
  const iconPath = getWindowIconPath();
  const iconUrl = pathToFileURL(getIconPath()).toString();
  splashWindow = new BrowserWindow({
    width: 440,
    height: 320,
    minWidth: 440,
    minHeight: 320,
    maxWidth: 440,
    maxHeight: 320,
    frame: false,
    resizable: false,
    movable: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    show: false,
    backgroundColor: "#081019",
    autoHideMenuBar: true,
    skipTaskbar: true,
    center: true,
    icon: iconPath,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  splashWindow.once("ready-to-show", () => splashWindow?.show());
  splashWindow.on("closed", () => {
    splashWindow = null;
  });
  splashWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(buildSplashHtml(iconUrl))}`).catch(() => {});
  return splashWindow;
}

function destroySplashWindow() {
  if (!splashWindow || splashWindow.isDestroyed()) {
    splashWindow = null;
    return;
  }
  splashWindow.close();
}

function createMainWindow() {
  const iconPath = getWindowIconPath();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 560,
    title: DESKTOP_APP_NAME,
    icon: iconPath,
    show: false,
    webPreferences: {
      preload: require.resolve("./preload"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  if (process.platform === "win32" && typeof mainWindow.setAppDetails === "function") {
    try {
      mainWindow.setAppDetails({
        appId: DESKTOP_APP_ID,
        appIconPath: iconPath,
        appIconIndex: 0,
        relaunchDisplayName: DESKTOP_APP_NAME,
        relaunchCommand: process.execPath,
      });
    } catch (_) {
      // Ignore setAppDetails failures; BrowserWindow icon is still applied.
    }
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    const loadUrl = getLoadUrl();
    if ((loadUrl && url.startsWith(loadUrl)) || url.startsWith(backendState.baseUrl)) {
      return { action: "allow" };
    }
    return { action: "deny" };
  });

  mainWindow.webContents.on("before-input-event", (event, input) => {
    const inputType = getInputType(input);
    if ((inputType === "mousewheel" || inputType === "wheel") && hasPrimaryModifier(input) && !hasAltModifier(input)) {
      event.preventDefault();
      const deltaY = getWheelDeltaY(input);
      if (deltaY < 0) {
        adjustMainWindowZoom(ZOOM_FACTOR_STEP);
      } else if (deltaY > 0) {
        adjustMainWindowZoom(-ZOOM_FACTOR_STEP);
      }
      return;
    }
    if (!["keydown", "rawkeydown"].includes(inputType)) {
      return;
    }
    if (!hasPrimaryModifier(input) || hasAltModifier(input)) {
      return;
    }
    if (isZoomInShortcutInput(input)) {
      event.preventDefault();
      adjustMainWindowZoom(ZOOM_FACTOR_STEP);
      return;
    }
    if (isZoomOutShortcutInput(input)) {
      event.preventDefault();
      adjustMainWindowZoom(-ZOOM_FACTOR_STEP);
      return;
    }
    if (isZoomResetShortcutInput(input)) {
      event.preventDefault();
      setMainWindowZoomFactor(1);
    }
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    destroySplashWindow();
  });
  mainWindow.webContents.once("did-finish-load", () => {
    destroySplashWindow();
  });
  mainWindow.webContents.once("did-fail-load", () => {
    destroySplashWindow();
  });
  const loadUrl = getLoadUrl();
  if (loadUrl) {
    mainWindow.loadURL(loadUrl);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
  mainWindow.on("close", (event) => {
    startupDebugLog("main-window-close", {
      isQuitting: Boolean(app.isQuitting),
      hasTray: Boolean(tray),
      prevented: Boolean(!app.isQuitting && tray),
    });
    if (!app.isQuitting && tray) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on("closed", () => {
    startupDebugLog("main-window-closed", {});
    mainWindow = null;
  });
  applyWindowsTaskbarUsage({
    windowLike: mainWindow,
    nativeImage,
    summary: buildUsageSummary(latestUsagePayload),
    config: desktopState?.config,
  });
}

async function refreshUsage() {
  try {
    if (apiClient) {
      desktopState = await apiClient.getDesktopState();
      maybeNotifyPendingAutoSwitch(desktopState);
      latestUsagePayload = desktopState.usage;
    } else {
      latestUsagePayload = await fetchCurrentUsage(backendState);
    }
  } catch (_) {
    latestUsagePayload = null;
  }
  const summary = buildUsageSummary(latestUsagePayload);
  syncDesktopTray(summary, desktopState?.config);
  syncWindowsMiniMeter({ summary, config: desktopState?.config });
  return summary;
}

function applyTrayFromLatestUsage() {
  const summary = buildUsageSummary(latestUsagePayload);
  syncDesktopTray(summary, desktopState?.config);
  applyWindowsTaskbarUsage({
    windowLike: mainWindow,
    nativeImage,
    summary,
    config: desktopState?.config,
  });
  syncWindowsMiniMeter({ summary, config: desktopState?.config });
  return summary;
}

async function sendTestNotification() {
  if (!latestUsagePayload) {
    await refreshUsage();
  }
  return sendUsageNotification(Notification, latestUsagePayload, openProfilesFromNotification, getIconPath());
}

function notifySwitchIfEnabled(nextDesktopState, previousProfileName = "") {
  const nextProfileName = String(nextDesktopState?.usage?.current_profile || nextDesktopState?.current?.profile_name || "").trim();
  const previousName = String(previousProfileName || "").trim();
  if (!nextProfileName || nextProfileName === previousName) {
    return { ok: false, reason: "No switched profile to notify." };
  }
  if (!notificationsEnabled(nextDesktopState?.config || {})) {
    return { ok: false, reason: "Notifications are disabled in desktop settings." };
  }
  return sendUsageNotification(Notification, nextDesktopState?.usage, openProfilesFromNotification, getIconPath());
}

function openWebPanel() {
  const targetUrl = String(backendState?.baseUrl || getDefaultBackendState().baseUrl || "http://127.0.0.1:4673/").trim();
  if (!targetUrl) {
    return;
  }
  shell.openExternal(targetUrl).catch(() => {});
}

function restartDesktopAppAndService() {
  const coreCommand = runtimeState?.core?.commandPath ? { command: runtimeState.core.commandPath } : {};
  runServiceCommand("restart", coreCommand);
  markQuitContext("restart-desktop-app-and-service", { coreCommand: coreCommand.command || "" });
  app.isQuitting = true;
  app.relaunch();
  app.exit(0);
}

function buildTrayActions() {
  return {
    onOpen: focusMainWindow,
    onOpenWebPanel: openWebPanel,
    onRefresh: () => {
      refreshUsage().catch(() => {});
    },
    onNotify: () => {
      sendTestNotification().catch(() => {});
    },
    onRestartService: restartDesktopAppAndService,
    onQuit: () => {
      requestAppQuit("tray-quit");
    },
  };
}

function buildMenuActions() {
  const coreCommand = runtimeState?.core?.commandPath ? { command: runtimeState.core.commandPath } : {};
  const quitAppAndStopCore = () => {
    runServiceCommand("kill-all", coreCommand);
    runServiceCommand("stop", coreCommand);
    requestAppQuit("menu-quit-and-stop-core", { coreCommand: coreCommand.command || "" });
  };

  return {
    onAbout: () => setRendererView("about"),
    onProfiles: () => setRendererView("profiles"),
    onAutoSwitch: () => setRendererView("autoswitch"),
    onSettings: () => setRendererView("settings"),
    onGuide: () => setRendererView("guide"),
    onUpdate: () => setRendererView("update"),
    onDebug: () => setRendererView("debug"),
    onUpdates: () => setRendererView("update"),
    onRefresh: () => {
      refreshUsage().catch(() => {});
      setRendererView("profiles");
      requestRendererRefresh();
    },
    onTestNotification: () => {
      sendTestNotification().catch(() => {});
    },
    onToggleSidebar: toggleRendererSidebar,
    onNextSection: () => cycleRendererView(1),
    onPreviousSection: () => cycleRendererView(-1),
    onZoomIn: () => adjustMainWindowZoom(ZOOM_FACTOR_STEP),
    onZoomOut: () => adjustMainWindowZoom(-ZOOM_FACTOR_STEP),
    onZoomReset: () => setMainWindowZoomFactor(1),
    onQuit: () => {
      requestAppQuit("menu-quit");
    },
    onQuitAndStopCore: quitAppAndStopCore,
  };
}

function installApplicationMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate(buildApplicationMenuTemplate({
    isMac: process.platform === "darwin",
    isDev: !app.isPackaged,
    actions: buildMenuActions(),
  })));
}

function createDesktopTray() {
  if (tray) {
    return tray;
  }
  const summary = buildUsageSummary(latestUsagePayload);
  tray = createTray({
    Tray,
    Menu,
    nativeImage,
    summary,
    actions: buildTrayActions(),
  });
  return tray;
}

function destroyDesktopTray() {
  if (!tray) {
    return;
  }
  if (typeof tray.destroy === "function") {
    tray.destroy();
  }
  tray = null;
}

function syncDesktopTray(summary = buildUsageSummary(latestUsagePayload), config = desktopState?.config) {
  if (process.env.CAM_ELECTRON_DISABLE_TRAY === "1") {
    destroyDesktopTray();
    return;
  }
  if (!statusBarEnabled(config, process.platform)) {
    destroyDesktopTray();
    return;
  }
  if (!tray) {
    createDesktopTray();
  }
  if (tray) {
    applyTrayState({ tray, Menu, summary, actions: buildTrayActions(), nativeImage });
  }
}

function createMockDesktopState() {
  return {
    current: { ok: true, profile_name: "work", account_hint: "work@example.test", email: "work@example.test" },
    list: {
      profiles: [
        { name: "work", email: "work@example.test", account_hint: "work@example.test | id:work-001", account_id: "work-001", is_current: true, auto_switch_eligible: true },
        { name: "backup", email: "backup@example.test", account_hint: "backup@example.test | id:backup-002", account_id: "backup-002", is_current: false, auto_switch_eligible: true },
      ],
    },
    usage: {
      current_profile: "work",
      profiles: [
        { name: "work", email: "work@example.test", account_hint: "work@example.test | id:work-001", account_id: "work-001", is_current: true, auto_switch_eligible: true, usage_5h: { remaining_percent: 49, resets_at: Math.floor(Date.now() / 1000) + 4100 }, usage_weekly: { remaining_percent: 88, resets_at: Math.floor(Date.now() / 1000) + 172800 } },
        { name: "backup", email: "backup@example.test", account_hint: "backup@example.test | id:backup-002", account_id: "backup-002", is_current: false, auto_switch_eligible: true, usage_5h: { remaining_percent: 92, resets_at: Math.floor(Date.now() / 1000) + 6500 }, usage_weekly: { remaining_percent: 97, resets_at: Math.floor(Date.now() / 1000) + 259200 } },
      ],
    },
    config: {
      ui: {
        theme: "auto",
        current_auto_refresh_enabled: true,
        current_refresh_interval_sec: 5,
        all_auto_refresh_enabled: true,
        all_refresh_interval_min: 5,
        macos_status_bar_enabled: true,
        windows_taskbar_usage_enabled: false,
        windows_mini_meter_enabled: false,
        windows_mini_meter_drag_enabled: false,
        windows_mini_meter_font_size: 14,
        windows_mini_meter_display_target: "follow_focus",
        windows_mini_meter_display_mode: "follow_focus",
      },
      notifications: { enabled: true, thresholds: { h5_warn_pct: 20, weekly_warn_pct: 20 } },
      auto_switch: { enabled: false, delay_sec: 60, ranking_mode: "balanced", thresholds: { h5_switch_pct: 20, weekly_switch_pct: 20 } },
    },
    autoSwitch: { enabled: false, switch_in_flight: false, pending_switch_due_at: null, pending_switch_due_at_text: "-" },
  };
}

function createMockApiClient() {
  const switchDelayMs = Number(process.env.CAM_ELECTRON_MOCK_SWITCH_DELAY_MS || 0);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  let exportIdCounter = 1;
  let addSessionCounter = 1;
  let updateAvailable = false;
  let releaseNotes = {
    status: "synced",
    status_text: "Synced from GitHub",
    source: "github",
    repo_url: "https://github.com/alisinaee/Codex-Account-Manager/releases",
    releases: [
      {
        tag: "v0.0.20",
        version: "v0.0.20",
        title: "v0.0.20",
        published_at: "2026-04-23T10:00:00Z",
        body: "Mock release notes",
        highlights: ["Mock release notes"],
        url: "https://example.com/release",
        is_prerelease: false,
        is_draft: false,
        is_current: false,
        source: "github",
      },
    ],
  };
  function nextState() {
    return createMockDesktopState();
  }
  function setCurrentProfile(name) {
    const state = nextState();
    state.current.profile_name = name;
    state.usage.current_profile = name;
    state.usage.profiles = state.usage.profiles.map((row) => ({ ...row, is_current: row.name === name }));
    state.list.profiles = state.list.profiles.map((row) => ({ ...row, is_current: row.name === name }));
    return state;
  }
  async function request(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const state = desktopState || (desktopState = nextState());
    const body = options.body ? JSON.parse(options.body) : {};
    if (method === "GET" && path === "/api/current") return state.current;
    if (method === "GET" && path === "/api/list") return state.list;
    if (method === "GET" && (path === "/api/usage-local" || path.startsWith("/api/usage-local?"))) return state.usage;
    if (method === "GET" && path.startsWith("/api/usage-local/current")) return state.usage;
    if (method === "GET" && path.startsWith("/api/usage-local/profile")) return state.usage;
    if (method === "GET" && path.startsWith("/api/health")) return { ok: true, version: "mock-ui-version" };
    if (method === "GET" && path === "/api/ui-config") return state.config;
    if (method === "GET" && path === "/api/auto-switch/state") return state.autoSwitch;
    if (method === "GET" && path === "/api/auto-switch/chain") {
      const chain = state.list.profiles.map((row) => row.name);
      return { chain, items: chain.map((name) => ({ name, remaining_5h: null, remaining_weekly: null })), manual_chain: chain, chain_text: chain.join(" -> ") || "-" };
    }
    if (method === "GET" && path === "/api/release-notes") return releaseNotes;
    if (method === "GET" && path.startsWith("/api/debug/logs")) {
      return { logs: [{ ts: new Date().toISOString(), level: "info", message: "mock log", details: {} }] };
    }
    if (method === "GET" && path === "/api/app-update-status") {
      return {
        status: "synced",
        update_available: updateAvailable,
        latest_version: "v0.0.20",
        latest_release: clone(releaseNotes.releases[0]),
        current_version: "v0.0.20",
        release_notes: clone(releaseNotes),
      };
    }
    if (method === "POST" && path === "/api/local/switch") {
      const name = String(body.name || "").trim();
      if (switchDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, switchDelayMs));
      }
      desktopState = setCurrentProfile(name);
      latestUsagePayload = desktopState.usage;
      return { switched: true, name };
    }
    if (method === "POST" && path === "/api/ui-config") {
      desktopState = {
        ...state,
        config: {
          ...state.config,
          ...body,
          ui: { ...(state.config.ui || {}), ...(body.ui || {}) },
          notifications: { ...(state.config.notifications || {}), ...(body.notifications || {}) },
          auto_switch: { ...(state.config.auto_switch || {}), ...(body.auto_switch || {}) },
        },
      };
      return desktopState.config;
    }
    if (method === "POST" && path === "/api/notifications/native-test") return { ok: true, profile_name: state.usage.current_profile };
    if (method === "POST" && path === "/api/system/restart") return { restarting: true, reload_after_ms: 50 };
    if (method === "POST" && path === "/api/system/kill-all") return { killed: true };
    if (method === "POST" && path === "/api/system/update") {
      updateAvailable = false;
      return { updated: true, stdout: "updated", stderr: "", command: ["pipx", "upgrade"], returncode: 0, update_status: { update_available: false, latest_version: "v0.0.20" } };
    }
    if (method === "POST" && path === "/api/local/remove-all") {
      desktopState = { ...state, list: { profiles: [] }, usage: { current_profile: null, profiles: [] } };
      return { removed: true };
    }
    if (method === "POST" && path === "/api/local/rename") {
      const oldName = String(body.old_name || "").trim();
      const newName = String(body.new_name || "").trim();
      const renamed = clone(state);
      renamed.list.profiles = renamed.list.profiles.map((row) => (row.name === oldName ? { ...row, name: newName } : row));
      renamed.usage.profiles = renamed.usage.profiles.map((row) => (row.name === oldName ? { ...row, name: newName } : row));
      if (renamed.current?.profile_name === oldName) renamed.current.profile_name = newName;
      if (renamed.usage.current_profile === oldName) renamed.usage.current_profile = newName;
      desktopState = renamed;
      latestUsagePayload = desktopState.usage;
      return { renamed: true, old_name: oldName, new_name: newName };
    }
    if (method === "POST" && path === "/api/local/remove") {
      const name = String(body.name || "").trim();
      desktopState = {
        ...state,
        list: { profiles: state.list.profiles.filter((row) => row.name !== name) },
        usage: { ...state.usage, profiles: state.usage.profiles.filter((row) => row.name !== name) },
      };
      latestUsagePayload = desktopState.usage;
      return { removed: true, name };
    }
    if (method === "POST" && path === "/api/local/add") {
      const name = String(body.name || "").trim();
      desktopState = {
        ...state,
        list: { profiles: [...state.list.profiles, { name, account_hint: `${name}@example.test`, is_current: false }] },
        usage: {
          ...state.usage,
          profiles: [...state.usage.profiles, { name, is_current: false, usage_5h: { remaining_percent: 90 }, usage_weekly: { remaining_percent: 90 } }],
        },
      };
      latestUsagePayload = desktopState.usage;
      return { added: true, name };
    }
    if (method === "POST" && path === "/api/local/add/start") {
      const name = String(body.name || "").trim();
      return { session_id: `mock-session-${addSessionCounter++}`, profile_name: name, url: "https://example.com/device", code: "ABCD-EFGH", status: "ready" };
    }
    if (method === "POST" && path === "/api/local/add/cancel") return { cancelled: true };
    if (method === "POST" && path === "/api/local/export/prepare") return { export_id: `mock-export-${exportIdCounter++}`, filename: "profiles.camzip", count: Array.isArray(body.names) ? body.names.length : 0 };
    if (method === "POST" && path === "/api/local/import/analyze") return { analysis_id: "mock-analysis", profiles: [{ name: "work", action: "import" }] };
    if (method === "POST" && path === "/api/local/import/apply") return { summary: { imported: 1, skipped: 0, overwritten: 0, failed: 0 } };
    if (method === "POST" && path === "/api/auto-switch/enable") {
      desktopState = { ...state, autoSwitch: { ...state.autoSwitch, enabled: Boolean(body.enabled) } };
      return desktopState.autoSwitch;
    }
    if (method === "POST" && path === "/api/auto-switch/chain") return { chain: state.list.profiles.map((row) => row.name), items: [], manual_chain: state.list.profiles.map((row) => row.name), chain_text: "mock" };
    if (method === "POST" && path === "/api/auto-switch/auto-arrange") return { chain: state.list.profiles.map((row) => row.name), items: [], manual_chain: state.list.profiles.map((row) => row.name), chain_text: "mock" };
    if (method === "POST" && path === "/api/auto-switch/run-switch") return { started: true };
    if (method === "POST" && path === "/api/auto-switch/rapid-test") return { started: true };
    if (method === "POST" && path === "/api/auto-switch/test-notif") {
      const nowSec = Math.floor(Date.now() / 1000);
      desktopState = {
        ...state,
        autoSwitch: {
          ...state.autoSwitch,
          enabled: true,
          pending_warning: {
            current: state.usage.current_profile,
            detail: { test_notif: true, target: state.list.profiles.find((row) => !row.is_current)?.name || "", lead_sec: 25 },
            created_at: nowSec,
          },
          pending_switch_due_at: nowSec + 25,
        },
      };
      return { armed: true, lead_sec: 25, current: state.usage.current_profile };
    }
    if (method === "POST" && path === "/api/auto-switch/stop") {
      desktopState = {
        ...state,
        autoSwitch: {
          ...state.autoSwitch,
          enabled: false,
          pending_switch_due_at: null,
          pending_warning: null,
        },
      };
      return desktopState.autoSwitch;
    }
    if (method === "POST" && path === "/api/auto-switch/stop-tests") return { stopped: true };
    if (method === "POST" && path === "/api/auto-switch/test") return { switched: false, used_threshold_5h: body.threshold_5h ?? null, timeout_sec: body.timeout_sec ?? 30 };
    if (method === "POST" && path === "/api/auto-switch/account-eligibility") return { name: body.name, eligible: Boolean(body.eligible) };
    if (method === "POST" && path === "/api/adv/status") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/list") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/login") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/switch") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/remove") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/import") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/config") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/daemon") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/clean") return { exit_code: 0, stdout: "", stderr: "" };
    if (method === "POST" && path === "/api/adv/auth") return { exit_code: 0, stdout: "", stderr: "" };
    throw new Error(`mock request not implemented: ${method} ${path}`);
  }
  return {
    getDesktopState: async () => {
      desktopState = createMockDesktopState();
      latestUsagePayload = desktopState.usage;
      return desktopState;
    },
    saveConfigPatch: async () => createMockDesktopState(),
    switchProfile: async (name) => {
      if (switchDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, switchDelayMs));
      }
      desktopState = setCurrentProfile(name);
      latestUsagePayload = desktopState.usage;
      return desktopState;
    },
    request,
  };
}

async function ensureReadyRuntimeBackend() {
  const forceRestart = desktopIdentity.isDevShell && !devBackendRestarted;
  if (forceRestart) {
    devBackendRestarted = true;
  }
  startupDebugLog("backend-ensure-start", {
    command: runtimeState.core.commandPath || "",
    forceRestart,
  });
  backendState = await ensureBackendRunning({
    command: runtimeState.core.commandPath || undefined,
    forceRestart,
  });
  startupDebugLog("backend-ensure-complete", {
    baseUrl: backendState.baseUrl,
    running: Boolean(backendState.running),
  });
  apiClient = createApiClient({ state: backendState });
  setRuntimeState({
    ...runtimeState,
    phase: "ready",
    message: "",
    uiService: {
      ...backendState,
      running: true,
      healthy: true,
    },
  });
}

async function ensureTrayRefreshLoop() {
  if (process.env.CAM_ELECTRON_DISABLE_TRAY === "1") {
    return;
  }
  await refreshUsage();
  if (!refreshTimer) {
    refreshTimer = setInterval(() => {
      refreshUsage().catch(() => {});
    }, Number(process.env.CAM_ELECTRON_REFRESH_MS || 30000));
  }
}

async function checkRuntime({ activateBackend = true } = {}) {
  runtimeProgress = [];
  if (process.env.CAM_ELECTRON_SKIP_BACKEND === "1") {
    apiClient = createMockApiClient();
    desktopState = await apiClient.getDesktopState();
    latestUsagePayload = desktopState.usage;
    setRuntimeState({
      phase: "ready",
      python: { available: true, supported: true, version: process.versions.node, path: process.execPath, command: process.execPath },
      core: { installed: true, version: "mock", commandPath: "mock-core", minSupportedVersion: "0.0.20", meetsMinimumVersion: true },
      uiService: { ...getDefaultBackendState(), running: true, healthy: true, token: "mock-token" },
      errors: [],
      mockMode: true,
    });
    return runtimeState;
  }

  const discovered = await resolveRuntimeStatus({
    loadStoredRuntimeState: () => loadStoredRuntimeState({ appLike: app }),
  });
  setRuntimeState(discovered);

  if (runtimeState.phase !== "ready" || !activateBackend) {
    return runtimeState;
  }

  setRuntimeState({
    ...runtimeState,
    phase: "service_starting",
    message: "Starting the local Python service...",
  });
  try {
    await ensureReadyRuntimeBackend();
    await ensureTrayRefreshLoop();
  } catch (error) {
    apiClient = null;
    desktopState = null;
    setRuntimeState({
      ...runtimeState,
      phase: "error",
      reason: "backend_start_failed",
      message: String(error?.message || error),
      errors: [...runtimeState.errors, { code: "BACKEND_START_FAILED", message: String(error?.message || error) }],
    });
  }
  return runtimeState;
}

function registerIpcHandlers() {
  const handle = (channel, listener) => {
    ipcMain.removeHandler(channel);
    ipcMain.handle(channel, listener);
    registeredIpcChannels.push(channel);
  };

  registeredIpcChannels = [];
  handle("desktop:debug-ipc", async () => ({
    appPath: app.getAppPath(),
    cwd: process.cwd(),
    pid: process.pid,
    channels: registeredIpcChannels,
    mainFile: __filename,
  }));
  handle("desktop:get-runtime-status", async () => runtimeState);
  handle("desktop:get-update-status", async (event, options = {}) => getUnifiedUpdateStatus({ force: Boolean(options?.force) }));
  handle("desktop:copy-runtime-diagnostics", async () => {
    const payload = await collectRuntimeDiagnostics();
    const text = formatRuntimeDiagnostics(payload);
    clipboard.writeText(text);
    return { copied: true, text };
  });
  handle("desktop:retry-runtime-check", async () => checkRuntime({ activateBackend: true }));
  const installCoreHandler = async () => {
    if (!runtimeState.python.available || !runtimeState.python.supported) {
      throw new Error("Python 3.11+ must be installed before the core can be bootstrapped.");
    }
    try {
      pushRuntimeProgress({ type: "run", status: "starting", label: "Bootstrap Python core" });
      await installPythonCore(runtimeState, {
        packageName: process.env.CAM_ELECTRON_CORE_INSTALL_SPEC || buildCoreInstallSpecForVersion(app.getVersion()),
        onProgress: (event) => pushRuntimeProgress(event),
      });
      pushRuntimeProgress({ type: "run", status: "done", label: "Bootstrap Python core" });
      return checkRuntime({ activateBackend: true });
    } catch (error) {
      setRuntimeState({
        ...runtimeState,
        phase: "error",
        reason: "core_install_failed",
        message: String(error?.message || error),
        errors: [...runtimeState.errors, { code: "CORE_INSTALL_FAILED", message: String(error?.message || error) }],
      });
      throw error;
    }
  };
  handle("desktop:install-python-core", installCoreHandler);
  handle("desktop:install-core", installCoreHandler);
  handle("desktop:install-python-runtime", async () => {
    try {
      pushRuntimeProgress({ type: "run", status: "starting", label: "Install Python runtime" });
      await installPythonRuntime(runtimeState, {
        onProgress: (event) => pushRuntimeProgress(event),
      });
      pushRuntimeProgress({ type: "run", status: "done", label: "Install Python runtime" });
      return checkRuntime({ activateBackend: true });
    } catch (error) {
      setRuntimeState({
        ...runtimeState,
        phase: "python_missing",
        reason: "python_install_failed",
        message: String(error?.message || error),
        errors: [...runtimeState.errors, { code: "PYTHON_INSTALL_FAILED", message: String(error?.message || error) }],
      });
      throw error;
    }
  });
  handle("desktop:run-unified-update", async (_event, options = {}) => {
    if (updateRunPromise) {
      return updateRunPromise;
    }
    updateRunPromise = runUnifiedUpdateFlow(options)
      .catch((error) => {
        pushUpdateProgress({
          phase: "failed",
          label: "Update failed",
          status: "failed",
          percent: 100,
          targetVersion: withVersionPrefix(app.getVersion()),
          error: String(error?.message || error),
          detail: String(error?.message || error),
        });
        throw error;
      })
      .finally(() => {
        updateRunPromise = null;
      });
    return updateRunPromise;
  });
  handle("desktop:start-backend-service", async () => checkRuntime({ activateBackend: true }));
  handle("desktop:stop-backend-service", async () => {
    if (runtimeState.core.commandPath) {
      runServiceCommand("stop", { command: runtimeState.core.commandPath });
    }
    apiClient = null;
    desktopState = null;
    latestUsagePayload = null;
    backendState = getDefaultBackendState();
    setRuntimeState({
      ...runtimeState,
      phase: "ready",
      uiService: { ...getDefaultBackendState(), running: false, healthy: false, token: "" },
    });
    return runtimeState;
  });
  handle("desktop:open-external", async (_event, url) => shell.openExternal(String(url || "")));
  handle("desktop:get-state", async () => {
    if (!apiClient) {
      throw new Error(runtimeState.message || "Python core is not ready.");
    }
    if (!desktopState) {
      try {
        desktopState = await apiClient.getDesktopState();
      } catch (error) {
        if (!isInvalidSessionTokenError(error)) {
          throw error;
        }
        await refreshBackendClient();
        desktopState = await apiClient.getDesktopState();
      }
      syncDesktopUsageCache(desktopState);
    }
    return desktopState;
  });
  handle("desktop:get-backend-state", async () => ({
    ...backendState,
    running: Boolean(apiClient && (desktopState || backendState)),
  }));
  handle("desktop:request", async (_event, path, options = {}) => {
    if (!apiClient) {
      throw new Error(runtimeState.message || "desktop request API is unavailable");
    }
    if (typeof apiClient.request === "function") {
      const result = await requestWithTokenRefresh(path, options);
      const method = String(options?.method || "GET").toUpperCase();
      if (method === "GET" && (
        path === "/api/usage-local"
        || path.startsWith("/api/usage-local?")
        || path.startsWith("/api/usage-local/current")
        || path.startsWith("/api/usage-local/profile")
      )) {
        latestUsagePayload = result;
        if (desktopState) {
          desktopState = { ...desktopState, usage: result };
        }
        applyTrayFromLatestUsage();
      }
      if (method === "GET" && path === "/api/current" && desktopState) {
        desktopState = { ...desktopState, current: result };
      }
      if (method === "GET" && path === "/api/list" && desktopState) {
        desktopState = { ...desktopState, list: result };
      }
      if (method === "GET" && path === "/api/auto-switch/state" && desktopState) {
        desktopState = { ...desktopState, autoSwitch: result };
        maybeNotifyPendingAutoSwitch(desktopState);
      }
      if ((method === "GET" || method === "POST") && path === "/api/ui-config") {
        if (desktopState) {
          desktopState = { ...desktopState, config: result };
        }
        applyTrayFromLatestUsage();
      }
      if (shouldInvalidateDesktopStateForRequest(path, options)) {
        desktopState = null;
        lastAutoSwitchWarningDueAt = null;
      }
      return result;
    }
    throw new Error("desktop request API is unavailable");
  });
  handle("desktop:refresh", async () => {
    if (!apiClient) {
      throw new Error(runtimeState.message || "Python core is not ready.");
    }
    try {
      desktopState = await apiClient.getDesktopState();
    } catch (error) {
      if (!isInvalidSessionTokenError(error)) {
        throw error;
      }
      await refreshBackendClient();
      desktopState = await apiClient.getDesktopState();
    }
    latestUsagePayload = desktopState.usage;
    await refreshUsage();
    return desktopState;
  });
  handle("desktop:switch-profile", async (_event, name, options = {}) => {
    if (!apiClient) {
      throw new Error(runtimeState.message || "Python core is not ready.");
    }
    startupDebugLog("switch-profile-start", {
      name: String(name || ""),
      options: options || {},
    });
    const previousProfileName = String(desktopState?.usage?.current_profile || desktopState?.current?.profile_name || "").trim();
    try {
      desktopState = await apiClient.switchProfile(String(name || ""), options || {});
    } catch (error) {
      startupDebugLog("switch-profile-error", {
        name: String(name || ""),
        message: String(error?.message || error),
      });
      if (!isInvalidSessionTokenError(error)) {
        throw error;
      }
      await refreshBackendClient();
      desktopState = await apiClient.switchProfile(String(name || ""), options || {});
    }
    latestUsagePayload = desktopState.usage;
    applyTrayFromLatestUsage();
    notifySwitchIfEnabled(desktopState, previousProfileName);
    startupDebugLog("switch-profile-complete", {
      name: String(name || ""),
      currentProfile: String(desktopState?.usage?.current_profile || desktopState?.current?.profile_name || "").trim(),
    });
    return desktopState;
  });
  handle("desktop:save-config", async (_event, patch) => {
    if (!apiClient) {
      throw new Error(runtimeState.message || "Python core is not ready.");
    }
    try {
      desktopState = await apiClient.saveConfigPatch(patch || {});
    } catch (error) {
      if (!isInvalidSessionTokenError(error)) {
        throw error;
      }
      await refreshBackendClient();
      desktopState = await apiClient.saveConfigPatch(patch || {});
    }
    latestUsagePayload = desktopState.usage;
    applyTrayFromLatestUsage();
    return desktopState;
  });
  handle("desktop:download-export", async (_event, exportId, filename) => {
    return downloadBackendExportArchive({
      backendState,
      exportId,
      filename,
      dialogImpl: dialog,
      windowRef: mainWindow,
    });
  });
  handle("desktop:list-displays", async () => {
    if (process.platform !== "win32") {
      return [];
    }
    return listDesktopDisplays();
  });
  handle("desktop:test-notification", async () => sendTestNotification());
}

async function bootstrap() {
  startupDebugLog("bootstrap-start", {});
  pendingUpdateState = loadPendingUpdateState({ appLike: app, fsImpl: fs });
  registerIpcHandlers();
  if (process.platform === "win32" && screen) {
    const reposition = () => positionWindowsMiniMeter(desktopState?.config || {});
    screen.on("display-metrics-changed", reposition);
    screen.on("display-added", reposition);
    screen.on("display-removed", reposition);
  }
  try {
    ensureWindowsNotificationShortcut({
      shell,
      app,
      appId: DESKTOP_APP_ID,
      appName: DESKTOP_APP_NAME,
      iconPath: process.execPath,
    });
  } catch (error) {
    console.warn(`Windows notification shortcut setup failed: ${String(error?.message || error)}`);
  }
  installApplicationMenu();
  pendingOpenProfilesFromNotification = wasLaunchedFromWindowsNotification(process.argv);
  createSplashWindow();
  createMainWindow();
  if (pendingOpenProfilesFromNotification) {
    openProfilesFromNotification();
  }
  await checkRuntime({ activateBackend: true });
  await maybeResumePendingUpdate();
  startupDebugLog("bootstrap-ready", {
    mainWindowCreated: Boolean(mainWindow),
    splashWindowCreated: Boolean(splashWindow),
  });
}

app.whenReady().then(() => {
  startupDebugLog("when-ready", {});
  bootstrap().catch((error) => {
    startupDebugLog("bootstrap-failed", {
      message: String(error?.message || error),
      stack: String(error?.stack || ""),
    });
    setRuntimeState({
      ...runtimeState,
      phase: "error",
      reason: "bootstrap_failed",
      message: String(error?.message || error),
      errors: [...runtimeState.errors, { code: "BOOTSTRAP_FAILED", message: String(error?.message || error) }],
    });
    if (!mainWindow) {
      createMainWindow();
    }
  });
});

app.on("second-instance", (_event, argv) => {
  startupDebugLog("second-instance", { argv });
  const activateFromNotification = () => {
    if (wasLaunchedFromWindowsNotification(argv)) {
      openProfilesFromNotification();
      return;
    }
    focusMainWindow();
  };
  if (app.isReady()) {
    activateFromNotification();
  } else {
    app.once("ready", activateFromNotification);
  }
});

app.on("activate", () => {
  startupDebugLog("activate", { windowCount: BrowserWindow.getAllWindows().length });
  if (BrowserWindow.getAllWindows().length === 0) {
    createSplashWindow();
    createMainWindow();
  } else {
    focusMainWindow();
  }
});

app.on("before-quit", () => {
  startupDebugLog("before-quit", {
    windowCount: BrowserWindow.getAllWindows().length,
    quitContext: pendingQuitContext,
  });
  app.isQuitting = true;
  if (refreshTimer) {
    clearInterval(refreshTimer);
  }
  if (miniMeterPersistTimer) {
    clearTimeout(miniMeterPersistTimer);
  }
  destroySplashWindow();
  destroyWindowsMiniMeterWindow();
});

app.on("will-quit", () => {
  startupDebugLog("will-quit", {});
});

app.on("quit", (_event, code) => {
  startupDebugLog("quit", { code });
});

app.on("window-all-closed", () => {
  startupDebugLog("window-all-closed", {
    hasTray: Boolean(tray),
    isQuitting: Boolean(app.isQuitting),
  });
  if (shouldQuitOnWindowAllClosed({ hasTray: Boolean(tray), isQuitting: Boolean(app.isQuitting) })) {
    requestAppQuit("window-all-closed");
  }
});

app.on("render-process-gone", (_event, webContents, details) => {
  startupDebugLog("render-process-gone", {
    url: webContents?.getURL?.() || "",
    reason: details?.reason || "",
    exitCode: details?.exitCode ?? null,
  });
});

app.on("child-process-gone", (_event, details) => {
  startupDebugLog("child-process-gone", {
    type: details?.type || "",
    reason: details?.reason || "",
    name: details?.name || "",
    serviceName: details?.serviceName || "",
    exitCode: details?.exitCode ?? null,
  });
});
