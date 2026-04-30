export async function refreshProfilesAfterMutation({
  desktop,
  request,
  appendSessionTokenFn,
} = {}) {
  if (!desktop || typeof desktop.getState !== "function" || typeof desktop.getBackendState !== "function") {
    throw new Error("desktop state bridge is unavailable");
  }
  if (typeof request !== "function") {
    throw new Error("request function is required");
  }
  if (typeof appendSessionTokenFn !== "function") {
    throw new Error("appendSessionTokenFn is required");
  }

  const [core, backend] = await Promise.all([
    desktop.getState(),
    desktop.getBackendState(),
  ]);

  const extrasPromise = Promise.all([
    request("/api/app-update-status", {}),
    request("/api/release-notes", {}),
    request(appendSessionTokenFn("/api/debug/logs?tail=240", backend?.token), {}),
    request("/api/auto-switch/chain", {}),
  ]).then(([update, notes, logs, chain]) => ({
    update,
    notes,
    logs,
    chain,
  }));

  return {
    core,
    backend,
    extrasPromise,
  };
}
