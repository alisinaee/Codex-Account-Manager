const test = require("node:test");
const assert = require("node:assert/strict");

const { shouldInvalidateDesktopStateForRequest } = require("../src/desktop-state-cache");

test("shouldInvalidateDesktopStateForRequest invalidates saved-profile mutations", () => {
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/local/remove-all", { method: "POST" }),
    true,
  );
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/local/remove?name=acc4", { method: "POST" }),
    true,
  );
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/local/rename", { method: "POST" }),
    true,
  );
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/local/import/apply", { method: "POST" }),
    true,
  );
});

test("shouldInvalidateDesktopStateForRequest ignores non-mutating local requests", () => {
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/local/remove-all", { method: "GET" }),
    false,
  );
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/local/export/prepare", { method: "POST" }),
    false,
  );
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/local/add/start", { method: "POST" }),
    false,
  );
  assert.equal(
    shouldInvalidateDesktopStateForRequest("/api/ui-config", { method: "POST" }),
    false,
  );
});
