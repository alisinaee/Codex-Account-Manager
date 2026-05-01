"use strict";

const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs");
const { execFileSync } = require("node:child_process");

const { APP_ID, APP_NAME, DEV_APP_ID, DEV_APP_NAME, getIconPath, getMacIconPath } = require("../src/icons");

const root = path.resolve(__dirname, "..");
const rendererUrl = "http://127.0.0.1:5173";
const MAC_RUNTIME_DIRNAME = ".codex-electron-runtime";
const MAC_APP_BUNDLE_NAME = `${DEV_APP_NAME}.app`;
const WINDOWS_RUNTIME_DIRNAME = ".codex-electron-runtime-win";
const WINDOWS_APP_EXE_NAME = `${DEV_APP_NAME}.exe`;
const DEV_CORE_WRAPPER_NAME = "codex-account-dev";

function devLog(event, details = {}) {
  const payload = {
    ts: new Date().toISOString(),
    event,
    ...details,
  };
  console.error(`[cam-dev] ${JSON.stringify(payload)}`);
}

function devCoreWrapperPath(rootDir) {
  return path.join(rootDir, MAC_RUNTIME_DIRNAME, DEV_CORE_WRAPPER_NAME);
}

function resolveDevPythonCommand({ env = process.env, fsImpl = fs } = {}) {
  const candidates = [
    env.CAM_ELECTRON_PYTHON,
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
    "python3",
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (path.isAbsolute(candidate) && !fsImpl.existsSync(candidate)) {
      continue;
    }
    return candidate;
  }
  return "python3";
}

function prepareDevCoreWrapper(rootDir, env = process.env, fsImpl = fs) {
  const wrapperPath = devCoreWrapperPath(rootDir);
  const repoCommand = path.resolve(rootDir, "..", "bin", "codex-account");
  const pythonCommand = resolveDevPythonCommand({ env, fsImpl });
  fsImpl.mkdirSync(path.dirname(wrapperPath), { recursive: true });
  fsImpl.writeFileSync(
    wrapperPath,
    `#!/bin/sh\nexec ${JSON.stringify(pythonCommand)} ${JSON.stringify(repoCommand)} "$@"\n`,
    { mode: 0o755 },
  );
  try {
    fsImpl.chmodSync(wrapperPath, 0o755);
  } catch (_) {}
  return wrapperPath;
}

function buildDevRuntimeEnv(rootDir, env = process.env, platform = process.platform, fsImpl = fs) {
  const nextEnv = {
    ...env,
    CAM_ELECTRON_RENDERER_URL: rendererUrl,
    CAM_ELECTRON_USE_DEV_SERVER: "1",
    CAM_ELECTRON_STARTUP_DEBUG: "1",
    CAM_ELECTRON_APP_LAUNCH_CONTEXT: "dev-script",
  };
  if (platform !== "win32") {
    nextEnv.CAM_ELECTRON_CORE_COMMAND = prepareDevCoreWrapper(rootDir, env, fsImpl);
  }
  return nextEnv;
}

function binPath(rootDir, name, platform = process.platform) {
  return path.join(rootDir, "node_modules", ".bin", platform === "win32" ? `${name}.cmd` : name);
}

function missingRuntimeBins({ root: rootDir = root, existsSync = require("node:fs").existsSync, platform = process.platform } = {}) {
  return ["vite", "electron"].filter((name) => !existsSync(binPath(rootDir, name, platform)));
}

function waitForVite() {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 20000;
    function check() {
      const req = http.get(rendererUrl, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() > deadline) {
          reject(new Error("Vite renderer did not start in time"));
          return;
        }
        setTimeout(check, 250);
      });
    }
    check();
  });
}

function getMacDevAppPaths(rootDir = root) {
  const sourceApp = path.join(rootDir, "node_modules", "electron", "dist", "Electron.app");
  const runtimeDir = path.join(rootDir, MAC_RUNTIME_DIRNAME);
  const appBundle = path.join(runtimeDir, MAC_APP_BUNDLE_NAME);
  return {
    sourceApp,
    runtimeDir,
    appBundle,
    executable: path.join(appBundle, "Contents", "MacOS", "Electron"),
    infoPlist: path.join(appBundle, "Contents", "Info.plist"),
    resourcesDir: path.join(appBundle, "Contents", "Resources"),
    iconTarget: path.join(appBundle, "Contents", "Resources", path.basename(getMacIconPath())),
  };
}

function getWindowsDevAppPaths(rootDir = root) {
  const sourceDist = path.join(rootDir, "node_modules", "electron", "dist");
  const runtimeDir = path.join(rootDir, WINDOWS_RUNTIME_DIRNAME);
  return {
    sourceDist,
    runtimeDir,
    sourceExecutable: path.join(sourceDist, "electron.exe"),
    executable: path.join(runtimeDir, WINDOWS_APP_EXE_NAME),
    stockExecutable: path.join(runtimeDir, "electron.exe"),
    iconPath: path.join(rootDir, "assets", path.basename(getIconPath("win32"))),
    rcedit: path.join(rootDir, "node_modules", "electron-winstaller", "vendor", "rcedit.exe"),
  };
}

function prepareMacDevAppBundle({
  rootDir = root,
  fsImpl = fs,
  execFileSyncImpl = execFileSync,
} = {}) {
  const paths = getMacDevAppPaths(rootDir);
  fsImpl.rmSync(paths.runtimeDir, { recursive: true, force: true });
  fsImpl.mkdirSync(paths.runtimeDir, { recursive: true });
  execFileSyncImpl("/usr/bin/ditto", [paths.sourceApp, paths.appBundle]);
  fsImpl.copyFileSync(getMacIconPath(), paths.iconTarget);

  const plistTool = "/usr/libexec/PlistBuddy";
  const plistCommands = [
    ["-c", `Set :CFBundleDisplayName ${DEV_APP_NAME}`, paths.infoPlist],
    ["-c", `Set :CFBundleName ${DEV_APP_NAME}`, paths.infoPlist],
    ["-c", `Set :CFBundleIdentifier ${DEV_APP_ID}`, paths.infoPlist],
    ["-c", `Set :CFBundleIconFile ${path.basename(getMacIconPath())}`, paths.infoPlist],
  ];
  for (const args of plistCommands) {
    execFileSyncImpl(plistTool, args);
  }
  return paths;
}

function prepareWindowsDevRuntime({
  rootDir = root,
  fsImpl = fs,
  execFileSyncImpl = execFileSync,
} = {}) {
  const paths = getWindowsDevAppPaths(rootDir);
  fsImpl.rmSync(paths.runtimeDir, { recursive: true, force: true });
  fsImpl.mkdirSync(paths.runtimeDir, { recursive: true });
  fsImpl.cpSync(paths.sourceDist, paths.runtimeDir, { recursive: true });
  fsImpl.copyFileSync(paths.stockExecutable, paths.executable);
  execFileSyncImpl(paths.rcedit, [
    paths.executable,
    "--set-icon",
    paths.iconPath,
    "--set-version-string",
    "ProductName",
    DEV_APP_NAME,
    "--set-version-string",
    "FileDescription",
    DEV_APP_NAME,
    "--set-version-string",
    "InternalName",
    DEV_APP_NAME,
    "--set-version-string",
    "OriginalFilename",
    WINDOWS_APP_EXE_NAME,
  ]);
  return paths;
}

function getElectronLaunchSpec({
  rootDir = root,
  platform = process.platform,
  env = process.env,
  fsImpl = fs,
  execFileSyncImpl = execFileSync,
} = {}) {
  if (platform === "darwin") {
    const paths = prepareMacDevAppBundle({ rootDir, fsImpl, execFileSyncImpl });
    return {
      command: paths.executable,
      args: ["."],
      options: {
        cwd: rootDir,
        stdio: "inherit",
        env: buildDevRuntimeEnv(rootDir, env, platform, fsImpl),
      },
      appBundle: paths.appBundle,
    };
  }
  if (platform === "win32") {
    const paths = prepareWindowsDevRuntime({ rootDir, fsImpl, execFileSyncImpl });
    return {
      command: paths.executable,
      args: ["."],
      options: {
        cwd: rootDir,
        stdio: "inherit",
        env: buildDevRuntimeEnv(rootDir, env, platform, fsImpl),
      },
      appBundle: "",
      runtimeDir: paths.runtimeDir,
    };
  }
  return {
    command: binPath(rootDir, "electron", platform),
    args: ["."],
    options: {
      cwd: rootDir,
      stdio: "inherit",
      env: buildDevRuntimeEnv(rootDir, env, platform, fsImpl),
    },
    appBundle: "",
  };
}

function main() {
  const missing = missingRuntimeBins();
  if (missing.length) {
    console.error(
      `Electron desktop shell dependencies are missing: ${missing.join(", ")}. Run \`codex-account electron\` without --no-install first.`,
    );
    process.exit(1);
  }

  devLog("dev-session-start", {
    root,
    platform: process.platform,
    pid: process.pid,
    node: process.version,
    rendererUrl,
  });

  const vite = spawn(binPath(root, "vite"), ["--host", "127.0.0.1"], {
    cwd: root,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  devLog("vite-spawned", { pid: vite.pid || null });
  vite.on("error", (error) => {
    devLog("vite-error", { message: error.message });
    console.error(`Failed to start Vite renderer: ${error.message}`);
    process.exit(1);
  });
  vite.on("exit", (code, signal) => {
    devLog("vite-exit", { code, signal: signal || "" });
  });

  waitForVite()
    .then(() => {
      const electronSpec = getElectronLaunchSpec();
      if (process.platform === "win32" && /\.cmd$/i.test(electronSpec.command)) {
        electronSpec.options.shell = true;
      }
      devLog("electron-launch", {
        command: electronSpec.command,
        args: electronSpec.args,
        appBundle: electronSpec.appBundle || "",
        cwd: electronSpec.options.cwd,
        coreCommand: electronSpec.options.env.CAM_ELECTRON_CORE_COMMAND || "",
        appLaunchContext: electronSpec.options.env.CAM_ELECTRON_APP_LAUNCH_CONTEXT || "",
      });
      const electron = spawn(electronSpec.command, electronSpec.args, electronSpec.options);
      devLog("electron-spawned", { pid: electron.pid || null });
      electron.on("error", (error) => {
        vite.kill();
        devLog("electron-error", { message: error.message });
        console.error(`Failed to start Electron: ${error.message}`);
        process.exit(1);
      });
      electron.on("exit", (code, signal) => {
        devLog("electron-exit", { code, signal: signal || "" });
        vite.kill();
        process.exit(code || 0);
      });
    })
    .catch((error) => {
      vite.kill();
      devLog("vite-wait-failed", { message: error.message });
      console.error(error.message);
      process.exit(1);
    });
}

if (require.main === module) {
  main();
}

module.exports = {
  binPath,
  getElectronLaunchSpec,
  getMacDevAppPaths,
  getWindowsDevAppPaths,
  prepareDevCoreWrapper,
  main,
  missingRuntimeBins,
  buildDevRuntimeEnv,
  prepareMacDevAppBundle,
  prepareWindowsDevRuntime,
};
