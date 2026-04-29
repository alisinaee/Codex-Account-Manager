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
          { label: "Quit App", accelerator: "CmdOrCtrl+Q", click: actions.onQuit },
          { label: "Quit + Stop Core", accelerator: "CmdOrCtrl+Shift+Q", click: actions.onQuitAndStopCore },
        ],
      }]
    : [];

  return [
    ...appMenu,
    {
      label: "File",
      submenu: [
        { label: "Profiles", accelerator: "CmdOrCtrl+1", click: actions.onProfiles },
        { label: "Auto Switch", accelerator: "CmdOrCtrl+2", click: actions.onAutoSwitch },
        { label: "Settings", accelerator: "CmdOrCtrl+,", click: actions.onSettings },
        { label: "Guide & Help", accelerator: "CmdOrCtrl+/", click: actions.onGuide },
        { label: "Update", accelerator: "CmdOrCtrl+U", click: actions.onUpdate },
        { label: "Debug", accelerator: "CmdOrCtrl+D", click: actions.onDebug },
        { label: "About", accelerator: "CmdOrCtrl+A", click: actions.onAbout },
        { type: "separator" },
        ...(isMac ? [{ role: "close" }] : [{ label: "Quit App", accelerator: "Alt+F4", click: actions.onQuit }]),
        { label: "Quit App", accelerator: "CmdOrCtrl+Q", click: actions.onQuit },
        { label: "Quit + Stop Core", accelerator: "CmdOrCtrl+Shift+Q", click: actions.onQuitAndStopCore },
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
        { label: "Refresh Table", accelerator: "CmdOrCtrl+R", click: actions.onRefresh },
        { label: "Refresh Table (F5)", accelerator: "F5", click: actions.onRefresh },
        { label: "Toggle Sidebar", accelerator: "CmdOrCtrl+B", click: actions.onToggleSidebar },
        { label: "Test Notification", accelerator: "CmdOrCtrl+Shift+N", click: actions.onTestNotification },
        { type: "separator" },
        { label: "Zoom In", accelerator: "CmdOrCtrl+=", click: actions.onZoomIn },
        { label: "Zoom Out", accelerator: "CmdOrCtrl+-", click: actions.onZoomOut },
        { label: "Reset Zoom", accelerator: "CmdOrCtrl+0", click: actions.onZoomReset },
        ...(isDev ? [{ type: "separator" }, { role: "reload" }, { role: "toggleDevTools" }] : []),
      ],
    },
    {
      label: "Go",
      submenu: [
        { label: "Profiles", accelerator: "CmdOrCtrl+1", click: actions.onProfiles },
        { label: "Auto Switch", accelerator: "CmdOrCtrl+2", click: actions.onAutoSwitch },
        { label: "Settings", accelerator: "CmdOrCtrl+,", click: actions.onSettings },
        { label: "Guide & Help", accelerator: "CmdOrCtrl+/", click: actions.onGuide },
        { label: "Update", accelerator: "CmdOrCtrl+U", click: actions.onUpdate },
        { label: "Debug", accelerator: "CmdOrCtrl+D", click: actions.onDebug },
        { label: "About", accelerator: "CmdOrCtrl+A", click: actions.onAbout },
        { type: "separator" },
        { label: "Next Section", accelerator: "CmdOrCtrl+PageDown", click: actions.onNextSection },
        { label: "Previous Section", accelerator: "CmdOrCtrl+PageUp", click: actions.onPreviousSection },
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
