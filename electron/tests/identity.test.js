const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  APP_ID,
  APP_NAME,
  getElectronAssetPath,
  getIconPath,
  getDockIconPath,
  getMacIconPath,
  getProjectSourceIconPath,
  getTrayIconPath,
} = require("../src/icons");

test("Electron identity constants use Codex Account Manager branding", () => {
  assert.equal(APP_ID, "com.codexaccountmanager.desktop");
  assert.equal(APP_NAME, "Codex Account Manager");
});

test("Electron icon helper resolves project-owned assets", () => {
  const source = getProjectSourceIconPath();
  const appIcon = getIconPath();
  const dock = getDockIconPath();
  const icns = getMacIconPath();
  const trayIcon = getTrayIconPath();

  assert.equal(path.basename(source), "codex_account_manager.svg");
  assert.match(source, /codex_account_manager[\\/]assets[\\/]codex_account_manager\.svg$/);
  if (process.platform === "win32") {
    assert.match(appIcon, /electron[\\/]assets[\\/]codex-account-manager-win\.ico$/);
  } else {
    assert.match(appIcon, /electron[\\/]assets[\\/]codex-account-manager\.png$/);
  }
  assert.match(dock, /electron[\\/]assets[\\/]codex-account-manager\.icns$/);
  assert.match(icns, /electron[\\/]assets[\\/]codex-account-manager\.icns$/);
  assert.match(trayIcon, /electron[\\/]assets[\\/]codex-account-manager-tray\.svg$/);
  assert.ok(fs.existsSync(source), "source SVG should exist");
  assert.ok(fs.existsSync(appIcon), "Electron app icon should exist");
  assert.ok(fs.existsSync(dock), "Electron Dock icon should exist");
  assert.ok(fs.existsSync(icns), "Electron macOS ICNS icon should exist");
  assert.ok(fs.existsSync(trayIcon), "Electron tray icon should exist");
});

test("Electron SVG icon uses a rounded macOS-style canvas", () => {
  const sourceSvg = fs.readFileSync(getProjectSourceIconPath(), "utf8");
  const electronSvg = fs.readFileSync(getElectronAssetPath("codex-account-manager.svg"), "utf8");

  assert.notEqual(electronSvg, sourceSvg);
  assert.match(electronSvg, /<rect[^>]+rx="4[0-9]{2}"/);
  assert.match(electronSvg, /<g[^>]+clip-path="url\(#appIconMask\)"/);
  assert.doesNotMatch(electronSvg, /<path[^>]+d="M 0 0 L 270\.227 0/);
});

test("electron package metadata is ready for packaged app identity", () => {
  const pkg = require("../package.json");

  assert.equal(pkg.productName, APP_NAME);
  assert.equal(pkg.build.appId, APP_ID);
  assert.equal(pkg.build.mac.icon, "assets/codex-account-manager.icns");
  assert.equal(pkg.build.dmg.icon, "assets/codex-account-manager.icns");
  assert.equal(pkg.build.win.icon, "assets/codex-account-manager-win.ico");
  assert.equal(pkg.build.linux.icon, "assets/codex-account-manager.png");
});

test("getElectronAssetPath only resolves inside electron assets", () => {
  const asset = getElectronAssetPath("codex-account-manager.png");

  assert.match(asset, /electron[\\/]assets[\\/]codex-account-manager\.png$/);
  assert.ok(fs.existsSync(asset));
});
