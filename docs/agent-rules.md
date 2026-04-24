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

## Recent Changes (Last 20)
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

### 2026-04-23T20:28:00+03:30
- Changed files: `codex_account_manager/cli.py`, `pyproject.toml`, `README.md`, `tests/test_cli_core.py`
- Summary: Added the tracked project SVG as the packaged web-panel/browser icon, showed it in the panel header, and reused it in the README project branding.
- Behavior impact: Recorded the current branding asset usage across README and web UI surfaces.
<!-- fingerprint:7d4d2bb2db09 -->

### 2026-04-23T18:48:00+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `config.json`, `pyproject.toml`, `uv.lock`, `docs/release-notes.md`, `release.zip`
- Summary: Prepared the 0.0.12 release by fixing the update dialog and post-update reload behavior, bumping package version metadata, updating release notes, rebuilding release.zip, and aligning the update-version test fixture.
- Behavior impact: Recorded the current release packaging and update-flow behavior for future AI context.
<!-- fingerprint:2d4a06f68555 -->

### 2026-04-23T17:33:00+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Fixed the in-app update dialog so it can be closed while an update is running, added an update progress bar with stage text, and surfaced short in-dialog updater output summaries.
- Behavior impact: Recorded the current update-dialog UX contract for future AI context.
<!-- fingerprint:4e68cecb7cf1 -->

### 2026-04-23T15:40:03+03:30
- Changed files: `README.md`
- Summary: Rewrote README to be cross-platform and web-UI-first, with top-level Install, Update, Features, Web Panel, and CLI sections and lighter CLI duplication.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:1337ef7a9976 -->

### 2026-04-23T14:10:11+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `config.json`, `pyproject.toml`, `uv.lock`, `docs/release-notes.md`, `release.zip`
- Summary: Prepared the 0.0.11 release by bumping version metadata, refreshing in-app help/tooltips for Profiles/Alarm/Update UI, updating release notes, rebuilding release.zip, and aligning update tests with the new current version.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:65563b7461eb -->

### 2026-04-23T13:16:06+03:30
- Changed files: `codex_account_manager/cli.py`
- Summary: Fixed a boot-breaking inline JS string escape in the in-app update flow that prevented the UI, including the accounts table, from loading after restart.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:7ac48d1a8bc9 -->

### 2026-04-23T13:01:55+03:30
- Changed files: `codex_account_manager/cli.py`
- Summary: Render loading placeholder rows immediately after /api/list returns so the accounts table does not stay blank while slow usage refresh completes after restart.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:5eefad97fcd7 -->

### 2026-04-23T12:43:42+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Added in-app update availability checks, release-notes review modal, header update badge/button, and pipx-based update endpoint with tests.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:f6561c745c29 -->

### 2026-04-23T11:32:07+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `docs/agent-rules.md`
- Summary: Added a selectable alarm preset system with 20 built-in sound patterns, a modal picker with per-item preview, inline test alarm controls, and persisted notifications.alarm_preset config fallback coverage.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:f66db384f231 -->

### 2026-04-23T11:13:33+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `docs/agent-rules.md`
- Summary: Redesigned the settings migration UI into a full-width Profiles panel, replaced inline export mode controls with a bulk-select export modal, and added custom export filename support to the local export prepare API with tests.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:e494abd16792 -->

### 2026-04-23T10:41:02+03:30
- Changed files: `codex_account_manager/cli.py`, `docs/agent-rules.md`
- Summary: Fixed the new export flow by removing invalid embedded JS strings, switching browser export to blob downloads, and keeping export sessions available during the TTL instead of deleting the archive immediately on first GET.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:85df301f51b0 -->

### 2026-04-23T08:56:39+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `docs/agent-rules.md`
- Summary: Added local camzip profile export/import commands, UI settings flows with warnings and conflict review, archive download/upload API endpoints, and automated tests for archive analysis/apply behavior.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:29dee45f42f5 -->

### 2026-04-23T08:56:05+03:30
- Changed files: `codex_account_manager/cli.py`, `tests/test_cli_core.py`
- Summary: Added local profile export/import migration support with camzip archives, browser UI warning/review flows, and tests for archive analysis and apply behavior.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:07f69298a16e -->

### 2026-04-22T23:06:00+03:30
- Changed files: `codex_account_manager/cli.py`, `config.json`, `pyproject.toml`, `uv.lock`, `docs/release-notes.md`, `docs/agent-rules.md`, `release.zip`
- Summary: Prepared v0.0.10 release content by updating the in-app guide/help copy, bumping version metadata, documenting the new refresh/auth workflow, and rebuilding release.zip.
- Behavior impact: Recorded release workflow and current UI/auth behavior for future AI context.
<!-- fingerprint:82c73c7fd4ea -->

## Last Updated
- 2026-04-24T11:38:07+03:30
