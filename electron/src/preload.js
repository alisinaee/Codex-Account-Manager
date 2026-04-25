"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("codexAccountDesktop", {
  platform: process.platform,
  shell: "electron",
  getState: () => ipcRenderer.invoke("desktop:get-state"),
  getBackendState: () => ipcRenderer.invoke("desktop:get-backend-state"),
  getRuntimeStatus: () => ipcRenderer.invoke("desktop:get-runtime-status"),
  copyRuntimeDiagnostics: () => ipcRenderer.invoke("desktop:copy-runtime-diagnostics"),
  retryRuntimeCheck: () => ipcRenderer.invoke("desktop:retry-runtime-check"),
  installPythonCore: () => ipcRenderer.invoke("desktop:install-python-core"),
  startBackendService: () => ipcRenderer.invoke("desktop:start-backend-service"),
  stopBackendService: () => ipcRenderer.invoke("desktop:stop-backend-service"),
  openExternal: (url) => ipcRenderer.invoke("desktop:open-external", url),
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
  onRuntimeStatus: (callback) => {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on("desktop:runtime-status", handler);
    return () => ipcRenderer.removeListener("desktop:runtime-status", handler);
  },
  onRuntimeProgress: (callback) => {
    const handler = (_event, progress) => callback(progress);
    ipcRenderer.on("desktop:runtime-progress", handler);
    return () => ipcRenderer.removeListener("desktop:runtime-progress", handler);
  },
});
