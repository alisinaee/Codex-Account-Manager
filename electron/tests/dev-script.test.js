const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const {
  getElectronLaunchSpec,
  getMacDevAppPaths,
  getWindowsDevAppPaths,
  missingRuntimeBins,
} = require("../scripts/dev");

function winPath(value) {
  return path.win32.normalize(value);
}

function assertWinPathEqual(actual, expected) {
  assert.equal(winPath(actual), winPath(expected));
}

function normalizeWindowsToolCall(call) {
  return [
    winPath(call[0]),
    call[1].map((value, index) => (index === 0 || index === 2 ? winPath(value) : value)),
  ];
}

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

test("getElectronLaunchSpec injects the repo core command for dev shells", () => {
  const fsCalls = [];
  const spec = getElectronLaunchSpec({
    rootDir: "/tmp/electron",
    platform: "linux",
    env: { TEST_ENV: "1" },
    fsImpl: {
      mkdirSync: (...args) => fsCalls.push(["mkdirSync", ...args]),
      writeFileSync: (...args) => fsCalls.push(["writeFileSync", ...args]),
      chmodSync: (...args) => fsCalls.push(["chmodSync", ...args]),
      existsSync: () => true,
    },
  });

  assert.equal(spec.options.env.CAM_ELECTRON_CORE_COMMAND, path.normalize("/tmp/electron/.codex-electron-runtime/codex-account-dev"));
  assert.equal(spec.options.env.CAM_ELECTRON_STARTUP_DEBUG, "1");
  assert.equal(spec.options.env.CAM_ELECTRON_APP_LAUNCH_CONTEXT, "dev-script");
  assert.equal(fsCalls[1][0], "writeFileSync");
  assert.match(fsCalls[1][2], /bin\/codex-account/);
});

test("getMacDevAppPaths targets a branded macOS runtime bundle", () => {
  const paths = getMacDevAppPaths("/tmp/electron");

  assert.equal(paths.sourceApp, path.normalize("/tmp/electron/node_modules/electron/dist/Electron.app"));
  assert.equal(paths.appBundle, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager Dev.app"));
  assert.equal(paths.executable, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager Dev.app/Contents/MacOS/Electron"));
  assert.equal(paths.infoPlist, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager Dev.app/Contents/Info.plist"));
  assert.equal(paths.iconTarget, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager Dev.app/Contents/Resources/codex-account-manager.icns"));
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
      writeFileSync: (...args) => fsCalls.push(["writeFileSync", ...args]),
      chmodSync: (...args) => fsCalls.push(["chmodSync", ...args]),
      existsSync: () => true,
    },
    execFileSyncImpl: (...args) => toolCalls.push(args),
  });

  assert.equal(spec.command, path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager Dev.app/Contents/MacOS/Electron"));
  assert.equal(spec.args[0], ".");
  assert.equal(spec.options.cwd, "/tmp/electron");
  assert.equal(spec.options.env.CAM_ELECTRON_RENDERER_URL, "http://127.0.0.1:5173");
  assert.equal(spec.options.env.CAM_ELECTRON_STARTUP_DEBUG, "1");
  assert.equal(spec.options.env.CAM_ELECTRON_CORE_COMMAND, path.normalize("/tmp/electron/.codex-electron-runtime/codex-account-dev"));
  assert.equal(fsCalls[0][0], "rmSync");
  assert.equal(fsCalls[2][0], "copyFileSync");
  assert.equal(toolCalls.length, 5);
  assert.deepEqual(toolCalls[0], [
    "/usr/bin/ditto",
    [path.normalize("/tmp/electron/node_modules/electron/dist/Electron.app"), path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager Dev.app")],
  ]);
  assert.deepEqual(toolCalls[1], [
    "/usr/libexec/PlistBuddy",
    ["-c", "Set :CFBundleDisplayName Codex Account Manager Dev", path.normalize("/tmp/electron/.codex-electron-runtime/Codex Account Manager Dev.app/Contents/Info.plist")],
  ]);
});

test("getWindowsDevAppPaths targets a branded Windows runtime executable", () => {
  const paths = getWindowsDevAppPaths("C:\\tmp\\electron");

  assertWinPathEqual(paths.sourceDist, "C:\\tmp\\electron\\node_modules\\electron\\dist");
  assertWinPathEqual(paths.runtimeDir, "C:\\tmp\\electron\\.codex-electron-runtime-win");
  assertWinPathEqual(paths.sourceExecutable, "C:\\tmp\\electron\\node_modules\\electron\\dist\\electron.exe");
  assertWinPathEqual(paths.executable, "C:\\tmp\\electron\\.codex-electron-runtime-win\\Codex Account Manager Dev.exe");
  assertWinPathEqual(paths.stockExecutable, "C:\\tmp\\electron\\.codex-electron-runtime-win\\electron.exe");
  assertWinPathEqual(paths.iconPath, "C:\\tmp\\electron\\assets\\codex-account-manager-win.ico");
  assertWinPathEqual(paths.rcedit, "C:\\tmp\\electron\\node_modules\\electron-winstaller\\vendor\\rcedit.exe");
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
      writeFileSync: (...args) => fsCalls.push(["writeFileSync", ...args]),
      chmodSync: (...args) => fsCalls.push(["chmodSync", ...args]),
      existsSync: () => true,
    },
    execFileSyncImpl: (...args) => toolCalls.push(args),
  });

  assertWinPathEqual(spec.command, "C:\\tmp\\electron\\.codex-electron-runtime-win\\Codex Account Manager Dev.exe");
  assert.equal(spec.args[0], ".");
  assert.equal(spec.options.cwd, "C:\\tmp\\electron");
  assert.equal(spec.options.env.CAM_ELECTRON_RENDERER_URL, "http://127.0.0.1:5173");
  assert.equal(spec.options.env.CAM_ELECTRON_STARTUP_DEBUG, "1");
  assert.equal(fsCalls[0][0], "rmSync");
  assert.equal(fsCalls[2][0], "cpSync");
  assert.equal(fsCalls[3][0], "copyFileSync");
  assert.equal(toolCalls.length, 1);
  assert.deepEqual(normalizeWindowsToolCall(toolCalls[0]), [
    winPath("C:\\tmp\\electron\\node_modules\\electron-winstaller\\vendor\\rcedit.exe"),
    [
      winPath("C:\\tmp\\electron\\.codex-electron-runtime-win\\Codex Account Manager Dev.exe"),
      "--set-icon",
      winPath("C:\\tmp\\electron\\assets\\codex-account-manager-win.ico"),
      "--set-version-string",
      "ProductName",
      "Codex Account Manager Dev",
      "--set-version-string",
      "FileDescription",
      "Codex Account Manager Dev",
      "--set-version-string",
      "InternalName",
      "Codex Account Manager Dev",
      "--set-version-string",
      "OriginalFilename",
      "Codex Account Manager Dev.exe",
    ],
  ]);
});
