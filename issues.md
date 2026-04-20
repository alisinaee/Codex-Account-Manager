# Compatibility Issues (macOS / Linux)

This document lists the remaining blockers found in `Codex account manager` and the recommended solutions.

## 1) Linux autostart assumes `systemd --user` is available

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

## 2) `ui-service stop` fallback uses `lsof` without availability check

- **Problem**: non-Windows stop path tries `lsof -ti tcp:<port>` when PID tracking fails.
- **Where**: `cmd_ui_service(... action="stop")` in `bin/codex-account`
- **Impact**: Stop flow is weaker on systems without `lsof`.

### Solution

- Guard with `shutil.which("lsof")`.
- Add fallback alternatives:
  - Linux/macOS: try `ss -lptn` or `netstat` parsing if `lsof` missing.
- Keep PID-file-based stop as primary path and ensure PID file reliability.

## Recommended Implementation Order

1. Improve Linux autostart with systemd detection + XDG fallback.
2. Harden `ui-service stop` fallbacks (`lsof` checks + alternatives).
