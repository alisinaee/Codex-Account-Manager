# Troubleshooting

## `Could not find 'codex' CLI`

Cause:

- `codex` executable is not discoverable in `PATH`.

Fixes:

- Install Codex CLI.
- Set environment override:

```bash
export CODEX_CLI_PATH="/absolute/path/to/codex"
```

- Or set project override in `config.json` under `codex.cli_path`.

## `add` Command Fails Before Login URL/Code

Most common on Windows when launcher path resolves to non-runnable app shims.

Fixes:

- set `CODEX_CLI_PATH` explicitly to working `codex.exe`
- configure `config.json` `codex.cli_path`
- retry with `--device-auth`

## UI Port Busy (`4673`)

Fix:

```bash
codex-account ui --port 7788
```

Or stop existing service:

```bash
codex-account ui-service stop
```

## UI Does Not Open Browser Automatically

Fix:

- open the printed URL manually
- or start with explicit host/port and `--no-open` to avoid launcher issues

## Profile Switch Permission Errors

Symptoms:

- cannot write to `~/.codex/auth.json`

Fixes:

- close running Codex/ChatGPT app windows
- ensure user-level write permissions on auth file
- retry switch operation

## Duplicate Profile / Duplicate Email Rejections

The app intentionally blocks:

- case-insensitive duplicate profile names
- multiple profiles with same normalized email

Fixes:

- use `rename` for naming conflicts
- switch to existing matching profile for duplicate email
- use `--force` only for same profile overwrite

## Linux Autostart Not Working

Behavior:

- prefers systemd user service when available
- otherwise falls back to XDG desktop autostart file

Checks:

```bash
codex-account ui-autostart status
```

## Advanced Commands Fail (`codex-auth` missing)

Fixes:

- install `codex-auth`, or
- install Node/NPM so wrapper can run `npx -y @loongphy/codex-auth`

## Known Cross-Platform Risk Areas

Detailed compatibility notes live in:

- `issues.md`
