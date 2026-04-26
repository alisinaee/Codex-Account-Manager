const test = require("node:test");
const assert = require("node:assert/strict");

const { buildNotificationOptions, notificationsEnabled } = require("../src/notifications");
const {
  buildMacMenuBarTitle,
  buildStatusIconDataUrl,
  buildStatusTone,
  buildTrayMenuTemplate,
  prepareTrayIcon,
  resolveTrayIconPath,
} = require("../src/tray");

test("buildNotificationOptions formats current usage for Electron notifications", () => {
  const payload = {
    current_profile: "work",
    profiles: [
      {
        name: "work",
        usage_5h: { remaining_percent: 51 },
        usage_weekly: { remaining_percent: 77 },
      },
    ],
  };

  assert.deepEqual(buildNotificationOptions(payload), {
    title: "Codex Account Manager",
    subtitle: "Profile work",
    body: "Profile work - 5H 51% left - Weekly 77% left",
    silent: false,
  });
});

test("buildNotificationOptions includes app icon when provided", () => {
  const payload = {
    current_profile: "work",
    profiles: [{ name: "work", usage_5h: { remaining_percent: 51 }, usage_weekly: { remaining_percent: 77 } }],
  };

  assert.equal(buildNotificationOptions(payload, "/tmp/icon.png").icon, "/tmp/icon.png");
});

test("notificationsEnabled follows the desktop notification toggle", () => {
  assert.equal(notificationsEnabled({ notifications: { enabled: true } }), true);
  assert.equal(notificationsEnabled({ notifications: { enabled: false } }), false);
  assert.equal(notificationsEnabled({}), false);
});

test("buildTrayMenuTemplate includes readable color-coded desktop status actions", () => {
  const items = buildTrayMenuTemplate({
    platform: "linux",
    summary: {
      available: true,
      profileName: "acc6",
      fiveHourPercent: 48,
      weeklyPercent: 78,
      trayTitle: "acc6 | 5H 48% | W 78%",
    },
    onOpen: () => {},
    onRefresh: () => {},
    onNotify: () => {},
    onStartService: () => {},
    onStopService: () => {},
    onQuit: () => {},
  });
  const labels = items.map((item) => item.label || item.type);

  assert.deepEqual(labels, [
    "Current acc6",
    "🟡 5H 48% left",
    "🟢 Weekly 78% left",
    "separator",
    "Open Codex Account Manager",
    "Refresh Usage",
    "Send Test Notification",
    "separator",
    "Start UI Service",
    "Stop UI Service",
    "Quit",
  ]);
  assert.equal(items[0].enabled, true);
  assert.equal(items[1].icon, undefined);
  assert.equal(items[2].icon, undefined);
});

test("buildTrayMenuTemplate avoids data-url menu icons on macOS", () => {
  const items = buildTrayMenuTemplate({
    platform: "darwin",
    summary: {
      available: true,
      profileName: "acc6",
      fiveHourPercent: 48,
      weeklyPercent: 78,
    },
    onOpen: () => {},
    onRefresh: () => {},
    onNotify: () => {},
    onStartService: () => {},
    onStopService: () => {},
    onQuit: () => {},
  });

  assert.equal(items[1].icon, undefined);
  assert.equal(items[2].icon, undefined);
  assert.match(items[1].label, /^🟡 /);
  assert.match(items[2].label, /^🟢 /);
});

test("buildMacMenuBarTitle keeps the macOS status bar compact but informative", () => {
  assert.equal(
    buildMacMenuBarTitle({
      available: true,
      profileName: "acc6",
      fiveHourPercent: 62,
      weeklyPercent: 80,
    }),
    "acc6 5H 62% W 80%",
  );
});

test("buildStatusTone colors usage by remaining percentage", () => {
  assert.equal(buildStatusTone(9), "danger");
  assert.equal(buildStatusTone(25), "warning");
  assert.equal(buildStatusTone(49), "caution");
  assert.equal(buildStatusTone(50), "good");
});

test("buildStatusIconDataUrl emits svg data for usage tone", () => {
  const icon = buildStatusIconDataUrl("warning");
  const decoded = Buffer.from(icon.replace("data:image/svg+xml;base64,", ""), "base64").toString("utf8");

  assert.match(decoded, /#ff9f43/);
});

test("prepareTrayIcon resizes macOS tray image and marks it as a template image", () => {
  const calls = [];
  const resized = {
    setTemplateImage(value) {
      calls.push(["setTemplateImage", value]);
    },
  };
  const image = {
    resize(options) {
      calls.push(["resize", options]);
      return resized;
    },
  };

  assert.equal(prepareTrayIcon(image, "darwin"), resized);
  assert.deepEqual(calls, [
    ["resize", { width: 18, height: 18 }],
    ["setTemplateImage", true],
  ]);
});

test("prepareTrayIcon resizes the Windows tray image to a compact 16px icon", () => {
  const calls = [];
  const resized = { kind: "win-resized" };
  const image = {
    resize(options) {
      calls.push(["resize", options]);
      return resized;
    },
  };

  assert.equal(prepareTrayIcon(image, "win32"), resized);
  assert.deepEqual(calls, [
    ["resize", { width: 16, height: 16 }],
  ]);
});

test("resolveTrayIconPath prefers the dedicated tray asset on macOS and Windows", () => {
  assert.match(resolveTrayIconPath("darwin"), /codex-account-manager-tray\.svg$/);
  assert.match(resolveTrayIconPath("win32"), /codex-account-manager\.png$/);
  assert.match(resolveTrayIconPath("linux"), /codex-account-manager\.png$/);
});
