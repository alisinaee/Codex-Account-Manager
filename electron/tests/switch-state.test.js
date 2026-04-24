const test = require("node:test");
const assert = require("node:assert/strict");

const switchState = import("../src/renderer/switch-state.mjs");

test("switch controller blocks duplicate profile switches until the active switch clears", async () => {
  const { createSwitchController } = await switchState;
  let calls = 0;
  let release;
  const blocker = new Promise((resolve) => {
    release = resolve;
  });
  const controller = createSwitchController(async (name) => {
    calls += 1;
    await blocker;
    return { current: name };
  });

  const first = controller.switchProfile("backup");
  assert.equal(controller.getPendingName(), "backup");

  await assert.rejects(() => controller.switchProfile("work"), /switch already in progress/i);
  assert.equal(calls, 1);

  release();
  assert.deepEqual(await first, { current: "backup" });
  assert.equal(controller.getPendingName(), "");
});

test("switch state helpers expose web panel parity classes", async () => {
  const { buildProfileRowClassName, buildSwitchButtonClassName } = await switchState;
  assert.equal(buildSwitchButtonClassName(true), "btn btn-primary btn-progress");
  assert.equal(buildSwitchButtonClassName(false), "btn btn-primary");
  assert.equal(buildProfileRowClassName({ isCurrent: true, isPending: false, isActivated: true }), "current-row switch-row-activated");
  assert.equal(buildProfileRowClassName({ isCurrent: false, isPending: true, isActivated: false }), "switch-row-pending");
});

test("usageTone matches web panel low mid and good usage thresholds", async () => {
  const { usageTone } = await switchState;
  assert.equal(usageTone(9), "low");
  assert.equal(usageTone(24), "midlow");
  assert.equal(usageTone(49), "mid");
  assert.equal(usageTone(50), "good");
  assert.equal(usageTone(null), "");
});
