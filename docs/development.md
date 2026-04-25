# Development

## Requirements

- Python `3.11+`
- `codex` CLI available in `PATH` for local profile login/switch flows
- Node.js/npm for the optional Electron desktop shell
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

## Electron Desktop Shell

The Electron app is optional. It keeps the Python backend and stable browser web panel intact, starts or connects to `codex-account ui-service`, and renders a separate React/Vite desktop UI with tray/status and Electron notification behavior.

From repository root:

```bash
codex-account electron
```

Raw npm fallback:

```bash
cd electron
npm install
npm run dev
```

Electron test commands:

```bash
cd electron
npm test
npm run test:e2e
npm run smoke:prod
npm run dist:dir
```

The development shell still assumes `codex-account` is available in `PATH`. The packaged shell now checks runtime health through `codex-account doctor --json`, starts or reconnects to `codex-account ui-service`, and shows a setup/bootstrap screen when Python or the Python core is missing. If the renderer dependencies are missing, `codex-account electron` runs `npm install` before starting the dev shell.

The development shell uses project-owned PNG/ICNS/SVG assets for the window, tray, notification, Dock icon API, and package metadata. macOS can still display `Electron` in the Dock when running the raw Electron development binary because the visible Dock name comes from the launched Electron app bundle. A packaged `.app` is required for the final launcher name and icon.

## Packaging

Packaging is defined in `pyproject.toml` using `setuptools`:

- Package name: `codex-account-manager`
- Version: `0.0.12`
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
- `electron/`: optional Electron desktop shell and tests
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

For Electron changes, also run:

```bash
cd electron
npm test
npm run test:e2e
npm run smoke:prod
```

## Refactor Candidates

The codebase is functional but monolithic. Highest-impact maintainability improvements:

- split command handlers by concern
- move embedded UI assets to separate files
- add unit tests around config sanitization, usage parsing, and candidate selection
- formalize API contracts with schema fixtures
