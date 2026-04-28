export function normalizeDebugLogRow(row = {}, fallbackSource = "app") {
  const level = String(row?.level || "info").toLowerCase() === "warning" ? "warn" : String(row?.level || "info").toLowerCase();
  return {
    ts: String(row?.ts || new Date().toISOString()),
    level,
    source: String(row?.source || fallbackSource),
    message: String(row?.message || ""),
    details: row?.details && typeof row.details === "object" ? row.details : {},
  };
}

export function buildDesktopLogEntry(level, message, details = {}, now = () => new Date()) {
  return normalizeDebugLogRow({
    ts: now().toISOString(),
    level,
    source: "electron",
    message,
    details,
  }, "electron");
}

export function mergeDebugLogs(backendLogs = [], desktopLogs = [], limit = 240) {
  return [...(Array.isArray(backendLogs) ? backendLogs : []), ...(Array.isArray(desktopLogs) ? desktopLogs : [])]
    .map((row) => normalizeDebugLogRow(row, row?.source || "backend"))
    .sort((left, right) => String(left.ts || "").localeCompare(String(right.ts || "")))
    .slice(-Math.max(1, Number(limit) || 240));
}
