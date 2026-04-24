function splitHash(value) {
  const text = String(value || "");
  const index = text.indexOf("#");
  if (index === -1) {
    return { path: text, hash: "" };
  }
  return {
    path: text.slice(0, index),
    hash: text.slice(index),
  };
}

export function appendSessionToken(path, token) {
  const target = String(path || "");
  const sessionToken = String(token || "").trim();
  if (!sessionToken) {
    return target;
  }
  const { path: basePath, hash } = splitHash(target);
  if (/(^|[?&])token=/.test(basePath)) {
    return target;
  }
  const separator = basePath.includes("?") ? "&" : "?";
  return `${basePath}${separator}token=${encodeURIComponent(sessionToken)}${hash}`;
}

export function buildAuthenticatedDownloadUrl(baseUrl, path, token, params = {}) {
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
