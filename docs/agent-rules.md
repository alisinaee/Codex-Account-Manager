# AI Agent Rules & Change Memory

## Project Snapshot
- Keep updates focused on architecture, behavior rules, and high-impact changes only.
- Prefer short, implementation-focused bullets over narrative prose.

## Behavior Rules
- Keep this file concise and clear for AI agents.
- Update this file after assistant turns that edit repo-tracked files.
- Capture new user behavior instructions as short imperative rules.
- Skip updates when there are no file edits and no new behavior instructions.
- Retain only the latest 20 change entries.
- Ensure documentation updates are thorough and written under the `docs/` folder.
- Ensure i want one command to fullllly test.
- Ensure dude its too slow similations i want to each swith happen about 30 sec also colorufll outputs , to know what happend what seelct in chain for next see the algorithm and.
- Ensure more fucus on web ui also need to user this is cross platfrom too.
- Ensure md file you need to blur my account emails first on image.
- Update the readme to include this data ( update readme.
- Ensure i dont want this scroll just on auto refresh , the loading cuase the change a little bit in columns , you need just fix that remove scroll on table.
- Ensure i want to see details of that and progress bar for instalion to find the issue.
- Ensure make codex-account electron command to show always info and progress.
- Ensure like other Mac icons it should be a rounded icon.

## Recent Changes (Last 20)
### 2026-04-25T17:26:22+03:30
- Changed files: `README.md`, `codex_account_manager/cli.py`, `docs/architecture.md`, `docs/cli-reference.md`, `docs/development.md`, `electron/package-lock.json`, `electron/package.json`, `electron/scripts/smoke.js`, +10 more
- Summary: Added packaged Electron runtime bootstrap with doctor JSON contract, setup screen, in-app Python core installer flow, production packaging scripts, and matching tests/docs.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:49f5dc16f4a1 -->

### 2026-04-24T14:46:42+03:30
- Changed files: `electron/assets/codex-account-manager-tray.svg`, `electron/src/icons.js`, `electron/src/tray.js`, `electron/tests/identity.test.js`, `electron/tests/desktop.test.js`
- Summary: Electron macOS status bar now uses a dedicated small tray template SVG resized to 18x18 instead of the full Dock app icon, preventing oversized black/green menu-bar rendering.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:265c6c3568d9 -->

### 2026-04-24T14:42:43+03:30
- Changed files: `electron/src/tray.js`, `electron/tests/desktop.test.js`
- Summary: Electron macOS status item now shows compact current profile plus 5H and weekly usage; tray context menu uses readable status rows with color-coded usage icons instead of a faded disabled summary row.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:b540e6979999 -->

### 2026-04-24T14:40:35+03:30
- Changed files: `electron/assets/codex-account-manager.svg`, `electron/assets/codex-account-manager.png`, `electron/assets/codex-account-manager.icns`, `electron/tests/identity.test.js`
- Summary: Regenerated Electron app icons as macOS-style rounded-square assets with transparent corners and added a regression test preventing raw square source icons in Electron.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:48db8f326fda -->

### 2026-04-24T14:37:57+03:30
- Changed files: `electron/src/tray.js`, `electron/tests/desktop.test.js`
- Summary: Electron macOS tray/status item is now icon-only; profile usage stays in tooltip/context menu instead of occupying menu-bar text.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:e6b75fe3d7e9 -->

### 2026-04-24T14:34:29+03:30
- Changed files: `electron/src/icons.js`, `electron/assets/codex-account-manager.svg`, `electron/assets/codex-account-manager.png`, `electron/assets/codex-account-manager.icns`, `electron/src/main.js`, `electron/src/tray.js`, `electron/src/menu.js`, `electron/src/renderer/App.jsx`, +10 more
- Summary: Electron now uses project-owned icon assets and app identity metadata, fixes file:// renderer builds, and aligns the Electron React UI/switch progress with the stable web panel visual system while leaving render_ui_html unchanged.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:291d3b6f4f2b -->

### 2026-04-24T14:05:57+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `docs/agent-rules.md`
- Summary: Changed codex-account electron so the default path always runs a visible npm install/check with progress/info output, even when runtime deps already exist; --no-install remains the explicit skip path.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:6f1eb43ec81b -->

### 2026-04-24T14:04:01+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `docs/agent-rules.md`
- Summary: Made codex-account electron dependency installation transparent by printing missing Electron deps, working directory, and the exact npm install command with foreground scripts, progress, and loglevel info; verified npm logs now show registry fetch progress.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:3276ad084c46 -->

### 2026-04-24T13:57:34+03:30
- Changed files: `codex_account_manager/cli.py`, `electron/scripts/dev.js`, `electron/tests/dev-script.test.js`, `tests/test_cli_core.py`, `docs/agent-rules.md`
- Summary: Fixed Electron --no-install missing dependency handling so it reports absent Vite/React/Electron deps before launching, and guarded the dev script against missing runtime binaries instead of throwing a Node spawn ENOENT stack trace.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:3ff869e7723c -->

### 2026-04-24T13:52:02+03:30
- Changed files: `README.md`, `codex_account_manager/cli.py`, `docs/architecture.md`, `docs/development.md`, `electron/package.json`, `electron/index.html`, `electron/vite.config.js`, `electron/scripts/dev.js`, +13 more
- Summary: Implemented Electron Desktop V2 foundations with separate React/Vite renderer, safe no_restart switch flow, service token parsing, app menu/lifecycle helpers, notification icon support, and Electron switch smoke coverage; npm registry access blocked dependency installation/build locally.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:90ba5d103901 -->

### 2026-04-24T13:50:29+03:30
- Changed files: `README.md`, `codex_account_manager/cli.py`, `docs/architecture.md`, `docs/development.md`, `electron/package.json`, `electron/index.html`, `electron/vite.config.js`, `electron/scripts/dev.js`, +12 more
- Summary: Implemented Electron Desktop V2 foundations: separate React/Vite renderer, safe no_restart desktop switch API client, service token parsing, app menu/lifecycle helpers, tray-stay behavior, notification icon support, docs updates, and regression tests while leaving the web panel unchanged.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:e7d5b2d9840e -->

### 2026-04-24T13:07:24+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `README.md`, `docs/development.md`, `docs/cli-reference.md`, `docs/agent-rules.md`
- Summary: Added codex-account electron convenience command that runs npm install when needed and starts the optional Electron dev shell from the source checkout; documented it as the preferred dev-shell launch command.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:1b987356e1ac -->

### 2026-04-24T12:40:38+03:30
- Changed files: `README.md`, `docs/architecture.md`, `docs/development.md`, `electron/package.json`, `electron/src/main.js`, `electron/src/preload.js`, `electron/src/backend.js`, `electron/src/usage.js`, +7 more
- Summary: Added optional Electron development shell that loads the existing local web panel, starts or connects to ui-service, shows current usage in tray/menu-bar state, supports Electron-native test notifications, and includes Node plus Playwright Electron tests.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:7a74444da071 -->

### 2026-04-24T11:38:07+03:30
- Changed files: `README.md`, `docs/agent-rules.md`
- Summary: Expanded README Privacy / Security language to clearly state there is no live API server or hosted backend and that profile/auth data stays local unless users explicitly export/share it.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:b63cc22f9f2f -->

### 2026-04-24T10:21:37+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Removed table-wide fixed-width constraints that caused horizontal scrolling; stabilized loading-state usage metric width by reserving consistent usage percentage space instead.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:bebdbafcfe54 -->

### 2026-04-24T10:17:11+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Locked account table layout to fixed mode so loading placeholders cannot reflow column widths during usage fetches; added regression assertion for table-layout fixed in UI render test.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:7ab5e1264878 -->

### 2026-04-24T09:15:30+03:30
- Changed files: `README.md`, `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Documented supported Codex clients and the manual reload caveat after account switches in README and in-app guide/help, with a render test.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:71d4e4060b11 -->

### 2026-04-24T09:07:00+03:30
- Changed files: `README.md`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`, `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/ISSUE_TEMPLATE/feature_request.md`, `.github/pull_request_template.md`, `docs/assets/screenshots/codex-account-manager-demo.gif`, `docs/agent-rules.md`
- Summary: Implemented the GitHub discoverability pass with a conversion-focused README rewrite, trust docs, GitHub templates, and a lightweight README demo GIF.
- Behavior impact: Recorded the current GitHub-facing onboarding and trust surfaces for future AI context.
<!-- fingerprint:fdc3ec6d9182 -->

### 2026-04-24T08:43:10+03:30
- Changed files: `README.md`, `docs/assets/screenshots/web-ui-panel-v0.0.12-blurred-emails.png`, `docs/assets/screenshots/web-ui-panel-blurred-emails.png`
- Summary: Renamed the README screenshot asset to a versioned filename so GitHub does not reuse a cached old image URL.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:7e744536d759 -->

### 2026-04-24T08:20:50+03:30
- Changed files: `docs/assets/screenshots/web-ui-panel-blurred-emails.png`, `README.md`
- Summary: Replaced the README web panel screenshot with the latest image and blurred account emails before committing it.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:38ea10b9051a -->

## Last Updated
- 2026-04-25T17:26:22+03:30
