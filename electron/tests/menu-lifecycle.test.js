const test = require("node:test");
const assert = require("node:assert/strict");

const { buildApplicationMenuTemplate, shouldQuitOnWindowAllClosed } = require("../src/menu");

test("buildApplicationMenuTemplate includes desktop app menus and shortcuts", () => {
  const labels = buildApplicationMenuTemplate({
    isMac: true,
    isDev: true,
    actions: {},
  }).map((item) => item.label || item.role);

  assert.deepEqual(labels, ["Codex Account Manager", "File", "Edit", "View", "Go", "Window", "Help"]);
});

test("application menu exposes refresh settings notification and sidebar actions", () => {
  const template = buildApplicationMenuTemplate({ isMac: false, isDev: false, actions: {} });
  const allLabels = template.flatMap((item) => (item.submenu || []).map((entry) => entry.label || entry.role));

  assert.ok(allLabels.includes("Refresh Table"));
  assert.ok(allLabels.includes("Profiles"));
  assert.ok(allLabels.includes("Auto Switch"));
  assert.ok(allLabels.includes("Settings"));
  assert.ok(allLabels.includes("Test Notification"));
  assert.ok(allLabels.includes("Toggle Sidebar"));
  assert.ok(allLabels.includes("Next Section"));
  assert.ok(allLabels.includes("Quit + Stop Core"));
});

test("shouldQuitOnWindowAllClosed keeps tray app alive until explicit quit", () => {
  assert.equal(shouldQuitOnWindowAllClosed({ hasTray: true, isQuitting: false }), false);
  assert.equal(shouldQuitOnWindowAllClosed({ hasTray: false, isQuitting: false }), true);
  assert.equal(shouldQuitOnWindowAllClosed({ hasTray: true, isQuitting: true }), true);
});
