const test = require("node:test");
const assert = require("node:assert/strict");

const { buildNotificationOptions } = require("../src/notifications");
const {
  buildMacMenuBarTitle,
  buildStatusIconDataUrl,
  buildStatusTone,
  buildTrayMenuTemplate,
  prepareTrayIcon,
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

test("buildTrayMenuTemplate includes readable color-coded desktop status actions", () => {
  const items = buildTrayMenuTemplate({
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
    "5H 48% left",
    "Weekly 78% left",
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
  assert.ok(items[1].icon.startsWith("data:image/svg+xml;base64,"));
  assert.ok(items[2].icon.startsWith("data:image/svg+xml;base64,"));
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
