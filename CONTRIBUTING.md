# Contributing

Thanks for contributing to Codex Account Manager.

## Before You Start

- Read [README.md](README.md) for product context and install guidance.
- Review [docs/development.md](docs/development.md) for the local developer workflow.
- Check [docs/architecture.md](docs/architecture.md) if you need a quick map of the current implementation.

## Local Setup

Requirements:

- Python `3.11+`
- Codex CLI installed and available as `codex` in your `PATH`

Install and smoke test locally:

```bash
python3 -m pip install -e .
./bin/codex-account --help
python3 -m pytest -q
```

## Pull Requests

- Keep changes focused and explain the user-facing reason in the PR description.
- Add or update tests when behavior changes.
- Update docs when commands, UI behavior, install flow, or release-facing behavior changes.
- If a change affects onboarding or trust, update `README.md`, `CHANGELOG.md`, or `SECURITY.md` as needed.

## Good Places To Start

- README polish and GitHub discoverability improvements
- cross-platform CLI and UI reliability fixes
- test coverage gaps in CLI flows and auto-switch behavior
- documentation improvements under `docs/`

## Reporting Bugs

Use the GitHub bug report template and include:

- operating system
- Python version
- Codex CLI availability/path details
- exact command or UI action
- observed output or screenshots when relevant
