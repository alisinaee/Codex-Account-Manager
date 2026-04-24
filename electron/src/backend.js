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
  let state = readServiceState(options);
  if (state.running) {
    return state;
  }
  state = getDefaultBackendState();
  try {
    await fetchJson(`${state.baseUrl}api/usage-local/current?timeout=1`, { timeoutMs: 1500 });
    return readServiceState(options);
  } catch (_) {
    runServiceCommand("start", options);
    await waitForBackend(state, options);
    return readServiceState(options);
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
  ensureBackendRunning,
  fetchCurrentUsage,
  getDefaultBackendState,
  normalizeServiceStatus,
  readServiceState,
  runServiceCommand,
  startServiceDetached,
};
