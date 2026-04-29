const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const {
  getElectronLaunchSpec,
  getMacDevAppPaths,
  getWindowsDevAppPaths,
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

  assert.equal(paths.sourceApp, path.normalize("/tmp/electron/node_modules/electron/dist/Electron.app"));
  assert.equal(paths.appBundle, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager.app"));
  assert.equal(paths.executable, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/MacOS/Electron"));
  assert.equal(paths.infoPlist, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/Info.plist"));
  assert.equal(paths.iconTarget, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/Resources/codex-account-manager.icns"));
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

  assert.equal(spec.command, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/MacOS/Electron"));
  assert.equal(spec.args[0], ".");
  assert.equal(spec.options.cwd, "/tmp/electron");
  assert.equal(spec.options.env.CAM_ELECTRON_RENDERER_URL, "http://127.0.0.1:5173");
  assert.equal(fsCalls[0][0], "rmSync");
  assert.equal(fsCalls[2][0], "copyFileSync");
  assert.equal(toolCalls.length, 5);
  assert.deepEqual(toolCalls[0], [
    "/usr/bin/ditto",
    [path.normalize("/tmp/electron/node_modules/electron/dist/Electron.app"), path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager.app")],
  ]);
  assert.deepEqual(toolCalls[1], [
    "/usr/libexec/PlistBuddy",
    ["-c", "Set :CFBundleDisplayName Codex Account Manager", path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager.app/Contents/Info.plist")],
  ]);
});

test("getWindowsDevAppPaths targets a branded Windows runtime executable", () => {
  const paths = getWindowsDevAppPaths("C:\\tmp\\electron");

  assert.equal(paths.sourceDist, path.normalize("C:\\tmp\\electron\\node_modules\\electron\\dist"));
  assert.equal(paths.runtimeDir, path.normalize("C:\\tmp\\electron\\.codex-electron-runtime-win"));
  assert.equal(paths.sourceExecutable, path.normalize("C:\\tmp\\electron\\node_modules\\electron\\dist\\electron.exe"));
  assert.equal(paths.executable, path.normalize("C:\\tmp\\electron\\.codex-electron-runtime-win\\Codex Account Manager Dev.exe"));
  assert.equal(paths.stockExecutable, path.normalize("C:\\tmp\\electron\\.codex-electron-runtime-win\\electron.exe"));
  assert.equal(paths.iconPath, path.normalize("C:\\tmp\\electron\\assets\\codex-account-manager-win.ico"));
  assert.equal(paths.rcedit, path.normalize("C:\\tmp\\electron\\node_modules\\electron-winstaller\\vendor\\rcedit.exe"));
});

test("getElectronLaunchSpec uses patched Windows dev executable", () => {
  const fsCalls = [];
  const toolCalls = [];
  const spec = getElectronLaunchSpec({
    rootDir: "C:\\tmp\\electron",
    platform: "win32",
    env: { TEST_ENV: "1" },
    fsImpl: {
      rmSync: (...args) => fsCalls.push(["rmSync", ...args]),
      mkdirSync: (...args) => fsCalls.push(["mkdirSync", ...args]),
      cpSync: (...args) => fsCalls.push(["cpSync", ...args]),
      copyFileSync: (...args) => fsCalls.push(["copyFileSync", ...args]),
    },
    execFileSyncImpl: (...args) => toolCalls.push(args),
  });

  assert.equal(spec.command, path.normalize("C:\\tmp\\electron\\.codex-electron-runtime-win\\Codex Account Manager Dev.exe"));
  assert.equal(spec.args[0], ".");
  assert.equal(spec.options.cwd, "C:\\tmp\\electron");
  assert.equal(spec.options.env.CAM_ELECTRON_RENDERER_URL, "http://127.0.0.1:5173");
  assert.equal(fsCalls[0][0], "rmSync");
  assert.equal(fsCalls[2][0], "cpSync");
  assert.equal(fsCalls[3][0], "copyFileSync");
  assert.equal(toolCalls.length, 1);
  assert.deepEqual(toolCalls[0], [
    path.normalize("C:\\tmp\\electron\\node_modules\\electron-winstaller\\vendor\\rcedit.exe"),
    [
      path.normalize("C:\\tmp\\electron\\.codex-electron-runtime-win\\Codex Account Manager Dev.exe"),
      "--set-icon",
      path.normalize("C:\\tmp\\electron\\assets\\codex-account-manager-win.ico"),
      "--set-version-string",
      "ProductName",
      "Codex Account Manager",
      "--set-version-string",
      "FileDescription",
      "Codex Account Manager",
      "--set-version-string",
      "InternalName",
      "Codex Account Manager",
      "--set-version-string",
      "OriginalFilename",
      "Codex Account Manager Dev.exe",
    ],
  ]);
});
