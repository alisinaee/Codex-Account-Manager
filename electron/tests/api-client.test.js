const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildApiHeaders,
  buildServiceStateFromStatus,
  createApiClient,
  parseServiceStatusOutput,
} = require("../src/api-client");

test("parseServiceStatusOutput reads status JSON", () => {
  assert.deepEqual(
    parseServiceStatusOutput('{"running": true, "url": "http://127.0.0.1:4673/", "pid_file": "/tmp/service.json"}'),
    {
      running: true,
      baseUrl: "http://127.0.0.1:4673/",
      pidFile: "/tmp/service.json",
    },
  );
});

test("buildServiceStateFromStatus reads token from service pid file", () => {
  const state = buildServiceStateFromStatus(
    {
      running: true,
      baseUrl: "http://127.0.0.1:4673/",
      pidFile: "/tmp/service.json",
    },
    {
      readFileSync: () => JSON.stringify({ token: "session-token", host: "127.0.0.1", port: 4673 }),
    },
  );

  assert.deepEqual(state, {
    running: true,
    baseUrl: "http://127.0.0.1:4673/",
    token: "session-token",
    host: "127.0.0.1",
    port: 4673,
  });
});

test("buildApiHeaders includes X-Codex-Token for POST requests", () => {
  assert.deepEqual(buildApiHeaders({ token: "session-token" }), {
    "Content-Type": "application/json",
    "X-Codex-Token": "session-token",
  });
});

test("switchProfile sends no_restart true and refreshes desktop state", async () => {
  const calls = [];
  const client = createApiClient({
    state: { baseUrl: "http://127.0.0.1:4673/", token: "session-token" },
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options });
      return {
        ok: true,
        json: async () => ({ ok: true, data: { ok: true } }),
      };
    },
  });

  await client.switchProfile("work");

  assert.equal(calls[0].url, "http://127.0.0.1:4673/api/local/switch");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["X-Codex-Token"], "session-token");
  assert.deepEqual(JSON.parse(calls[0].options.body), { name: "work", no_restart: true });
  assert.deepEqual(
    calls.slice(1).map((call) => call.url),
    [
      "http://127.0.0.1:4673/api/current",
      "http://127.0.0.1:4673/api/list",
      "http://127.0.0.1:4673/api/usage-local/current?timeout=7",
      "http://127.0.0.1:4673/api/ui-config",
      "http://127.0.0.1:4673/api/auto-switch/state",
    ],
  );
});

test("generic request attaches X-Codex-Token to POST requests", async () => {
  const calls = [];
  const client = createApiClient({
    state: { baseUrl: "http://127.0.0.1:4673/", token: "session-token" },
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options });
      return {
        ok: true,
        json: async () => ({ ok: true, data: { updated: true } }),
      };
    },
  });

  await client.request("/api/system/restart", {
    method: "POST",
    body: JSON.stringify({}),
  });

  assert.equal(calls[0].options.headers["X-Codex-Token"], "session-token");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
});
