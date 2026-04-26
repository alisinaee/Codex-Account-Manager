"use strict";

const path = require("node:path");

function windowsTaskbarUsageEnabled(config = {}) {
  return Boolean(config?.ui?.windows_taskbar_usage_enabled);
}

function buildTaskbarUsageOverlayDataUrl(summary = {}) {
  const percent = Number(summary?.fiveHourPercent);
  if (!summary?.available || !Number.isFinite(percent)) {
    return "";
  }
  const label = percent >= 100 ? "100" : String(Math.max(0, Math.round(percent)));
  const fontSize = label.length >= 3 ? 13 : 16;
  const x = label.length >= 3 ? 16 : 16;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
      <rect x="0" y="0" width="32" height="32" rx="8" fill="#0b1220"/>
      <rect x="1.25" y="1.25" width="29.5" height="29.5" rx="7" fill="none" stroke="#1f2a3a" stroke-width="1.5"/>
      <text x="${x}" y="20" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="${fontSize}" font-weight="700" fill="#3fff8b">${label}</text>
    </svg>
  `.trim();
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

function applyWindowsTaskbarUsage({ windowLike, nativeImage, summary, config, platform = process.platform }) {
  if (platform !== "win32" || !windowLike || typeof windowLike.setOverlayIcon !== "function") {
    return false;
  }
  if (!windowsTaskbarUsageEnabled(config) || !summary?.available) {
    const emptyIcon = nativeImage?.createEmpty ? nativeImage.createEmpty() : null;
    windowLike.setOverlayIcon(emptyIcon, "");
    return false;
  }
  const dataUrl = buildTaskbarUsageOverlayDataUrl(summary);
  const overlay = nativeImage?.createFromDataURL ? nativeImage.createFromDataURL(dataUrl) : null;
  const description = `Current ${summary.profileName}: 5H ${summary.fiveHourPercent}% left, Weekly ${summary.weeklyPercent}% left`;
  windowLike.setOverlayIcon(overlay, description);
  return true;
}

function buildWindowsNotificationShortcutSpec({
  app,
  appId,
  appName,
  iconPath,
  platform = process.platform,
  processExecPath = process.execPath,
} = {}) {
  if (platform !== "win32" || !app) {
    return null;
  }
  const startMenuPath = app.getPath?.("startMenu");
  const appPath = app.getAppPath?.();
  if (!startMenuPath || !appPath) {
    return null;
  }
  return {
    shortcutPath: path.join(startMenuPath, "Programs", `${appName}.lnk`),
    operation: "create",
    options: {
      target: processExecPath,
      cwd: path.dirname(processExecPath),
      args: app.isPackaged ? "" : `"${appPath}"`,
      description: appName,
      icon: iconPath,
      iconIndex: 0,
      appUserModelId: appId,
    },
  };
}

function ensureWindowsNotificationShortcut({ shell, ...rest } = {}) {
  const spec = buildWindowsNotificationShortcutSpec(rest);
  if (!spec || typeof shell?.writeShortcutLink !== "function") {
    return { ok: false, reason: "unsupported" };
  }
  const ok = shell.writeShortcutLink(spec.shortcutPath, spec.operation, spec.options);
  return { ok, shortcutPath: spec.shortcutPath };
}

module.exports = {
  applyWindowsTaskbarUsage,
  buildTaskbarUsageOverlayDataUrl,
  buildWindowsNotificationShortcutSpec,
  ensureWindowsNotificationShortcut,
  windowsTaskbarUsageEnabled,
};
