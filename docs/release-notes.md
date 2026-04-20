# Release Notes

This file tracks user-visible changes by version.

## Unreleased

### Accounts and Plan Metadata

- Added `plan_type` and `is_paid` fields to `usage-local --json` profile rows.
- Added `Plan` and `Paid` columns in the Accounts table.
- Kept `Plan` and `Paid` hidden by default in column preferences (users can enable from `Columns`).

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
