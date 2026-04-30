"use strict";

const INVALIDATING_POST_PATHS = new Set([
  "/api/local/save",
  "/api/local/add",
  "/api/local/import/apply",
  "/api/local/remove",
  "/api/local/remove-all",
  "/api/local/rename",
]);

function normalizeRequestPath(path) {
  const raw = String(path || "").trim();
  if (!raw) {
    return "";
  }
  try {
    return new URL(raw, "http://127.0.0.1").pathname;
  } catch (_) {
    const queryIndex = raw.indexOf("?");
    return queryIndex >= 0 ? raw.slice(0, queryIndex) : raw;
  }
}

function shouldInvalidateDesktopStateForRequest(path, options = {}) {
  const method = String(options?.method || "GET").trim().toUpperCase();
  if (method !== "POST") {
    return false;
  }
  return INVALIDATING_POST_PATHS.has(normalizeRequestPath(path));
}

module.exports = {
  normalizeRequestPath,
  shouldInvalidateDesktopStateForRequest,
};
