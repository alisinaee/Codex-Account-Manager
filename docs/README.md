# Codex Account Manager Docs

This folder contains maintainable technical documentation for the `codex-account-manager` project.

## Docs Map

- `architecture.md`: system architecture, runtime model, and core workflows.
- `cli-reference.md`: complete command and flag reference from the Python CLI parser.
- `ui-api.md`: local web UI server behavior and HTTP API endpoints.
- `config-and-storage.md`: config schema, file locations, and runtime state.
- `development.md`: packaging, local development workflow, CI, and release checklist.
- `troubleshooting.md`: practical troubleshooting and platform-specific notes.
- `release-notes.md`: versioned user-visible changes and release highlights.
- `agent-rules.md`: AI-oriented project memory maintained with the `auto-docs` skill.

## Quick Orientation

- Entry point: `codex_account_manager/cli.py`
- Python package script: `codex-account = codex_account_manager.cli:main`
- Local launcher: `bin/codex-account`
- Main runtime domains:
  - Local profile management (`~/.codex/account-profiles`)
  - Usage inspection (`/backend-api/wham/usage`)
  - Advanced wrappers (`codex-auth` / `npx @loongphy/codex-auth`)
  - Embedded local web UI (`ThreadingHTTPServer`)
  - Background auto-switch evaluation loop

## Suggested Reading Order

1. `architecture.md`
2. `config-and-storage.md`
3. `cli-reference.md`
4. `ui-api.md`
5. `development.md`
6. `release-notes.md`
7. `troubleshooting.md`
