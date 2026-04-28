export function extractEmailFromHint(hint) {
  const left = String(hint || "").split("|")[0].trim();
  return left.includes("@") ? left : "";
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
    return {
      ...list,
      ...prev,
      ...next,
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
