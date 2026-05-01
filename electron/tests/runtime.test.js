const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildBootstrapInstallPlan,
  buildPythonRuntimeInstallPlan,
  extractCommandErrorDetail,
  detectPython,
  detectPipx,
  formatRuntimeDiagnostics,
  installPythonCore,
  installPythonRuntime,
  resolveWindowsPythonWingetIds,
  resolveRuntimeStatus,
} = require("../src/runtime");

test("buildBootstrapInstallPlan installs pipx and the Python core through the selected interpreter", () => {
  const plan = buildBootstrapInstallPlan({
    python: { command: "/usr/bin/python3", path: "/usr/bin/python3", version: "3.11.9", supported: true, available: true },
  });

  assert.deepEqual(plan.map((step) => [step.label, step.command, step.args]), [
    ["Install pipx", "/usr/bin/python3", ["-m", "pip", "install", "--user", "--break-system-packages", "pipx"]],
    ["Refresh pipx path", "/usr/bin/python3", ["-m", "pipx", "ensurepath"]],
    ["Install Codex Account Manager", "/usr/bin/python3", ["-m", "pipx", "install", "--force", "git+https://github.com/alisinaee/Codex-Account-Manager.git@main"]],
  ]);
});

test("buildPythonRuntimeInstallPlan uses winget on Windows", () => {
  const plan = buildPythonRuntimeInstallPlan({
    platform: "win32",
    packageIds: ["Python.Python.3.14"],
  });
  assert.deepEqual(plan.map((step) => [step.label, step.command, step.args]), [
    ["Install Python 3", "winget", [
      "install",
      "-e",
      "--id",
      "Python.Python.3.14",
      "--source",
      "winget",
      "--scope",
      "user",
      "--silent",
      "--disable-interactivity",
      "--accept-source-agreements",
      "--accept-package-agreements",
    ]],
  ]);
});

test("resolveWindowsPythonWingetIds picks latest Python 3 ids from winget search", () => {
  const ids = resolveWindowsPythonWingetIds({
    spawnSyncImpl: (_command, args) => {
      if (args?.[0] === "search") {
        return {
          status: 0,
          stdout: "Python 3.11 Python.Python.3.11 3.11.9\nPython 3.14 Python.Python.3.14 3.14.4",
          stderr: "",
        };
      }
      return { status: 1, stdout: "", stderr: "" };
    },
  });
  assert.equal(ids[0], "Python.Python.3.14");
  assert.ok(ids.includes("Python.Python.3.11"));
});

test("extractCommandErrorDetail drops progress bar noise and keeps final errors", () => {
  const message = extractCommandErrorDetail({
    stdout: "█████▒▒▒▒ 10%\n██████▒▒▒ 20%\n",
    stderr: "No package found matching input criteria.\n",
    code: 1,
  });
  assert.equal(message, "No package found matching input criteria.");
});

test("buildBootstrapInstallPlan skips pipx installation when a pipx binary is already available", () => {
  const plan = buildBootstrapInstallPlan({
    python: { command: "/opt/homebrew/bin/python3", path: "/opt/homebrew/bin/python3", version: "3.14.4", supported: true, available: true },
    pipx: { available: true, command: "/opt/homebrew/bin/pipx" },
  });

  assert.deepEqual(plan.map((step) => [step.label, step.command, step.args]), [
    ["Refresh pipx path", "/opt/homebrew/bin/pipx", ["ensurepath"]],
    ["Install Codex Account Manager", "/opt/homebrew/bin/pipx", ["install", "--force", "git+https://github.com/alisinaee/Codex-Account-Manager.git@main"]],
  ]);
});

test("detectPipx checks common macOS install locations outside Finder PATH", () => {
  const calls = [];
  const pipx = detectPipx({
    platform: "darwin",
    env: {},
    spawnSyncImpl: (command, args) => {
      calls.push([command, args]);
      if (command === "/opt/homebrew/bin/pipx") {
        return { status: 0, stdout: "1.7.1\n", stderr: "" };
      }
      return { status: 1, stdout: "", stderr: "not found" };
    },
  });

  assert.equal(pipx.available, true);
  assert.equal(pipx.command, "/opt/homebrew/bin/pipx");
  assert.ok(calls.some(([command]) => command === "/opt/homebrew/bin/pipx"));
});

test("buildBootstrapInstallPlan prefers Homebrew for pipx when pipx is missing on macOS", () => {
  const plan = buildBootstrapInstallPlan({
    python: { command: "/opt/homebrew/bin/python3", path: "/opt/homebrew/bin/python3", version: "3.14.4", supported: true, available: true },
    pipx: { available: false, command: "" },
    brew: { available: true, command: "/opt/homebrew/bin/brew" },
  });

  assert.deepEqual(plan.map((step) => [step.label, step.command, step.args]), [
    ["Install pipx", "/opt/homebrew/bin/brew", ["install", "pipx"]],
    ["Refresh pipx path", "pipx", ["ensurepath"]],
    ["Install Codex Account Manager", "pipx", ["install", "--force", "git+https://github.com/alisinaee/Codex-Account-Manager.git@main"]],
  ]);
});

test("detectPython checks common macOS install locations when PATH only exposes the system python", () => {
  const calls = [];
  const python = detectPython({
    platform: "darwin",
    env: {},
    spawnSyncImpl: (command, args) => {
      calls.push([command, args]);
      if (command === "python3") {
        return { status: 0, stdout: "Python 3.9.6", stderr: "" };
      }
      if (command === "/opt/homebrew/bin/python3") {
        return { status: 0, stdout: "Python 3.14.4", stderr: "" };
      }
      return { status: 1, stdout: "", stderr: "not found" };
    },
  });

  assert.equal(python.version, "3.14.4");
  assert.equal(python.path, "/opt/homebrew/bin/python3");
  assert.ok(calls.some(([command]) => command === "/opt/homebrew/bin/python3"));
});

test("resolveRuntimeStatus reports core_missing when Python is available but codex-account is not", async () => {
  const runtime = await resolveRuntimeStatus({
    loadStoredRuntimeState: () => ({}),
    detectPython: async () => ({
      available: true,
      supported: true,
      version: "3.11.9",
      path: "/usr/bin/python3",
      command: "/usr/bin/python3",
    }),
    runDoctor: async () => null,
  });

  assert.equal(runtime.phase, "core_missing");
  assert.equal(runtime.python.version, "3.11.9");
  assert.equal(runtime.core.installed, false);
});

test("resolveRuntimeStatus uses the stored command path when PATH lookup is stale", async () => {
  const runtime = await resolveRuntimeStatus({
    loadStoredRuntimeState: () => ({ commandPath: "/Users/test/.local/bin/codex-account" }),
    detectPython: async () => ({
      available: true,
      supported: true,
      version: "3.11.9",
      path: "/usr/bin/python3",
      command: "/usr/bin/python3",
    }),
    runDoctor: async (commandPath) => {
      if (commandPath !== "/Users/test/.local/bin/codex-account") {
        return null;
      }
      return {
        python: { available: true, supported: true, version: "3.11.9", path: "/usr/bin/python3" },
        core: {
          installed: true,
          version: "0.0.21",
          command_path: "/Users/test/.local/bin/codex-account",
          min_supported_version: "0.0.21",
          meets_minimum_version: true,
        },
        ui_service: {
          running: false,
          healthy: false,
          host: "127.0.0.1",
          port: 4673,
          base_url: "http://127.0.0.1:4673/",
          token: "",
        },
        errors: [],
      };
    },
  });

  assert.equal(runtime.phase, "ready");
  assert.equal(runtime.core.commandPath, "/Users/test/.local/bin/codex-account");
});

test("resolveRuntimeStatus keeps the explicit dev core command over doctor path hints", async () => {
  const runtime = await resolveRuntimeStatus({
    env: { CAM_ELECTRON_CORE_COMMAND: "/repo/bin/codex-account" },
    loadStoredRuntimeState: () => ({ commandPath: "/Users/test/.local/bin/codex-account" }),
    detectPython: async () => ({
      available: true,
      supported: true,
      version: "3.11.9",
      path: "/usr/bin/python3",
      command: "/usr/bin/python3",
    }),
    runDoctor: async (commandPath) => {
      if (commandPath !== "/repo/bin/codex-account") {
        return null;
      }
      return {
        python: { available: true, supported: true, version: "3.11.9", path: "/usr/bin/python3" },
        core: {
          installed: true,
          version: "0.0.21",
          command_path: "/Users/test/.local/bin/codex-account",
          min_supported_version: "0.0.21",
          meets_minimum_version: true,
        },
        ui_service: {
          running: false,
          healthy: false,
          host: "127.0.0.1",
          port: 4673,
          base_url: "http://127.0.0.1:4673/",
          token: "",
        },
        errors: [],
      };
    },
  });

  assert.equal(runtime.phase, "ready");
  assert.equal(runtime.core.commandPath, "/repo/bin/codex-account");
});

test("resolveRuntimeStatus blocks outdated Python core versions", async () => {
  const runtime = await resolveRuntimeStatus({
    minCoreVersion: "0.0.21",
    loadStoredRuntimeState: () => ({}),
    detectPython: async () => ({
      available: true,
      supported: true,
      version: "3.11.9",
      path: "/usr/bin/python3",
      command: "/usr/bin/python3",
    }),
    runDoctor: async () => ({
      python: { available: true, supported: true, version: "3.11.9", path: "/usr/bin/python3" },
      core: {
        installed: true,
        version: "0.0.10",
        command_path: "/Users/test/.local/bin/codex-account",
        min_supported_version: "0.0.21",
        meets_minimum_version: false,
      },
      ui_service: {
        running: false,
        healthy: false,
        host: "127.0.0.1",
        port: 4673,
        base_url: "http://127.0.0.1:4673/",
        token: "",
      },
      errors: [],
    }),
  });

  assert.equal(runtime.phase, "error");
  assert.equal(runtime.reason, "core_update_required");
});

test("resolveRuntimeStatus accepts a legacy installed core when doctor is unsupported", async () => {
  const runtime = await resolveRuntimeStatus({
    loadStoredRuntimeState: () => ({ commandPath: "/Users/test/.local/bin/codex-account" }),
    detectPython: async () => ({
      available: true,
      supported: true,
      version: "3.14.4",
      path: "/opt/homebrew/bin/python3",
      command: "/opt/homebrew/bin/python3",
    }),
    runDoctor: async (commandPath) => {
      if (commandPath === "/Users/test/.local/bin/codex-account") {
        return { legacy: true, commandPath, message: "doctor command is not supported" };
      }
      return null;
    },
  });

  assert.equal(runtime.phase, "ready");
  assert.equal(runtime.reason, "legacy_core");
  assert.equal(runtime.core.installed, true);
  assert.equal(runtime.core.commandPath, "/Users/test/.local/bin/codex-account");
  assert.equal(runtime.core.version, "legacy");
  assert.ok(runtime.errors.some((row) => row.code === "LEGACY_CORE"));
});

test("installPythonCore refreshes the Homebrew pipx command and streams progress", async () => {
  const progress = [];
  const spawned = [];
  const childFactories = [];
  let brewInstalledPipx = false;
  const makeChild = ({ stdout = "", stderr = "", code = 0 }) => ({
    stdout: {
      setEncoding() {},
      on(event, handler) {
        if (event === "data" && stdout) process.nextTick(() => handler(stdout));
      },
    },
    stderr: {
      setEncoding() {},
      on(event, handler) {
        if (event === "data" && stderr) process.nextTick(() => handler(stderr));
      },
    },
    on(event, handler) {
      if (event === "close") process.nextTick(() => handler(code));
    },
  });

  childFactories.push(makeChild({ stdout: "brew done\n" }));
  childFactories.push(makeChild({ stdout: "ensurepath done\n" }));
  childFactories.push(makeChild({ stdout: "install done\n" }));

  await installPythonCore({
    python: { path: "/opt/homebrew/bin/python3", command: "/opt/homebrew/bin/python3", supported: true, available: true },
  }, {
    onProgress: (event) => progress.push(event),
    spawnSyncImpl: (command) => {
      if (command === "pipx") return { status: 1, stdout: "", stderr: "missing" };
      if (command === "/opt/homebrew/bin/pipx") {
        return brewInstalledPipx
          ? { status: 0, stdout: "1.7.1\n", stderr: "" }
          : { status: 1, stdout: "", stderr: "missing" };
      }
      if (command === "brew" || command === "/opt/homebrew/bin/brew") return { status: 0, stdout: "Homebrew 4.0.0\n", stderr: "" };
      return { status: 1, stdout: "", stderr: "missing" };
    },
    spawnImpl: (command, args) => {
      spawned.push([command, args]);
      if ((command === "brew" || command === "/opt/homebrew/bin/brew") && args[0] === "install" && args[1] === "pipx") {
        brewInstalledPipx = true;
      }
      return childFactories.shift() || makeChild({});
    },
  });

  assert.equal(spawned.length, 3);
  assert.deepEqual(spawned.map(([, args]) => args), [
    ["install", "pipx"],
    ["ensurepath"],
    ["install", "--force", "git+https://github.com/alisinaee/Codex-Account-Manager.git@main"],
  ]);
  assert.equal(spawned[0][0], "brew");
  assert.equal(spawned[1][0], "/opt/homebrew/bin/pipx");
  assert.equal(spawned[2][0], "/opt/homebrew/bin/pipx");
  assert.ok(progress.some((event) => event.label === "Install pipx" && event.status === "running"));
  assert.ok(progress.some((event) => event.label === "Refresh pipx path" && event.message === "ensurepath done"));
  assert.ok(progress.some((event) => event.label === "Install Codex Account Manager" && event.status === "done"));
});

test("installPythonRuntime installs Python with winget and streams progress", async () => {
  const progress = [];
  const spawned = [];
  const makeChild = ({ stdout = "", stderr = "", code = 0 }) => ({
    stdout: {
      setEncoding() {},
      on(event, handler) {
        if (event === "data" && stdout) process.nextTick(() => handler(stdout));
      },
    },
    stderr: {
      setEncoding() {},
      on(event, handler) {
        if (event === "data" && stderr) process.nextTick(() => handler(stderr));
      },
    },
    on(event, handler) {
      if (event === "close") process.nextTick(() => handler(code));
    },
  });

  await installPythonRuntime({}, {
    platform: "win32",
    onProgress: (event) => progress.push(event),
    spawnSyncImpl: (command, args) => {
      if (command === "winget" && args?.[0] === "--version") {
        return { status: 0, stdout: "v1.9.0", stderr: "" };
      }
      if (command === "winget" && args?.[0] === "search") {
        return { status: 0, stdout: "Python 3.14 Python.Python.3.14 3.14.4", stderr: "" };
      }
      return { status: 1, stdout: "", stderr: "missing" };
    },
    spawnImpl: (command, args) => {
      spawned.push([command, args]);
      return makeChild({ stdout: "Successfully installed\n" });
    },
  });

  assert.equal(spawned.length, 1);
  assert.deepEqual(spawned[0], [
    "winget",
    [
      "install",
      "-e",
      "--id",
      "Python.Python.3.14",
      "--source",
      "winget",
      "--scope",
      "user",
      "--silent",
      "--disable-interactivity",
      "--accept-source-agreements",
      "--accept-package-agreements",
    ],
  ]);
  assert.ok(progress.some((event) => event.label === "Install Python 3" && event.status === "running"));
  assert.ok(progress.some((event) => event.label === "Install Python 3" && event.status === "done"));
});

test("formatRuntimeDiagnostics includes backend logs and runtime details", () => {
  const output = formatRuntimeDiagnostics({
    runtimeState: {
      phase: "core_missing",
      reason: "core_missing",
      message: "Codex Account Manager core is not installed yet.",
      python: { available: true, supported: true, version: "3.14.4", path: "/opt/homebrew/bin/python3" },
      core: { installed: false, version: "", commandPath: "" },
      uiService: { running: false, healthy: false, baseUrl: "http://127.0.0.1:4673/", host: "127.0.0.1", port: 4673 },
      errors: [{ code: "CORE_MISSING", message: "Core not installed." }],
    },
    runtimeProgress: [{ ts: 10, label: "Bootstrap Python core", status: "running", message: "starting" }],
    backendState: { running: false, healthy: false, baseUrl: "http://127.0.0.1:4673/", host: "127.0.0.1", port: 4673 },
    backendLogs: [{ ts: "2026-04-25T12:00:00.000Z", level: "warn", message: "backend unavailable" }],
  });

  assert.match(output, /Runtime/);
  assert.match(output, /Phase: core_missing/);
  assert.match(output, /Version: 3.14.4/);
  assert.match(output, /CORE_MISSING: Core not installed/);
  assert.match(output, /Bootstrap Python core \(running\): starting/);
  assert.match(output, /WARN backend unavailable/);
});

test("formatRuntimeDiagnostics records backend fetch failures", () => {
  const output = formatRuntimeDiagnostics({
    runtimeState: { phase: "error", errors: [] },
    backendState: {},
    fetchError: "invalid session token",
  });

  assert.match(output, /Backend Logs/);
  assert.match(output, /unavailable: invalid session token/);
});
