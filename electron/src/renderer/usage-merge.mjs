export function extractEmailFromHint(hint) {
  const left = String(hint || "").split("|")[0].trim();
  return left.includes("@") ? left : "";
}

function usageMetricHasObservedValues(metric) {
  if (!metric || typeof metric !== "object") return false;
  if (metric.remaining_percent !== null && metric.remaining_percent !== undefined) return true;
  return ![null, undefined, "", 0].includes(metric.resets_at);
}

function usageRowHasObservedValues(row) {
  if (!row || typeof row !== "object") return false;
  if (usageMetricHasObservedValues(row.usage_5h)) return true;
  if (usageMetricHasObservedValues(row.usage_weekly)) return true;
  if (typeof row.plan_type === "string" && row.plan_type.trim()) return true;
  return typeof row.is_paid === "boolean";
}

function mergeUsageRow(prev, next) {
  if (!next || typeof next !== "object") return prev || {};
  if (!prev || typeof prev !== "object" || !Object.keys(prev).length) {
    return next;
  }
  const transientError = Boolean(String(next.error || "").trim()) && !usageRowHasObservedValues(next);
  if (!transientError) {
    return next;
  }
  return {
    ...prev,
    name: next.name ?? prev.name,
    email: next.email ?? prev.email,
    account_id: next.account_id ?? prev.account_id,
    same_principal: next.same_principal ?? prev.same_principal,
    saved_at: next.saved_at ?? prev.saved_at,
    auto_switch_eligible: next.auto_switch_eligible ?? prev.auto_switch_eligible,
    is_current: Boolean(next.is_current ?? prev.is_current),
  };
}

export function mergeUsagePayload(prevUsage, nextUsage, listPayload, currentPayload) {
  if (!nextUsage || nextUsage.__error) return nextUsage;

  const prevRows = Array.isArray(prevUsage?.profiles) ? prevUsage.profiles : [];
  const nextRows = Array.isArray(nextUsage?.profiles) ? nextUsage.profiles : [];
  const listRows = Array.isArray(listPayload?.profiles) ? listPayload.profiles : [];
  const currentHint = extractEmailFromHint(currentPayload?.account_hint);

  const prevByName = new Map();
  const nextByName = new Map();
  prevRows.forEach((row) => {
    const name = String(row?.name || "").trim();
    if (name) prevByName.set(name, row);
  });
  nextRows.forEach((row) => {
    const name = String(row?.name || "").trim();
    if (name) nextByName.set(name, row);
  });

  const orderedNames = [];
  listRows.forEach((row) => {
    const name = String(row?.name || "").trim();
    if (name && !orderedNames.includes(name)) orderedNames.push(name);
  });
  prevRows.forEach((row) => {
    const name = String(row?.name || "").trim();
    if (name && !orderedNames.includes(name)) orderedNames.push(name);
  });
  nextRows.forEach((row) => {
    const name = String(row?.name || "").trim();
    if (name && !orderedNames.includes(name)) orderedNames.push(name);
  });

  const mergedRows = orderedNames.map((name) => {
    const prev = prevByName.get(name) || {};
    const next = nextByName.get(name) || {};
    const list = listRows.find((row) => String(row?.name || "").trim() === name) || {};
    const mergedRow = mergeUsageRow(prev, next);
    return {
      ...list,
      ...mergedRow,
      name,
      // Per-row loading flags are UI-local and must not survive a fresh payload merge.
      loading_usage: false,
    };
  });

  const detectedCurrentByHint = currentHint
    ? mergedRows.find((row) => String(row?.email || "").trim().toLowerCase() === currentHint.toLowerCase())?.name
    : "";
  const nextCurrent = String(
    nextUsage?.current_profile
    || detectedCurrentByHint
    || prevUsage?.current_profile
    || "",
  ).trim() || null;

  const profiles = mergedRows.map((row) => ({
    ...row,
    is_current: nextCurrent ? String(row?.name || "").trim() === nextCurrent : Boolean(row?.is_current),
  }));

  return {
    ...prevUsage,
    ...nextUsage,
    refreshed_at: nextUsage?.refreshed_at || new Date().toISOString(),
    current_profile: nextCurrent,
    profiles,
  };
}
