"use strict";

const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs");
const { execFileSync } = require("node:child_process");

const { APP_ID, APP_NAME, getMacIconPath } = require("../src/icons");

const root = path.resolve(__dirname, "..");
const rendererUrl = "http://127.0.0.1:5173";
const MAC_RUNTIME_DIRNAME = ".codex-electron-runtime";
const MAC_APP_BUNDLE_NAME = `${APP_NAME}.app`;

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
    ["-c", `Set :CFBundleDisplayName ${APP_NAME}`, paths.infoPlist],
    ["-c", `Set :CFBundleName ${APP_NAME}`, paths.infoPlist],
    ["-c", `Set :CFBundleIdentifier ${APP_ID}.dev`, paths.infoPlist],
    ["-c", `Set :CFBundleIconFile ${path.basename(getMacIconPath())}`, paths.infoPlist],
  ];
  for (const args of plistCommands) {
    execFileSyncImpl(plistTool, args);
  }
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
        env: { ...env, CAM_ELECTRON_RENDERER_URL: rendererUrl, CAM_ELECTRON_USE_DEV_SERVER: "1" },
      },
      appBundle: paths.appBundle,
    };
  }
  return {
    command: binPath(rootDir, "electron", platform),
    args: ["."],
    options: {
      cwd: rootDir,
      stdio: "inherit",
      env: { ...env, CAM_ELECTRON_RENDERER_URL: rendererUrl, CAM_ELECTRON_USE_DEV_SERVER: "1" },
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

  const vite = spawn(binPath(root, "vite"), ["--host", "127.0.0.1"], {
    cwd: root,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  vite.on("error", (error) => {
    console.error(`Failed to start Vite renderer: ${error.message}`);
    process.exit(1);
  });

  waitForVite()
    .then(() => {
      const electronSpec = getElectronLaunchSpec();
      if (process.platform === "win32") {
        electronSpec.options.shell = true;
      }
      const electron = spawn(electronSpec.command, electronSpec.args, electronSpec.options);
      electron.on("error", (error) => {
        vite.kill();
        console.error(`Failed to start Electron: ${error.message}`);
        process.exit(1);
      });
      electron.on("exit", (code) => {
        vite.kill();
        process.exit(code || 0);
      });
    })
    .catch((error) => {
      vite.kill();
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
  main,
  missingRuntimeBins,
  prepareMacDevAppBundle,
};
