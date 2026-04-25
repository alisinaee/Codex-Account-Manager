"use strict";

const { getIconPath, getTrayIconPath } = require("./icons");

const TONE_COLORS = {
  danger: "#ff6b6b",
  warning: "#ff9f43",
  caution: "#ffd16c",
  good: "#3fff8b",
  neutral: "#adaaaa",
};

function toPercentLabel(value) {
  const percent = Number(value);
  return Number.isFinite(percent) ? `${Math.round(percent)}%` : "-";
}

function buildStatusTone(value) {
  const percent = Number(value);
  if (!Number.isFinite(percent)) return "neutral";
  if (percent < 10) return "danger";
  if (percent < 30) return "warning";
  if (percent < 50) return "caution";
  return "good";
}

function buildStatusIconDataUrl(tone = "neutral") {
  const color = TONE_COLORS[tone] || TONE_COLORS.neutral;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="5.5" fill="${color}"/></svg>`;
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

function compactProfileName(name) {
  const value = String(name || "").trim();
  if (!value) return "";
  return value.length > 12 ? `${value.slice(0, 11)}…` : value;
}

function statusItem(label, tone, platform) {
  if (platform === "darwin") {
    return { label, enabled: true };
  }
  return {
    label,
    enabled: true,
    icon: buildStatusIconDataUrl(tone),
  };
}

function buildTrayMenuTemplate(actions = {}) {
  const summary = actions.summary || {};
  const platform = actions.platform || process.platform;
  const profileName = compactProfileName(summary.profileName);
  const statusItems = summary.available
    ? [
        { label: `Current ${profileName}`, enabled: true },
        statusItem(`5H ${toPercentLabel(summary.fiveHourPercent)} left`, buildStatusTone(summary.fiveHourPercent), platform),
        statusItem(`Weekly ${toPercentLabel(summary.weeklyPercent)} left`, buildStatusTone(summary.weeklyPercent), platform),
      ]
    : [statusItem("Usage unavailable", "neutral", platform)];
  return [
    ...statusItems,
    { type: "separator" },
    { label: "Open Codex Account Manager", click: actions.onOpen },
    { label: "Refresh Usage", click: actions.onRefresh },
    { label: "Send Test Notification", click: actions.onNotify },
    { type: "separator" },
    { label: "Start UI Service", click: actions.onStartService },
    { label: "Stop UI Service", click: actions.onStopService },
    { label: "Quit", click: actions.onQuit },
  ];
}

function buildMacMenuBarTitle(summary = {}) {
  if (!summary.available) return "";
  const profileName = compactProfileName(summary.profileName);
  if (!profileName) return "";
  return `${profileName} 5H ${toPercentLabel(summary.fiveHourPercent)} W ${toPercentLabel(summary.weeklyPercent)}`;
}

function applyTrayState({ tray, Menu, summary, actions }) {
  if (!tray || !Menu) {
    return;
  }
  if (typeof tray.setToolTip === "function") {
    tray.setToolTip(summary?.tooltip || "Codex Account Manager");
  }
  if (process.platform === "darwin" && typeof tray.setTitle === "function") {
    tray.setTitle(buildMacMenuBarTitle(summary));
  }
  tray.setContextMenu(Menu.buildFromTemplate(buildTrayMenuTemplate({ ...actions, summary })));
}

function prepareTrayIcon(image, platform = process.platform) {
  if (platform !== "darwin" || !image) {
    return image;
  }
  const resized = typeof image.resize === "function" ? image.resize({ width: 18, height: 18 }) : image;
  if (typeof resized.setTemplateImage === "function") {
    resized.setTemplateImage(true);
  }
  return resized;
}

function createTray({ Tray, Menu, nativeImage, summary, actions }) {
  const iconPath = process.platform === "darwin" ? getTrayIconPath() : getIconPath();
  const rawIcon = nativeImage?.createFromPath ? nativeImage.createFromPath(iconPath) : iconPath;
  const icon = prepareTrayIcon(rawIcon);
  const tray = new Tray(icon);
  applyTrayState({ tray, Menu, summary, actions });
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
};
