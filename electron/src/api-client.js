"use strict";

const fs = require("node:fs");

const DEFAULT_REQUEST_TIMEOUT_MS = 12000;

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

function fallbackUsagePayload({ list, current, previousUsage } = {}) {
  const profileRows = Array.isArray(list?.profiles) ? list.profiles : [];
  const previousRows = Array.isArray(previousUsage?.profiles) ? previousUsage.profiles : [];
  const previousByName = new Map(previousRows.map((row) => [String(row?.name || ""), row]));
  const activeHint = String(current?.account_hint || "").split("|")[0].trim().toLowerCase();

  const profiles = profileRows.map((row) => {
    const name = String(row?.name || "");
    const previous = previousByName.get(name) || {};
    const accountHint = String(row?.account_hint || "");
    const emailHint = accountHint.split("|")[0].trim().toLowerCase();
    const isCurrent = activeHint && emailHint ? activeHint === emailHint : Boolean(row?.is_current);
    return {
      ...previous,
      ...row,
      name,
      usage_5h: previous?.usage_5h || { remaining_percent: null, resets_at: null, text: "-" },
      usage_weekly: previous?.usage_weekly || { remaining_percent: null, resets_at: null, text: "-" },
      is_current: isCurrent,
      error: previous?.error || "usage unavailable",
    };
  });

  return {
    refreshed_at: new Date().toISOString(),
    current_profile: profiles.find((row) => row?.is_current)?.name || null,
    profiles,
  };
}

function createApiClient({ state, fetchImpl = fetch }) {
  let lastDesktopState = null;

  async function request(path, options = {}) {
    const timeoutMs = Math.max(1000, Number(options?.timeoutMs || state?.requestTimeoutMs || DEFAULT_REQUEST_TIMEOUT_MS));
    const headers = {
      ...buildApiHeaders(state),
      ...(options.headers || {}),
    };
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timeout = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const response = await fetchImpl(joinUrl(state.baseUrl, path), {
        ...options,
        headers,
        signal: options?.signal || controller?.signal,
      });
      const payload = await response.json();
      if (!response.ok || payload?.ok === false) {
        throw new Error(payload?.error?.message || `request failed: ${response.status}`);
      }
      return unwrapApiPayload(payload);
    } catch (error) {
      if (controller && error?.name === "AbortError") {
        throw new Error(`request timeout after ${timeoutMs}ms: ${path}`);
      }
      throw error;
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }

  function getDesktopState(options = {}) {
    const usageScope = String(options?.usageScope || "current").toLowerCase() === "all" ? "all" : "current";
    const timeoutSec = Math.max(1, Number(options?.usageTimeoutSec || 7));
    const usageForce = usageScope === "all" && !!options?.usageForce;
    const usagePath = usageScope === "all"
      ? `/api/usage-local?timeout=${encodeURIComponent(String(timeoutSec))}${usageForce ? "&force=true" : ""}`
      : `/api/usage-local/current?timeout=${encodeURIComponent(String(timeoutSec))}`;
    return Promise.allSettled([
      request("/api/current"),
      request("/api/list"),
      request(usagePath),
      request("/api/ui-config"),
      request("/api/auto-switch/state"),
    ]).then((results) => {
      const [currentResult, listResult, usageResult, configResult, autoSwitchResult] = results;

      const current = currentResult.status === "fulfilled"
        ? currentResult.value
        : (lastDesktopState?.current || { ok: false, account_hint: "unknown", account_id: "-" });
      const list = listResult.status === "fulfilled"
        ? listResult.value
        : (lastDesktopState?.list || { profiles: [] });
      const config = configResult.status === "fulfilled"
        ? configResult.value
        : (lastDesktopState?.config || {});
      const autoSwitch = autoSwitchResult.status === "fulfilled"
        ? autoSwitchResult.value
        : (lastDesktopState?.autoSwitch || {});
      const usage = usageResult.status === "fulfilled"
        ? usageResult.value
        : fallbackUsagePayload({
            list,
            current,
            previousUsage: lastDesktopState?.usage,
          });

      const hasAnySuccess = results.some((result) => result.status === "fulfilled");
      if (!hasAnySuccess && !lastDesktopState) {
        const reason = currentResult.status === "rejected" ? currentResult.reason : new Error("desktop state unavailable");
        throw reason;
      }

      const nextState = { current, list, usage, config, autoSwitch };
      lastDesktopState = nextState;
      return nextState;
    });
  }

  async function switchProfile(name) {
    await request("/api/local/switch", {
      method: "POST",
      headers: buildApiHeaders(state),
      body: JSON.stringify({ name, no_restart: true }),
    });
    return getDesktopState({ usageScope: "all", usageTimeoutSec: 8, usageForce: true });
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
