"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("codexAccountDesktop", {
  platform: process.platform,
  shell: "electron",
  debugIpc: () => ipcRenderer.invoke("desktop:debug-ipc"),
  getState: () => ipcRenderer.invoke("desktop:get-state"),
  getBackendState: () => ipcRenderer.invoke("desktop:get-backend-state"),
  getRuntimeStatus: () => ipcRenderer.invoke("desktop:get-runtime-status"),
  getUpdateStatus: (options) => ipcRenderer.invoke("desktop:get-update-status", options),
  copyRuntimeDiagnostics: () => ipcRenderer.invoke("desktop:copy-runtime-diagnostics"),
  retryRuntimeCheck: () => ipcRenderer.invoke("desktop:retry-runtime-check"),
  installPythonRuntime: () => ipcRenderer.invoke("desktop:install-python-runtime"),
  installPythonCore: async () => {
    try {
      return await ipcRenderer.invoke("desktop:install-python-core");
    } catch (error) {
      if (!/No handler registered/i.test(String(error?.message || error))) {
        throw error;
      }
      return ipcRenderer.invoke("desktop:install-core");
    }
  },
  startBackendService: () => ipcRenderer.invoke("desktop:start-backend-service"),
  stopBackendService: () => ipcRenderer.invoke("desktop:stop-backend-service"),
  runUnifiedUpdate: (options) => ipcRenderer.invoke("desktop:run-unified-update", options),
  openExternal: (url) => ipcRenderer.invoke("desktop:open-external", url),
  refresh: () => ipcRenderer.invoke("desktop:refresh"),
  switchProfile: (name, options) => ipcRenderer.invoke("desktop:switch-profile", name, options),
  saveConfig: (patch) => ipcRenderer.invoke("desktop:save-config", patch),
  downloadExport: (exportId, filename) => ipcRenderer.invoke("desktop:download-export", exportId, filename),
  listDisplays: () => ipcRenderer.invoke("desktop:list-displays"),
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
  onCycleView: (callback) => {
    const handler = (_event, step) => callback(step);
    ipcRenderer.on("desktop:cycle-view", handler);
    return () => ipcRenderer.removeListener("desktop:cycle-view", handler);
  },
  onRefreshRequested: (callback) => {
    const handler = () => callback();
    ipcRenderer.on("desktop:refresh-requested", handler);
    return () => ipcRenderer.removeListener("desktop:refresh-requested", handler);
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
  onUpdateProgress: (callback) => {
    const handler = (_event, progress) => callback(progress);
    ipcRenderer.on("desktop:update-progress", handler);
    return () => ipcRenderer.removeListener("desktop:update-progress", handler);
  },
  onAutoSwitchStopped: (callback) => {
    const handler = (_event, payload) => callback(payload);
    ipcRenderer.on("desktop:auto-switch-stopped", handler);
    return () => ipcRenderer.removeListener("desktop:auto-switch-stopped", handler);
  },
  onAutoSwitchPending: (callback) => {
    const handler = (_event, payload) => callback(payload);
    ipcRenderer.on("desktop:auto-switch-pending", handler);
    return () => ipcRenderer.removeListener("desktop:auto-switch-pending", handler);
  },
});
