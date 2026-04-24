export function usageTone(value) {
  if (value === null || value === undefined || value === "") return "";
  const percent = Number(value);
  if (!Number.isFinite(percent)) return "";
  if (percent < 10) return "low";
  if (percent < 30) return "midlow";
  if (percent < 50) return "mid";
  return "good";
}

export function buildSwitchButtonClassName(active) {
  return active ? "btn btn-primary btn-progress" : "btn btn-primary";
}

export function buildProfileRowClassName({ isCurrent = false, isPending = false, isActivated = false } = {}) {
  return [
    isCurrent ? "current-row" : "",
    isPending ? "switch-row-pending" : "",
    isActivated ? "switch-row-activated" : "",
  ].filter(Boolean).join(" ");
}

export function createSwitchController(switchFn) {
  let pendingName = "";

  return {
    getPendingName() {
      return pendingName;
    },
    async switchProfile(name) {
      const target = String(name || "").trim();
      if (!target) {
        throw new Error("profile name is required");
      }
      if (pendingName) {
        throw new Error("switch already in progress");
      }
      pendingName = target;
      try {
        return await switchFn(target);
      } finally {
        pendingName = "";
      }
    },
  };
}
