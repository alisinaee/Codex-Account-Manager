const test = require("node:test");
const assert = require("node:assert/strict");

test("error banner countdown clamps remaining seconds to a 30 second window", async () => {
  const { getErrorBannerCountdownSeconds } = await import("../src/renderer/error-banner.mjs");

  const expiresAtMs = 60_000;

  assert.equal(getErrorBannerCountdownSeconds(expiresAtMs, 30_000), 30);
  assert.equal(getErrorBannerCountdownSeconds(expiresAtMs, 30_999), 30);
  assert.equal(getErrorBannerCountdownSeconds(expiresAtMs, 31_000), 29);
  assert.equal(getErrorBannerCountdownSeconds(expiresAtMs, 59_001), 1);
  assert.equal(getErrorBannerCountdownSeconds(expiresAtMs, 60_000), 0);
  assert.equal(getErrorBannerCountdownSeconds(expiresAtMs, 75_000), 0);
});
