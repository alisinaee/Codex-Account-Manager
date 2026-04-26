const test = require("node:test");
const assert = require("node:assert/strict");

const {
  applyWindowsTaskbarUsage,
  buildTaskbarUsageOverlayDataUrl,
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

test("buildWindowsNotificationShortcutSpec creates a branded start menu shortcut contract", () => {
  const spec = buildWindowsNotificationShortcutSpec({
    platform: "win32",
    appId: "com.codexaccountmanager.desktop",
    appName: "Codex Account Manager",
    iconPath: "C:\\repo\\electron\\assets\\codex-account-manager.png",
    processExecPath: "C:\\repo\\electron\\node_modules\\electron\\dist\\electron.exe",
    app: {
      isPackaged: false,
      getPath(kind) {
        assert.equal(kind, "startMenu");
        return "C:\\Users\\alisi\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu";
      },
      getAppPath() {
        return "C:\\repo\\electron";
      },
    },
  });

  assert.match(spec.shortcutPath, /Codex Account Manager\.lnk$/);
  assert.equal(spec.options.appUserModelId, "com.codexaccountmanager.desktop");
  assert.equal(spec.options.target, "C:\\repo\\electron\\node_modules\\electron\\dist\\electron.exe");
  assert.equal(spec.options.args, "\"C:\\repo\\electron\"");
});
