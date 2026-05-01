const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const appSourcePath = path.join(__dirname, "..", "src", "renderer", "App.jsx");

test("profiles toolbar does not include the TA test animation button", () => {
  const source = fs.readFileSync(appSourcePath, "utf8");

  assert.doesNotMatch(source, /className="test-animation-btn"/);
  assert.doesNotMatch(source, /onTestAnimation/);
  assert.doesNotMatch(source, />test snak</);
  assert.doesNotMatch(source, /onTestSnack/);
});
