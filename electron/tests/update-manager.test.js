const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildCoreInstallSpecForVersion,
  buildUnifiedUpdateStatus,
  fetchGitHubReleaseNotes,
  selectReleaseAsset,
  shouldResumePendingCoreSync,
} = require("../src/update-manager");

test("buildCoreInstallSpecForVersion pins pipx installs to the matching release tag", () => {
  assert.equal(
    buildCoreInstallSpecForVersion("0.0.20"),
    "git+https://github.com/alisinaee/Codex-Account-Manager.git@v0.0.20",
  );
});

test("buildUnifiedUpdateStatus uses the Electron bundle version as current version and flags core sync separately", () => {
  const status = buildUnifiedUpdateStatus({
    appVersion: "0.0.20",
    runtimeState: {
      core: {
        installed: true,
        version: "0.0.12",
      },
    },
    releaseNotes: {
      status: "synced",
      status_text: "Synced from GitHub",
      core_install_spec: "git+file:///tmp/cam-real-update/src/codex_account_manager_0_0_16@v0.0.16",
      releases: [
        { tag: "v0.0.20", published_at: "2026-04-30T10:00:00Z" },
      ],
    },
  });

  assert.equal(status.current_version, "v0.0.20");
  assert.equal(status.latest_version, "v0.0.20");
  assert.equal(status.desktop_update_needed, false);
  assert.equal(status.core_update_needed, true);
  assert.equal(status.update_available, true);
  assert.equal(status.core_version, "v0.0.12");
  assert.equal(
    status.core_install_spec,
    "git+https://github.com/alisinaee/Codex-Account-Manager.git@v0.0.20",
  );
});

test("buildUnifiedUpdateStatus treats a newer desktop release as a desktop app update", () => {
  const status = buildUnifiedUpdateStatus({
    appVersion: "0.0.12",
    runtimeState: {
      core: {
        installed: true,
        version: "0.0.12",
      },
    },
    releaseNotes: {
      status: "synced",
      status_text: "Synced from GitHub",
      releases: [
        { tag: "v0.0.20", published_at: "2026-04-30T10:00:00Z" },
      ],
    },
  });

  assert.equal(status.desktop_update_needed, true);
  assert.equal(status.core_update_needed, false);
  assert.equal(status.update_available, true);
  assert.equal(status.target_version, "v0.0.20");
});

test("buildUnifiedUpdateStatus ignores release feed versions older than the installed app", () => {
  const status = buildUnifiedUpdateStatus({
    appVersion: "0.0.20",
    runtimeState: {
      core: {
        installed: true,
        version: "0.0.16",
      },
    },
    releaseNotes: {
      status: "synced",
      status_text: "Synced from stale GitHub cache",
      core_install_spec: "git+https://github.com/alisinaee/Codex-Account-Manager.git@v0.0.12",
      releases: [
        { tag: "v0.0.12", published_at: "2026-04-23T10:00:00Z" },
      ],
    },
  });

  assert.equal(status.current_version, "v0.0.20");
  assert.equal(status.latest_version, "v0.0.20");
  assert.equal(status.desktop_update_needed, false);
  assert.equal(status.core_update_needed, true);
  assert.equal(status.target_version, "v0.0.20");
  assert.equal(
    status.core_install_spec,
    "git+https://github.com/alisinaee/Codex-Account-Manager.git@v0.0.20",
  );
});

test("buildUnifiedUpdateStatus clears stale pending desktop update after current app and core match", () => {
  const status = buildUnifiedUpdateStatus({
    appVersion: "0.0.20",
    runtimeState: {
      python: {
        available: true,
        supported: true,
        version: "3.14.4",
      },
      core: {
        installed: true,
        version: "0.0.20",
      },
    },
    pendingUpdate: {
      targetVersion: "v0.0.20",
      awaitingDesktopInstall: true,
    },
    releaseNotes: {
      status: "synced",
      status_text: "Synced from GitHub",
      releases: [
        { tag: "v0.0.20", published_at: "2026-05-01T10:00:00Z" },
      ],
    },
  });

  assert.equal(status.status, "up_to_date");
  assert.equal(status.update_available, false);
  assert.equal(status.desktop_update_needed, false);
  assert.equal(status.core_update_needed, false);
  assert.equal(status.current_version, "v0.0.20");
  assert.equal(status.latest_version, "v0.0.20");
});

test("fetchGitHubReleaseNotes preserves localhost feed metadata and marks the source as custom", async () => {
  const payload = {
    status: "synced",
    status_text: "Synced from localhost",
    simulation_mode: true,
    releases: [
      {
        tag_name: "v0.0.16",
        name: "v0.0.16",
        published_at: "2026-04-30T10:00:00Z",
        assets: [
          {
            name: "Codex-Account-Manager-0.0.16-arm64.dmg",
            browser_download_url: "http://127.0.0.1:8765/Codex-Account-Manager-0.0.16-arm64.dmg",
            simulate_open: true,
          },
        ],
      },
    ],
    system_python: {
      version: "3.14.4",
      install_url: "http://127.0.0.1:8765/python",
    },
    python_core: {
      install_spec: "git+file:///tmp/cam-real-update/src/codex_account_manager_0_0_16@v0.0.16",
    },
  };

  const result = await fetchGitHubReleaseNotes({
    apiUrl: "http://127.0.0.1:8765/releases.json",
    repoUrl: "http://127.0.0.1:8765/releases",
    fetchImpl: async () => ({
      ok: true,
      json: async () => payload,
    }),
  });

  assert.equal(result.source, "custom");
  assert.equal(result.repo_url, "http://127.0.0.1:8765/releases");
  assert.equal(result.simulation_mode, true);
  assert.equal(result.system_python.version, "3.14.4");
  assert.equal(
    result.core_install_spec,
    "git+file:///tmp/cam-real-update/src/codex_account_manager_0_0_16@v0.0.16",
  );
  assert.equal(result.releases[0].tag, "v0.0.16");
  assert.equal(result.releases[0].assets[0].simulate_open, true);
});

test("buildUnifiedUpdateStatus makes system python required when runtime python is missing", () => {
  const status = buildUnifiedUpdateStatus({
    appVersion: "0.0.20",
    runtimeState: {
      python: {
        available: false,
        supported: false,
        version: "",
        installUrl: "https://python.example/download",
      },
      core: {
        installed: false,
        version: "",
      },
    },
    releaseNotes: {
      status: "synced",
      status_text: "Local feed ready",
      source: "custom",
      system_python: {
        version: "3.14.4",
        install_url: "https://python.example/download",
      },
      releases: [
        { tag: "v0.0.20", published_at: "2026-04-30T10:00:00Z" },
      ],
    },
    updaterDevMode: true,
    platform: "win32",
  });

  assert.equal(status.updater_dev_mode, true);
  assert.equal(status.system_python.required, true);
  assert.equal(status.system_python.optional, false);
  assert.equal(status.system_python.update_available, true);
  assert.equal(status.system_python.auto_update_supported, true);
  assert.equal(status.status, "system_python_required");
});

test("buildUnifiedUpdateStatus exposes optional system python updates when the current python is already supported", () => {
  const status = buildUnifiedUpdateStatus({
    appVersion: "0.0.20",
    runtimeState: {
      python: {
        available: true,
        supported: true,
        version: "3.11.9",
        installUrl: "https://python.example/download",
      },
      core: {
        installed: true,
        version: "0.0.20",
      },
    },
    releaseNotes: {
      status: "synced",
      status_text: "Local feed ready",
      source: "custom",
      system_python: {
        version: "3.14.4",
        install_url: "https://python.example/download",
      },
      releases: [
        { tag: "v0.0.20", published_at: "2026-04-30T10:00:00Z" },
      ],
    },
    platform: "darwin",
  });

  assert.equal(status.system_python.required, false);
  assert.equal(status.system_python.optional, true);
  assert.equal(status.system_python.update_available, true);
  assert.equal(status.system_python.recommended_version, "3.14.4");
  assert.equal(status.system_python.auto_update_supported, false);
});

test("selectReleaseAsset picks the matching macOS arm64 DMG from release assets", () => {
  const asset = selectReleaseAsset({
    release: {
      tag: "v0.0.20",
      assets: [
        { name: "Codex.Account.Manager-0.0.20-mac.zip", browser_download_url: "https://example.test/mac.zip" },
        { name: "Codex.Account.Manager-0.0.20-arm64.dmg", browser_download_url: "https://example.test/arm64.dmg" },
        { name: "Codex.Account.Manager-0.0.20-x64.dmg", browser_download_url: "https://example.test/x64.dmg" },
      ],
    },
    platform: "darwin",
    arch: "arm64",
  });

  assert.equal(asset.name, "Codex.Account.Manager-0.0.20-arm64.dmg");
});

test("shouldResumePendingCoreSync resumes only after the new app version is installed and the core still lags", () => {
  assert.equal(
    shouldResumePendingCoreSync({
      pendingUpdate: { targetVersion: "v0.0.20", awaitingDesktopInstall: true },
      appVersion: "0.0.20",
      runtimeState: { core: { version: "0.0.12", installed: true } },
    }),
    true,
  );
  assert.equal(
    shouldResumePendingCoreSync({
      pendingUpdate: { targetVersion: "v0.0.20", awaitingDesktopInstall: true },
      appVersion: "0.0.12",
      runtimeState: { core: { version: "0.0.12", installed: true } },
    }),
    false,
  );
  assert.equal(
    shouldResumePendingCoreSync({
      pendingUpdate: {
        targetVersion: "v0.0.20",
        awaitingDesktopInstall: true,
        systemPythonRequired: true,
      },
      appVersion: "0.0.20",
      runtimeState: {
        python: { available: false, supported: false, version: "" },
        core: { version: "0.0.12", installed: true },
      },
    }),
    false,
  );
  assert.equal(
    shouldResumePendingCoreSync({
      pendingUpdate: {
        targetVersion: "v0.0.20",
        awaitingDesktopInstall: true,
        systemPythonRequired: true,
      },
      appVersion: "0.0.20",
      runtimeState: {
        python: { available: true, supported: true, version: "3.14.4" },
        core: { version: "0.0.12", installed: true },
      },
    }),
    true,
  );
});
