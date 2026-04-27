"use strict";

const path = require("node:path");
const { app, BrowserWindow, Menu, Notification, Tray, clipboard, ipcMain, nativeImage, screen, shell } = require("electron");

const { createApiClient } = require("./api-client");
const { ensureBackendRunning, fetchCurrentUsage, getDefaultBackendState, runServiceCommand } = require("./backend");
const { APP_ID, APP_NAME, getIconPath } = require("./icons");
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
const { applyTrayState, createTray } = require("./tray");
const { buildUsageSummary } = require("./usage");
const { applyWindowsTaskbarUsage, ensureWindowsNotificationShortcut } = require("./windows-integration");
const { usageHexColor } = require("./usage-thresholds");

app.setName(APP_NAME);
app.name = APP_NAME;
if (typeof app.setAppUserModelId === "function") {
  app.setAppUserModelId(APP_ID);
}

let mainWindow = null;
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
let registeredIpcChannels = [];
const MINI_METER_BASE_FONT_SIZE = 14;

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
  const valueColumnWidth = Math.round(fontSize * 2.85);
  const metricColumnWidth = Math.round(fontSize * 1.85);
  const horizontalPadding = Math.round(fontSize * 0.9);
  const verticalPadding = Math.round(fontSize * 0.56);
  const rowHeight = Math.round(fontSize * 1.06);
  const rowGap = Math.round(fontSize * 0.18);
  return {
    width: Math.max(82, Math.min(172, valueColumnWidth + metricColumnWidth + (horizontalPadding * 2))),
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
    ".meter { box-sizing:border-box; width:100%; height:100%; padding:calc(var(--meter-font-size) * 0.28) calc(var(--meter-font-size) * 0.45); border-radius:calc(var(--meter-font-size) * 0.5); background:rgba(10,12,15,0.90); border:1px solid rgba(255,255,255,0.10); display:flex; flex-direction:column; justify-content:center; gap:calc(var(--meter-font-size) * 0.18); --meter-font-size:14px; }",
    ".meter.draggable { -webkit-app-region: drag; cursor:move; }",
    ".row { display:flex; align-items:center; font-size:var(--meter-font-size); line-height:1.05; font-weight:700; letter-spacing:0.1px; text-shadow:0 0 4px rgba(0,0,0,0.45); }",
    ".five { color:#22c55e; }",
    ".week { color:#22c55e; }",
    ".value { min-width:calc(var(--meter-font-size) * 2.85); margin-right:calc(var(--meter-font-size) * 0.24); }",
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
    minCoreVersion: process.env.CAM_ELECTRON_MIN_CORE_VERSION || "0.0.12",
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

function toggleRendererSidebar() {
  if (mainWindow) {
    mainWindow.webContents.send("desktop:toggle-sidebar");
    focusMainWindow();
  }
}

function createMainWindow() {
  const iconPath = getIconPath();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 560,
    title: APP_NAME,
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

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    const loadUrl = getLoadUrl();
    if ((loadUrl && url.startsWith(loadUrl)) || url.startsWith(backendState.baseUrl)) {
      return { action: "allow" };
    }
    return { action: "deny" };
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  const loadUrl = getLoadUrl();
  if (loadUrl) {
    mainWindow.loadURL(loadUrl);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
  mainWindow.on("close", (event) => {
    if (!app.isQuitting && tray) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on("closed", () => {
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
      latestUsagePayload = desktopState.usage;
    } else {
      latestUsagePayload = await fetchCurrentUsage(backendState);
    }
  } catch (_) {
    latestUsagePayload = null;
  }
  const summary = buildUsageSummary(latestUsagePayload);
  if (tray) {
    applyTrayState({ tray, Menu, summary, actions: buildTrayActions(), nativeImage });
  }
  syncWindowsMiniMeter({ summary, config: desktopState?.config });
  return summary;
}

function applyTrayFromLatestUsage() {
  const summary = buildUsageSummary(latestUsagePayload);
  if (tray) {
    applyTrayState({ tray, Menu, summary, actions: buildTrayActions(), nativeImage });
  }
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
  return sendUsageNotification(Notification, latestUsagePayload, focusMainWindow, getIconPath());
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
  return sendUsageNotification(Notification, nextDesktopState?.usage, focusMainWindow, getIconPath());
}

function buildTrayActions() {
  return {
    onOpen: focusMainWindow,
    onRefresh: () => {
      refreshUsage().catch(() => {});
    },
    onNotify: () => {
      sendTestNotification().catch(() => {});
    },
    onStartService: () => {
      runServiceCommand("start");
    },
    onStopService: () => {
      runServiceCommand("stop");
    },
    onQuit: () => {
      app.isQuitting = true;
      app.quit();
    },
  };
}

function buildMenuActions() {
  return {
    onAbout: () => setRendererView("about"),
    onProfiles: () => setRendererView("profiles"),
    onSettings: () => setRendererView("settings"),
    onUpdates: () => setRendererView("settings"),
    onRefresh: () => {
      refreshUsage().then(() => {
        if (mainWindow) mainWindow.webContents.send("desktop:navigate", "profiles");
      }).catch(() => {});
    },
    onTestNotification: () => {
      sendTestNotification().catch(() => {});
    },
    onToggleSidebar: toggleRendererSidebar,
    onQuit: () => {
      app.isQuitting = true;
      app.quit();
    },
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
  const summary = buildUsageSummary(latestUsagePayload);
  tray = createTray({
    Tray,
    Menu,
    nativeImage,
    summary,
    actions: buildTrayActions(),
  });
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
  let updateAvailable = true;
  let releaseNotes = {
    status: "synced",
    status_text: "Synced from GitHub",
    source: "github",
    repo_url: "https://github.com/alisinaee/Codex-Account-Manager/releases",
    releases: [
      {
        tag: "v0.0.13",
        version: "v0.0.13",
        title: "v0.0.13",
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
        latest_version: "v0.0.13",
        latest_release: clone(releaseNotes.releases[0]),
        current_version: "v0.0.12",
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
      return { updated: true, stdout: "updated", stderr: "", command: ["pipx", "upgrade"], returncode: 0, update_status: { update_available: false, latest_version: "v0.0.13" } };
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
  backendState = await ensureBackendRunning({ command: runtimeState.core.commandPath || undefined });
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
  if (!tray) {
    createDesktopTray();
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
      core: { installed: true, version: "mock", commandPath: "mock-core", minSupportedVersion: "0.0.12", meetsMinimumVersion: true },
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
      if (method === "GET" && (path === "/api/usage-local" || path.startsWith("/api/usage-local?") || path.startsWith("/api/usage-local/current"))) {
        latestUsagePayload = result;
        if (desktopState) {
          desktopState = { ...desktopState, usage: result };
        }
        applyTrayFromLatestUsage();
      }
      if ((method === "GET" || method === "POST") && path === "/api/ui-config") {
        if (desktopState) {
          desktopState = { ...desktopState, config: result };
        }
        applyTrayFromLatestUsage();
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
  handle("desktop:switch-profile", async (_event, name) => {
    if (!apiClient) {
      throw new Error(runtimeState.message || "Python core is not ready.");
    }
    const previousProfileName = String(desktopState?.usage?.current_profile || desktopState?.current?.profile_name || "").trim();
    try {
      desktopState = await apiClient.switchProfile(String(name || ""));
    } catch (error) {
      if (!isInvalidSessionTokenError(error)) {
        throw error;
      }
      await refreshBackendClient();
      desktopState = await apiClient.switchProfile(String(name || ""));
    }
    latestUsagePayload = desktopState.usage;
    applyTrayFromLatestUsage();
    notifySwitchIfEnabled(desktopState, previousProfileName);
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
  handle("desktop:list-displays", async () => {
    if (process.platform !== "win32") {
      return [];
    }
    return listDesktopDisplays();
  });
  handle("desktop:test-notification", async () => sendTestNotification());
}

async function bootstrap() {
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
      appId: APP_ID,
      appName: APP_NAME,
      iconPath: getIconPath(),
    });
  } catch (error) {
    console.warn(`Windows notification shortcut setup failed: ${String(error?.message || error)}`);
  }
  installApplicationMenu();
  createMainWindow();
  await checkRuntime({ activateBackend: true });
}

app.whenReady().then(() => {
  bootstrap().catch((error) => {
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

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  } else {
    focusMainWindow();
  }
});

app.on("before-quit", () => {
  app.isQuitting = true;
  if (refreshTimer) {
    clearInterval(refreshTimer);
  }
  if (miniMeterPersistTimer) {
    clearTimeout(miniMeterPersistTimer);
  }
  destroyWindowsMiniMeterWindow();
});

app.on("window-all-closed", () => {
  if (shouldQuitOnWindowAllClosed({ hasTray: Boolean(tray), isQuitting: Boolean(app.isQuitting) })) {
    app.quit();
  }
});
