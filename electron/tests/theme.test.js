const test = require("node:test");
const assert = require("node:assert/strict");

const themeModule = import("../src/renderer/theme.mjs");

test("normalizeThemeMode keeps theme values inside the supported auto-light-dark set", async () => {
  const { normalizeThemeMode } = await themeModule;

  assert.equal(normalizeThemeMode("auto"), "auto");
  assert.equal(normalizeThemeMode("LIGHT"), "light");
  assert.equal(normalizeThemeMode("dark"), "dark");
  assert.equal(normalizeThemeMode("sepia"), "auto");
});

test("resolveThemeMode respects explicit modes and resolves auto from system preference", async () => {
  const { resolveThemeMode } = await themeModule;

  assert.equal(resolveThemeMode("dark", "light"), "dark");
  assert.equal(resolveThemeMode("light", "dark"), "light");
  assert.equal(resolveThemeMode("auto", "light"), "light");
  assert.equal(resolveThemeMode("auto", "dark"), "dark");
});

test("watchThemePreference applies explicit theme modes without needing system listeners", async () => {
  const { watchThemePreference } = await themeModule;
  const target = { dataset: {}, style: {} };

  const cleanup = watchThemePreference(target, "light");

  assert.deepEqual(target.dataset, { theme: "light", themeMode: "light" });
  assert.equal(target.style.colorScheme, "light");
  cleanup();
});

test("watchThemePreference tracks system changes while auto mode is active", async () => {
  const { watchThemePreference } = await themeModule;
  const listeners = new Set();
  const mediaQueryList = {
    matches: true,
    addEventListener(eventName, listener) {
      assert.equal(eventName, "change");
      listeners.add(listener);
    },
    removeEventListener(eventName, listener) {
      assert.equal(eventName, "change");
      listeners.delete(listener);
    },
  };
  const target = { dataset: {}, style: {} };

  const cleanup = watchThemePreference(target, "auto", () => mediaQueryList);
  assert.deepEqual(target.dataset, { theme: "dark", themeMode: "auto" });

  mediaQueryList.matches = false;
  for (const listener of listeners) {
    listener();
  }

  assert.deepEqual(target.dataset, { theme: "light", themeMode: "auto" });
  assert.equal(target.style.colorScheme, "light");

  cleanup();
  assert.equal(listeners.size, 0);
});
