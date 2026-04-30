const test = require("node:test");
const assert = require("node:assert/strict");

test("refreshProfilesAfterMutation returns core state before slow ancillary requests finish", async () => {
  const { refreshProfilesAfterMutation } = await import("../src/renderer/post-mutation-refresh.mjs");

  let resolveSlowRequest;
  const slowRequest = new Promise((resolve) => {
    resolveSlowRequest = resolve;
  });
  const requestCalls = [];

  const result = await Promise.race([
    refreshProfilesAfterMutation({
      desktop: {
        getState: async () => ({ list: { profiles: [{ name: "imported" }] } }),
        getBackendState: async () => ({ token: "backend-token" }),
      },
      request: async (path) => {
        requestCalls.push(path);
        if (path === "/api/release-notes") {
          return slowRequest;
        }
        if (path.startsWith("/api/debug/logs")) {
          return { logs: [] };
        }
        if (path === "/api/app-update-status") {
          return { status: "ok" };
        }
        if (path === "/api/auto-switch/chain") {
          return { chain: ["imported"] };
        }
        throw new Error(`unexpected path: ${path}`);
      },
      appendSessionTokenFn: (path, token) => `${path}&token=${token}`,
    }),
    new Promise((_, reject) => setTimeout(() => reject(new Error("timed out waiting for immediate refresh")), 100)),
  ]);

  assert.deepEqual(result.core.list.profiles, [{ name: "imported" }]);
  assert.deepEqual(result.backend, { token: "backend-token" });
  assert.equal(typeof result.extrasPromise?.then, "function");

  let extrasSettled = false;
  result.extrasPromise.finally(() => {
    extrasSettled = true;
  });
  await Promise.resolve();
  assert.equal(extrasSettled, false);

  resolveSlowRequest({
    status: "synced",
    releases: [],
  });
  const extras = await result.extrasPromise;
  assert.deepEqual(extras.update, { status: "ok" });
  assert.deepEqual(extras.notes, { status: "synced", releases: [] });
  assert.deepEqual(extras.logs, { logs: [] });
  assert.deepEqual(extras.chain, { chain: ["imported"] });
  assert.deepEqual(requestCalls, [
    "/api/app-update-status",
    "/api/release-notes",
    "/api/debug/logs?tail=240&token=backend-token",
    "/api/auto-switch/chain",
  ]);
});
