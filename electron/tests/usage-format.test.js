const test = require("node:test");
const assert = require("node:assert/strict");

const { buildUsageSummary, selectCurrentUsageRow } = require("../src/usage");

test("selectCurrentUsageRow prefers current_profile match", () => {
  const payload = {
    current_profile: "work",
    profiles: [
      { name: "personal", is_current: true },
      { name: "work", is_current: false },
    ],
  };

  assert.equal(selectCurrentUsageRow(payload).name, "work");
});

test("buildUsageSummary includes current profile and remaining usage", () => {
  const payload = {
    current_profile: "work",
    profiles: [
      {
        name: "work",
        usage_5h: { remaining_percent: 49.4 },
        usage_weekly: { remaining_percent: 88.2 },
      },
    ],
  };

  assert.deepEqual(buildUsageSummary(payload), {
    available: true,
    profileName: "work",
    fiveHourPercent: 49,
    weeklyPercent: 88,
    trayTitle: "work | 5H 49% | W 88%",
    tooltip: "Codex Account Manager\nProfile work\n5H 49% left\nWeekly 88% left",
    notificationBody: "Profile work - 5H 49% left - Weekly 88% left",
  });
});

test("buildUsageSummary returns unavailable state when usage is incomplete", () => {
  assert.deepEqual(buildUsageSummary({ profiles: [] }), {
    available: false,
    profileName: "",
    fiveHourPercent: null,
    weeklyPercent: null,
    trayTitle: "Codex Account Manager",
    tooltip: "Codex Account Manager\nUsage unavailable",
    notificationBody: "Usage unavailable",
  });
});
