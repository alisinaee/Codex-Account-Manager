"use strict";

const fs = require("node:fs");

function joinUrl(baseUrl, path) {
  return `${String(baseUrl || "").replace(/\/+$/, "")}${path}`;
}

function parseServiceStatusOutput(stdout) {
  const raw = JSON.parse(String(stdout || "{}"));
  return {
    running: Boolean(raw.running),
    baseUrl: String(raw.url || "http://127.0.0.1:4673/"),
    pidFile: String(raw.pid_file || ""),
  };
}

function buildServiceStateFromStatus(status, fsImpl = fs) {
  let pidInfo = {};
  if (status?.pidFile) {
    try {
      pidInfo = JSON.parse(fsImpl.readFileSync(status.pidFile, "utf8"));
    } catch (_) {
      pidInfo = {};
    }
  }
  const host = String(pidInfo.host || new URL(status.baseUrl).hostname || "127.0.0.1");
  const port = Number(pidInfo.port || new URL(status.baseUrl).port || 4673);
  return {
    running: Boolean(status.running),
    baseUrl: String(status.baseUrl || `http://${host}:${port}/`),
    token: String(pidInfo.token || ""),
    host,
    port,
  };
}

function buildApiHeaders(state = {}) {
  const headers = {
    "Content-Type": "application/json",
  };
  if (state.token) {
    headers["X-Codex-Token"] = state.token;
  }
  return headers;
}

function unwrapApiPayload(payload) {
  if (payload && payload.ok === true && Object.prototype.hasOwnProperty.call(payload, "data")) {
    return payload.data;
  }
  return payload;
}

function createApiClient({ state, fetchImpl = fetch }) {
  async function request(path, options = {}) {
    const headers = {
      ...buildApiHeaders(state),
      ...(options.headers || {}),
    };
    const response = await fetchImpl(joinUrl(state.baseUrl, path), {
      ...options,
      headers,
    });
    const payload = await response.json();
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.error?.message || `request failed: ${response.status}`);
    }
    return unwrapApiPayload(payload);
  }

  function getDesktopState() {
    return Promise.all([
      request("/api/current"),
      request("/api/list"),
      request("/api/usage-local/current?timeout=7"),
      request("/api/ui-config"),
      request("/api/auto-switch/state"),
    ]).then(([current, list, usage, config, autoSwitch]) => ({ current, list, usage, config, autoSwitch }));
  }

  async function switchProfile(name) {
    await request("/api/local/switch", {
      method: "POST",
      headers: buildApiHeaders(state),
      body: JSON.stringify({ name, no_restart: true }),
    });
    return getDesktopState();
  }

  async function saveConfigPatch(patch) {
    await request("/api/ui-config", {
      method: "POST",
      headers: buildApiHeaders(state),
      body: JSON.stringify(patch),
    });
    return getDesktopState();
  }

  return {
    getDesktopState,
    request,
    saveConfigPatch,
    switchProfile,
  };
}

module.exports = {
  buildApiHeaders,
  buildServiceStateFromStatus,
  createApiClient,
  parseServiceStatusOutput,
};
