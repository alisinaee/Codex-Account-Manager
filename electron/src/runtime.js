"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const { buildServiceRuntimeContract, getDefaultBackendState } = require("./backend");

const DEFAULT_MIN_CORE_VERSION = "0.0.12";
const DEFAULT_INSTALL_SPEC = "git+https://github.com/alisinaee/Codex-Account-Manager.git@main";
const RUNTIME_STATE_FILE = "runtime-state.json";
const WINGET_PYTHON_ID_PREFIX = "Python.Python.";

function formatLogLines(rows = []) {
  if (!Array.isArray(rows) || !rows.length) {
    return "none";
  }
  return rows
    .map((row) => {
      if (typeof row === "string") {
        return row;
      }
      const ts = row?.ts ? `[${row.ts}] ` : "";
      const level = row?.level ? `${String(row.level).toUpperCase()} ` : "";
      const message = row?.message ? String(row.message) : JSON.stringify(row);
      return `${ts}${level}${message}`.trim();
    })
    .join("\n");
}

function formatRuntimeDiagnostics({ runtimeState = {}, runtimeProgress = [], backendState = {}, backendLogs = [], fetchError = "" } = {}) {
  const state = normalizeRuntimeStatus(runtimeState);
  const progress = Array.isArray(runtimeProgress) ? runtimeProgress : [];
  const errors = Array.isArray(state.errors) ? state.errors : [];
  const backend = backendState || {};

  const lines = [
    "Codex Account Manager Runtime Diagnostics",
    `Generated: ${new Date().toISOString()}`,
    "",
    "Runtime",
    `Phase: ${state.phase || "unknown"}`,
    `Reason: ${state.reason || "-"}`,
    `Message: ${state.message || "-"}`,
    "",
    "Python",
    `Available: ${state.python?.available ? "yes" : "no"}`,
    `Supported: ${state.python?.supported ? "yes" : "no"}`,
    `Version: ${state.python?.version || "-"}`,
    `Path: ${state.python?.path || "-"}`,
    "",
    "Core",
    `Installed: ${state.core?.installed ? "yes" : "no"}`,
    `Version: ${state.core?.version || "-"}`,
    `Command: ${state.core?.commandPath || "-"}`,
    `Minimum Supported: ${state.core?.minSupportedVersion || "-"}`,
    "",
    "Backend",
    `Running: ${backend.running ? "yes" : "no"}`,
    `Healthy: ${backend.healthy ? "yes" : "no"}`,
    `Base URL: ${backend.baseUrl || state.uiService?.baseUrl || "-"}`,
    `Host: ${backend.host || state.uiService?.host || "-"}`,
    `Port: ${backend.port || state.uiService?.port || "-"}`,
    "",
    "Errors",
    errors.length ? errors.map((row) => `- ${row.code}: ${row.message}`).join("\n") : "none",
    "",
    "Bootstrap Progress",
    progress.length
      ? progress.map((row) => {
        const ts = row?.ts ? `[${new Date(row.ts).toISOString()}] ` : "";
        const label = row?.label ? `${row.label}` : row?.type || "Step";
        const status = row?.status ? ` (${row.status})` : "";
        const message = row?.message ? `: ${row.message}` : "";
        return `${ts}${label}${status}${message}`;
      }).join("\n")
      : "none",
    "",
    "Backend Logs",
    fetchError ? `unavailable: ${fetchError}` : formatLogLines(backendLogs),
  ];

  return lines.join("\n");
}

function versionParts(raw) {
  return String(raw || "")
    .trim()
    .replace(/^v/i, "")
    .split(".")
    .map((part) => Number.parseInt(part, 10))
    .map((part) => (Number.isFinite(part) ? part : 0));
}

function isVersionAtLeast(found, minimum) {
  const a = versionParts(found);
  const b = versionParts(minimum);
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const left = a[index] || 0;
    const right = b[index] || 0;
    if (left > right) return true;
    if (left < right) return false;
  }
  return true;
}

function pythonInstallUrl(platform = process.platform) {
  if (platform === "win32") {
    return "https://www.python.org/downloads/windows/";
  }
  if (platform === "darwin") {
    return "https://www.python.org/downloads/macos/";
  }
  return "https://www.python.org/downloads/";
}

function normalizeRuntimeStatus(status = {}, { minCoreVersion = DEFAULT_MIN_CORE_VERSION, platform = process.platform } = {}) {
  const fallbackBackend = getDefaultBackendState();
  const python = status.python || {};
  const core = status.core || {};
  const uiService = status.uiService || status.ui_service || {};
  return {
    phase: String(status.phase || "checking_runtime"),
    reason: String(status.reason || ""),
    message: String(status.message || ""),
    minCoreVersion,
    python: {
      available: Boolean(python.available),
      supported: Boolean(python.supported),
      version: String(python.version || ""),
      path: String(python.path || ""),
      command: String(python.command || python.path || ""),
      args: Array.isArray(python.args) ? python.args.map((item) => String(item)) : [],
      installUrl: String(python.installUrl || python.install_url || pythonInstallUrl(platform)),
    },
    core: {
      installed: Boolean(core.installed),
      version: String(core.version || ""),
      commandPath: String(core.commandPath || core.command_path || ""),
      minSupportedVersion: String(core.minSupportedVersion || core.min_supported_version || minCoreVersion),
      meetsMinimumVersion: Boolean(core.meetsMinimumVersion ?? core.meets_minimum_version ?? false),
    },
    uiService: buildServiceRuntimeContract({
      running: uiService.running,
      healthy: uiService.healthy,
      host: uiService.host || fallbackBackend.host,
      port: uiService.port || fallbackBackend.port,
      baseUrl: uiService.baseUrl || uiService.base_url || fallbackBackend.baseUrl,
      token: uiService.token || "",
    }),
    errors: Array.isArray(status.errors) ? status.errors.map((row) => ({
      code: String(row?.code || "UNKNOWN"),
      message: String(row?.message || ""),
    })) : [],
    mockMode: Boolean(status.mockMode),
  };
}

function runtimeStatePath({ appLike }) {
  return path.join(appLike.getPath("userData"), RUNTIME_STATE_FILE);
}

function loadStoredRuntimeState({ appLike, fsImpl = fs } = {}) {
  try {
    const raw = fsImpl.readFileSync(runtimeStatePath({ appLike }), "utf8");
    const payload = JSON.parse(raw);
    return payload && typeof payload === "object" ? payload : {};
  } catch (_) {
    return {};
  }
}

function saveStoredRuntimeState(state, { appLike, fsImpl = fs } = {}) {
  if (!appLike) return;
  const next = {
    commandPath: String(state?.commandPath || ""),
    version: String(state?.version || ""),
    pythonPath: String(state?.pythonPath || ""),
    updatedAt: new Date().toISOString(),
  };
  try {
    fsImpl.mkdirSync(appLike.getPath("userData"), { recursive: true });
    fsImpl.writeFileSync(runtimeStatePath({ appLike }), JSON.stringify(next, null, 2));
  } catch (_) {}
}

function unique(items) {
  return [...new Set((items || []).filter(Boolean))];
}

function detectPython({ platform = process.platform, env = process.env, spawnSyncImpl = spawnSync } = {}) {
  const candidates = [];
  if (env.CAM_ELECTRON_PYTHON) {
    candidates.push({ command: env.CAM_ELECTRON_PYTHON, args: [] });
  }
  if (platform === "win32") {
    candidates.push({ command: "py", args: ["-3.11"] });
    candidates.push({ command: "py", args: ["-3"] });
    candidates.push({ command: "python", args: [] });
  } else if (platform === "darwin") {
    candidates.push({ command: "python3", args: [] });
    candidates.push({ command: "/opt/homebrew/bin/python3", args: [] });
    candidates.push({ command: "/usr/local/bin/python3", args: [] });
    candidates.push({ command: "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", args: [] });
    candidates.push({ command: "python", args: [] });
  } else {
    candidates.push({ command: "python3", args: [] });
    candidates.push({ command: "python", args: [] });
  }

  const seen = new Set();
  let fallback = null;
  for (const candidate of candidates) {
    const key = `${candidate.command} ${candidate.args.join(" ")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const result = spawnSyncImpl(candidate.command, [...candidate.args, "--version"], {
      encoding: "utf8",
      timeout: 8000,
    });
    if (result.error || result.status !== 0) {
      continue;
    }
    const output = String(result.stdout || result.stderr || "").trim();
    const match = output.match(/Python\s+(\d+\.\d+(?:\.\d+)?)/i);
    if (!match) {
      continue;
    }
    const version = match[1];
    const detected = {
      available: true,
      supported: isVersionAtLeast(version, "3.11.0"),
      version,
      path: candidate.command,
      command: [candidate.command, ...candidate.args].join(" ").trim(),
      args: candidate.args,
      installUrl: pythonInstallUrl(platform),
    };
    if (detected.supported) {
      return detected;
    }
    if (!fallback) {
      fallback = detected;
    }
  }
  return fallback || {
    available: false,
    supported: false,
    version: "",
    path: "",
    command: "",
    args: [],
    installUrl: pythonInstallUrl(platform),
  };
}

function candidateCoreCommands({ platform = process.platform, env = process.env, storedState = {} } = {}) {
  const home = os.homedir();
  const items = [
    env.CAM_ELECTRON_CORE_COMMAND,
    storedState.commandPath,
    platform === "win32" ? "codex-account.exe" : "",
    platform === "win32" ? "codex-account.cmd" : "",
    "codex-account",
    platform === "win32" ? path.join(home, ".local", "bin", "codex-account.exe") : path.join(home, ".local", "bin", "codex-account"),
  ];
  return unique(items);
}

function detectPipx({ platform = process.platform, env = process.env, spawnSyncImpl = spawnSync } = {}) {
  const home = os.homedir();
  const candidates = unique([
    env.CAM_ELECTRON_PIPX,
    "pipx",
    platform === "darwin" ? "/opt/homebrew/bin/pipx" : "",
    platform === "darwin" ? "/usr/local/bin/pipx" : "",
    platform === "win32" ? path.join(home, "AppData", "Roaming", "Python", "Python311", "Scripts", "pipx.exe") : "",
    platform !== "win32" ? path.join(home, ".local", "bin", "pipx") : "",
  ]);

  for (const command of candidates) {
    const result = spawnSyncImpl(command, ["--version"], {
      encoding: "utf8",
      timeout: 8000,
    });
    if (result.error || result.status !== 0) {
      continue;
    }
    return {
      available: true,
      command,
      version: String(result.stdout || result.stderr || "").trim(),
    };
  }

  return {
    available: false,
    command: "",
    version: "",
  };
}

function detectBrew({ platform = process.platform, spawnSyncImpl = spawnSync } = {}) {
  if (platform !== "darwin") {
    return { available: false, command: "" };
  }
  for (const command of ["brew", "/opt/homebrew/bin/brew", "/usr/local/bin/brew"]) {
    const result = spawnSyncImpl(command, ["--version"], {
      encoding: "utf8",
      timeout: 8000,
    });
    if (!result.error && result.status === 0) {
      return { available: true, command };
    }
  }
  return { available: false, command: "" };
}

function runDoctor(commandPath, { spawnSyncImpl = spawnSync } = {}) {
  const result = spawnSyncImpl(commandPath, ["doctor", "--json"], {
    encoding: "utf8",
    timeout: 12000,
  });
  const output = String(result.stdout || result.stderr || result.error?.message || "").trim();
  if (result.error || result.status !== 0) {
    if (/invalid choice:\s*['"]doctor['"]|unrecognized arguments|unknown command/i.test(output)) {
      return {
        legacy: true,
        commandPath,
        message: output || "Installed core does not support desktop diagnostics yet.",
      };
    }
    return null;
  }
  try {
    return JSON.parse(String(result.stdout || "{}"));
  } catch (_) {
    if (/invalid choice:\s*['"]doctor['"]|unrecognized arguments|unknown command/i.test(output)) {
      return {
        legacy: true,
        commandPath,
        message: output || "Installed core does not support desktop diagnostics yet.",
      };
    }
    return null;
  }
}

async function resolveRuntimeStatus({
  env = process.env,
  platform = process.platform,
  minCoreVersion = DEFAULT_MIN_CORE_VERSION,
  loadStoredRuntimeState: loadStoredStateImpl = () => ({}),
  detectPython: detectPythonImpl = detectPython,
  runDoctor: runDoctorImpl = runDoctor,
} = {}) {
  if (env.CAM_ELECTRON_RUNTIME_FIXTURE) {
    return normalizeRuntimeStatus(JSON.parse(env.CAM_ELECTRON_RUNTIME_FIXTURE), { minCoreVersion, platform });
  }

  const storedState = loadStoredStateImpl() || {};
  const python = await detectPythonImpl({ platform, env });
  if (!python.available || !python.supported) {
    const reason = !python.available ? "python_missing" : "python_unsupported";
    return normalizeRuntimeStatus({
      phase: "python_missing",
      reason,
      message: !python.available
        ? "Python 3.11+ is required before the desktop shell can install the core."
        : `Python ${python.version} is too old. Python 3.11+ is required.`,
      python,
      core: { installed: false, version: "", commandPath: "" },
      uiService: getDefaultBackendState(),
      errors: [{ code: reason.toUpperCase(), message: !python.available ? "Python 3.11+ was not found." : "Python 3.11+ is required." }],
    }, { minCoreVersion, platform });
  }

  const candidates = candidateCoreCommands({ platform, env, storedState });
  for (const candidate of candidates) {
    const doctor = await runDoctorImpl(candidate);
    if (!doctor) {
      continue;
    }
    if (doctor.legacy) {
      return normalizeRuntimeStatus({
        phase: "ready",
        reason: "legacy_core",
        message: "A legacy Codex Account Manager core was detected. The desktop shell will try to start it and verify the backend directly.",
        python,
        core: {
          installed: true,
          version: storedState.version || "legacy",
          commandPath: doctor.commandPath || candidate,
          minSupportedVersion: minCoreVersion,
          meetsMinimumVersion: true,
        },
        uiService: getDefaultBackendState(),
        errors: [{
          code: "LEGACY_CORE",
          message: "The installed Python core does not support desktop diagnostics yet. Start the backend to verify it, then upgrade when possible.",
        }],
      }, { minCoreVersion, platform });
    }
    const normalized = normalizeRuntimeStatus({
      phase: "ready",
      python: doctor.python || python,
      core: {
        ...doctor.core,
        installed: true,
        commandPath: doctor.core?.command_path || candidate,
        minSupportedVersion: doctor.core?.min_supported_version || minCoreVersion,
        meetsMinimumVersion: doctor.core?.meets_minimum_version ?? isVersionAtLeast(doctor.core?.version || "", minCoreVersion),
      },
      uiService: doctor.ui_service || getDefaultBackendState(),
      errors: doctor.errors || [],
    }, { minCoreVersion, platform });
    if (!normalized.core.meetsMinimumVersion) {
      return {
        ...normalized,
        phase: "error",
        reason: "core_update_required",
        message: `Codex Account Manager core ${normalized.core.version || "unknown"} is older than the required ${normalized.core.minSupportedVersion}.`,
        errors: [...normalized.errors, { code: "CORE_UPDATE_REQUIRED", message: "Update the Python core before continuing." }],
      };
    }
    return normalized;
  }

  return normalizeRuntimeStatus({
    phase: "core_missing",
    reason: "core_missing",
    message: "Codex Account Manager core is not installed yet.",
    python,
    core: { installed: false, version: "", commandPath: "" },
    uiService: getDefaultBackendState(),
    errors: [{ code: "CORE_MISSING", message: "Codex Account Manager core is not installed." }],
  }, { minCoreVersion, platform });
}

function buildBootstrapInstallPlan({ python, pipx, brew, packageName = DEFAULT_INSTALL_SPEC } = {}) {
  const pythonCommand = String(python?.path || python?.command || "python3");
  const pythonArgs = Array.isArray(python?.args) ? python.args.map((item) => String(item)) : [];
  if (pipx?.available && pipx.command) {
    return [
      { label: "Refresh pipx path", command: pipx.command, args: ["ensurepath"] },
      { label: "Install Codex Account Manager", command: pipx.command, args: ["install", "--force", packageName] },
    ];
  }
  if (brew?.available && brew.command) {
    return [
      { label: "Install pipx", command: brew.command, args: ["install", "pipx"] },
      { label: "Refresh pipx path", command: "pipx", args: ["ensurepath"] },
      { label: "Install Codex Account Manager", command: "pipx", args: ["install", "--force", packageName] },
    ];
  }
  return [
    { label: "Install pipx", command: pythonCommand, args: [...pythonArgs, "-m", "pip", "install", "--user", "--break-system-packages", "pipx"] },
    { label: "Refresh pipx path", command: pythonCommand, args: [...pythonArgs, "-m", "pipx", "ensurepath"] },
    { label: "Install Codex Account Manager", command: pythonCommand, args: [...pythonArgs, "-m", "pipx", "install", "--force", packageName] },
  ];
}

function parseWingetPythonVersionFromId(id) {
  const value = String(id || "");
  if (!value.startsWith(WINGET_PYTHON_ID_PREFIX)) {
    return [];
  }
  return versionParts(value.slice(WINGET_PYTHON_ID_PREFIX.length));
}

function compareVersionArrays(left = [], right = []) {
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const a = Number.isFinite(left[index]) ? left[index] : 0;
    const b = Number.isFinite(right[index]) ? right[index] : 0;
    if (a > b) return 1;
    if (a < b) return -1;
  }
  return 0;
}

function buildPythonRuntimeInstallPlan({ platform = process.platform } = {}) {
  if (platform !== "win32") {
    return [];
  }
  return [];
}

function resolveWindowsPythonWingetIds({ spawnSyncImpl = spawnSync } = {}) {
  const discovered = new Set();
  const query = spawnSyncImpl("winget", ["search", "Python.Python", "--source", "winget"], {
    encoding: "utf8",
    timeout: 12000,
  });
  const output = String(query.stdout || query.stderr || "");
  const matches = output.match(/Python\.Python\.[0-9.]+/g) || [];
  for (const id of matches) {
    discovered.add(id);
  }

  const candidates = Array.from(discovered)
    .filter((id) => parseWingetPythonVersionFromId(id)[0] >= 3)
    .sort((a, b) => compareVersionArrays(parseWingetPythonVersionFromId(b), parseWingetPythonVersionFromId(a)));

  const fallback = ["Python.Python.3.14", "Python.Python.3.13", "Python.Python.3.12", "Python.Python.3.11"];
  return unique([...candidates, ...fallback]);
}

function buildPythonRuntimeInstallPlan({ platform = process.platform, packageIds = [] } = {}) {
  if (platform !== "win32") {
    return [];
  }
  return unique(packageIds).map((id, index) => ({
    label: index === 0 ? "Install Python 3" : `Install Python 3 (fallback ${index})`,
    command: "winget",
    args: [
      "install",
      "-e",
      "--id",
      String(id),
      "--source",
      "winget",
      "--scope",
      "user",
      "--silent",
      "--disable-interactivity",
      "--accept-source-agreements",
      "--accept-package-agreements",
    ],
    timeoutMs: 600000,
  }));
}

function stripAnsi(text) {
  return String(text || "").replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, "");
}

function normalizeOutputChunk(text) {
  return stripAnsi(text)
    .replace(/\u0008/g, "")
    .replace(/\r/g, "\n");
}

function isSpinnerFrame(text) {
  const compact = String(text || "").replace(/\s+/g, "");
  return compact.length > 0 && /^[-\\|/]+$/.test(compact);
}

function isProgressBarLine(text) {
  const line = String(text || "").trim();
  if (!line) return false;
  return /^[\u2588\u2593\u2592\u2591]+\s+\d+(?:\.\d+)?\s*(?:[KMG]B)\s*\/\s*\d+(?:\.\d+)?\s*(?:[KMG]B)$/i.test(line)
    || /^[\u2588\u2593\u2592\u2591]+\s+\d+%$/.test(line)
    || /^\d+%$/.test(line);
}

function isIgnorableTerminalLine(text) {
  return isSpinnerFrame(text) || isProgressBarLine(text);
}

function extractCommandErrorDetail({ stdout = "", stderr = "", code = 1 } = {}) {
  const merged = `${stderr}\n${stdout}`;
  const filtered = normalizeOutputChunk(merged)
    .split(/[\r\n]+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !isIgnorableTerminalLine(line));
  if (!filtered.length) {
    return `command exited with ${code}`;
  }
  return filtered.slice(-3).join("\n");
}

function runInstallStep(step, { spawnImpl = spawn, onProgress = () => {} } = {}) {
  return new Promise((resolve, reject) => {
    const stdout = [];
    const stderr = [];
    let lastProgressMessage = "";
    let settled = false;
    let timer = null;

    function finish(error, result) {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (error) {
        reject(error);
        return;
      }
      resolve(result);
    }

    let child;
    try {
      child = spawnImpl(step.command, step.args, {
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      finish(error);
      return;
    }

    function bindStream(stream, bucket) {
      if (!stream || typeof stream.on !== "function") return;
      if (typeof stream.setEncoding === "function") {
        stream.setEncoding("utf8");
      }
      stream.on("data", (chunk) => {
        const text = normalizeOutputChunk(chunk);
        if (!text) return;
        const lines = text
          .split(/[\r\n]+/)
          .map((line) => line.trim())
          .filter(Boolean);
        const meaningful = lines.filter((line) => !isIgnorableTerminalLine(line));
        if (meaningful.length) {
          bucket.push(`${meaningful.join("\n")}\n`);
        }
        for (const line of meaningful) {
          if (line === lastProgressMessage) continue;
          lastProgressMessage = line;
          onProgress({ type: "output", status: "running", label: step.label, message: line });
        }
      });
    }

    bindStream(child.stdout, stdout);
    bindStream(child.stderr, stderr);

    if (typeof child.on === "function") {
      child.on("error", (error) => finish(error));
      child.on("close", (code) => {
        const result = {
          status: code,
          stdout: stdout.join(""),
          stderr: stderr.join(""),
        };
        if (code === 0) {
          finish(null, result);
          return;
        }
        const detail = extractCommandErrorDetail(result);
        finish(new Error(detail));
      });
    } else {
      finish(new Error("Failed to start installer process."));
      return;
    }

    timer = setTimeout(() => {
      if (typeof child.kill === "function") {
        child.kill("SIGTERM");
      }
      finish(new Error(`Timed out while running ${step.label}.`));
    }, Number(step.timeoutMs || 120000));
  });
}

async function installPythonCore(runtimeState, {
  spawnImpl = spawn,
  spawnSyncImpl = spawnSync,
  onProgress = () => {},
  packageName = process.env.CAM_ELECTRON_CORE_INSTALL_SPEC || DEFAULT_INSTALL_SPEC,
} = {}) {
  let pipx = detectPipx({ spawnSyncImpl });
  const brew = detectBrew({ spawnSyncImpl });
  const plan = buildBootstrapInstallPlan({ python: runtimeState?.python, pipx, brew, packageName });
  const logs = [];
  for (const step of plan) {
    const command = step.command === "pipx" && pipx?.available && pipx.command ? pipx.command : step.command;
    onProgress({ type: "step", status: "running", label: step.label });
    const result = await runInstallStep({
      ...step,
      command,
    }, {
      spawnImpl,
      onProgress,
    });
    logs.push({
      label: step.label,
      command,
      args: step.args,
      stdout: String(result.stdout || ""),
      stderr: String(result.stderr || ""),
      status: result.status,
    });
    if (step.label === "Install pipx" || step.label === "Refresh pipx path") {
      pipx = detectPipx({ spawnSyncImpl });
    }
    onProgress({ type: "step", status: "done", label: step.label });
  }
  return logs;
}

async function installPythonRuntime(runtimeState, {
  platform = process.platform,
  spawnImpl = spawn,
  spawnSyncImpl = spawnSync,
  onProgress = () => {},
} = {}) {
  if (platform !== "win32") {
    throw new Error("Automatic Python installation is currently supported only on Windows.");
  }

  const wingetCheck = spawnSyncImpl("winget", ["--version"], {
    encoding: "utf8",
    timeout: 8000,
  });
  if (wingetCheck.error || wingetCheck.status !== 0) {
    throw new Error("winget is not available. Install App Installer (Microsoft Store) and try again.");
  }

  const packageIds = resolveWindowsPythonWingetIds({ spawnSyncImpl });
  const plan = buildPythonRuntimeInstallPlan({ platform, runtimeState, packageIds });
  if (!plan.length) {
    throw new Error("No compatible Python package was found in winget sources.");
  }

  const logs = [];
  let lastError = null;
  for (let index = 0; index < plan.length; index += 1) {
    const step = plan[index];
    onProgress({ type: "step", status: "running", label: step.label });
    try {
      const result = await runInstallStep(step, {
        spawnImpl,
        onProgress,
      });
      logs.push({
        label: step.label,
        command: step.command,
        args: step.args,
        stdout: String(result.stdout || ""),
        stderr: String(result.stderr || ""),
        status: result.status,
      });
      onProgress({ type: "step", status: "done", label: step.label });
      return logs;
    } catch (error) {
      lastError = error;
      onProgress({ type: "step", status: "failed", label: step.label, message: String(error?.message || error) });
      const noPackageFound = /no package found matching input criteria/i.test(String(error?.message || ""));
      if (!noPackageFound || index === plan.length - 1) {
        throw error;
      }
    }
  }
  if (lastError) {
    throw lastError;
  }
  return logs;
}

module.exports = {
  buildBootstrapInstallPlan,
  buildPythonRuntimeInstallPlan,
  compareVersionArrays,
  detectBrew,
  detectPipx,
  detectPython,
  extractCommandErrorDetail,
  formatRuntimeDiagnostics,
  installPythonCore,
  installPythonRuntime,
  isProgressBarLine,
  isSpinnerFrame,
  isVersionAtLeast,
  loadStoredRuntimeState,
  normalizeRuntimeStatus,
  parseWingetPythonVersionFromId,
  pythonInstallUrl,
  resolveWindowsPythonWingetIds,
  resolveRuntimeStatus,
  runDoctor,
  saveStoredRuntimeState,
};
