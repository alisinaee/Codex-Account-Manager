const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const appSource = fs.readFileSync(path.join(__dirname, "..", "src", "renderer", "App.jsx"), "utf8");
const settingsSource = fs.readFileSync(path.join(__dirname, "..", "src", "renderer", "SettingsView.jsx"), "utf8");
const componentsCss = fs.readFileSync(path.join(__dirname, "..", "src", "styles", "components.css"), "utf8");

test("settings source includes a macOS-only status bar card wired to desktop ui config", () => {
  assert.match(settingsSource, /settings-card-status-bar/);
  assert.match(settingsSource, /macos_status_bar_enabled/);
  assert.match(settingsSource, /Status bar/);
  assert.match(settingsSource, /menu bar/);
});

test("runtime setup footer source keeps the details action in a dedicated right-aligned group", () => {
  assert.match(appSource, /runtime-action-primary/);
  assert.match(appSource, /runtime-action-meta/);
  assert.match(componentsCss, /\.runtime-action-primary\s*\{/);
  assert.match(componentsCss, /\.runtime-action-meta\s*\{[\s\S]*margin-left:\s*auto;/);
  assert.match(componentsCss, /\.runtime-action-meta\s*\{[\s\S]*justify-content:\s*flex-end;/);
});
