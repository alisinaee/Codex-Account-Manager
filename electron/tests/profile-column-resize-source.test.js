const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const appSourcePath = path.join(__dirname, "..", "src", "renderer", "App.jsx");
const dataTableSourcePath = path.join(__dirname, "..", "src", "renderer", "components", "DataTable.jsx");

test("columns dialog includes width resize controls and reset actions", () => {
  const source = fs.readFileSync(appSourcePath, "utf8");

  assert.match(source, /Change columns width/);
  assert.match(source, /Reset width/);
  assert.match(source, /Reset to default/);
  assert.match(source, /column_width_overrides:\s+Object\.keys\(normalized\)\.length \? normalized : null/);
  assert.match(source, /column_width_resize_enabled/);
  assert.match(source, /column_width_overrides/);
});

test("data table source includes header resize handles and pointer drag wiring", () => {
  const source = fs.readFileSync(dataTableSourcePath, "utf8");

  assert.match(source, /data-col-resize-handle=/);
  assert.match(source, /onPointerDown=/);
  assert.match(source, /onColumnResize\?\./);
});

test("workspace error banner source includes a dismiss countdown and close button", () => {
  const source = fs.readFileSync(appSourcePath, "utf8");

  assert.match(source, /Close error/);
  assert.match(source, /Dismiss in \{errorCountdownSeconds\}s/);
  assert.match(source, /dialog-close workspace-error-close/);
});

test("update view source uses a unified update progress dialog and desktop update status wiring", () => {
  const source = fs.readFileSync(appSourcePath, "utf8");

  assert.match(source, /Update progress/);
  assert.match(source, /desktop\.getUpdateStatus/);
  assert.match(source, /desktop\.runUnifiedUpdate/);
  assert.match(source, /desktop\.onUpdateProgress/);
  assert.match(source, /update-status-summary/);
  assert.match(source, /update-source-row/);
  assert.match(source, /update-source-pill/);
  assert.match(source, /update-layer-item/);
  assert.match(source, /update-layer-item-label/);
  assert.match(source, /update-layer-item-value/);
  assert.match(source, /isInstallerHandoff = modal\?\.phase === "awaiting_installer" && modal\?\.status === "awaiting-user"/);
  assert.match(source, /update-progress-detail-warning/);
  assert.match(source, /dismissible: \["done", "failed"\]\.includes\(String\(progress\?\.status \|\| ""\)\)/);
  assert.doesNotMatch(source, /dismissible: \["done", "failed", "awaiting-user"\]/);
  assert.doesNotMatch(source, /LabelValueRow label="Current version"/);
  assert.doesNotMatch(source, /LabelValueRow label="Latest version"/);
  assert.doesNotMatch(source, /update-status-note/);
  assert.match(source, /compactStatusSummary/);
});
