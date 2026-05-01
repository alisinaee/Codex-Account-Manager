const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const appSourcePath = path.join(__dirname, "..", "src", "renderer", "App.jsx");

test("sidebar about button includes a small right-aligned version label", () => {
  const source = fs.readFileSync(appSourcePath, "utf8");

  assert.match(source, /sidebar-about-version/);
  assert.match(source, /sidebar-dev-badge/);
  assert.match(source, /view\.id === "about"/);
  assert.doesNotMatch(source, /App version/);
  assert.match(source, /SIDEBAR_APP_VERSION_FALLBACK = "v0\.0\.20"/);
  assert.match(source, /desktopVersion/);
  assert.match(source, /updaterDevMode/);
  assert.doesNotMatch(source, /version=\{updateStatus\?\.current_version/);
});

test("minimal sidebar update item adds a dedicated blink class only when updates are available", () => {
  const source = fs.readFileSync(appSourcePath, "utf8");

  assert.match(source, /nav-mark \$\{mode === "minimal" && view\.id === "update" && updateAvailable \? "nav-mark-update-alert" : ""\}/);
  assert.match(source, /view\.id === "update" && updateAvailable && mode !== "minimal" \? <span className="nav-dot"/);
});
