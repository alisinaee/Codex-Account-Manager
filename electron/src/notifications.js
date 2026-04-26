"use strict";

const { buildUsageSummary } = require("./usage");

const APP_TITLE = "Codex Account Manager";

function notificationsEnabled(config = {}) {
  return Boolean(config?.notifications?.enabled);
}

function buildNotificationOptions(usagePayload, iconPath = "") {
  const summary = buildUsageSummary(usagePayload);
  const options = {
    title: APP_TITLE,
    subtitle: summary.available ? `Profile ${summary.profileName}` : "",
    body: summary.notificationBody,
    silent: false,
  };
  if (iconPath) {
    options.icon = iconPath;
  }
  return options;
}

function sendUsageNotification(electronNotification, usagePayload, onClick, iconPath = "") {
  if (!electronNotification?.isSupported?.()) {
    return { ok: false, reason: "Electron notifications are not supported on this platform." };
  }
  const notification = new electronNotification(buildNotificationOptions(usagePayload, iconPath));
  if (typeof onClick === "function") {
    notification.on("click", onClick);
  }
  notification.show();
  return { ok: true };
}

module.exports = {
  APP_TITLE,
  buildNotificationOptions,
  notificationsEnabled,
  sendUsageNotification,
};
