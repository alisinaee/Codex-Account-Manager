const test = require("node:test");
const assert = require("node:assert/strict");

test("profile column width overrides drop invalid entries and keep valid CSS widths", async () => {
  const { normalizeProfileColumnWidthOverrides } = await import("../src/renderer/table-layout.mjs");

  const normalized = normalizeProfileColumnWidthOverrides({
    profile: "240px",
    email: "33.5%",
    actions: "140px",
    unknown: "120px",
    note: "wide",
    paid: "-4px",
  });

  assert.deepEqual(normalized, {
    profile: "240px",
    email: "33.5%",
  });
});

test("resolved profile column widths prefer user overrides over computed defaults", async () => {
  const { resolveProfileColumnWidths } = await import("../src/renderer/table-layout.mjs");

  const widths = resolveProfileColumnWidths(
    ["profile", "email", "actions"],
    "size-wide",
    {
      profile: "240px",
      email: "32%",
      actions: "200px",
    },
  );

  assert.equal(widths.profile, "240px");
  assert.equal(widths.email, "32%");
  assert.equal(widths.actions, "116px");
});

test("profile column resize bounds clamp manual widths and skip locked columns", async () => {
  const {
    clampProfileColumnWidthPx,
    isProfileColumnResizable,
  } = await import("../src/renderer/table-layout.mjs");

  assert.equal(isProfileColumnResizable("cur"), false);
  assert.equal(isProfileColumnResizable("actions"), false);
  assert.equal(isProfileColumnResizable("profile"), true);
  assert.equal(clampProfileColumnWidthPx("profile", 20), 96);
  assert.equal(clampProfileColumnWidthPx("email", 2000), 640);
});
