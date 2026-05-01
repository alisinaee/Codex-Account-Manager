const test = require("node:test");
const assert = require("node:assert/strict");

test("debug logs merge backend and Electron app errors into one timeline", async () => {
  const { buildDesktopLogEntry, mergeDebugLogs } = await import("../src/renderer/debug-logs.mjs");

  const backend = [{ ts: "2026-04-28T10:00:00.000Z", level: "info", message: "backend ready" }];
  const desktop = [
    buildDesktopLogEntry(
      "error",
      "Error invoking remote method 'desktop:request': Error: request timeout after 12000ms: /api/auto-switch/chain",
      { path: "/api/auto-switch/chain" },
      () => new Date("2026-04-28T10:00:01.000Z"),
    ),
  ];

  const merged = mergeDebugLogs(backend, desktop);

  assert.deepEqual(merged.map((row) => row.source), ["backend", "electron"]);
  assert.equal(merged[1].level, "error");
  assert.match(merged[1].message, /desktop:request/);
  assert.equal(merged[1].details.path, "/api/auto-switch/chain");
});
