"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("codexAccountDesktop", {
  platform: process.platform,
  shell: "electron",
  getState: () => ipcRenderer.invoke("desktop:get-state"),
  getBackendState: () => ipcRenderer.invoke("desktop:get-backend-state"),
  refresh: () => ipcRenderer.invoke("desktop:refresh"),
  switchProfile: (name) => ipcRenderer.invoke("desktop:switch-profile", name),
  saveConfig: (patch) => ipcRenderer.invoke("desktop:save-config", patch),
  request: (path, options) => ipcRenderer.invoke("desktop:request", path, options),
  testNotification: () => ipcRenderer.invoke("desktop:test-notification"),
  navigate: (view) => ipcRenderer.send("desktop:navigate", view),
  toggleSidebar: () => ipcRenderer.send("desktop:toggle-sidebar"),
  onNavigate: (callback) => {
    const handler = (_event, view) => callback(view);
    ipcRenderer.on("desktop:navigate", handler);
    return () => ipcRenderer.removeListener("desktop:navigate", handler);
  },
  onToggleSidebar: (callback) => {
    const handler = () => callback();
    ipcRenderer.on("desktop:toggle-sidebar", handler);
    return () => ipcRenderer.removeListener("desktop:toggle-sidebar", handler);
  },
});
