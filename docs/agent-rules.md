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
### 2026-04-27T15:13:39+03:30
- Changed files: `electron/src/renderer/SettingsView.jsx`, `electron/src/styles/components.css`
- Summary: Simplified the Electron settings internals so each settings group now uses a single stacked subsection lane instead of side-by-side inner grids, making the page follow the `Current account refresh` box pattern more consistently.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:2dbfb2d0af9c -->

### 2026-04-27T14:48:26+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/SettingsView.jsx`, `electron/src/renderer/theme.mjs`, `electron/src/styles/components.css`, `electron/src/styles/tokens.css`, `electron/tests/e2e/electron-shell.spec.js`, `electron/tests/theme.test.js`
- Summary: Extracted the Electron settings screen into a dedicated module, rebuilt it as a responsive card-based layout with bottom-right section actions, fixed settings-page scrolling, and completed renderer-side light/dark/auto theme application with new regression coverage.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:7c2a93f7f0f8 -->

### 2026-04-27T13:11:42+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Refined the Electron Settings layout into a full-width card stack, token-driven 2-to-1 responsive inner grids, aligned right-edge controls, and stabilized shared stepper sizing and Windows helper-copy rows.
- Behavior impact: Added or refreshed 4 behavior rule(s) from user instructions.
<!-- fingerprint:4e62bad66447 -->

### 2026-04-27T09:25:57+03:30
- Changed files: `electron/src/renderer/App.jsx`, `docs/agent-rules.md`
- Summary: Disabled automatic core installation on the Electron setup screen; install steps now wait for explicit user action.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:69791133204e -->

### 2026-04-27T09:22:24+03:30
- Changed files: `docs/agent-rules.md`
- Summary: Recorded that Electron prerequisite install flow must work generally across Windows systems, not only the local machine.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:8acfc423dee7 -->

### 2026-04-27T09:05:43+03:30
- Changed files: `electron/src/main.js`, `electron/src/preload.js`, `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Fixed Windows Electron setup IPC registration so shortcut setup failures cannot leave runtime install handlers unregistered; added IPC diagnostics and compact runtime layout spacing tweaks.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:86431e977a6e -->

### 2026-04-26T23:24:39+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`, `electron/tests/e2e/electron-shell.spec.js`, `electron/tests/runtime.test.js`
- Summary: Implemented space-first Electron desktop layouts with explicit scroll containers, per-page flex fill behavior, Auto Switch stats fill area, Update guidance details, E2E layout regression coverage, and refreshed stale runtime/E2E assertions.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:a5b19558dddf -->

### 2026-04-26T23:01:13+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Widened the Electron profile table Auto column to prevent toggle clipping beside Actions.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:e25ad94ecad8 -->

### 2026-04-26T22:53:35+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Tightened Electron profile table Actions column widths across breakpoints and redistributed freed width to data columns.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:43f820feda19 -->

### 2026-04-26T21:41:56+03:30
- Changed files: `electron/src/styles/components.css`
- Summary: Made profiles table action controls fixed-size inside the Actions column so Switch no longer stretches or truncates unnecessarily.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:ad8282d82576 -->

### 2026-04-26T21:40:36+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Restored real colgroup sizing for the profiles table and widened the actions column so Switch and row actions fit.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:a552f9010904 -->

### 2026-04-26T21:35:10+03:30
- Changed files: `electron/src/styles/components.css`
- Summary: Pinned the profiles table row actions menu button inside the actions cell and made the switch button shrink within the remaining width.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:c27ee072b336 -->

### 2026-04-26T19:18:40+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`, `electron/src/renderer/components/DataTable.jsx`, `electron/src/renderer/components/StatusDot.jsx`, `electron/src/renderer/icon-pack.jsx`, `electron/src/renderer/table-layout.mjs`, `electron/tests/table-layout.test.js`
- Summary: Implemented collapsed sidebar mini usage arcs, resilient sidebar toggle/exit/nav hit targets, fixed-layout profiles table with colgroup responsive hiding, restored colored usage bars, truncation/date formatting/tooltip rules, and row-actions copy/edit/remove options.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:362c4023c1dd -->

### 2026-04-26T18:42:19+03:30
- Changed files: `electron/src/main.js`, `electron/src/renderer/App.jsx`, `electron/src/styles/base.css`, `electron/src/styles/components.css`, `electron/src/styles/tokens.css`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Reworked Electron responsive behavior around a full-window shell and body breakpoint classes (`size-*`, `height-*`), removed web-style centered/max-width primary layouts, added per-page height-aware fill/scroll rules, and updated shell E2E expectations for compact and runtime layouts.
- Behavior impact: Added or refreshed 3 behavior rule(s) from user instructions.
<!-- fingerprint:56e1d014ac0c -->

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

## Last Updated
- 2026-04-27T15:13:39+03:30
