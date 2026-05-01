"use strict";

const { buildUsageSummary } = require("./usage");

const APP_TITLE = "Codex Account Manager";
const activeNotifications = new Set();

function notificationsEnabled(config = {}) {
  return Boolean(config?.notifications?.enabled);
}

function buildNotificationOptions(usagePayload, iconPath = "", overrides = {}) {
  const summary = buildUsageSummary(usagePayload);
  const options = {
    title: APP_TITLE,
    subtitle: summary.available ? `Profile ${summary.profileName}` : "",
    body: summary.notificationBody,
    silent: false,
    ...overrides,
  };
  if (iconPath) {
    options.icon = iconPath;
  }
  return options;
}

function sendUsageNotification(electronNotification, usagePayload, onClick, iconPath = "", options = {}) {
  if (!electronNotification?.isSupported?.()) {
    return { ok: false, reason: "Electron notifications are not supported on this platform." };
  }
  const notification = new electronNotification(buildNotificationOptions(usagePayload, iconPath, options));
  activeNotifications.add(notification);
  const release = () => activeNotifications.delete(notification);
  notification.on("close", release);
  notification.on("failed", release);
  if (typeof onClick === "function") {
    notification.on("click", (...args) => {
      try {
        onClick(...args);
      } finally {
        release();
      }
    });
  }
  if (typeof options?.onAction === "function") {
    notification.on("action", (...args) => {
      try {
        options.onAction(...args);
      } finally {
        release();
      }
    });
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
