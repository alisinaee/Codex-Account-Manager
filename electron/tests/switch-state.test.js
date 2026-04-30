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
  assert.equal(buildSwitchButtonClassName(true), "btn btn-primary btn-progress switch-loading-btn");
  assert.equal(buildSwitchButtonClassName(false), "btn btn-primary");
  assert.equal(buildProfileRowClassName({ isCurrent: true, isPending: false, isActivated: true }), "current-row switch-row-activated");
  assert.equal(buildProfileRowClassName({ isCurrent: false, isPending: true, isActivated: false }), "switch-row-pending");
});

test("switch row motion helper returns inverse transforms for moved rows only", async () => {
  const { buildSwitchRowMotionPlans } = await switchState;
  const plans = buildSwitchRowMotionPlans(
    {
      acc1: { left: 10, top: 20 },
      acc2: { left: 10, top: 64 },
      acc3: { left: 10, top: 108 },
    },
    {
      acc2: { left: 10, top: 20 },
      acc1: { left: 10, top: 64 },
      acc3: { left: 10, top: 108 },
    },
  );

  assert.deepEqual(plans, [
    { name: "acc1", dx: 0, dy: -44 },
    { name: "acc2", dx: 0, dy: 44 },
  ]);
});

test("switch row motion timing is intentionally calm and readable", async () => {
  const { SWITCH_ROW_CLEANUP_BUFFER_MS, SWITCH_ROW_MOTION_MS } = await switchState;
  assert.equal(SWITCH_ROW_MOTION_MS, 4000);
  assert.ok(SWITCH_ROW_CLEANUP_BUFFER_MS >= 100);
});

test("test animation helpers pick a non-top row and preview it at the top", async () => {
  const { buildDeckMoveAffectedNames, buildRowsByNameOrder, buildTestSwitchAnimationPreviewRows, pickTestSwitchAnimationTarget } = await switchState;
  assert.equal(pickTestSwitchAnimationTarget(["acc1", "acc2", "acc3"], 0), "acc2");
  assert.equal(pickTestSwitchAnimationTarget(["acc1", "acc2", "acc3"], 0.99), "acc3");
  assert.equal(pickTestSwitchAnimationTarget(["acc1"], 0), "");

  const rows = [{ name: "acc1" }, { name: "acc2" }, { name: "acc3" }, { name: "acc4" }];
  assert.deepEqual(buildDeckMoveAffectedNames(rows.map((row) => row.name), "acc3"), ["acc3", "acc1", "acc2"]);
  assert.deepEqual(buildDeckMoveAffectedNames(rows.map((row) => row.name), "acc1"), []);
  assert.deepEqual(buildTestSwitchAnimationPreviewRows(rows, "acc3").map((row) => row.name), ["acc3", "acc1", "acc2", "acc4"]);
  assert.deepEqual(buildTestSwitchAnimationPreviewRows(rows, "missing"), rows);

  const firstPreview = buildTestSwitchAnimationPreviewRows(rows, "acc3");
  const secondPreview = buildTestSwitchAnimationPreviewRows(firstPreview, "acc2");
  assert.deepEqual(secondPreview.map((row) => row.name), ["acc2", "acc3", "acc1", "acc4"]);
  assert.deepEqual(buildRowsByNameOrder(rows, secondPreview.map((row) => row.name)).map((row) => row.name), ["acc2", "acc3", "acc1", "acc4"]);

  const realSwitchPreview = buildTestSwitchAnimationPreviewRows(secondPreview, "acc4");
  assert.deepEqual(realSwitchPreview.map((row) => row.name), ["acc4", "acc2", "acc3", "acc1"]);
  assert.deepEqual(buildDeckMoveAffectedNames(secondPreview.map((row) => row.name), "acc4"), ["acc4", "acc2", "acc3", "acc1"]);
});

test("shared switch animation preview keeps TA and live switch deck movement identical", async () => {
  const { buildSwitchAnimationPreview } = await switchState;
  const rows = [{ name: "acc1" }, { name: "acc2" }, { name: "acc3" }, { name: "acc4" }];

  const firstPreview = buildSwitchAnimationPreview(rows, "acc3");
  assert.deepEqual(firstPreview.affectedNames, ["acc3", "acc1", "acc2"]);
  assert.deepEqual(firstPreview.nextRows.map((row) => row.name), ["acc3", "acc1", "acc2", "acc4"]);

  const liveSwitchPreview = buildSwitchAnimationPreview(firstPreview.nextRows, "acc4");
  assert.deepEqual(liveSwitchPreview.affectedNames, ["acc4", "acc3", "acc1", "acc2"]);
  assert.deepEqual(liveSwitchPreview.nextRows.map((row) => row.name), ["acc4", "acc3", "acc1", "acc2"]);
});

test("usageTone maps remaining percentage to the shared four-band palette", async () => {
  const { usageTone } = await switchState;
  assert.equal(usageTone(9), "danger");
  assert.equal(usageTone(40), "warning");
  assert.equal(usageTone(70), "caution");
  assert.equal(usageTone(90), "success");
  assert.equal(usageTone(null), "");
});
