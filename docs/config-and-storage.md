# Config And Storage

## Base Paths

Defaults resolve from `CODEX_HOME` (or `~/.codex` if unset):

- Active auth: `~/.codex/auth.json`
- Profiles: `~/.codex/account-profiles/`
- Profile homes: `~/.codex/profile-homes/`
- Auth backups: `~/.codex/account-backups/`
- App runtime dir: `~/.codex/account-manager/`
- Runtime config: `~/.codex/account-manager/config.json`
- Runtime log: `~/.codex/account-manager/ui.log`
- UI service state: `~/.codex/ui-service/service.json`

Project-level config:

- `<repo>/config.json`

## Profile Files

Each profile has:

- `auth.json`: saved auth snapshot
- `meta.json`:

```json
{
  "name": "work",
  "saved_at": "2026-04-20T12:00:00",
  "account_hint": "user@example.com | id:...",
  "source_auth": "/path/to/source/auth.json"
}
```

## Runtime Config Schema (`CAM_CONFIG_FILE`)

Top-level sections:

- `ui`
  - `theme`: `dark|light|auto`
  - `advanced_mode`: bool
  - `auto_refresh`: bool
  - `refresh_interval_sec`: int (1..3600)
  - `debug_mode`: bool

- `notifications`
  - `enabled`: bool
  - `scope`: `any|5h|weekly`
  - `thresholds.h5_warn_pct`: int (0..100)
  - `thresholds.weekly_warn_pct`: int (0..100)

- `auto_switch`
  - `enabled`: bool
  - `trigger_mode`: `any|all`
  - `delay_sec`: int (0..3600)
  - `thresholds.h5_switch_pct`: int (0..100)
  - `thresholds.weekly_switch_pct`: int (0..100)
  - `candidate_policy`: fixed to `only_selected`
  - `same_principal_policy`: `skip|allow`
  - `cooldown_sec`: int (0..3600)
  - `ranking_mode`: `balanced|max_5h|max_weekly|manual`
  - `weights`: normalized float weights
  - `manual_chain`: unique list of profile names

- `profiles`
  - `eligibility`: `{ "profileName": true|false }`

Normalization is performed by `sanitize_cam_config()` on load/save.

## Project Config (`config.json`)

Used for lightweight app metadata and optional path overrides.

Supported keys used by runtime:

- `app.version`
- `codex.cli_path`
- `codex.app_path_macos`
- `codex.app_path_windows`
- `codex.app_path_linux`

## Permissions Behavior

- POSIX: files are chmodded to `0600` where appropriate.
- Windows: best-effort ACL hardening via `icacls` for user write access.

## Logging

UI and runtime events are appended to `ui.log` as newline-delimited JSON with fields:

- `ts`
- `level`
- `message`
- `details`
