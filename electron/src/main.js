"use strict";

const path = require("node:path");
const { app, BrowserWindow, Menu, Notification, Tray, ipcMain, nativeImage } = require("electron");

const { createApiClient } = require("./api-client");
const { ensureBackendRunning, fetchCurrentUsage, getDefaultBackendState, runServiceCommand } = require("./backend");
const { APP_ID, APP_NAME, getIconPath } = require("./icons");
const { buildApplicationMenuTemplate, shouldQuitOnWindowAllClosed } = require("./menu");
const { sendUsageNotification } = require("./notifications");
const { applyTrayState, createTray } = require("./tray");
const { buildUsageSummary } = require("./usage");

app.setName(APP_NAME);
app.name = APP_NAME;
if (typeof app.setAppUserModelId === "function") {
  app.setAppUserModelId(APP_ID);
}

let mainWindow = null;
let tray = null;
let backendState = getDefaultBackendState();
let apiClient = null;
let desktopState = null;
let latestUsagePayload = null;
let refreshTimer = null;

function isInvalidSessionTokenError(error) {
  const message = String(error?.message || "");
  return /invalid session token/i.test(message);
}

async function refreshBackendClient() {
  if (process.env.CAM_ELECTRON_SKIP_BACKEND === "1") {
    return;
  }
  backendState = await ensureBackendRunning();
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
    width: 1240,
    height: 820,
    minWidth: 480,
    minHeight: 640,
    title: APP_NAME,
    icon: iconPath,
    show: false,
    webPreferences: {
      preload: require.resolve("./preload"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
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
    applyTrayState({ tray, Menu, summary, actions: buildTrayActions() });
  }
  return summary;
}

function applyTrayFromLatestUsage() {
  const summary = buildUsageSummary(latestUsagePayload);
  if (tray) {
    applyTrayState({ tray, Menu, summary, actions: buildTrayActions() });
  }
  return summary;
}

async function sendTestNotification() {
  if (!latestUsagePayload) {
    await refreshUsage();
  }
  return sendUsageNotification(Notification, latestUsagePayload, focusMainWindow, getIconPath());
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
    if (method === "GET" && path.startsWith("/api/usage-local/current")) return state.usage;
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

function registerIpcHandlers() {
  ipcMain.handle("desktop:get-state", async () => {
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
  ipcMain.handle("desktop:get-backend-state", async () => ({
    ...backendState,
    running: Boolean(desktopState || backendState),
  }));
  ipcMain.handle("desktop:request", async (_event, path, options = {}) => {
    if (typeof apiClient.request === "function") {
      return requestWithTokenRefresh(path, options);
    }
    throw new Error("desktop request API is unavailable");
  });
  ipcMain.handle("desktop:refresh", async () => {
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
  ipcMain.handle("desktop:switch-profile", async (_event, name) => {
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
    return desktopState;
  });
  ipcMain.handle("desktop:save-config", async (_event, patch) => {
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
  ipcMain.handle("desktop:test-notification", async () => sendTestNotification());
}

async function bootstrap() {
  if (process.env.CAM_ELECTRON_SKIP_BACKEND !== "1") {
    backendState = await ensureBackendRunning();
    apiClient = createApiClient({ state: backendState });
  } else {
    apiClient = createMockApiClient();
    desktopState = await apiClient.getDesktopState();
  }
  registerIpcHandlers();
  installApplicationMenu();
  createMainWindow();
  if (process.env.CAM_ELECTRON_DISABLE_TRAY !== "1") {
    try {
      createDesktopTray();
      await refreshUsage();
      refreshTimer = setInterval(() => {
        refreshUsage().catch(() => {});
      }, Number(process.env.CAM_ELECTRON_REFRESH_MS || 30000));
    } catch (_) {
      tray = null;
    }
  }
}

app.whenReady().then(() => {
  bootstrap().catch((error) => {
    createMainWindow();
    mainWindow.webContents.once("did-finish-load", () => {
      mainWindow.webContents.executeJavaScript(
        `document.body.innerHTML = ${JSON.stringify(`<pre>Failed to start Codex Account Manager desktop shell:\n${error.message}</pre>`)};`,
      );
    });
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
});

app.on("window-all-closed", () => {
  if (shouldQuitOnWindowAllClosed({ hasTray: Boolean(tray), isQuitting: Boolean(app.isQuitting) })) {
    app.quit();
  }
});
