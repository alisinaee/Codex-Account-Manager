#!/usr/bin/env bash
set -euo pipefail

echo "Removing Codex Account Manager bootstrap prerequisites for installation testing..."

HOME_DIR="${HOME}"
LOCAL_BIN="${HOME_DIR}/.local/bin"
LOCAL_PIPX="${HOME_DIR}/.local/pipx"
CODEX_DIR="${HOME_DIR}/.codex"
UI_SERVICE_DIR="${CODEX_DIR}/ui-service"
ACCOUNT_MANAGER_DIR="${CODEX_DIR}/account-manager"
ELECTRON_APP_SUPPORT="${HOME_DIR}/Library/Application Support/Codex Account Manager"

remove_path() {
  local target="$1"
  if [ -e "$target" ] || [ -L "$target" ]; then
    rm -rf "$target"
    echo "Removed: $target"
  else
    echo "Not present: $target"
  fi
}

run_if_present() {
  local cmd="$1"
  shift
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" >/dev/null 2>&1 || true
    echo "Ran: $cmd $*"
  else
    echo "Command not found, skipped: $cmd"
  fi
}

run_if_present codex-account ui-service stop
run_if_present pipx uninstall codex-account-manager

remove_path "${LOCAL_BIN}/codex-account"
remove_path "${LOCAL_PIPX}/venvs/codex-account-manager"
remove_path "${LOCAL_PIPX}/shared"
remove_path "${LOCAL_PIPX}/logs"
remove_path "${UI_SERVICE_DIR}/service.json"
remove_path "${ACCOUNT_MANAGER_DIR}/runtime-state.json"
remove_path "${ELECTRON_APP_SUPPORT}/runtime-state.json"

echo
echo "Kept intentionally:"
echo "  ${CODEX_DIR}/account-profiles"
echo "  ${CODEX_DIR}/profile-homes"
echo "  exported .camzip archives"
echo
echo "Cleanup complete. The packaged app should now behave like 'core missing' on next launch."
