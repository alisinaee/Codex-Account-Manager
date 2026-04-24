"use strict";

const { APP_NAME } = require("./icons");

function buildApplicationMenuTemplate({ isMac = process.platform === "darwin", isDev = false, actions = {} } = {}) {
  const appMenu = isMac
    ? [{
        label: APP_NAME,
        submenu: [
          { role: "about" },
          { type: "separator" },
          { label: "Settings", accelerator: "CmdOrCtrl+,", click: actions.onSettings },
          { type: "separator" },
          { role: "services" },
          { type: "separator" },
          { role: "hide" },
          { role: "hideOthers" },
          { role: "unhide" },
          { type: "separator" },
          { label: "Quit", accelerator: "CmdOrCtrl+Q", click: actions.onQuit },
        ],
      }]
    : [];

  return [
    ...appMenu,
    {
      label: "File",
      submenu: [
        { label: "Profiles", accelerator: "CmdOrCtrl+1", click: actions.onProfiles },
        { label: "Settings", accelerator: "CmdOrCtrl+,", click: actions.onSettings },
        { type: "separator" },
        ...(isMac ? [{ role: "close" }] : [{ label: "Quit", accelerator: "Alt+F4", click: actions.onQuit }]),
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: "View",
      submenu: [
        { label: "Refresh", accelerator: "CmdOrCtrl+R", click: actions.onRefresh },
        { label: "Toggle Sidebar", accelerator: "CmdOrCtrl+B", click: actions.onToggleSidebar },
        { label: "Test Notification", accelerator: "CmdOrCtrl+Shift+N", click: actions.onTestNotification },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        ...(isDev ? [{ type: "separator" }, { role: "reload" }, { role: "toggleDevTools" }] : []),
      ],
    },
    {
      label: "Window",
      submenu: [
        { role: "minimize" },
        { role: "zoom" },
        ...(isMac ? [{ type: "separator" }, { role: "front" }] : [{ role: "close" }]),
      ],
    },
    {
      label: "Help",
      submenu: [
        { label: "About Codex Account Manager", click: actions.onAbout },
        { label: "Check for Updates", click: actions.onUpdates },
      ],
    },
  ];
}

function shouldQuitOnWindowAllClosed({ hasTray, isQuitting }) {
  return Boolean(isQuitting || !hasTray);
}

module.exports = {
  buildApplicationMenuTemplate,
  shouldQuitOnWindowAllClosed,
};
