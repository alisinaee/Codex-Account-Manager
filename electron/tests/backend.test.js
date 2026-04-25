const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildServiceCommand,
  buildServiceRuntimeContract,
  getDefaultBackendState,
  normalizeServiceStatus,
} = require("../src/backend");

test("buildServiceCommand starts ui-service without opening a browser", () => {
  assert.deepEqual(buildServiceCommand("start", { host: "127.0.0.1", port: 4673 }), {
    command: "codex-account",
    args: ["ui-service", "start", "--host", "127.0.0.1", "--port", "4673", "--no-open"],
  });
});

test("getDefaultBackendState uses the existing web panel port", () => {
  assert.deepEqual(getDefaultBackendState(), {
    host: "127.0.0.1",
    port: 4673,
    baseUrl: "http://127.0.0.1:4673/",
  });
});

test("normalizeServiceStatus accepts healthy service state", () => {
  assert.deepEqual(
    normalizeServiceStatus({
      running: true,
      url: "http://127.0.0.1:4673/",
      host: "127.0.0.1",
      port: 4673,
    }),
    {
      running: true,
      host: "127.0.0.1",
      port: 4673,
      baseUrl: "http://127.0.0.1:4673/",
    },
  );
});

test("buildServiceRuntimeContract carries desktop-ready backend details", () => {
  assert.deepEqual(
    buildServiceRuntimeContract({
      running: true,
      host: "127.0.0.1",
      port: 4673,
      baseUrl: "http://127.0.0.1:4673/",
      token: "session-token",
    }),
    {
      running: true,
      healthy: true,
      host: "127.0.0.1",
      port: 4673,
      baseUrl: "http://127.0.0.1:4673/",
      token: "session-token",
    },
  );
});
