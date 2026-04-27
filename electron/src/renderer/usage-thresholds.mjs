export function clampPercent(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

export function usageBandForPercent(value) {
  const percent = clampPercent(value);
  if (percent === null) return "neutral";
  if (percent <= 25) return "danger";
  if (percent <= 50) return "warning";
  if (percent <= 75) return "caution";
  return "good";
}

export function usageCssColorVar(value) {
  const band = usageBandForPercent(value);
  if (band === "danger") return "var(--color-red)";
  if (band === "warning") return "var(--color-orange)";
  if (band === "caution") return "var(--color-yellow)";
  if (band === "good") return "var(--color-green)";
  return "var(--text-secondary)";
}

export function usageProgressTone(value) {
  const band = usageBandForPercent(value);
  if (band === "danger") return "danger";
  if (band === "warning") return "warning";
  if (band === "caution") return "caution";
  if (band === "good") return "success";
  return "";
}

