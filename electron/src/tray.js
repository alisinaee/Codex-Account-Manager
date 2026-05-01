"use strict";

const { getIconPath, getTrayIconPath } = require("./icons");
const { usageBandForPercent, usageHexColorForBand } = require("./usage-thresholds");

function toPercentLabel(value) {
  const percent = Number(value);
  return Number.isFinite(percent) ? `${Math.round(percent)}%` : "-";
}

function buildStatusTone(value) {
  return usageBandForPercent(value);
}

function buildStatusIconDataUrl(tone = "neutral") {
  const color = usageHexColorForBand(tone);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="5.5" fill="${color}"/></svg>`;
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

function compactProfileName(name) {
  const value = String(name || "").trim();
  if (!value) return "";
  return value.length > 12 ? `${value.slice(0, 11)}…` : value;
}

function toneAnsiColor(value) {
  const tone = buildStatusTone(value);
  if (tone === "danger") return "\u001b[31m";
  if (tone === "warning") return "\u001b[33m";
  if (tone === "caution") return "\u001b[33m";
  if (tone === "good") return "\u001b[32m";
  return "\u001b[37m";
}

function colorizeMacTitleValue(label, value) {
  return `${label} ${toneAnsiColor(value)}${toPercentLabel(value)}\u001b[0m`;
}

function statusItem(label, tone, platform) {
  const marker = tone === "danger"
    ? "🔴"
    : tone === "warning"
      ? "🟠"
      : tone === "caution"
        ? "🟡"
        : tone === "good"
          ? "🟢"
          : "⚪";
  const prefixedLabel = `${marker} ${label}`;
  return { label: prefixedLabel, enabled: false };
}

function parseMacMajorVersion(version) {
  const major = Number.parseInt(String(version || "").split(".")[0], 10);
  return Number.isFinite(major) ? major : 0;
}

function supportsMacTrayHeaders(version) {
  return parseMacMajorVersion(version) >= 14;
}

function buildTrayStatusItems(summary = {}, platform = process.platform, options = {}) {
  const profileName = compactProfileName(summary.profileName);
  if (!summary.available) {
    return [statusItem("Usage unavailable", "neutral", platform)];
  }
  const macSystemVersion = String(
    options.macSystemVersion
    || (typeof process.getSystemVersion === "function" ? process.getSystemVersion() : ""),
  ).trim();
  const usageItems = [
    statusItem(`5H ${toPercentLabel(summary.fiveHourPercent)} left`, buildStatusTone(summary.fiveHourPercent), platform),
    statusItem(`Weekly ${toPercentLabel(summary.weeklyPercent)} left`, buildStatusTone(summary.weeklyPercent), platform),
  ];
  if (platform === "darwin" && supportsMacTrayHeaders(macSystemVersion)) {
    return [
      { type: "header", label: `Current ${profileName}` },
      { type: "header", label: `5H ${toPercentLabel(summary.fiveHourPercent)} left` },
      { type: "header", label: `Weekly ${toPercentLabel(summary.weeklyPercent)} left` },
    ];
  }
  if (platform === "darwin") {
    return [{
      label: `Status ${profileName}`,
      submenu: usageItems,
    }];
  }
  return [
    { label: `Current ${profileName}`, enabled: false },
    ...usageItems,
  ];
}

function buildTrayMenuTemplate(actions = {}) {
  const summary = actions.summary || {};
  const platform = actions.platform || process.platform;
  const statusItems = buildTrayStatusItems(summary, platform, {
    macSystemVersion: actions.macSystemVersion,
  });
  return [
    ...statusItems,
    { type: "separator" },
    { label: "Open Codex Account Manager", click: actions.onOpen },
    { label: "Web Panel", click: actions.onOpenWebPanel },
    { label: "Refresh Usage", click: actions.onRefresh },
    { label: "Send Test Notification", click: actions.onNotify },
    { type: "separator" },
    { label: "Restart Service", click: actions.onRestartService },
    { label: "Quit", click: actions.onQuit },
  ];
}

function buildMacMenuBarTitle(summary = {}) {
  if (!summary.available) return "";
  const profileName = compactProfileName(summary.profileName);
  if (!profileName) return "";
  return `${profileName} ${colorizeMacTitleValue("5H", summary.fiveHourPercent)} ${colorizeMacTitleValue("W", summary.weeklyPercent)}`;
}

function statusBarEnabled(config = {}, platform = process.platform) {
  if (platform !== "darwin") {
    return true;
  }
  return config?.ui?.macos_status_bar_enabled !== false;
}

function applyTrayState({ tray, Menu, summary, actions, nativeImage }) {
  if (!tray || !Menu) {
    return;
  }
  if (typeof tray.setToolTip === "function") {
    tray.setToolTip(summary?.tooltip || "Codex Account Manager");
  }
  if (process.platform === "darwin" && typeof tray.setTitle === "function") {
    tray.setTitle(buildMacMenuBarTitle(summary), { fontType: "monospacedDigit" });
  }
  tray.setContextMenu(Menu.buildFromTemplate(buildTrayMenuTemplate({ ...actions, summary })));
}

function prepareTrayIcon(image, platform = process.platform) {
  if (!image) {
    return image;
  }
  if (platform === "darwin") {
    const resized = typeof image.resize === "function" ? image.resize({ width: 18, height: 18 }) : image;
    if (typeof resized.setTemplateImage === "function") {
      resized.setTemplateImage(true);
    }
    return resized;
  }
  if (platform === "win32") {
    return typeof image.resize === "function" ? image.resize({ width: 16, height: 16 }) : image;
  }
  return typeof image.resize === "function" ? image.resize({ width: 18, height: 18 }) : image;
}

function resolveTrayIconPath(platform = process.platform) {
  if (platform === "darwin") {
    return getTrayIconPath();
  }
  return getIconPath(platform);
}

function createTray({ Tray, Menu, nativeImage, summary, actions }) {
  const iconPath = resolveTrayIconPath(process.platform);
  const rawIcon = nativeImage?.createFromPath ? nativeImage.createFromPath(iconPath) : iconPath;
  const icon = prepareTrayIcon(rawIcon);
  const tray = new Tray(icon);
  applyTrayState({ tray, Menu, summary, actions, nativeImage });
  return tray;
}

module.exports = {
  applyTrayState,
  buildMacMenuBarTitle,
  buildStatusIconDataUrl,
  buildStatusTone,
  buildTrayMenuTemplate,
  createTray,
  getIconPath,
  prepareTrayIcon,
  resolveTrayIconPath,
  statusBarEnabled,
};
