import { buildAuthenticatedDownloadUrl } from "./request-paths.mjs";

export function triggerBlobDownload(blob, filename, {
  documentRef = document,
  urlApi = URL,
  setTimeoutImpl = (fn, delay) => window.setTimeout(fn, delay),
  revokeDelayMs = 1500,
} = {}) {
  if (!documentRef?.body || typeof documentRef.createElement !== "function") {
    throw new Error("download requires a document body");
  }
  const objectUrl = urlApi.createObjectURL(blob);
  const anchor = documentRef.createElement("a");
  anchor.href = objectUrl;
  anchor.download = String(filename || "download.bin");
  documentRef.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeoutImpl(() => {
    try {
      urlApi.revokeObjectURL(objectUrl);
    } catch (_) {}
  }, revokeDelayMs);
}

export async function downloadBackendExport({
  desktop = null,
  backendState = null,
  fetchImpl = fetch,
  path,
  params = {},
  filename,
  documentRef = document,
  urlApi = URL,
  setTimeoutImpl = (fn, delay) => window.setTimeout(fn, delay),
  readErrorMessage = async (_response, fallbackMessage) => fallbackMessage,
} = {}) {
  let activeBackend = backendState;
  if ((!activeBackend?.baseUrl || !activeBackend?.token) && desktop && typeof desktop.getBackendState === "function") {
    activeBackend = await desktop.getBackendState();
  }
  if (!activeBackend?.baseUrl || !activeBackend?.token) {
    throw new Error("desktop backend session is unavailable; refresh the app and try export again");
  }
  const href = buildAuthenticatedDownloadUrl(
    activeBackend.baseUrl,
    path,
    activeBackend.token,
    params,
  );
  const response = await fetchImpl(href, { method: "GET", cache: "no-store", credentials: "same-origin" });
  if (!response.ok) {
    const detail = await readErrorMessage(response, `download failed (${response.status})`);
    throw new Error(detail);
  }
  const blob = await response.blob();
  triggerBlobDownload(blob, filename, { documentRef, urlApi, setTimeoutImpl });
  return activeBackend;
}
