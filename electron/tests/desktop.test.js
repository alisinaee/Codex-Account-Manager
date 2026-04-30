const test = require("node:test");
const assert = require("node:assert/strict");

const { buildNotificationOptions, notificationsEnabled, sendUsageNotification } = require("../src/notifications");
const {
  applyTrayState,
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

test("sendUsageNotification keeps click callback active and invokes it on click", () => {
  class NotificationMock {
    static isSupported() { return true; }
    constructor(options) {
      this.options = options;
      this.handlers = new Map();
    }
    on(event, handler) {
      this.handlers.set(event, handler);
    }
    show() {}
    emit(event, ...args) {
      const handler = this.handlers.get(event);
      if (typeof handler === "function") handler(...args);
    }
  }

  let clicked = 0;
  const result = sendUsageNotification(
    NotificationMock,
    { current_profile: "work", profiles: [{ name: "work", usage_5h: { remaining_percent: 50 }, usage_weekly: { remaining_percent: 80 } }] },
    () => { clicked += 1; },
  );

  assert.equal(result.ok, true);
  // Trigger callback through the same notification instance.
  // In production this is emitted by the native Windows toast activation.
  const instance = new NotificationMock({});
  // Recreate event wiring behavior for assertion by invoking the wired path end-to-end.
  let onClick;
  instance.on = (event, handler) => {
    if (event === "click") onClick = handler;
  };
  sendUsageNotification(
    class InlineNotificationMock extends NotificationMock {
      constructor(options) {
        super(options);
        return instance;
      }
    },
    { current_profile: "work", profiles: [{ name: "work", usage_5h: { remaining_percent: 50 }, usage_weekly: { remaining_percent: 80 } }] },
    () => { clicked += 1; },
  );
  onClick?.();
  assert.equal(clicked, 1);
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
    onOpenWebPanel: () => {},
    onRefresh: () => {},
    onNotify: () => {},
    onRestartService: () => {},
    onQuit: () => {},
  });
  const labels = items.map((item) => item.label || item.type);

  assert.equal(labels[0], "Current acc6");
  assert.match(labels[1], /5H 48% left$/);
  assert.match(labels[2], /Weekly 78% left$/);
  assert.deepEqual(labels.slice(3), [
    "separator",
    "Open Codex Account Manager",
    "Web Panel",
    "Refresh Usage",
    "Send Test Notification",
    "separator",
    "Restart Service",
    "Quit",
  ]);
  assert.equal(items[0].enabled, false);
  assert.equal(items[1].icon, undefined);
  assert.equal(items[2].icon, undefined);
  assert.equal(items[1].enabled, false);
  assert.equal(items[2].enabled, false);
});

test("buildTrayMenuTemplate uses native macOS headers for status rows when supported", () => {
  const items = buildTrayMenuTemplate({
    platform: "darwin",
    macSystemVersion: "14.4.0",
    summary: {
      available: true,
      profileName: "acc6",
      fiveHourPercent: 48,
      weeklyPercent: 78,
    },
    onOpen: () => {},
    onOpenWebPanel: () => {},
    onRefresh: () => {},
    onNotify: () => {},
    onRestartService: () => {},
    onQuit: () => {},
  });

  assert.deepEqual(
    items.slice(0, 3).map((item) => ({ type: item.type, label: item.label })),
    [
      { type: "header", label: "Current acc6" },
      { type: "header", label: "5H 48% left" },
      { type: "header", label: "Weekly 78% left" },
    ],
  );
});

test("buildTrayMenuTemplate falls back to a grouped macOS submenu when header items are unavailable", () => {
  const items = buildTrayMenuTemplate({
    platform: "darwin",
    macSystemVersion: "13.6.0",
    summary: {
      available: true,
      profileName: "acc6",
      fiveHourPercent: 48,
      weeklyPercent: 78,
    },
    onOpen: () => {},
    onOpenWebPanel: () => {},
    onRefresh: () => {},
    onNotify: () => {},
    onRestartService: () => {},
    onQuit: () => {},
  });

  assert.equal(items[0].label, "Status acc6");
  assert.equal(Array.isArray(items[0].submenu), true);
  assert.deepEqual(
    items[0].submenu.map((item) => ({ label: item.label, enabled: item.enabled, icon: item.icon })),
    [
      { label: "🟠 5H 48% left", enabled: false, icon: undefined },
      { label: "🟢 Weekly 78% left", enabled: false, icon: undefined },
    ],
  );
});

test("buildMacMenuBarTitle keeps the macOS fallback title compact and uses standard ansi colors", () => {
  assert.equal(
    buildMacMenuBarTitle({
      available: true,
      profileName: "acc6",
      fiveHourPercent: 9,
      weeklyPercent: 70,
    }),
    "acc6 5H \u001b[31m9%\u001b[0m W \u001b[33m70%\u001b[0m",
  );
});

test("applyTrayState uses macOS tray title with ansi-colored percentages and monospaced digits", () => {
  const calls = [];
  const summary = {
    available: true,
    profileName: "acc6",
    fiveHourPercent: 9,
    weeklyPercent: 70,
    tooltip: "Codex Account Manager\nProfile acc6",
  };
  const tray = {
    setToolTip(value) {
      calls.push(["tooltip", value]);
    },
    setTitle(title, options) {
      calls.push(["title", title, options]);
    },
    setContextMenu(menu) {
      calls.push(["menu", menu]);
    },
  };
  const Menu = {
    buildFromTemplate(template) {
      return { template };
    },
  };

  const originalPlatform = process.platform;
  Object.defineProperty(process, "platform", { value: "darwin" });
  try {
    applyTrayState({ tray, Menu, summary, actions: {} });
  } finally {
    Object.defineProperty(process, "platform", { value: originalPlatform });
  }

  assert.deepEqual(calls[0], ["tooltip", "Codex Account Manager\nProfile acc6"]);
  assert.deepEqual(calls[1], [
    "title",
    "acc6 5H \u001b[31m9%\u001b[0m W \u001b[33m70%\u001b[0m",
    { fontType: "monospacedDigit" },
  ]);
  assert.equal(calls[2][0], "menu");
});

test("buildStatusTone colors usage by remaining percentage", () => {
  assert.equal(buildStatusTone(9), "danger");
  assert.equal(buildStatusTone(25), "danger");
  assert.equal(buildStatusTone(40), "warning");
  assert.equal(buildStatusTone(70), "caution");
  assert.equal(buildStatusTone(90), "good");
});

test("buildStatusIconDataUrl emits svg data for usage tone", () => {
  const icon = buildStatusIconDataUrl("warning");
  const decoded = Buffer.from(icon.replace("data:image/svg+xml;base64,", ""), "base64").toString("utf8");

  assert.match(decoded, /#f97316/);
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
  assert.match(resolveTrayIconPath("win32"), /codex-account-manager-win\.ico$/);
  assert.match(resolveTrayIconPath("linux"), /codex-account-manager\.png$/);
});
