export function deepMerge(target, patch) {
  if (!patch || typeof patch !== "object" || Array.isArray(patch)) {
    return patch;
  }
  const base = target && typeof target === "object" && !Array.isArray(target) ? target : {};
  const next = { ...base };
  Object.entries(patch).forEach(([key, value]) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      next[key] = deepMerge(base[key], value);
      return;
    }
    next[key] = value;
  });
  return next;
}

export function applyProfileSelection(snapshot, profileName) {
  if (!snapshot || !profileName) {
    return snapshot;
  }
  const target = String(profileName).trim();
  return {
    ...snapshot,
    current: snapshot.current ? { ...snapshot.current, profile_name: target } : snapshot.current,
    list: snapshot.list ? {
      ...snapshot.list,
      profiles: Array.isArray(snapshot.list.profiles)
        ? snapshot.list.profiles.map((row) => ({ ...row, is_current: row.name === target }))
        : snapshot.list.profiles,
    } : snapshot.list,
    usage: snapshot.usage ? {
      ...snapshot.usage,
      current_profile: target,
      profiles: Array.isArray(snapshot.usage.profiles)
        ? snapshot.usage.profiles.map((row) => ({ ...row, is_current: row.name === target }))
        : snapshot.usage.profiles,
    } : snapshot.usage,
  };
}

export function buildDesktopSwitchOptions(input = {}) {
  const { platform = "", noRestart } = input || {};
  const normalizedPlatform = String(platform || "").trim().toLowerCase();
  const nextOptions = {};
  if (normalizedPlatform) {
    nextOptions.platform = normalizedPlatform;
  }
  if (Object.prototype.hasOwnProperty.call(input || {}, "noRestart")) {
    nextOptions.noRestart = Boolean(noRestart);
  }
  return nextOptions;
}

export function getCurrentRefreshIntervalMs(ui = {}) {
  if (!ui?.current_auto_refresh_enabled) {
    return null;
  }
  const intervalSec = Math.max(1, Number(ui.current_refresh_interval_sec || 5));
  return intervalSec * 1000;
}

export function getAllRefreshIntervalMs(ui = {}) {
  if (!ui?.all_auto_refresh_enabled) {
    return null;
  }
  const intervalMin = Math.max(1, Math.min(60, Number(ui.all_refresh_interval_min || 5)));
  return intervalMin * 60 * 1000;
}

export function isTimeoutErrorMessage(error) {
  const message = String(error?.message || error || "").trim().toLowerCase();
  if (!message) {
    return false;
  }
  return message.includes("timed out") || message.includes("timeout after");
}

export function formatUsageRefreshError(error, { scope = "usage", profileName = "" } = {}) {
  if (!isTimeoutErrorMessage(error)) {
    return String(error?.message || error || "request failed");
  }

  switch (String(scope || "").trim().toLowerCase()) {
    case "current":
      return "Current usage refresh timed out. The app will retry automatically.";
    case "profile": {
      const name = String(profileName || "").trim();
      return name
        ? `Usage refresh for ${name} timed out. Try again in a moment.`
        : "Usage refresh timed out. Try again in a moment.";
    }
    case "all":
      return "Refreshing usage for saved accounts timed out. Existing values are still shown.";
    default:
      return "Usage refresh timed out. Try again in a moment.";
  }
}

export function shouldRunStartupAllAccountsRefresh({
  runtimeStatus,
  loading,
  state,
  alreadyStarted = false,
} = {}) {
  if (alreadyStarted || loading) {
    return false;
  }
  const runtimeReady = runtimeStatus?.phase === "ready" || Boolean(
    runtimeStatus?.python?.supported
      && runtimeStatus?.core?.installed
      && runtimeStatus?.uiService?.running,
  );
  if (!runtimeReady) {
    return false;
  }

  const currentName = String(
    state?.usage?.current_profile
    || state?.current?.profile_name
    || "",
  ).trim();
  const listProfiles = Array.isArray(state?.list?.profiles) ? state.list.profiles : [];
  const usageProfiles = Array.isArray(state?.usage?.profiles) ? state.usage.profiles : [];
  const sourceProfiles = listProfiles.length ? listProfiles : usageProfiles;
  const names = new Set();
  for (const row of sourceProfiles) {
    const name = String(row?.name || "").trim();
    if (name) names.add(name);
  }
  if (names.size < 2) {
    return false;
  }
  if (!currentName) {
    return true;
  }
  for (const name of names) {
    if (name !== currentName) {
      return true;
    }
  }
  return false;
}

export function formatAutoSwitchCountdown(dueAtText, dueAt, nowMs = Date.now()) {
  if (!dueAt) {
    return dueAtText || "No pending switch";
  }
  const remaining = Math.max(0, Math.floor(Number(dueAt) - nowMs / 1000));
  const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
  const ss = String(remaining % 60).padStart(2, "0");
  return `Switching in ${mm}:${ss}`;
}

export async function waitForServiceRestart({
  fetchHealth,
  wait,
  previousVersion = "",
  reloadAfterMs = 1200,
  pollIntervalMs = 700,
  restartTimeoutMs = 20000,
  recoveryTimeoutMs = 4000,
  now = () => Date.now(),
}) {
  let sawServiceDrop = false;
  await wait(reloadAfterMs);

  const restartDeadline = now() + restartTimeoutMs;
  while (now() < restartDeadline) {
    try {
      const health = await fetchHealth();
      const nextVersion = String(health?.version || "").trim();
      const versionChanged = !!nextVersion && !!previousVersion && nextVersion !== previousVersion;
      if (sawServiceDrop || versionChanged || !previousVersion) {
        return health;
      }
    } catch (_) {
      sawServiceDrop = true;
    }
    await wait(pollIntervalMs);
  }

  const recoveryDeadline = now() + recoveryTimeoutMs;
  while (now() < recoveryDeadline) {
    try {
      return await fetchHealth();
    } catch (_) {
      await wait(pollIntervalMs);
    }
  }

  throw new Error("UI restart timed out. Reload the app manually.");
}
