const test = require("node:test");
const assert = require("node:assert/strict");

const {
  getElectronLaunchSpec,
  getMacDevAppPaths,
  missingRuntimeBins,
} = require("../scripts/dev");

test("missingRuntimeBins reports missing vite and electron binaries", () => {
  const missing = missingRuntimeBins({
    root: "/tmp/electron",
    existsSync: () => false,
    platform: "darwin",
  });

  assert.deepEqual(missing, ["vite", "electron"]);
});

test("missingRuntimeBins passes when runtime binaries exist", () => {
  const missing = missingRuntimeBins({
    root: "/tmp/electron",
    existsSync: () => true,
    platform: "darwin",
  });

  assert.deepEqual(missing, []);
});

test("getMacDevAppPaths targets a branded macOS runtime bundle", () => {
  const paths = getMacDevAppPaths("/tmp/electron");

  assert.equal(paths.sourceApp, "/tmp/electron/node_modules/electron/dist/Electron.app");
  assert.equal(paths.appBundle, "/tmp/electron/.codex-electron-runtime/Codex Account Manager.app");
  assert.equal(paths.executable, "/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/MacOS/Electron");
  assert.equal(paths.infoPlist, "/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/Info.plist");
  assert.equal(paths.iconTarget, "/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/Resources/codex-account-manager.icns");
});

test("getElectronLaunchSpec uses branded macOS app bundle launcher", () => {
  const fsCalls = [];
  const toolCalls = [];
  const spec = getElectronLaunchSpec({
    rootDir: "/tmp/electron",
    platform: "darwin",
    env: { TEST_ENV: "1" },
    fsImpl: {
      rmSync: (...args) => fsCalls.push(["rmSync", ...args]),
      mkdirSync: (...args) => fsCalls.push(["mkdirSync", ...args]),
      copyFileSync: (...args) => fsCalls.push(["copyFileSync", ...args]),
    },
    execFileSyncImpl: (...args) => toolCalls.push(args),
  });

  assert.equal(spec.command, "/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/MacOS/Electron");
  assert.equal(spec.args[0], ".");
  assert.equal(spec.options.cwd, "/tmp/electron");
  assert.equal(spec.options.env.CAM_ELECTRON_RENDERER_URL, "http://127.0.0.1:5173");
  assert.equal(fsCalls[0][0], "rmSync");
  assert.equal(fsCalls[2][0], "copyFileSync");
  assert.equal(toolCalls.length, 5);
  assert.deepEqual(toolCalls[0], [
    "/usr/bin/ditto",
    ["/tmp/electron/node_modules/electron/dist/Electron.app", "/tmp/electron/.codex-electron-runtime/Codex Account Manager.app"],
  ]);
  assert.deepEqual(toolCalls[1], [
    "/usr/libexec/PlistBuddy",
    ["-c", "Set :CFBundleDisplayName Codex Account Manager", "/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/Info.plist"],
  ]);
});
