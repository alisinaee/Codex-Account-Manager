"use strict";

const USAGE_TONE_HEX = {
  danger: "#ef4444",
  warning: "#f97316",
  caution: "#facc15",
  good: "#22c55e",
  neutral: "#adaaaa",
};

function clampPercent(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function usageBandForPercent(value) {
  const percent = clampPercent(value);
  if (percent === null) return "neutral";
  if (percent <= 25) return "danger";
  if (percent <= 50) return "warning";
  if (percent <= 75) return "caution";
  return "good";
}

function usageCssColorVar(value) {
  const band = usageBandForPercent(value);
  if (band === "danger") return "var(--color-red)";
  if (band === "warning") return "var(--color-orange)";
  if (band === "caution") return "var(--color-yellow)";
  if (band === "good") return "var(--color-green)";
  return "var(--text-secondary)";
}

function usageHexColor(value) {
  return USAGE_TONE_HEX[usageBandForPercent(value)] || USAGE_TONE_HEX.neutral;
}

function usageHexColorForBand(band) {
  return USAGE_TONE_HEX[String(band || "neutral")] || USAGE_TONE_HEX.neutral;
}

function usageProgressTone(value) {
  const band = usageBandForPercent(value);
  if (band === "danger") return "danger";
  if (band === "warning") return "warning";
  if (band === "caution") return "caution";
  if (band === "good") return "success";
  return "";
}

module.exports = {
  USAGE_TONE_HEX,
  clampPercent,
  usageBandForPercent,
  usageCssColorVar,
  usageHexColor,
  usageHexColorForBand,
  usageProgressTone,
};
