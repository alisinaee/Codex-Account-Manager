const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const themeModule = import("../src/renderer/theme.mjs");
const tokensCss = fs.readFileSync(path.join(__dirname, "../src/styles/tokens.css"), "utf8");
const componentsCss = fs.readFileSync(path.join(__dirname, "../src/styles/components.css"), "utf8");

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

test("getNextThemeMode cycles auto light and dark in order", async () => {
  const { getNextThemeMode } = await themeModule;

  assert.equal(getNextThemeMode("auto"), "light");
  assert.equal(getNextThemeMode("light"), "dark");
  assert.equal(getNextThemeMode("dark"), "auto");
  assert.equal(getNextThemeMode("sepia"), "light");
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

test("toggle palette tokens are defined for base and light themes", () => {
  assert.match(tokensCss, /--control-toggle-track-off:/);
  assert.match(tokensCss, /--control-toggle-track-on:/);
  assert.match(tokensCss, /--control-toggle-thumb-off:/);
  assert.match(tokensCss, /--control-toggle-thumb-on:/);

  const lightThemeBlock = tokensCss.match(/:root\[data-theme="light"\]\s*\{([\s\S]*?)\n\}/);
  assert.ok(lightThemeBlock, "light theme block should exist");
  assert.match(lightThemeBlock[1], /--control-toggle-track-off:/);
  assert.match(lightThemeBlock[1], /--control-toggle-track-on:/);
  assert.match(lightThemeBlock[1], /--control-toggle-thumb-off:/);
  assert.match(lightThemeBlock[1], /--control-toggle-thumb-on:/);
});

test("spinner styles use a shared calmer loading duration", () => {
  assert.match(tokensCss, /--duration-spinner:\s*(?:9[0-9]{2}|1[0-9]{3})ms;/);
  assert.match(componentsCss, /\.btn-progress::after\s*\{[\s\S]*animation:\s*spin var\(--duration-spinner\) linear infinite;/);
  assert.match(componentsCss, /\.remain-loading-spinner\s*\{[\s\S]*animation:\s*spin var\(--duration-spinner\) linear infinite;/);
});
