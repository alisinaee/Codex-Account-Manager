const test = require("node:test");
const assert = require("node:assert/strict");

test("buildProfileRows prefers explicit email over account_hint display", async () => {
  const { buildProfileRows } = await import("../src/renderer/view-model.mjs");

  const rows = buildProfileRows({
    current: { profile_name: "work", account_hint: "work@example.test | id:abc" },
    list: {
      profiles: [
        {
          name: "work",
          email: "work@example.test",
          account_hint: "work@example.test | id:abc",
          account_id: "abc",
          is_current: true,
        },
      ],
    },
    usage: {
      current_profile: "work",
      profiles: [
        {
          name: "work",
          email: "work@example.test",
          account_hint: "work@example.test | id:abc",
          account_id: "abc",
          is_current: true,
          usage_5h: { remaining_percent: 44 },
          usage_weekly: { remaining_percent: 87 },
        },
      ],
    },
  });

  assert.equal(rows.length, 1);
  assert.equal(rows[0].email_display, "work@example.test");
  assert.equal(rows[0].account_hint, "work@example.test | id:abc");
});

test("buildSidebarCurrentProfile builds footer summary from the current usage row", async () => {
  const { buildSidebarCurrentProfile } = await import("../src/renderer/view-model.mjs");

  const summary = buildSidebarCurrentProfile({
    current: { profile_name: "work", account_hint: "work@example.test" },
    list: {
      profiles: [
        {
          name: "work",
          email: "work@example.test",
          account_hint: "work@example.test",
          is_current: true,
        },
      ],
    },
    usage: {
      current_profile: "work",
      profiles: [
        {
          name: "work",
          email: "work@example.test",
          account_hint: "work@example.test",
          is_current: true,
          usage_5h: { remaining_percent: 44 },
          usage_weekly: { remaining_percent: 87 },
        },
      ],
    },
  });

  assert.deepEqual(summary, {
    name: "work",
    email: "work@example.test",
    usage5h: 44,
    usageWeekly: 87,
    hasUsage: true,
  });
});

test("buildProfileRows uses usage.current_profile over stale list is_current flags", async () => {
  const { buildProfileRows } = await import("../src/renderer/view-model.mjs");

  const rows = buildProfileRows({
    current: { profile_name: "backup" },
    list: {
      profiles: [
        { name: "work", email: "work@example.test", is_current: true },
        { name: "backup", email: "backup@example.test", is_current: false },
      ],
    },
    usage: {
      current_profile: "backup",
      profiles: [
        { name: "work", email: "work@example.test", is_current: false },
        { name: "backup", email: "backup@example.test", is_current: false },
      ],
    },
  });

  assert.equal(rows.find((row) => row.name === "work")?.is_current, false);
  assert.equal(rows.find((row) => row.name === "backup")?.is_current, true);
});
