function usagePercentValue(usage) {
  const value = Number(usage?.remaining_percent);
  if (!Number.isFinite(value)) {
    return null;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function currentProfileName(state) {
  return state?.usage?.current_profile || state?.current?.profile_name || "";
}

export function profilesFromState(state) {
  const usageRows = Array.isArray(state?.usage?.profiles) ? state.usage.profiles : [];
  const usageByName = new Map(usageRows.map((row) => [row.name, row]));
  const profileRows = Array.isArray(state?.list?.profiles) ? state.list.profiles : usageRows;
  const current = currentProfileName(state);
  return profileRows.map((profile) => {
    const usage = usageByName.get(profile.name) || profile;
    const isCurrent = current
      ? profile.name === current
      : Boolean(profile.is_current || usage.is_current);
    return {
      ...profile,
      ...usage,
      is_current: isCurrent,
    };
  });
}

export function buildProfileRows(state) {
  return profilesFromState(state).map((profile) => ({
    ...profile,
    email_display: String(profile.email || "").trim() || "-",
  }));
}

export function buildSidebarCurrentProfile(state) {
  const currentName = currentProfileName(state);
  const rows = buildProfileRows(state);
  const row = rows.find((profile) => profile.name === currentName) || rows.find((profile) => profile.is_current) || null;

  return {
    name: String(row?.name || currentName || "").trim(),
    email: String(row?.email || "").trim() || "-",
    usage5h: usagePercentValue(row?.usage_5h),
    usageWeekly: usagePercentValue(row?.usage_weekly),
    hasUsage: usagePercentValue(row?.usage_5h) !== null || usagePercentValue(row?.usage_weekly) !== null,
  };
}

export function usagePercentNumber(row, key) {
  return usagePercentValue(row?.[key]);
}
