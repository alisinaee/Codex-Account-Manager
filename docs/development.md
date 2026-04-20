# Development

## Requirements

- Python `3.11+`
- `codex` CLI available in `PATH` for local profile login/switch flows
- Optional for advanced wrappers: `npx` or globally installed `codex-auth`

## Local Run

From repository root:

```bash
python -m codex_account_manager --help
./bin/codex-account --help
```

Or install package in environment:

```bash
python -m pip install -e .
codex-account --help
```

## Packaging

Packaging is defined in `pyproject.toml` using `setuptools`:

- Package name: `codex-account-manager`
- Version: `0.0.7`
- Console script: `codex-account`
- Supported Python: `>=3.11`

## CI

Current GitHub workflow:

- `.github/workflows/windows-ci.yml`

It validates:

1. install on Windows runner
2. module entrypoint help output
3. console script help output
4. mocked `codex login` path using temporary `codex.cmd`

## Project Structure

- `codex_account_manager/cli.py`: all runtime logic
- `codex_account_manager/__main__.py`: module entrypoint
- `bin/codex-account`: local launcher wrapper
- `README.md`: user-facing install and command overview
- `issues.md`: known platform and compatibility notes
- `docs/`: technical docs

## Recommended Dev Workflow

1. Update code in `codex_account_manager/cli.py`.
2. Run command-level smoke checks:

```bash
python -m codex_account_manager --help
python -m codex_account_manager list --json
python -m codex_account_manager ui-service status
```

3. Validate key local flows manually:
- profile save/switch/list
- usage-local
- ui open + api health
- ui-service start/stop

4. Keep docs updated in `docs/` with behavior changes.
5. Update `docs/release-notes.md` for `Unreleased` and versioned entries before shipping.

## Refactor Candidates

The codebase is functional but monolithic. Highest-impact maintainability improvements:

- split command handlers by concern
- move embedded UI assets to separate files
- add unit tests around config sanitization, usage parsing, and candidate selection
- formalize API contracts with schema fixtures
