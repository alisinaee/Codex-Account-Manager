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

### 2026-04-29T19:25:00+03:30
- Changed files: `electron/src/backend.js`, `electron/src/main.js`, `electron/tests/backend.test.js`
- Summary: Fixed Electron dev mode reusing stale global UI services by force-restarting the backend once with the repo `bin/codex-account` before dev switch requests are sent.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:a92ef2c9156d -->

### 2026-04-29T18:51:38+03:30
- Changed files: `electron/scripts/dev.js`, `electron/src/main.js`, `electron/tests/dev-script.test.js`
- Summary: Added dev-only startup diagnostics so `npm run dev` now prints Electron launch context, single-instance lock results, lifecycle events, and child exit details directly to the terminal.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:834e46303f4f -->

### 2026-04-29T18:42:21+03:30
- Changed files: `electron/src/icons.js`, `electron/src/main.js`, `electron/scripts/dev.js`, `electron/tests/dev-script.test.js`, `electron/tests/identity.test.js`
- Summary: Isolated the Electron dev shell under a distinct app name, bundle id, and user-data path so macOS and Electron no longer treat it as the packaged Codex Account Manager instance during launch or restart flows.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:db7f25d21fb8 -->

### 2026-04-29T18:06:13+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `electron/scripts/dev.js`, `electron/tests/dev-script.test.js`
- Summary: Fixed macOS Codex restart targeting to use strict app bundle paths and made Electron dev sessions pin the repo checkout's Python core instead of a legacy installed codex-account binary.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:d1eef4f4a5cd -->

### 2026-04-29T17:58:27+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Fixed macOS Codex restart targeting to use strict app bundle paths instead of fuzzy app names, preventing Electron dev Account Manager sessions from being quit or relaunched during profile switches.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:35dafa443eee -->

### 2026-04-29T17:39:21+03:30
- Changed files: `electron/src/api-client.js`, `electron/src/renderer/App.jsx`, `electron/src/renderer/parity.mjs`, `electron/tests/api-client.test.js`, `electron/tests/parity.test.js`
- Summary: Fixed Electron macOS switches to allow backend Codex restart again and preserved previous usage rows when the immediate forced post-switch usage refresh fails transiently.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:4655a2cb0c78 -->

### 2026-04-29T17:05:00+03:30
- Changed files: `electron/src/tray.js`, `electron/src/main.js`, `electron/tests/desktop.test.js`
- Summary: Reworked the tray menu so macOS 14+ uses native non-action header rows for usage status, replaced start/stop service tray actions with `Web Panel` and a full `Restart Service` relaunch path, and kept an older-macOS submenu fallback.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:b8dd2734ab11 -->

### 2026-04-29T16:50:04+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/parity.mjs`, `electron/tests/parity.test.js`
- Summary: Map Electron usage refresh timeouts to friendly footer copy instead of showing raw desktop IPC timeout errors, and recognize request timeout after messages as timeout states.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:900a24bc18bc -->

### 2026-04-29T16:50:00+03:30
- Changed files: `electron/src/tray.js`, `electron/src/api-client.js`, `electron/src/renderer/App.jsx`, `electron/tests/desktop.test.js`, `electron/tests/api-client.test.js`
- Summary: Fixed macOS desktop switches to stay on the no-restart backend path, made tray usage rows informational instead of actionable, and stabilized macOS tray-title percentage coloring with standard ANSI output plus monospaced digits.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:8283a6c25d0b -->

## Last Updated
- 2026-04-30T10:38:25+03:30
