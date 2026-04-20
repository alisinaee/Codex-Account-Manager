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

## Recent Changes (Last 20)
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
- 2026-04-20T21:04:40+03:30
