"use strict";

const fs = require("node:fs");

function buildAuthenticatedDownloadUrl(baseUrl, path, token, params = {}) {
  const root = String(baseUrl || "").replace(/\/+$/, "");
  const target = new URL(String(path || ""), `${root}/`);
  if (token) {
    target.searchParams.set("token", String(token));
  }
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    target.searchParams.set(key, String(value));
  }
  return target.toString();
}

async function downloadBackendExportArchive({
  backendState = {},
  exportId,
  filename,
  fetchImpl = fetch,
  dialogImpl,
  windowRef = null,
  fsImpl = fs,
} = {}) {
  const baseUrl = String(backendState?.baseUrl || "").trim();
  const token = String(backendState?.token || "").trim();
  const cleanExportId = String(exportId || "").trim();
  const defaultFilename = String(filename || "profiles.camzip").trim() || "profiles.camzip";

  if (!baseUrl || !token) {
    throw new Error("desktop backend session is unavailable");
  }
  if (!cleanExportId) {
    throw new Error("export id is required");
  }
  if (!dialogImpl || typeof dialogImpl.showSaveDialog !== "function") {
    throw new Error("save dialog is unavailable");
  }

  const href = buildAuthenticatedDownloadUrl(
    baseUrl,
    "/api/local/export/download",
    token,
    { id: cleanExportId },
  );
  const response = await fetchImpl(href, { method: "GET", cache: "no-store" });
  if (!response.ok) {
    throw new Error(`download failed (${response.status})`);
  }
  const raw = await response.arrayBuffer();
  const saveResult = await dialogImpl.showSaveDialog(windowRef, {
    defaultPath: defaultFilename,
    filters: [{ name: "Codex Account Manager Export", extensions: ["camzip"] }],
  });
  if (saveResult?.canceled || !saveResult?.filePath) {
    return { saved: false, canceled: true, filePath: String(saveResult?.filePath || "") };
  }
  fsImpl.writeFileSync(saveResult.filePath, Buffer.from(raw));
  return { saved: true, canceled: false, filePath: saveResult.filePath };
}

module.exports = {
  buildAuthenticatedDownloadUrl,
  downloadBackendExportArchive,
};
