const ARC_CIRCUMFERENCE = 94.2;

export function clampPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

export function usageColor(value) {
  const percent = clampPercent(value);
  if (percent === null) return "var(--text-secondary)";
  if (percent >= 90) return "var(--color-red)";
  if (percent >= 70) return "var(--color-amber)";
  return "var(--color-green)";
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
