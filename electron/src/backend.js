"use strict";

const { spawn, spawnSync } = require("node:child_process");
const {
  buildServiceStateFromStatus,
  parseServiceStatusOutput,
} = require("./api-client");

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 4673;
const DEFAULT_COMMAND = "codex-account";

function getDefaultBackendState() {
  return {
    host: DEFAULT_HOST,
    port: DEFAULT_PORT,
    baseUrl: `http://${DEFAULT_HOST}:${DEFAULT_PORT}/`,
  };
}

function buildServiceCommand(action, options = {}) {
  const host = options.host || DEFAULT_HOST;
  const port = Number(options.port || DEFAULT_PORT);
  const args = ["ui-service", action, "--host", host, "--port", String(port)];
  if (action === "start" || action === "restart") {
    args.push("--no-open");
  }
  return {
    command: options.command || DEFAULT_COMMAND,
    args,
  };
}

function normalizeServiceStatus(status = {}) {
  const fallback = getDefaultBackendState();
  const host = String(status.host || fallback.host);
  const port = Number(status.port || fallback.port);
  const baseUrl = String(status.url || `http://${host}:${port}/`);
  return {
    running: Boolean(status.running),
    host,
    port,
    baseUrl,
  };
}

function buildServiceRuntimeContract(status = {}) {
  const normalized = normalizeServiceStatus({
    running: status.running,
    host: status.host,
    port: status.port,
    url: status.baseUrl || status.url,
  });
  return {
    ...normalized,
    healthy: Boolean(status.healthy ?? normalized.running),
    token: String(status.token || ""),
  };
}

function runServiceCommand(action, options = {}) {
  const spec = buildServiceCommand(action, options);
  const result = spawnSync(spec.command, spec.args, {
    encoding: "utf8",
    timeout: options.timeoutMs || 10000,
  });
  return {
    ok: result.status === 0,
    status: result.status,
    stdout: result.stdout || "",
    stderr: result.stderr || "",
  };
}

function readServiceState(options = {}) {
  const result = runServiceCommand("status", options);
  if (!result.ok) {
    return { ...getDefaultBackendState(), running: false, token: "" };
  }
  try {
    return buildServiceStateFromStatus(parseServiceStatusOutput(result.stdout));
  } catch (_) {
    return { ...getDefaultBackendState(), running: false, token: "" };
  }
}

function startServiceDetached(options = {}) {
  const spec = buildServiceCommand("start", options);
  const child = spawn(spec.command, spec.args, {
    detached: true,
    stdio: "ignore",
  });
  child.unref();
  return child.pid;
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 10000);
  try {
    const response = await fetch(url, { signal: controller.signal });
    const payload = await response.json();
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.error?.message || `request failed: ${response.status}`);
    }
    return payload?.data || payload;
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForBackend(state, options = {}) {
  const deadline = Date.now() + (options.timeoutMs || 10000);
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      await fetchJson(`${state.baseUrl}api/usage-local/current?timeout=1`, { timeoutMs: 1500 });
      return true;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
  }
  throw new Error(`Codex Account Manager UI service did not become ready: ${lastError?.message || "timeout"}`);
}

async function ensureBackendRunning(options = {}) {
  const readServiceStateImpl = options.readServiceStateImpl || readServiceState;
  const runServiceCommandImpl = options.runServiceCommandImpl || runServiceCommand;
  const fetchJsonImpl = options.fetchJsonImpl || fetchJson;
  const waitForBackendImpl = options.waitForBackendImpl || waitForBackend;
  if (options.forceRestart) {
    const state = getDefaultBackendState();
    runServiceCommandImpl("restart", options);
    await waitForBackendImpl(state, options);
    return readServiceStateImpl(options);
  }

  let state = readServiceStateImpl(options);
  if (state.running) {
    return state;
  }
  state = getDefaultBackendState();
  try {
    await fetchJsonImpl(`${state.baseUrl}api/usage-local/current?timeout=1`, { timeoutMs: 1500 });
    return readServiceStateImpl(options);
  } catch (_) {
    runServiceCommandImpl("start", options);
    await waitForBackendImpl(state, options);
    return readServiceStateImpl(options);
  }
}

async function fetchCurrentUsage(state = getDefaultBackendState(), options = {}) {
  const timeout = Number(options.timeoutSec || 7);
  return fetchJson(`${state.baseUrl}api/usage-local/current?timeout=${encodeURIComponent(String(timeout))}`, {
    timeoutMs: options.timeoutMs || 12000,
  });
}

module.exports = {
  buildServiceCommand,
  buildServiceRuntimeContract,
  ensureBackendRunning,
  fetchCurrentUsage,
  getDefaultBackendState,
  normalizeServiceStatus,
  readServiceState,
  runServiceCommand,
  startServiceDetached,
};
