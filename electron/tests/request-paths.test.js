const test = require("node:test");
const assert = require("node:assert/strict");

test("appendSessionToken adds token to protected GET paths", async () => {
  const { appendSessionToken } = await import("../src/renderer/request-paths.mjs");

  assert.equal(
    appendSessionToken("/api/debug/logs?tail=240", "session-token"),
    "/api/debug/logs?tail=240&token=session-token",
  );
});

test("appendSessionToken preserves existing token and hash fragments", async () => {
  const { appendSessionToken } = await import("../src/renderer/request-paths.mjs");

  assert.equal(
    appendSessionToken("/api/debug/logs?tail=240&token=present#logs", "session-token"),
    "/api/debug/logs?tail=240&token=present#logs",
  );
});

test("buildAuthenticatedDownloadUrl includes token and export id", async () => {
  const { buildAuthenticatedDownloadUrl } = await import("../src/renderer/request-paths.mjs");

  assert.equal(
    buildAuthenticatedDownloadUrl("http://127.0.0.1:4673/", "/api/local/export/download", "session-token", { id: "export-1" }),
    "http://127.0.0.1:4673/api/local/export/download?token=session-token&id=export-1",
  );
});
