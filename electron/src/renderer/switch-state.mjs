import { usageProgressTone } from "./usage-thresholds.mjs";

export function usageTone(value) {
  return usageProgressTone(value);
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
