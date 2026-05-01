const ARC_CIRCUMFERENCE = 94.2;
import { clampPercent as clampPercentShared, usageCssColorVar } from "./usage-thresholds.mjs";

const PROFILE_FIXED_COLUMN_WIDTHS = {
  cur: { compact: 18, default: 24 },
  auto: { compact: 48, default: 48 },
  actions: { compact: 80, default: 116 },
};

const PROFILE_RESIZE_LOCKED_COLUMNS = new Set(["cur", "actions"]);

const PROFILE_RESIZE_BOUNDS = {
  profile: { min: 96, max: 420 },
  email: { min: 140, max: 640 },
  h5: { min: 72, max: 320 },
  h5remain: { min: 88, max: 320 },
  h5reset: { min: 88, max: 320 },
  weekly: { min: 72, max: 320 },
  weeklyremain: { min: 88, max: 320 },
  weeklyreset: { min: 88, max: 320 },
  plan: { min: 64, max: 220 },
  paid: { min: 64, max: 220 },
  id: { min: 88, max: 320 },
  added: { min: 88, max: 320 },
  note: { min: 96, max: 480 },
  auto: { min: 60, max: 120 },
};

const PROFILE_FLEX_COLUMN_WEIGHTS = {
  profile: 0.75,
  email: 1.05,
  h5: 1.25,
  h5remain: 0.9,
  h5reset: 0.85,
  weekly: 1.25,
  weeklyremain: 0.9,
  weeklyreset: 0.85,
  plan: 0.55,
  paid: 0.55,
  id: 0.75,
  added: 0.7,
  note: 0.85,
};

const PROFILE_COLUMN_KEYS = new Set([
  ...Object.keys(PROFILE_FIXED_COLUMN_WIDTHS),
  ...Object.keys(PROFILE_FLEX_COLUMN_WEIGHTS),
]);

function formatCssNumber(value) {
  return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function fixedWidthForColumn(key, viewportSizeClass) {
  const width = PROFILE_FIXED_COLUMN_WIDTHS[key];
  if (!width) return null;
  return viewportSizeClass === "size-compact" ? width.compact : width.default;
}

function isValidProfileColumnWidthValue(value) {
  const match = String(value || "").trim().match(/^([0-9]+(?:\.[0-9]+)?)(px|%)$/);
  if (!match) return false;
  const numeric = Number(match[1]);
  if (!Number.isFinite(numeric) || numeric <= 0) return false;
  if (match[2] === "%") {
    return numeric <= 100;
  }
  return numeric <= 2000;
}

export function buildProfileColumnWidths(visibleKeys, viewportSizeClass = "size-normal") {
  const keys = Array.isArray(visibleKeys) ? visibleKeys.filter(Boolean) : [];
  const widths = {};
  const flexKeys = keys.filter((key) => fixedWidthForColumn(key, viewportSizeClass) === null);
  const flexTotal = flexKeys.reduce((total, key) => total + (PROFILE_FLEX_COLUMN_WEIGHTS[key] || 1), 0);

  for (const key of keys) {
    const fixedWidth = fixedWidthForColumn(key, viewportSizeClass);
    if (fixedWidth !== null) {
      widths[key] = `${fixedWidth}px`;
      continue;
    }
    const weight = PROFILE_FLEX_COLUMN_WEIGHTS[key] || 1;
    const share = flexTotal > 0 ? weight / flexTotal : 1;
    const sharePercent = formatCssNumber(share * 100);
    widths[key] = `${sharePercent}%`;
  }

  return widths;
}

export function isProfileColumnResizable(key) {
  return !PROFILE_RESIZE_LOCKED_COLUMNS.has(String(key || "").trim());
}

export function normalizeProfileColumnWidthOverrides(overrides) {
  const next = {};
  if (!overrides || typeof overrides !== "object") {
    return next;
  }
  for (const [key, rawValue] of Object.entries(overrides)) {
    if (!PROFILE_COLUMN_KEYS.has(key)) {
      continue;
    }
    if (!isProfileColumnResizable(key)) {
      continue;
    }
    const value = String(rawValue || "").trim();
    if (!isValidProfileColumnWidthValue(value)) {
      continue;
    }
    next[key] = value;
  }
  return next;
}

export function resolveProfileColumnWidths(visibleKeys, viewportSizeClass = "size-normal", overrides = {}) {
  const widths = buildProfileColumnWidths(visibleKeys, viewportSizeClass);
  const normalizedOverrides = normalizeProfileColumnWidthOverrides(overrides);
  for (const key of Object.keys(widths)) {
    if (normalizedOverrides[key] && isProfileColumnResizable(key)) {
      widths[key] = normalizedOverrides[key];
    }
  }
  return widths;
}

export function getProfileColumnResizeBounds(key) {
  const bounds = PROFILE_RESIZE_BOUNDS[String(key || "").trim()] || { min: 72, max: 640 };
  return { min: bounds.min, max: bounds.max };
}

export function clampProfileColumnWidthPx(key, nextWidthPx) {
  const numeric = Number(nextWidthPx);
  if (!isProfileColumnResizable(key)) {
    return null;
  }
  const { min, max } = getProfileColumnResizeBounds(key);
  if (!Number.isFinite(numeric)) {
    return min;
  }
  return Math.max(min, Math.min(max, Math.round(numeric)));
}

export function clampPercent(value) {
  return clampPercentShared(value);
}

export function usageColor(value) {
  return usageCssColorVar(value);
}

export function arcDasharray(value) {
  const percent = clampPercent(value);
  const resolved = percent === null ? 0 : percent;
  const usedArc = (resolved * ARC_CIRCUMFERENCE) / 100;
  return `${usedArc.toFixed(1)} ${ARC_CIRCUMFERENCE}`;
}

function toSafeDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return date;
}

export function formatShortDateFromSeconds(epochSeconds) {
  if (!epochSeconds && epochSeconds !== 0) return "unknown";
  const date = toSafeDate(Number(epochSeconds) * 1000);
  if (!date) return "unknown";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatFullDateFromSeconds(epochSeconds) {
  if (!epochSeconds && epochSeconds !== 0) return "unknown";
  const date = toSafeDate(Number(epochSeconds) * 1000);
  if (!date) return "unknown";
  return date.toLocaleString();
}

export function formatShortDateFromValue(value) {
  if (!value) return "-";
  const date = toSafeDate(value);
  if (!date) return String(value);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatFullDateFromValue(value) {
  if (!value) return "-";
  const date = toSafeDate(value);
  if (!date) return String(value);
  return date.toLocaleString();
}

export function truncateAccountId(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  if (text.length <= 8) return text;
  return `${text.slice(0, 8)}…`;
}

export function truncateNote(value, maxLength = 12) {
  const text = String(value || "").trim();
  if (!text) return "-";
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}

export function remainSecondsFromResetEpochSeconds(epochSeconds, nowMs = Date.now()) {
  if (!epochSeconds && epochSeconds !== 0) return null;
  const resetSeconds = Number(epochSeconds);
  if (!Number.isFinite(resetSeconds)) return null;
  return Math.max(0, Math.floor(resetSeconds - (Number(nowMs) / 1000)));
}

export function remainToneFromResetEpochSeconds(epochSeconds, nowMs = Date.now()) {
  const remainingSeconds = remainSecondsFromResetEpochSeconds(epochSeconds, nowMs);
  if (remainingSeconds === null) return "normal";
  if (remainingSeconds < 30 * 60) return "danger";
  if (remainingSeconds <= 2 * 60 * 60) return "warning";
  return "normal";
}
