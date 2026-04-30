import { usageProgressTone } from "./usage-thresholds.mjs";

export const SWITCH_ROW_MOTION_MS = 4000;
export const SWITCH_ROW_CLEANUP_BUFFER_MS = 180;

export function usageTone(value) {
  return usageProgressTone(value);
}

export function buildSwitchButtonClassName(active) {
  return active ? "btn btn-primary btn-progress switch-loading-btn" : "btn btn-primary";
}

export function buildProfileRowClassName({ isCurrent = false, isPending = false, isActivated = false } = {}) {
  return [
    isCurrent ? "current-row" : "",
    isPending ? "switch-row-pending" : "",
    isActivated ? "switch-row-activated" : "",
  ].filter(Boolean).join(" ");
}

export function buildSwitchRowMotionPlans(beforeRects = {}, afterRects = {}, { minDelta = 2 } = {}) {
  const plans = [];
  Object.entries(afterRects || {}).forEach(([name, after]) => {
    const before = beforeRects?.[name];
    if (!before || !after) return;
    const dx = Math.round(Number(before.left || 0) - Number(after.left || 0));
    const dy = Math.round(Number(before.top || 0) - Number(after.top || 0));
    if (Math.abs(dx) <= minDelta && Math.abs(dy) <= minDelta) {
      return;
    }
    plans.push({ name, dx, dy });
  });
  return plans.sort((a, b) => String(a.name).localeCompare(String(b.name)));
}

export function pickTestSwitchAnimationTarget(names = [], randomValue = Math.random()) {
  const normalized = (Array.isArray(names) ? names : [])
    .map((name) => String(name || "").trim())
    .filter(Boolean);
  const candidates = normalized.slice(1);
  if (!candidates.length) {
    return "";
  }
  const safeRandom = Math.max(0, Math.min(0.999999, Number(randomValue) || 0));
  return candidates[Math.floor(safeRandom * candidates.length)] || "";
}

export function buildDeckMoveAffectedNames(names = [], targetName = "") {
  const normalized = (Array.isArray(names) ? names : [])
    .map((name) => String(name || "").trim())
    .filter(Boolean);
  const target = String(targetName || "").trim();
  const targetIndex = normalized.indexOf(target);
  if (!target || targetIndex <= 0) {
    return [];
  }
  return [target, ...normalized.slice(0, targetIndex)];
}

export function buildRowsByNameOrder(rows = [], orderedNames = [], getName = (row) => row?.name) {
  if (!Array.isArray(rows) || !Array.isArray(orderedNames) || !orderedNames.length) {
    return rows;
  }
  const rowByName = new Map(rows.map((row) => [String(getName(row) || "").trim(), row]));
  const usedNames = new Set();
  const orderedRows = [];
  orderedNames.forEach((rawName) => {
    const name = String(rawName || "").trim();
    const row = rowByName.get(name);
    if (!name || !row || usedNames.has(name)) return;
    usedNames.add(name);
    orderedRows.push(row);
  });
  if (!orderedRows.length) {
    return rows;
  }
  return [...orderedRows, ...rows.filter((row) => !usedNames.has(String(getName(row) || "").trim()))];
}

export function buildTestSwitchAnimationPreviewRows(rows = [], targetName = "", getName = (row) => row?.name) {
  if (!Array.isArray(rows) || rows.length < 2) {
    return rows;
  }
  const target = String(targetName || "").trim();
  if (!target) {
    return rows;
  }
  const targetRow = rows.find((row) => String(getName(row) || "").trim() === target);
  if (!targetRow) {
    return rows;
  }
  return [targetRow, ...rows.filter((row) => row !== targetRow)];
}

export function buildSwitchAnimationPreview(rows = [], targetName = "", getName = (row) => row?.name) {
  const normalizedRows = Array.isArray(rows) ? rows : [];
  const target = String(targetName || "").trim();
  return {
    target,
    affectedNames: buildDeckMoveAffectedNames(
      normalizedRows.map((row) => String(getName(row) || "").trim()),
      target,
    ),
    nextRows: buildTestSwitchAnimationPreviewRows(normalizedRows, target, getName),
  };
}

export function createSwitchController(switchFn) {
  let pendingName = "";

  return {
    getPendingName() {
      return pendingName;
    },
    async switchProfile(name, options = {}) {
      const target = String(name || "").trim();
      if (!target) {
        throw new Error("profile name is required");
      }
      if (pendingName) {
        throw new Error("switch already in progress");
      }
      pendingName = target;
      try {
        return await switchFn(target, options || {});
      } finally {
        pendingName = "";
      }
    },
  };
}
