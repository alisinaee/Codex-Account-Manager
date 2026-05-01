# AI Agent Rules & Change Memory

## Project Snapshot

- Python package source lives in `codex_account_manager/` with CLI and local web service behavior centered in `cli.py`.
- Browser web UI assets live in `codex_account_manager/web/`.
- Electron desktop app lives in `electron/` and uses Vite, Electron Builder, and Node test suites.
- Release/version metadata is duplicated across `pyproject.toml`, `config.json`, Electron package files, runtime constants, and user-facing docs.
- GitHub Releases are the primary binary distribution surface for desktop installers.
- Private owner-specific AI workflow files can be mounted through `.private/ai` and are not required for public build or test flows.

## Behavior Rules

- Use `rtk` as the prefix for shell commands in this repository.
- Use jCodeMunch MCP tools for code exploration when they can answer the question.
- Preserve private owner-specific workflow files; do not require them for public repository build, test, or usage.
- Before release completion claims, run fresh verification and report the actual command results.

## Recent Changes (Last 20)

- 2026-05-01: Merged the Electron desktop branch into `main` and aligned release metadata for `v0.0.20`.
- 2026-05-01: Cleared stale pending desktop update state when app and core already match, preventing false topbar update warnings.
- 2026-05-01: Fixed Electron update status so stale older release feeds cannot downgrade the displayed latest version or Python core sync target.
- 2026-05-01: Restored AI-facing project memory after the Electron merge removed the previous `docs/agent-rules.md`.

## Last Updated

2026-05-01
