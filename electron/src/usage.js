"use strict";

function toPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return null;
  }
  return Math.round(n);
}

function selectCurrentUsageRow(payload) {
  const currentName = String(payload?.current_profile || "").trim();
  const rows = Array.isArray(payload?.profiles) ? payload.profiles : [];
  if (currentName) {
    const byName = rows.find((row) => String(row?.name || "").trim() === currentName);
    if (byName) {
      return byName;
    }
  }
  return rows.find((row) => Boolean(row?.is_current)) || null;
}

function buildUsageSummary(payload) {
  const row = selectCurrentUsageRow(payload);
  const profileName = String(row?.name || payload?.current_profile || "").trim();
  const fiveHourPercent = toPercent(row?.usage_5h?.remaining_percent);
  const weeklyPercent = toPercent(row?.usage_weekly?.remaining_percent);

  if (!row || !profileName || fiveHourPercent === null || weeklyPercent === null) {
    return {
      available: false,
      profileName: "",
      fiveHourPercent: null,
      weeklyPercent: null,
      trayTitle: "Codex Account Manager",
      tooltip: "Codex Account Manager\nUsage unavailable",
      notificationBody: "Usage unavailable",
    };
  }

  return {
    available: true,
    profileName,
    fiveHourPercent,
    weeklyPercent,
    trayTitle: `${profileName} | 5H ${fiveHourPercent}% | W ${weeklyPercent}%`,
    tooltip: `Codex Account Manager\nProfile ${profileName}\n5H ${fiveHourPercent}% left\nWeekly ${weeklyPercent}% left`,
    notificationBody: `Profile ${profileName} - 5H ${fiveHourPercent}% left - Weekly ${weeklyPercent}% left`,
  };
}

module.exports = {
  buildUsageSummary,
  selectCurrentUsageRow,
};
