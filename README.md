<p align="center">
  <img src="docs/assets/codex_account_manager.svg" alt="Codex Account Manager" width="120" />
</p>

# Codex Account Manager

Codex Account Manager is a cross-platform local profile manager for Codex that works on macOS, Windows, and Linux. It gives you a polished local web panel for day-to-day account management, plus a CLI for scripting, automation, and advanced workflows.

The project is built around a fast local UI instead of a heavy desktop stack. You can manage saved profiles, monitor live usage, import and export migration archives, tune alarms, run auto-switch flows, review release notes, and update the app from the web panel while still keeping the CLI available for power use.

## Install

Recommended install for macOS, Windows, and Linux:

```bash
pipx install "git+https://github.com/alisinaee/Codex-Account-Manager.git@main"
codex-account --help
```

Requirements:

- Python `3.11+`
- Codex CLI installed and available as `codex` in your `PATH`
- Optional for advanced wrapper commands: `npx` for `@loongphy/codex-auth`

Developer or local-repo run:

```bash
chmod +x bin/codex-account
./bin/codex-account --help
```

Quick start:

```bash
codex-account save work
codex-account list --json
codex-account switch work
codex-account ui
```

If the browser does not open automatically, open `http://127.0.0.1:4673`.

Short troubleshooting notes:

- Port busy: `codex-account ui --port 7788`
- Browser not opening: `codex-account ui --no-open`
- Codex CLI path issues on Windows: set `CODEX_CLI_PATH` or use the project `config.json` override described in the app docs

If you need to remove the app later:

```bash
pipx uninstall codex-account-manager
```

## Update

CLI update path:

```bash
pipx upgrade codex-account-manager
```

The web panel also supports in-app update checks. When a newer release is available, the header shows an `Update available` badge and an `Update` button. The app opens the latest release notes first, then can run the pipx upgrade flow from the UI.

This means the same cross-platform install path also gives you a cross-platform update path on macOS, Windows, and Linux.

## Features

### Profile Management

- Save the current Codex auth as a named local profile
- Add accounts through a guided login flow with device-login and normal-login options
- List, switch, rename, and remove saved profiles
- Keep the current active account visible in both the CLI and the web panel

### Usage Monitoring

- Track per-profile `5H` and `Weekly` usage locally
- Refresh only the current account on a fast timer or sweep all saved accounts on a slower background timer
- Show live remaining percentages, reset timers, plan metadata, account IDs, and account health states
- Improve reliability by syncing healthy live auth back into the saved profile snapshot when appropriate

### Import / Export Migration

- Export all saved profiles or selected profiles into private `.camzip` migration archives
- Review imports before applying them
- Detect conflicts before overwrite/import actions are applied
- Support migration workflows between machines while keeping the process local-first

### Alarm Presets and Warnings

- Configure warning thresholds for both `5H` and `Weekly` usage
- Choose from 20 built-in alarm presets
- Preview alarm presets before saving one
- Run a `Test Alarm` flow directly from the web panel

### Auto-Switch Automation

- Enable or disable auto-switching rules locally
- Configure thresholds, delay, ranking mode, and candidate eligibility
- Preview and manually edit the switch chain
- Run one-off switch tests, rapid tests, and controlled auto-switch test flows

### Release Notes and App Updates

- Load release notes from GitHub with local fallback
- Show update availability inside the header
- Review release notes before starting an in-app upgrade flow

### Diagnostics and Control

- View a local debug/system output panel in the web UI
- Export debug logs
- Restart the local UI service from the panel
- Use wrapped advanced commands when you need deeper `codex-auth` operations

## Web Panel

The web panel is the main experience of Codex Account Manager. It runs locally on your machine, opens in your browser, and gives you a fast, modern control surface without requiring Electron, Tauri, Node, Rust, Cargo, or a heavy desktop runtime.

Start it with:

```bash
codex-account ui
```

Default local address:

- URL: `http://127.0.0.1:4673`
- Host: `127.0.0.1`
- Port: `4673`

What you can do in the panel:

- Add, switch, rename, and remove accounts
- Refresh the current account separately from all-account background refresh
- Manage profiles from the full-width `Profiles` section with `Import` and `Export`
- Export selected profiles with bulk selection and custom archive naming
- Review migration imports before applying them
- Configure warning thresholds, choose alarm presets, and run alarm previews
- Control auto-switch behavior, test it, and edit the switch chain
- Read in-app release notes and trigger app updates when a newer version exists
- Use the debug/system output panel for troubleshooting
- Learn the UI through built-in guide/help content and broad tooltip coverage

Why the panel matters:

- It keeps account management local and visual
- It is faster to operate than raw command sequences for daily use
- It exposes the project’s strongest features in one place
- It is available across macOS, Windows, and Linux with the same workflow

### Web UI Screenshot

> Note: account emails are blurred in this image.

![Codex Account Manager Web UI (emails blurred)](docs/assets/screenshots/web-ui-panel-v0.0.12-blurred-emails.png)

## CLI

The CLI is still a first-class part of the project, especially for scripting, terminal-first workflows, and advanced operations.

Most important commands:

```bash
codex-account --help
codex-account save work
codex-account add work --device-auth
codex-account list --json
codex-account current --json
codex-account switch work
codex-account ui
codex-account export-profiles -o ./profiles.camzip
codex-account import-profiles ./profiles.camzip
```

Useful command groups:

- Local profile workflows: `save`, `add`, `list`, `current`, `switch`, `rename`, `remove`, `run`
- Usage monitoring: `usage-local`, `usage`
- Web UI control: `ui`, `ui-service`, `ui-autostart`
- Advanced wrappers: `status`, `login`, `list-adv`, `switch-adv`, `import`, `remove-adv`, `config`, `daemon`, `clean`, `auth`

For the full CLI command surface, flags, and command behavior, use the dedicated reference:

- [CLI Reference](docs/cli-reference.md)

For local UI endpoints and runtime API behavior:

- [UI API](docs/ui-api.md)

## License

MIT License

Copyright (c) 2026 drnoobmaster

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
