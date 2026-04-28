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
      "http://127.0.0.1:4673/api/usage-local?timeout=8&force=true",
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

test("getDesktopState falls back when usage endpoint fails", async () => {
  const client = createApiClient({
    state: { baseUrl: "http://127.0.0.1:4673/", token: "session-token" },
    fetchImpl: async (url) => {
      if (url.endsWith("/api/usage-local/current?timeout=7")) {
        return {
          ok: false,
          json: async () => ({ ok: false, error: { message: "http 401" } }),
        };
      }
      if (url.endsWith("/api/current")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { ok: true, account_hint: "a@example.com | id:1", account_id: "1" } }),
        };
      }
      if (url.endsWith("/api/list")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { profiles: [{ name: "acc-a", account_hint: "a@example.com | id:1", is_current: true }] } }),
        };
      }
      if (url.endsWith("/api/ui-config")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { ui: {} } }),
        };
      }
      if (url.endsWith("/api/auto-switch/state")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { enabled: false } }),
        };
      }
      throw new Error(`unexpected URL: ${url}`);
    },
  });

  const state = await client.getDesktopState();

  assert.equal(Array.isArray(state.usage?.profiles), true);
  assert.equal(state.usage.profiles.length, 1);
  assert.equal(state.usage.profiles[0].name, "acc-a");
  assert.equal(state.usage.profiles[0].error, "usage unavailable");
});

test("request times out when backend hangs", async () => {
  const client = createApiClient({
    state: { baseUrl: "http://127.0.0.1:4673/", token: "session-token", requestTimeoutMs: 25 },
    fetchImpl: (_url, options = {}) => new Promise((_resolve, reject) => {
      const onAbort = () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      };
      options.signal?.addEventListener?.("abort", onAbort, { once: true });
    }),
  });

  await assert.rejects(
    () => client.request("/api/current", {}),
    /request timeout after/i,
  );
});
