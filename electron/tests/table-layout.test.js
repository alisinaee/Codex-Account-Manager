const test = require("node:test");
const assert = require("node:assert/strict");

test("table layout helpers map usage percentage to threshold colors", async () => {
  const { usageColor } = await import("../src/renderer/table-layout.mjs");

  assert.equal(usageColor(20), "var(--color-green)");
  assert.equal(usageColor(71), "var(--color-amber)");
  assert.equal(usageColor(100), "var(--color-red)");
});

test("table layout helpers compute circular arc stroke dasharray", async () => {
  const { arcDasharray } = await import("../src/renderer/table-layout.mjs");

  assert.equal(arcDasharray(20), "18.8 94.2");
  assert.equal(arcDasharray(100), "94.2 94.2");
});

test("table layout helpers format compact month/day labels", async () => {
  const { formatShortDateFromSeconds, formatShortDateFromValue } = await import("../src/renderer/table-layout.mjs");

  const resetTs = Math.floor(Date.UTC(2026, 3, 26, 12, 0, 0) / 1000);
  assert.equal(formatShortDateFromSeconds(resetTs), "Apr 26");

  assert.equal(formatShortDateFromValue("2026-04-16T09:15:00.000Z"), "Apr 16");
});

test("table layout helpers truncate id and note fields", async () => {
  const { truncateAccountId, truncateNote } = await import("../src/renderer/table-layout.mjs");

  assert.equal(truncateAccountId("318b28ff-5a11-4674-bf84-97898d8db2ec"), "318b28ff…");
  assert.equal(truncateAccountId("short"), "short");

  assert.equal(truncateNote("long note text for testing"), "long note te…");
  assert.equal(truncateNote("short note"), "short note");
});

test("table layout helpers classify remain columns by urgency", async () => {
  const { remainToneFromResetEpochSeconds } = await import("../src/renderer/table-layout.mjs");

  const nowMs = Date.UTC(2026, 3, 26, 10, 0, 0);
  const overTwoHours = Math.floor((nowMs + 3 * 60 * 60 * 1000) / 1000);
  const warning = Math.floor((nowMs + 90 * 60 * 1000) / 1000);
  const danger = Math.floor((nowMs + 20 * 60 * 1000) / 1000);

  assert.equal(remainToneFromResetEpochSeconds(overTwoHours, nowMs), "normal");
  assert.equal(remainToneFromResetEpochSeconds(warning, nowMs), "warning");
  assert.equal(remainToneFromResetEpochSeconds(danger, nowMs), "danger");
});
