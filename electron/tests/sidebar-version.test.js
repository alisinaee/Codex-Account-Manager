const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const appSourcePath = path.join(__dirname, "..", "src", "renderer", "App.jsx");

test("sidebar about button includes a small right-aligned version label", () => {
  const source = fs.readFileSync(appSourcePath, "utf8");

  assert.match(source, /sidebar-about-version/);
  assert.match(source, /view\.id === "about"/);
  assert.doesNotMatch(source, /App version/);
  assert.match(source, /SIDEBAR_APP_VERSION_FALLBACK = "v0\.0\.15"/);
});
