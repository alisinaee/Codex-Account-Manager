const test = require("node:test");
const assert = require("node:assert/strict");

test("table layout helpers map usage percentage to threshold colors", async () => {
  const { usageColor } = await import("../src/renderer/table-layout.mjs");

  assert.equal(usageColor(9), "var(--color-red)");
  assert.equal(usageColor(40), "var(--color-orange)");
  assert.equal(usageColor(70), "var(--color-yellow)");
  assert.equal(usageColor(90), "var(--color-green)");
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

function shareFromWidth(value) {
  const match = String(value).match(/^([0-9.]+)%$/);
  return match ? Number(match[1]) : NaN;
}

test("profile column widths allocate only visible columns and cap actions", async () => {
  const { buildProfileColumnWidths } = await import("../src/renderer/table-layout.mjs");

  const widths = buildProfileColumnWidths(
    ["profile", "email", "h5", "h5remain", "weekly", "weeklyremain", "actions"],
    "size-wide",
  );

  assert.deepEqual(Object.keys(widths), ["profile", "email", "h5", "h5remain", "weekly", "weeklyremain", "actions"]);
  assert.equal(widths.actions, "116px");
  assert.equal(widths.id, undefined);
  assert.equal(widths.note, undefined);
  assert.match(widths.email, /^[0-9.]+%$/);
});

test("profile column widths redistribute flexible space by visible column weights", async () => {
  const { buildProfileColumnWidths } = await import("../src/renderer/table-layout.mjs");

  const reduced = buildProfileColumnWidths(
    ["profile", "email", "h5", "h5remain", "weekly", "weeklyremain", "actions"],
    "size-wide",
  );
  const full = buildProfileColumnWidths(
    ["profile", "email", "h5", "h5remain", "h5reset", "weekly", "weeklyremain", "weeklyreset", "plan", "paid", "added", "actions"],
    "size-wide",
  );

  assert.ok(shareFromWidth(reduced.email) > shareFromWidth(reduced.profile));
  assert.ok(shareFromWidth(reduced.h5remain) > shareFromWidth(reduced.profile));
  assert.ok(shareFromWidth(reduced.email) > shareFromWidth(full.email));
  assert.ok(shareFromWidth(reduced.email) <= 22);
  assert.ok(shareFromWidth(reduced.profile) <= 15);
  assert.ok(shareFromWidth(full.email) <= 20);
  assert.ok(shareFromWidth(full.profile) <= 12);
});

test("profile column widths use compact fixed widths for utility columns", async () => {
  const { buildProfileColumnWidths } = await import("../src/renderer/table-layout.mjs");

  const widths = buildProfileColumnWidths(["cur", "profile", "email", "h5", "weekly", "actions"], "size-compact");

  assert.equal(widths.cur, "18px");
  assert.equal(widths.actions, "80px");
  assert.match(widths.email, /^[0-9.]+%$/);
});
