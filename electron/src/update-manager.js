"use strict";

const fs = require("node:fs");
const path = require("node:path");

const PROJECT_REPO_URL = "https://github.com/alisinaee/Codex-Account-Manager";
const PROJECT_RELEASES_URL = `${PROJECT_REPO_URL}/releases`;
const PROJECT_RELEASES_API_URL = "https://api.github.com/repos/alisinaee/Codex-Account-Manager/releases";
const PENDING_UPDATE_FILE = "pending-update.json";

function pythonInstallUrl(platform = process.platform) {
  if (platform === "win32") {
    return "https://www.python.org/downloads/windows/";
  }
  if (platform === "darwin") {
    return "https://www.python.org/downloads/macos/";
  }
  return "https://www.python.org/downloads/";
}

function normalizeVersion(raw) {
  return String(raw || "").trim().replace(/^v/i, "");
}

function versionParts(raw) {
  return normalizeVersion(raw)
    .split(".")
    .map((part) => Number.parseInt(part, 10))
    .map((part) => (Number.isFinite(part) ? part : 0));
}

function compareVersions(left, right) {
  const a = versionParts(left);
  const b = versionParts(right);
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const lhs = a[index] || 0;
    const rhs = b[index] || 0;
    if (lhs > rhs) return 1;
    if (lhs < rhs) return -1;
  }
  return 0;
}

function withVersionPrefix(raw) {
  const normalized = normalizeVersion(raw);
  return normalized ? `v${normalized}` : "";
}

function buildCoreInstallSpecForVersion(version, { repoUrl = PROJECT_REPO_URL } = {}) {
  const normalized = normalizeVersion(version);
  return `${repoUrl}.git@v${normalized}`.replace("https://github.com/", "git+https://github.com/");
}

function parseHighlightsFromBody(body = "") {
  return String(body || "")
    .split(/\n+/)
    .map((line) => line.replace(/^\s*[-*]\s*/, "").trim())
    .filter(Boolean)
    .slice(0, 8);
}

function isDefaultReleaseSource({ apiUrl = PROJECT_RELEASES_API_URL, repoUrl = PROJECT_RELEASES_URL } = {}) {
  return String(apiUrl || "").trim() === PROJECT_RELEASES_API_URL
    && String(repoUrl || "").trim() === PROJECT_RELEASES_URL;
}

function normalizeSystemPythonMeta(systemPython = {}) {
  if (!systemPython || typeof systemPython !== "object") {
    return null;
  }
  const version = normalizeVersion(
    systemPython.version
      || systemPython.recommended_version
      || systemPython.tag
      || systemPython.tag_name,
  );
  const installUrl = String(
    systemPython.install_url
      || systemPython.download_url
      || systemPython.url
      || "",
  ).trim();
  const notes = String(systemPython.notes || systemPython.body || "").trim();
  if (!version && !installUrl && !notes) {
    return null;
  }
  return {
    version,
    install_url: installUrl,
    notes,
  };
}

function normalizeCoreInstallSpec(raw) {
  return String(raw || "").trim();
}

function normalizeGitHubRelease(release = {}) {
  return {
    tag: String(release.tag_name || release.tag || "").trim(),
    title: String(release.name || release.title || release.tag_name || release.tag || "").trim(),
    body: String(release.body || "").trim(),
    published_at: release.published_at || release.created_at || "",
    html_url: String(release.html_url || "").trim(),
    is_draft: Boolean(release.draft || release.is_draft),
    is_prerelease: Boolean(release.prerelease || release.is_prerelease),
    highlights: parseHighlightsFromBody(release.body || ""),
    simulation_mode: Boolean(release.simulation_mode || release.is_simulation),
    assets: Array.isArray(release.assets)
      ? release.assets.map((asset) => ({
        name: String(asset.name || "").trim(),
        browser_download_url: String(asset.browser_download_url || asset.url || "").trim(),
        size: Number(asset.size || 0) || 0,
        content_type: String(asset.content_type || "").trim(),
        updated_at: String(asset.updated_at || "").trim(),
        simulate_open: Boolean(asset.simulate_open || asset.is_simulation),
      }))
      : [],
  };
}

function latestStableRelease(releases = []) {
  const stable = (Array.isArray(releases) ? releases : []).filter((release) => {
    const tag = String(release?.tag || release?.tag_name || "").trim();
    return tag && !release?.is_draft && !release?.is_prerelease && !release?.draft && !release?.prerelease;
  });
  if (!stable.length) return null;
  return stable.reduce((best, current) => {
    if (!best) return current;
    const cmp = compareVersions(current.tag || current.tag_name, best.tag || best.tag_name);
    if (cmp > 0) return current;
    if (cmp < 0) return best;
    return String(current.published_at || current.created_at || "") > String(best.published_at || best.created_at || "")
      ? current
      : best;
  }, null);
}

async function fetchGitHubReleaseNotes({
  fetchImpl = global.fetch,
  apiUrl = PROJECT_RELEASES_API_URL,
  repoUrl = PROJECT_RELEASES_URL,
} = {}) {
  if (typeof fetchImpl !== "function") {
    throw new Error("fetch is not available in the desktop runtime");
  }
  const response = await fetchImpl(apiUrl, {
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "codex-account-manager-electron",
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub releases request failed: ${response.status}`);
  }
  const payload = await response.json();
  const root = payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
  const rows = Array.isArray(payload)
    ? payload
    : Array.isArray(root.releases)
      ? root.releases
      : [];
  const releases = rows.map(normalizeGitHubRelease);
  const defaultSource = isDefaultReleaseSource({ apiUrl, repoUrl });
  return {
    status: String(root.status || "synced"),
    status_text: String(root.status_text || (defaultSource ? "Synced from GitHub" : "Synced from custom feed")),
    source: defaultSource ? "github" : "custom",
    repo_url: String(root.repo_url || repoUrl || PROJECT_RELEASES_URL),
    fetched_at: new Date().toISOString(),
    simulation_mode: Boolean(root.simulation_mode || root.is_simulation),
    releases,
    core_install_spec: normalizeCoreInstallSpec(
      root.core_install_spec
        || root.python_core?.install_spec
        || root.core?.install_spec,
    ),
    system_python: normalizeSystemPythonMeta(root.system_python || root.python_runtime),
  };
}

function buildUnifiedUpdateStatus({
  appVersion,
  runtimeState = {},
  releaseNotes = {},
  pendingUpdate = null,
  updaterDevMode = false,
  platform = process.platform,
} = {}) {
  const currentVersion = withVersionPrefix(appVersion);
  const currentCoreVersion = withVersionPrefix(runtimeState?.core?.version);
  const latestRelease = latestStableRelease(releaseNotes?.releases || []);
  const releaseVersion = withVersionPrefix(latestRelease?.tag || "");
  const releaseIsNewerThanCurrent = releaseVersion ? compareVersions(releaseVersion, currentVersion) > 0 : false;
  const latestVersion = releaseIsNewerThanCurrent ? releaseVersion : currentVersion;
  const desktopUpdateNeeded = releaseIsNewerThanCurrent;
  const pending = pendingUpdate && typeof pendingUpdate === "object" ? pendingUpdate : null;
  const pendingTarget = withVersionPrefix(pending?.targetVersion);
  const coreVersionMatchesApp = Boolean(currentCoreVersion) && compareVersions(currentCoreVersion, currentVersion) === 0;
  const coreInstalled = Boolean(runtimeState?.core?.installed);
  const coreUpdateNeeded = !desktopUpdateNeeded && (!coreInstalled || !coreVersionMatchesApp);
  const installerAwaiting = Boolean(pending?.awaitingDesktopInstall);
  const pendingDesktopInstallStillNeeded = installerAwaiting
    && Boolean(pendingTarget)
    && compareVersions(pendingTarget, currentVersion) > 0;
  const pendingCoreSyncStillNeeded = installerAwaiting
    && Boolean(pendingTarget)
    && compareVersions(pendingTarget, currentVersion) === 0
    && !coreVersionMatchesApp;
  const runtimePython = runtimeState?.python || {};
  const currentPythonVersion = normalizeVersion(runtimePython.version);
  const releasePython = normalizeSystemPythonMeta(releaseNotes?.system_python);
  const recommendedPythonVersion = normalizeVersion(releasePython?.version);
  const pythonAvailable = Boolean(runtimePython.available);
  const pythonSupported = Boolean(runtimePython.supported);
  const systemPythonRequired = !pythonAvailable || !pythonSupported;
  const systemPythonOptional = !systemPythonRequired
    && Boolean(recommendedPythonVersion)
    && compareVersions(recommendedPythonVersion, currentPythonVersion) > 0;
  const systemPythonSelected = Boolean(pending?.systemPythonSelected) || systemPythonRequired;
  const systemPythonSkipped = Boolean(pending?.systemPythonSkipped) && !systemPythonRequired;
  const systemPythonAutoUpdateSupported = String(platform || process.platform).toLowerCase() === "win32";
  const systemPython = {
    available: pythonAvailable,
    supported: pythonSupported,
    version: currentPythonVersion || "",
    install_url: String(runtimePython.installUrl || releasePython?.install_url || pythonInstallUrl(platform)).trim(),
    recommended_version: recommendedPythonVersion || "",
    auto_update_supported: systemPythonAutoUpdateSupported,
    required: systemPythonRequired,
    optional: systemPythonOptional,
    selected: systemPythonSelected,
    skipped: systemPythonSkipped,
    update_available: systemPythonRequired || systemPythonOptional,
    can_skip: !systemPythonRequired,
    action: systemPythonRequired ? "required" : (systemPythonOptional ? "optional" : "none"),
    notes: String(releasePython?.notes || "").trim(),
  };
  let status = "up_to_date";
  let statusText = String(releaseNotes?.status_text || releaseNotes?.status || "Up to date");

  if (pendingDesktopInstallStillNeeded) {
    status = "awaiting_desktop_install";
    statusText = `Installer ready for ${pendingTarget}. Finish installation and relaunch the app.`;
  } else if (desktopUpdateNeeded) {
    status = "desktop_update_required";
    statusText = `Desktop update ${latestVersion} is available.`;
  } else if (systemPythonRequired) {
    status = "system_python_required";
    statusText = currentPythonVersion
      ? `System Python ${currentPythonVersion} is unsupported. Install Python 3.11+ before finishing the update.`
      : "System Python 3.11+ must be installed before the update can continue.";
  } else if (coreUpdateNeeded) {
    status = "core_update_required";
    statusText = currentCoreVersion
      ? `Python core ${currentCoreVersion} must be synced to ${currentVersion}.`
      : `Python core must be installed for ${currentVersion}.`;
  } else if (systemPythonOptional) {
    status = "system_python_optional";
    statusText = `Optional System Python ${recommendedPythonVersion} is available.`;
  } else if (pendingCoreSyncStillNeeded) {
    status = "core_sync_pending";
    statusText = `Desktop update installed. Finishing Python core sync for ${currentVersion}.`;
  } else if (!latestVersion && !statusText) {
    statusText = "Unable to determine release status.";
  } else if (!statusText) {
    statusText = "Up to date";
  }

  return {
    updater_dev_mode: Boolean(updaterDevMode),
    current_version: currentVersion || "-",
    latest_version: latestVersion || currentVersion || "-",
    update_available: desktopUpdateNeeded
      || coreUpdateNeeded
      || systemPython.update_available
      || pendingDesktopInstallStillNeeded
      || pendingCoreSyncStillNeeded,
    desktop_update_needed: desktopUpdateNeeded,
    core_update_needed: coreUpdateNeeded,
    core_version: currentCoreVersion || "-",
    target_version: latestVersion || pendingTarget || currentVersion || "",
    latest_release: releaseIsNewerThanCurrent ? latestRelease : null,
    status,
    status_text: statusText,
    source: String(releaseNotes?.source || ""),
    repo_url: String(releaseNotes?.repo_url || PROJECT_RELEASES_URL),
    fetched_at: releaseNotes?.fetched_at || "",
    core_install_spec: releaseIsNewerThanCurrent
      ? normalizeCoreInstallSpec(releaseNotes?.core_install_spec)
      : buildCoreInstallSpecForVersion(currentVersion),
    pending_update: pending,
    system_python: systemPython,
    release_notes: releaseNotes,
  };
}

function selectReleaseAsset({
  release = {},
  platform,
  arch,
} = {}) {
  const assets = Array.isArray(release?.assets) ? release.assets : [];
  if (!assets.length) return null;
  const normalizedPlatform = String(platform || process.platform).toLowerCase();
  const normalizedArch = String(arch || process.arch).toLowerCase();
  if (normalizedPlatform === "darwin") {
    const dmgAssets = assets.filter((asset) => /\.dmg$/i.test(String(asset?.name || "")));
    const exact = dmgAssets.find((asset) => String(asset.name || "").toLowerCase().includes(normalizedArch));
    if (exact) return exact;
    const universal = dmgAssets.find((asset) => /universal/i.test(String(asset.name || "")));
    if (universal) return universal;
    return dmgAssets[0] || null;
  }
  if (normalizedPlatform === "win32") {
    const exeAssets = assets.filter((asset) => /\.(exe|msi)$/i.test(String(asset?.name || "")));
    const exact = exeAssets.find((asset) => String(asset.name || "").toLowerCase().includes(normalizedArch));
    return exact || exeAssets[0] || null;
  }
  const appImageAssets = assets.filter((asset) => /\.(AppImage|deb|rpm)$/i.test(String(asset?.name || "")));
  return appImageAssets[0] || assets[0] || null;
}

function pendingUpdateStatePath({ appLike }) {
  return path.join(appLike.getPath("userData"), PENDING_UPDATE_FILE);
}

function loadPendingUpdateState({ appLike, fsImpl = fs } = {}) {
  try {
    const raw = fsImpl.readFileSync(pendingUpdateStatePath({ appLike }), "utf8");
    const payload = JSON.parse(raw);
    return payload && typeof payload === "object" ? payload : null;
  } catch (_) {
    return null;
  }
}

function savePendingUpdateState(state, { appLike, fsImpl = fs } = {}) {
  if (!appLike || !state) return;
  fsImpl.mkdirSync(appLike.getPath("userData"), { recursive: true });
  fsImpl.writeFileSync(pendingUpdateStatePath({ appLike }), JSON.stringify(state, null, 2));
}

function clearPendingUpdateState({ appLike, fsImpl = fs } = {}) {
  try {
    fsImpl.unlinkSync(pendingUpdateStatePath({ appLike }));
  } catch (_) {}
}

function shouldResumePendingCoreSync({
  pendingUpdate = null,
  appVersion,
  runtimeState = {},
} = {}) {
  const pending = pendingUpdate && typeof pendingUpdate === "object" ? pendingUpdate : null;
  if (!pending?.awaitingDesktopInstall) return false;
  if (pending?.systemPythonRequired && (!runtimeState?.python?.available || !runtimeState?.python?.supported)) {
    return false;
  }
  const targetVersion = withVersionPrefix(pending.targetVersion);
  const currentVersion = withVersionPrefix(appVersion);
  if (!targetVersion || !currentVersion || compareVersions(targetVersion, currentVersion) !== 0) {
    return false;
  }
  const coreVersion = withVersionPrefix(runtimeState?.core?.version);
  return compareVersions(coreVersion, currentVersion) !== 0;
}

async function downloadReleaseAsset({
  asset,
  destinationDir,
  fetchImpl = global.fetch,
  fsImpl = fs,
  onProgress = () => {},
} = {}) {
  if (!asset?.browser_download_url) {
    throw new Error("Release asset is missing a download URL.");
  }
  if (typeof fetchImpl !== "function") {
    throw new Error("fetch is not available in the desktop runtime");
  }
  const response = await fetchImpl(asset.browser_download_url, {
    headers: {
      Accept: "application/octet-stream",
      "User-Agent": "codex-account-manager-electron",
    },
  });
  if (!response.ok || !response.body) {
    throw new Error(`Asset download failed: ${response.status}`);
  }
  const reader = response.body.getReader();
  const chunks = [];
  const total = Number(response.headers.get("content-length") || asset.size || 0) || 0;
  let received = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = Buffer.from(value);
    chunks.push(chunk);
    received += chunk.length;
    const percent = total > 0 ? Math.max(1, Math.min(100, Math.round((received / total) * 100))) : null;
    onProgress({
      phase: "downloading_desktop_update",
      status: "running",
      percent,
      detail: total > 0 ? `${received} / ${total} bytes` : `${received} bytes`,
    });
  }
  fsImpl.mkdirSync(destinationDir, { recursive: true });
  const destinationPath = path.join(destinationDir, String(asset.name || "desktop-update.bin"));
  fsImpl.writeFileSync(destinationPath, Buffer.concat(chunks));
  return destinationPath;
}

module.exports = {
  PROJECT_RELEASES_API_URL,
  PROJECT_RELEASES_URL,
  buildCoreInstallSpecForVersion,
  buildUnifiedUpdateStatus,
  clearPendingUpdateState,
  compareVersions,
  downloadReleaseAsset,
  fetchGitHubReleaseNotes,
  loadPendingUpdateState,
  savePendingUpdateState,
  selectReleaseAsset,
  shouldResumePendingCoreSync,
  withVersionPrefix,
};
