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
### 2026-04-30T16:08:33+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`, `electron/tests/sidebar-version.test.js`
- Summary: Moved the sidebar version text into the About nav item, removed the 'App version' label, and reduced the font size.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:414b4cf5ac0e -->

### 2026-04-30T15:17:09+03:30
- Changed files: `pyproject.toml`, `config.json`, `uv.lock`, `electron/package.json`, `electron/package-lock.json`, `codex_account_manager/cli.py`, `electron/src/runtime.js`, `electron/src/main.js`, +5 more
- Summary: Bumped Python core, web UI, and Electron version sources to 0.0.15 and added a small app-version label to the Electron sidebar account section.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:b5f2f5297da0 -->

### 2026-04-30T15:06:32+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/tests/profiles-toolbar.test.js`
- Summary: Removed the temporary 'test snak' toolbar button after using it to preview the bottom error banner behavior.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:401509946c53 -->

### 2026-04-30T15:02:45+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/tests/profiles-toolbar.test.js`
- Summary: Changed the temporary 'test snak' toolbar button to trigger the bottom error banner preview instead of the toast system.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:e24d76629eff -->

### 2026-04-30T12:42:57+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/tests/profiles-toolbar.test.js`
- Summary: Added a temporary 'test snak' button in the Profiles toolbar that triggers a warning toast preview.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:ae13460831cb -->

### 2026-04-30T12:27:31+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/error-banner.mjs`, `electron/src/styles/components.css`, `electron/tests/error-banner.test.js`, `electron/tests/profile-column-resize-source.test.js`
- Summary: Added a timed bottom error banner with a 30-second countdown and dialog-style manual close button.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:93844564a4b2 -->

### 2026-04-30T11:46:37+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`, `electron/tests/profile-column-resize-source.test.js`
- Summary: Made the column width controls row span the full columns dialog width and fixed width reset persistence by clearing saved overrides with null.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:0d1eff42f8bd -->

### 2026-04-30T11:43:22+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`, `electron/tests/profile-column-resize-source.test.js`
- Summary: Added a width-only reset button beside the profile table column resize toggle in the columns dialog.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:e9d84ded4f28 -->

### 2026-04-30T11:27:13+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/components/DataTable.jsx`, `electron/src/renderer/table-layout.mjs`, `electron/src/styles/components.css`, `electron/tests/table-layout.test.js`, `electron/tests/profile-column-resize-source.test.js`, `electron/tests/table-column-resize.test.js`
- Summary: Added profile table column width resize mode with persisted overrides, header drag handles, reset-to-default behavior, and related tests.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:f106bbfd2e0c -->

### 2026-04-30T10:38:25+03:30
- Changed files: `electron/src/main.js`, `electron/src/desktop-state-cache.js`, `electron/tests/desktop-state-cache.test.js`
- Summary: Invalidate cached Electron desktop state after saved-profile mutations so loadAll fetches fresh list/current data after remove-all/remove/rename/import/save/add.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:3caf4ee91b6b -->

### 2026-04-30T10:21:39+03:30
- Changed files: `electron/src/main.js`, `electron/src/preload.js`, `electron/src/renderer/App.jsx`, `electron/src/export-download.js`, `electron/tests/export-download.test.js`
- Summary: Replaced Electron account export blob-download handoff with a native desktop save-dialog flow wired through IPC, because backend archive creation was succeeding but renderer downloads were not producing user-visible files.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:a982ca794821 -->

### 2026-04-30T09:49:20+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/download-utils.mjs`, `electron/tests/download-utils.test.js`
- Summary: Fixed Electron export delivery by adding a tested download helper, falling back to desktop.getBackendState when renderer backend state is stale, and attaching download anchors to the DOM before clicking.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:ffd726204da1 -->

### 2026-04-30T09:40:32+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Hardened current-profile auth snapshot sync to require canonical/principal identity, blocked email-only live auth write-back, and added archive duplicate-email detection with regression tests.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:11e985d2d141 -->

### 2026-04-30T09:40:27+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`, `electron/tests/profiles-toolbar.test.js`
- Summary: Removed the profiles toolbar TA test-animation button and its unused renderer wiring, and added a focused regression test that guards against the TA control returning.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:408d9fff091a -->

### 2026-04-30T07:57:26+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `electron/src/renderer/usage-merge.mjs`, `electron/tests/usage-merge.test.js`
- Summary: Preserve last good usage rows on both the Python core cache/store path and the Electron renderer merge path so transient post-switch all-account refresh errors no longer collapse the table to unknown values.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:c8fd405be036 -->

### 2026-04-30T07:33:48+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Preserve last good per-profile usage rows across transient post-switch all-accounts refresh failures by merging degraded backend payloads with the previous snapshot instead of overwriting cache with null/error rows.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:1181ac9a8734 -->

### 2026-04-30T07:22:49+03:30
- Changed files: `electron/src/styles/tokens.css`, `electron/src/styles/components.css`, `electron/tests/theme.test.js`
- Summary: Slowed Electron loading spinners by introducing a shared spinner duration token and using it for button and remain-value circular loaders, with CSS regression coverage.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:1eeab2d26df5 -->

### 2026-04-30T07:17:11+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/switch-state.mjs`, `electron/tests/switch-state.test.js`
- Summary: Use the TA preview ordering immediately for real profile switches in Electron, share the preview helper between TA and live switch flows, and cover it with switch-state tests.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:1c1d9610d254 -->

### 2026-04-29T23:00:54+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/components/DataTable.jsx`, `electron/src/renderer/switch-state.mjs`, `electron/src/styles/components.css`, `electron/tests/switch-state.test.js`
- Summary: Applied the 4-second deck-style FLIP row motion to real Electron profile switches and the `TA` preview, preserving displayed deck order, moving cell-level row separators, and clearing the custom order when the user changes table sort.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:cb784cfeb1d4 -->

### 2026-04-29T19:37:00+03:30
- Changed files: `electron/scripts/dev.js`, `electron/src/runtime.js`, `electron/tests/dev-script.test.js`, `electron/tests/runtime.test.js`
- Summary: Fixed Electron dev runtime resolution by generating a Python-backed repo core wrapper and preserving the successful runtime candidate over stale `doctor` command path hints.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:61f4282a0e4a -->

## Last Updated
- 2026-04-30T16:08:33+03:30
