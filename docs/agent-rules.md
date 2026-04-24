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

## Recent Changes (Last 20)
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

### 2026-04-20T21:04:40+03:30
- Changed files: `codex_account_manager/autoswitch_sim.py`, `README.md`, `release.zip`
- Summary: Added real-mode candidate exclusion diagnostics and prepare-test flag to auto-enable profile eligibility for 30-second cycle switching tests; rebuilt release.zip.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:089b981a0b60 -->

### 2026-04-20T20:49:01+03:30
- Changed files: `codex_account_manager/autoswitch_sim.py`, `README.md`
- Summary: Added colorful real-cycle auto-switch tester mode with 30s cadence, chain/candidate diagnostics, and optional real app restart switching.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:3b500d15e57b -->

### 2026-04-20T20:37:51+03:30
- Changed files: `README.md`, `codex_account_manager/cli.py`, `tests/test_cli_core.py`, `bin/cam-autoswitch-test`, `codex_account_manager/autoswitch_sim.py`, `tests/test_autoswitch_sim.py`
- Summary: Fixed inclusive auto-switch threshold comparison and added one-command terminal auto-switch simulation tool with live tick diagnostics and tests.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:67fe0a9096d0 -->

### 2026-04-20T17:50:14+03:30
- Changed files: `docs/README.md`, `docs/architecture.md`, `docs/cli-reference.md`, `docs/ui-api.md`, `docs/config-and-storage.md`, `docs/development.md`, `docs/troubleshooting.md`
- Summary: Added a full technical documentation suite under docs covering architecture, CLI, API, config/state, development workflow, and troubleshooting.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:2fc5b9367fb4 -->

## Last Updated
- 2026-04-24T08:20:50+03:30
