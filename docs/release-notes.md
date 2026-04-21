# Release Notes

This file tracks user-visible changes by version.

## Unreleased

No unreleased entries yet.

## 0.0.8

### UI and Workflow Improvements

- Improved light-theme toggle switch colors for better visibility/contrast.
- Replaced the header Debug button icon with a clearer terminal-style glyph.
- Increased the header Settings button size for better click/tap usability.
- Increased inner size of Debug/Settings header icons while keeping equal button container sizes.
- Improved manual `Refresh` button responsiveness so a single click triggers immediate visible refresh state.
- Updated `Kill All` confirmation modal to use a red confirm action for clearer destructive intent.
- Scoped `Kill All` shutdown to Codex Account Manager processes only (no Codex desktop/app shutdown side effects).
- Reworked switch-row feedback so the entire row blinks slowly while a switch is in progress.
- Added a post-switch drag/drop-style animation that moves the newly selected current row to the top after refresh completes.

### Accounts and Metadata

- Added `plan_type` and `is_paid` fields to `usage-local --json` profile rows.
- Added `Plan` and `Paid` columns in the Accounts table.
- Kept `Plan` and `Paid` hidden by default in column preferences (users can enable from `Columns`).

### Auto-Switch and Selection Fixes

- Fixed auto-arrange chain ranking so exhausted accounts are pushed to the end instead of appearing as next preferred switch targets.
- Fixed candidate selection to skip accounts with `0%` remaining quota when auto-switch chooses the next account.
- Fixed balanced-mode chain generation so stale manual-chain ordering no longer leaks into auto-arranged previews.
- Fixed red switch-state rendering so accounts with `0%` on either `5H` or `Weekly` show the blocked visual state consistently.

### macOS Switch Reliability

- Restored the macOS switch flow to close and relaunch Codex instead of using the close-only path.
- Improved macOS app relaunch reliability by preserving the detected app target and retrying launch when the app is still shutting down.

### Guide and Help

- Rewrote in-app `Guide & Help` content to reflect current visible panel controls and workflows.
- Added in-app release-notes sync from GitHub Releases with local fallback to this file.
- Added manual in-guide release-note refresh and status states (`Synced`, `Fallback`, `Failed`).

### Stability and Platform Improvements

- Improved Windows-focused reliability in current iteration (login/service and runtime behavior hardening).
- Continued general UI reliability and diagnostics improvements in active development.

## 0.0.7

- Packaged baseline cross-platform CLI + local web UI release.
- Core profile management (`save`, `add`, `list`, `switch`, `remove`).
- Live usage monitoring and local UI service controls.
- Auto-switch controls and local event/diagnostics surfaces.
