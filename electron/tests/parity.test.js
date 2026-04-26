const test = require("node:test");
const assert = require("node:assert/strict");

test("parity helpers merge config patches deeply without losing sibling keys", async () => {
  const { deepMerge } = await import("../src/renderer/parity.mjs");

  assert.deepEqual(
    deepMerge(
      { ui: { theme: "auto", current_refresh_interval_sec: 5 }, notifications: { enabled: false } },
      { ui: { current_refresh_interval_sec: 9 }, notifications: { enabled: true } },
    ),
    { ui: { theme: "auto", current_refresh_interval_sec: 9 }, notifications: { enabled: true } },
  );
});

test("parity helpers apply optimistic profile selection across current list and usage snapshots", async () => {
  const { applyProfileSelection } = await import("../src/renderer/parity.mjs");

  const next = applyProfileSelection({
    current: { profile_name: "a" },
    list: { profiles: [{ name: "a", is_current: true }, { name: "b", is_current: false }] },
    usage: { current_profile: "a", profiles: [{ name: "a", is_current: true }, { name: "b", is_current: false }] },
  }, "b");

  assert.equal(next.current.profile_name, "b");
  assert.deepEqual(next.list.profiles.map((row) => row.is_current), [false, true]);
  assert.equal(next.usage.current_profile, "b");
  assert.deepEqual(next.usage.profiles.map((row) => row.is_current), [false, true]);
});

test("parity helpers clamp current and all refresh intervals to the stable web panel rules", async () => {
  const { getAllRefreshIntervalMs, getCurrentRefreshIntervalMs } = await import("../src/renderer/parity.mjs");

  assert.equal(getCurrentRefreshIntervalMs({ current_auto_refresh_enabled: false, current_refresh_interval_sec: 9 }), null);
  assert.equal(getCurrentRefreshIntervalMs({ current_auto_refresh_enabled: true, current_refresh_interval_sec: 0 }), 5000);
  assert.equal(getCurrentRefreshIntervalMs({ current_auto_refresh_enabled: true, current_refresh_interval_sec: 9 }), 9000);

  assert.equal(getAllRefreshIntervalMs({ all_auto_refresh_enabled: false, all_refresh_interval_min: 4 }), null);
  assert.equal(getAllRefreshIntervalMs({ all_auto_refresh_enabled: true, all_refresh_interval_min: 0 }), 300000);
  assert.equal(getAllRefreshIntervalMs({ all_auto_refresh_enabled: true, all_refresh_interval_min: 120 }), 3600000);
});

test("parity helpers format auto-switch countdown from due timestamp", async () => {
  const { formatAutoSwitchCountdown } = await import("../src/renderer/parity.mjs");

  assert.equal(formatAutoSwitchCountdown("", 130, 100000), "Switching in 00:30");
  assert.equal(formatAutoSwitchCountdown("No pending switch", null, 100000), "No pending switch");
});

test("restart parity waits for service drop before accepting recovery", async () => {
  const { waitForServiceRestart } = await import("../src/renderer/parity.mjs");

  let nowMs = 0;
  const waits = [];
  const responses = [
    { error: new Error("offline") },
    { value: { version: "same-version" } },
  ];

  const result = await waitForServiceRestart({
    previousVersion: "same-version",
    reloadAfterMs: 1200,
    pollIntervalMs: 700,
    now: () => nowMs,
    wait: async (ms) => {
      waits.push(ms);
      nowMs += ms;
    },
    fetchHealth: async () => {
      const next = responses.shift();
      if (next.error) {
        throw next.error;
      }
      return next.value;
    },
  });

  assert.deepEqual(result, { version: "same-version" });
  assert.deepEqual(waits, [1200, 700]);
});

test("restart parity accepts version changes without needing a visible drop", async () => {
  const { waitForServiceRestart } = await import("../src/renderer/parity.mjs");

  let nowMs = 0;
  const result = await waitForServiceRestart({
    previousVersion: "v1",
    reloadAfterMs: 500,
    pollIntervalMs: 250,
    now: () => nowMs,
    wait: async (ms) => {
      nowMs += ms;
    },
    fetchHealth: async () => ({ version: "v2" }),
  });

  assert.deepEqual(result, { version: "v2" });
});

test("restart parity times out cleanly when backend never returns", async () => {
  const { waitForServiceRestart } = await import("../src/renderer/parity.mjs");

  let nowMs = 0;
  await assert.rejects(
    waitForServiceRestart({
      previousVersion: "v1",
      reloadAfterMs: 200,
      pollIntervalMs: 300,
      restartTimeoutMs: 900,
      recoveryTimeoutMs: 600,
      now: () => nowMs,
      wait: async (ms) => {
        nowMs += ms;
      },
      fetchHealth: async () => {
        throw new Error("offline");
      },
    }),
    /restart timed out/i,
  );
});
