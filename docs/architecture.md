# Architecture

## Overview

`codex-account-manager` is a single-package Python CLI application that manages Codex authentication profiles and provides a local browser UI.

Core implementation lives in one module:

- `codex_account_manager/cli.py` (~7k lines)

This module implements:

- CLI argument parsing and command dispatch
- Profile/auth persistence
- usage API calls
- process control (restart/stop/start)
- local HTTP server and static UI renderer
- auto-switch scheduler and event timeline
- cross-platform autostart integration

## Runtime Components

1. `CLI Layer`
- `argparse` parser in `main()` defines all subcommands.
- Commands call `cmd_*` functions and return process exit codes.

2. `Profile Manager`
- Stores named profiles under `~/.codex/account-profiles/<name>/auth.json`.
- Stores metadata in `meta.json` (`saved_at`, `account_hint`, source info).
- Enforces duplicate-account protection using email extraction from JWT payload.

3. `Auth + Usage Reader`
- Reads active/local auth JSON files.
- Derives identity hints from `id_token`/`account_id`.
- Calls `https://chatgpt.com/backend-api/wham/usage` with bearer token and account ID.
- Normalizes usage windows to 5-hour and weekly metrics.

4. `Codex Process Controller`
- Detects running Codex app across macOS, Windows, Linux.
- Supports stop/start/restart with platform-specific fallbacks.
- Uses optional project-level overrides in `config.json` (`codex.cli_path`, `app_path_*`).

5. `Embedded UI Service`
- `ThreadingHTTPServer` serves:
  - `/` HTML (embedded CSS/JS)
  - `/sw.js` service worker
  - `/api/*` JSON endpoints
- Uses per-session token (`X-Codex-Token`) for POST protection.
- Supports detached background mode via `ui` and service management via `ui-service`.

6. `Optional Electron Desktop Shell`
- Lives under `electron/` and is not required for the main Python package.
- Starts or connects to the local `ui-service`, then renders a separate React/Vite desktop UI.
- Uses `codex-account doctor --json` as the machine-readable runtime contract for packaged desktop startup.
- Can bootstrap the Python core with an in-app installer flow when Python 3.11+ exists but `codex-account-manager` is not installed yet.
- Adds desktop-only behavior: sidebar navigation, tray/menu-bar status, current usage tooltip/menu text, and Electron-native notifications.
- Uses project-owned Electron icon assets and package metadata for desktop identity; raw Electron dev runs may still show the Electron Dock bundle name until packaged.
- Keeps account, profile, usage, and switching logic in the Python backend.

7. `Auto-Switch Engine`
- Background thread periodically evaluates usage thresholds.
- Produces timeline events (warning/cancel/switch/error/rapid-test).
- Applies configurable delay, cooldown, ranking, and eligibility filters.
- Executes switches using existing `cmd_switch()` flow.

## High-Level Flow

### Save Current Account as Profile

1. Read `~/.codex/auth.json`
2. Validate target profile name and duplicate email constraints
3. Copy to `~/.codex/account-profiles/<name>/auth.json`
4. Write metadata

### Add New Account (Isolated Login)

1. Create temporary isolated `CODEX_HOME`
2. Run `codex login` (or fallback runner)
3. Wait for login completion and temp `auth.json`
4. Persist as named profile
5. Cleanup temp home unless requested otherwise

### Switch Profile

1. Validate profile exists
2. Optionally detect and stop running Codex app
3. Backup current active auth to `~/.codex/account-backups/auth-<timestamp>.json`
4. Copy selected profile auth into active `~/.codex/auth.json`
5. Optionally restart Codex app

### UI Service Startup

1. Resolve host/port and check if service already healthy
2. Generate token and start server (foreground or detached child process)
3. Start background auto-switch thread
4. Expose API endpoints for local and advanced operations

## Design Characteristics

- Single-file core for portability and low dependency footprint.
- Stdlib-first implementation (no heavy framework).
- JSON-based state for transparency/debuggability.
- Best-effort cross-platform behavior with platform-specific fallbacks.
- Local-only UI defaults (`127.0.0.1`) and warning for all-interface bind.
- Optional Electron shell uses Node/Electron/React only for desktop integration; the browser web panel remains stable and independently available.

## Current Structural Tradeoffs

- Large monolithic `cli.py` increases cognitive load.
- UI HTML/CSS/JS embedded as long Python string makes UI changes harder.
- CLI, service, storage, and API all coupled in one module.

A natural future refactor is splitting into modules like:

- `profiles.py`
- `usage.py`
- `process_control.py`
- `ui_server.py`
- `autoswitch.py`
- `commands.py`
