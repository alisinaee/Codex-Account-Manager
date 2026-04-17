# Cross-Platform Compatibility Issues (macOS / Windows / Linux)

This document lists the current blockers found in `Codex account manager` for true cross-platform behavior and the recommended solutions.

## 1) `switch` can fail on Windows (`pgrep` hard dependency)

- **Problem**: `cmd_switch()` calls `detect_running_app_name()` which calls `_proc_running()`. `_proc_running()` runs `pgrep -f ...`, which is typically unavailable on Windows.
- **Where**: `bin/codex-account` (`_proc_running`, `detect_running_app_name`, `cmd_switch`)
- **Impact**: `codex-account switch <name>` can error before profile switch completes on Windows.

### Solution

- Make process detection OS-aware:
  - On **Windows**: use `tasklist` or `wmic`/PowerShell query.
  - On **macOS/Linux**: keep `pgrep` path but guard with `shutil.which("pgrep")`.
- Add safe fallback:
  - If process detection is unavailable, continue switching auth file and skip restart detection logic.
- Wrap all process-detection calls in `try/except` so switching profiles never fails due to optional restart behavior.

---

## 2) Restart logic is macOS-only (`osascript`, `open -a`, mac app paths)

- **Problem**:
  - Stop path uses `osascript` + `pkill` and app bundle process patterns.
  - Start path uses `open -a <AppName>`.
  - App candidates are hardcoded macOS app bundle paths under `/Applications/...`.
- **Where**: `APP_CANDIDATES`, `stop_codex()`, `start_codex()` in `bin/codex-account`
- **Impact**: Restart flow is not implemented for Windows/Linux; may fail or do nothing.

### Solution

- Split restart into platform implementations:
  - **macOS**: keep current behavior.
  - **Windows**: stop with `taskkill` on executable/process name, start with `start`/direct executable path.
  - **Linux**: stop with `pkill`/`killall`, start with discovered executable.
- Make restart **best effort**:
  - Profile switching must succeed even if app restart is unavailable.
  - Emit warning instead of hard failure when restart is unsupported.
- Replace hardcoded app paths with configurable values:
  - Add config keys (for example in `config.json`): `codex.app_path_macos`, `codex.app_path_windows`, `codex.app_path_linux`.

---

## 3) `resolve_codex_cli()` fallback is macOS-specific

- **Problem**: fallback only checks `/Applications/Codex.app/Contents/Resources/codex`.
- **Where**: `resolve_codex_cli()` in `bin/codex-account`
- **Impact**: Windows/Linux users without `codex` on PATH get a macOS-specific error path.

### Solution

- Keep `shutil.which("codex")` as primary.
- Add platform-specific fallback candidates:
  - **Windows**: common install paths and `codex.exe` candidates.
  - **Linux**: common local/bin paths.
- Add config override:
  - If `CODEX_CLI_PATH` env var is set, use it first.
  - Optionally allow `config.json` key for explicit CLI path.
- Improve error message to include platform-specific install instructions.

---

## 4) Linux autostart assumes `systemd --user` is available

- **Problem**: Linux branch directly writes a user service and executes `systemctl --user ...`.
- **Where**: `cmd_ui_autostart()` Linux branch in `bin/codex-account`
- **Impact**: Fails on Linux environments without systemd user session (WSL, OpenRC, runit, minimal containers, some desktops).

### Solution

- Detect init capability before install/uninstall/status:
  - Check `shutil.which("systemctl")` and whether user systemd is active.
- If systemd is unavailable, provide fallback autostart methods:
  - XDG autostart (`~/.config/autostart/*.desktop`) for desktop sessions.
  - Optional shell profile hook for terminal-only users.
- Update status output to show backend type (`systemd`, `xdg`, `none`).

---

## 5) `ui-service stop` fallback uses `lsof` without availability check

- **Problem**: non-Windows stop path tries `lsof -ti tcp:<port>` when PID tracking fails.
- **Where**: `cmd_ui_service(... action="stop")` in `bin/codex-account`
- **Impact**: Stop flow is weaker on systems without `lsof`.

### Solution

- Guard with `shutil.which("lsof")`.
- Add fallback alternatives:
  - Linux/macOS: try `ss -lptn` or `netstat` parsing if `lsof` missing.
- Keep PID-file-based stop as primary path and ensure PID file reliability.

---

## 6) Distribution/entrypoint is unclear for Windows

- **Problem**: repository currently has a Unix-style script entry (`bin/codex-account` with shebang) and no explicit Windows packaging/launcher metadata.
- **Where**: project layout
- **Impact**: Even if code is logically cross-platform, installation and command invocation on Windows are not guaranteed to be smooth.

### Solution

- Package as an installable Python CLI with console entry points:
  - Add `pyproject.toml` and script entry point (`codex-account = <module>:main`).
  - This generates native launchers on Windows (`codex-account.exe`) and scripts on macOS/Linux.
- Optionally publish as `pipx`-friendly package for all platforms.
- Add install/run docs for each OS in `README.md`.

---

## 7) POSIX permission calls (`os.chmod(..., 0o600)`) are not meaningful on Windows

- **Problem**: several auth files are chmod’ed to `0o600`; on Windows this is not equivalent to UNIX permissions.
- **Where**: `prepare_profile_home()`, `cmd_switch()`, backup writes in `bin/codex-account`
- **Impact**: Security expectation may be inconsistent across OSes.

### Solution

- Keep chmod on POSIX only (`if os.name == "posix": ...`).
- On Windows, either:
  - skip with explicit note, or
  - implement optional ACL hardening using `icacls` (best-effort).
- Update docs to explain permission model differences.

---

## Recommended Implementation Order

1. Fix Windows `pgrep` crash path in `switch` (highest user-facing risk).
2. Make restart behavior OS-aware + best-effort (do not block switching).
3. Improve `resolve_codex_cli()` with cross-platform discovery and config override.
4. Harden `ui-service stop` fallbacks (`lsof` checks + alternatives).
5. Improve Linux autostart with systemd detection + XDG fallback.
6. Add Python packaging/entrypoints for clean Windows/macOS/Linux install.
7. Normalize permission handling across OSes.

