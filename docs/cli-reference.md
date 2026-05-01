# CLI Reference

Binary name: `codex-account`

Python entry point: `codex_account_manager.cli:main`

## Local Profile Commands

### `save <name> [--force]`
Save current active `~/.codex/auth.json` as a named profile.

### `add <name> [--timeout N] [--force] [--keep-temp-home] [--device-auth]`
Run isolated login flow and persist the resulting auth as profile.

### `list [--json]`
List saved profiles and metadata.

### `current [--json]`
Show active account hint/account ID from current auth.

### `switch <name> [--no-restart]`
Switch active auth file to selected profile, optionally restarting Codex app.

### `rename <old_name> <new_name> [--force]`
Rename profile directory and metadata.

### `remove <name>`
Delete one profile.

### `run <name> [-- <command...>]`
Run command with isolated profile `CODEX_HOME` (`profile-homes/<name>`).

If no command is passed, runs resolved `codex` CLI.

## Usage Commands

### `usage-local [--timeout N] [--watch] [--interval S] [--json]`
Fetch usage per local profile and optionally watch-refresh.

### `usage [local] [--timeout N] [--watch] [--interval S] [--json]`
Alias wrapper currently supporting `local` scope.

## Advanced Wrapper Commands (`codex-auth`)

These call `codex-auth` directly if available, otherwise `npx -y @loongphy/codex-auth`.

### `status [--json]`
Advanced status summary.

### `doctor [--json]`
Report local desktop runtime diagnostics for the packaged Electron shell.

JSON fields include:
- `python`: availability, version, path, and support status
- `core`: installed/version/command path details for `codex-account`
- `ui_service`: current local service host/port/token/health state
- `errors`: normalized actionable runtime failures

### `login [--device-auth]`
Advanced login wrapper.

### `list-adv [--debug]`
Advanced account list.

### `switch-adv [query]`
Advanced switch.

### `import [path] [--alias NAME] [--cpa] [--purge]`
Import auth material into advanced registry.

### `remove-adv [query] [--all]`
Remove advanced managed accounts.

### `config <auto|api> [enable|disable] [--5h N] [--weekly N]`
Configure advanced service mode and thresholds.

### `daemon (--watch | --once)`
Run advanced daemon in watch/once mode.

### `clean`
Run advanced cleanup.

### `auth -- <raw args...>`
Raw passthrough to `codex-auth`.

## Web UI and Service Commands

### `ui [--host H] [--port P] [--no-open] [--interval S] [--idle-timeout SEC] [--foreground]`
Start local web UI. Default detached background mode.

### `electron [--no-install]`
Run the optional Electron desktop shell from a source checkout.

### `ui-service <start|stop|restart|status> [--host H] [--port P] [--no-open] [--interval S] [--idle-timeout SEC]`
Manage background UI process.

### `ui-autostart <install|uninstall|status> [--host H] [--port P]`
Configure startup integration:
- macOS: LaunchAgent plist
- Windows: Scheduled Task
- Linux: systemd user service or XDG autostart fallback

## Auto-Switch and Notifications

### `autoswitch <status|enable|disable|stop|run-once>`
Manage local auto-switch behavior and trigger manual one-shot switch selection.

### `notify test`
Helper command that points to UI notification testing endpoint.

## Command Exit Behavior

- Returns non-zero on validation failures, missing dependencies, command failures, and failed switches.
- JSON modes typically return structured payloads for integration.

## Hidden/Internal UI Flags

Defined for internal service process orchestration:

- `ui --serve`
- `ui --token <value>`
- legacy hidden compatibility flags are intentionally rejected (`--dev`, `--build`, `--check`, `--no-install`).
