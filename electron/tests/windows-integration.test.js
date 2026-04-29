const test = require("node:test");
const assert = require("node:assert/strict");

const {
  applyWindowsTrayUsage,
  applyWindowsTaskbarUsage,
  buildTaskbarUsageOverlayDataUrl,
  buildWindowsTrayUsageDataUrl,
  buildWindowsNotificationShortcutSpec,
  windowsTaskbarUsageEnabled,
} = require("../src/windows-integration");

test("windowsTaskbarUsageEnabled follows the UI config flag", () => {
  assert.equal(windowsTaskbarUsageEnabled({ ui: { windows_taskbar_usage_enabled: true } }), true);
  assert.equal(windowsTaskbarUsageEnabled({ ui: { windows_taskbar_usage_enabled: false } }), false);
  assert.equal(windowsTaskbarUsageEnabled({}), false);
});

test("buildTaskbarUsageOverlayDataUrl emits svg data when usage is available", () => {
  const icon = buildTaskbarUsageOverlayDataUrl({
    available: true,
    fiveHourPercent: 74,
  });
  const decoded = Buffer.from(icon.replace("data:image/svg+xml;base64,", ""), "base64").toString("utf8");

  assert.match(decoded, />74</);
});

test("buildWindowsTrayUsageDataUrl emits compact svg data for tray usage", () => {
  const icon = buildWindowsTrayUsageDataUrl({
    available: true,
    fiveHourPercent: 74,
  });
  const decoded = Buffer.from(icon.replace("data:image/svg+xml;base64,", ""), "base64").toString("utf8");

  assert.match(decoded, />74</);
  assert.match(decoded, /width="16"/);
});

test("applyWindowsTaskbarUsage sets a taskbar overlay when enabled", () => {
  const calls = [];
  const windowLike = {
    setOverlayIcon(icon, description) {
      calls.push([icon, description]);
    },
  };
  const nativeImage = {
    createFromDataURL(dataUrl) {
      return { dataUrl };
    },
  };

  const applied = applyWindowsTaskbarUsage({
    platform: "win32",
    windowLike,
    nativeImage,
    summary: { available: true, profileName: "acc4", fiveHourPercent: 74, weeklyPercent: 55 },
    config: { ui: { windows_taskbar_usage_enabled: true } },
  });

  assert.equal(applied, true);
  assert.match(calls[0][0].dataUrl, /^data:image\/svg\+xml;base64,/);
  assert.match(calls[0][1], /Current acc4: 5H 74% left, Weekly 55% left/);
});

test("applyWindowsTaskbarUsage clears overlay when disabled", () => {
  const calls = [];
  const windowLike = {
    setOverlayIcon(icon, description) {
      calls.push([icon, description]);
    },
  };

  const applied = applyWindowsTaskbarUsage({
    platform: "win32",
    windowLike,
    nativeImage: {},
    summary: { available: true, profileName: "acc4", fiveHourPercent: 74, weeklyPercent: 55 },
    config: { ui: { windows_taskbar_usage_enabled: false } },
  });

  assert.equal(applied, false);
  assert.deepEqual(calls[0], [null, ""]);
});

test("applyWindowsTrayUsage sets a dynamic tray icon on Windows when enabled", () => {
  const calls = [];
  const tray = {
    setImage(image) {
      calls.push(image);
    },
  };
  const defaultIcon = { kind: "default-tray-icon" };
  const nativeImage = {
    createFromDataURL(dataUrl) {
      return { dataUrl };
    },
  };

  const applied = applyWindowsTrayUsage({
    platform: "win32",
    tray,
    nativeImage,
    defaultIcon,
    summary: { available: true, fiveHourPercent: 74 },
    config: { ui: { windows_taskbar_usage_enabled: true } },
  });

  assert.equal(applied, true);
  assert.match(calls[0].dataUrl, /^data:image\/svg\+xml;base64,/);
});

test("applyWindowsTrayUsage restores the default icon when disabled", () => {
  const calls = [];
  const tray = {
    setImage(image) {
      calls.push(image);
    },
  };
  const defaultIcon = { kind: "default-tray-icon" };

  const applied = applyWindowsTrayUsage({
    platform: "win32",
    tray,
    nativeImage: {},
    defaultIcon,
    summary: { available: true, fiveHourPercent: 74 },
    config: { ui: { windows_taskbar_usage_enabled: false } },
  });

  assert.equal(applied, false);
  assert.deepEqual(calls[0], defaultIcon);
});

test("buildWindowsNotificationShortcutSpec returns null for unpackaged apps", () => {
  const spec = buildWindowsNotificationShortcutSpec({
    platform: "win32",
    appId: "com.codexaccountmanager.desktop",
    appName: "Codex Account Manager",
    iconPath: "C:\\repo\\electron\\assets\\codex-account-manager-win.ico",
    processExecPath: "C:\\repo\\electron\\node_modules\\electron\\dist\\electron.exe",
    app: {
      isPackaged: false,
      getPath() {
        return "C:\\Users\\alisi\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu";
      },
    },
  });
  assert.equal(spec, null);
});

test("buildWindowsNotificationShortcutSpec creates a branded start menu shortcut contract", () => {
  const spec = buildWindowsNotificationShortcutSpec({
    platform: "win32",
    appId: "com.codexaccountmanager.desktop",
    appName: "Codex Account Manager",
    iconPath: "C:\\repo\\electron\\assets\\codex-account-manager-win.ico",
    processExecPath: "C:\\repo\\Codex Account Manager.exe",
    app: {
      isPackaged: true,
      getPath(kind) {
        assert.equal(kind, "startMenu");
        return "C:\\Users\\alisi\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu";
      },
    },
  });

  assert.match(spec.shortcutPath, /Codex Account Manager\.lnk$/);
  assert.equal(spec.options.appUserModelId, "com.codexaccountmanager.desktop");
  assert.equal(spec.operation, "update");
  assert.equal(spec.options.target, "C:\\repo\\Codex Account Manager.exe");
  assert.equal(spec.options.args, "");
  assert.equal(spec.options.icon, "C:\\repo\\electron\\assets\\codex-account-manager-win.ico");
});
