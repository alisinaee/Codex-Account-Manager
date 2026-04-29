#!/usr/bin/env python3
import argparse
import base64
import collections
import copy
import contextlib
import datetime as dt
import difflib
import hashlib
import io
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import ssl
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

try:
    from .contracts import CommandResult
    from . import native_notifications
    from .services import DiagnosticsLogger, UiConfigService, UsageService
except Exception:
    # Support direct script execution (python path/to/cli.py ...)
    from contracts import CommandResult  # type: ignore
    import native_notifications  # type: ignore
    from services import DiagnosticsLogger, UiConfigService, UsageService  # type: ignore

CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGE_ASSETS_DIR = PACKAGE_ROOT / "assets"
PROJECT_CONFIG_FILE = PROJECT_ROOT / "config.json"
APP_ICON_FILE = PACKAGE_ASSETS_DIR / "codex_account_manager.svg"
AUTH_FILE = CODEX_HOME / "auth.json"
PROFILES_DIR = CODEX_HOME / "account-profiles"
BACKUPS_DIR = CODEX_HOME / "account-backups"
PROFILE_HOMES_DIR = CODEX_HOME / "profile-homes"
UI_STATE_DIR = CODEX_HOME / "ui-service"
UI_PID_FILE = UI_STATE_DIR / "service.json"
UI_DEFAULT_HOST = "127.0.0.1"
UI_DEFAULT_PORT = 4673
CAM_DIR = CODEX_HOME / "account-manager"
CAM_CONFIG_FILE = CAM_DIR / "config.json"
CAM_LOG_FILE = CAM_DIR / "ui.log"
CAM_LOG_MAX_BYTES = 2 * 1024 * 1024
CAM_LOG_BACKUPS = 4
APP_CANDIDATES = ("Codex", "CodexBar")
UI_BUILD_VERSION = hashlib.sha1(f"{Path(__file__).resolve()}:{Path(__file__).stat().st_mtime_ns}".encode("utf-8")).hexdigest()[:12]
DEFAULT_APP_VERSION = "0.0.12"
AUTO_SWITCH_MIN_INTERNAL_COOLDOWN_SEC = 20
PROFILE_ARCHIVE_VERSION = 1
PROFILE_ARCHIVE_EXT = ".camzip"
EXPORT_SESSION_TTL_SEC = 15 * 60
IMPORT_ANALYSIS_TTL_SEC = 30 * 60


_RAW_SUBPROCESS_RUN = subprocess.run
_RAW_SUBPROCESS_CALL = subprocess.call
EXPORT_SESSION_LOCK = threading.Lock()
EXPORT_SESSIONS: dict[str, dict] = {}
IMPORT_ANALYSIS_LOCK = threading.Lock()
IMPORT_ANALYSES: dict[str, dict] = {}


def _with_windows_hidden_subprocess(kwargs: dict) -> dict:
    if not sys.platform.startswith("win"):
        return kwargs
    out = dict(kwargs)
    flags = int(out.get("creationflags") or 0)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out["creationflags"] = flags
    if "startupinfo" not in out and hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        si.wShowWindow = 0
        out["startupinfo"] = si
    return out


def _subprocess_run(*popenargs, **kwargs):
    return _RAW_SUBPROCESS_RUN(*popenargs, **_with_windows_hidden_subprocess(kwargs))


def _subprocess_call(*popenargs, **kwargs):
    return _RAW_SUBPROCESS_CALL(*popenargs, **_with_windows_hidden_subprocess(kwargs))


def load_app_version() -> str:
    try:
        if PROJECT_CONFIG_FILE.exists():
            raw = json.loads(PROJECT_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                app = raw.get("app", {})
                if isinstance(app, dict):
                    v = app.get("version")
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                v2 = raw.get("version")
                if isinstance(v2, str) and v2.strip():
                    return v2.strip()
    except Exception:
        pass
    return DEFAULT_APP_VERSION


APP_VERSION = load_app_version()
PROJECT_RELEASES_URL = "https://github.com/alisinaee/Codex-Account-Manager/releases"
GITHUB_RELEASES_API_URL = "https://api.github.com/repos/alisinaee/Codex-Account-Manager/releases"
RELEASE_NOTES_FALLBACK_FILE = PROJECT_ROOT / "docs" / "release-notes.md"
RELEASE_NOTES_CACHE_TTL_SEC = 180.0


def load_app_icon_svg() -> str:
    candidates = [
        APP_ICON_FILE,
        PROJECT_ROOT / "docs" / "assets" / "codex_account_manager.svg",
    ]
    for path in candidates:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception:
            pass
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
        "<rect width='64' height='64' rx='12' fill='#090d12'/>"
        "<rect x='8' y='8' width='48' height='48' rx='10' fill='none' stroke='#57fd7c' stroke-width='4'/>"
        "</svg>"
    )


def _load_project_config() -> dict:
    try:
        if PROJECT_CONFIG_FILE.exists():
            raw = json.loads(PROJECT_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {}


def _codex_project_config() -> dict:
    raw = _load_project_config().get("codex")
    return raw if isinstance(raw, dict) else {}


def _config_str(raw, key: str) -> str | None:
    val = raw.get(key)
    if isinstance(val, str):
        val = val.strip()
        if val:
            return val
    return None


def _set_private_permissions(path: Path) -> None:
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return
    if sys.platform.startswith("win") and shutil.which("icacls"):
        user = os.environ.get("USERNAME")
        if user:
            try:
                _subprocess_run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass


def _ensure_windows_user_writable(path: Path) -> bool:
    if not sys.platform.startswith("win"):
        return True
    if not shutil.which("icacls"):
        return False
    user = os.environ.get("USERNAME")
    if not user:
        return False
    try:
        res = _subprocess_run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def _copy_auth_file_with_repair(source_auth: Path, target_auth: Path) -> None:
    try:
        shutil.copy2(source_auth, target_auth)
        return
    except PermissionError:
        if not _ensure_windows_user_writable(target_auth):
            raise
        shutil.copy2(source_auth, target_auth)


DEFAULT_CAM_CONFIG = {
    "ui": {
        "theme": "auto",
        "advanced_mode": False,
        "current_auto_refresh_enabled": True,
        "current_refresh_interval_sec": 5,
        "all_auto_refresh_enabled": False,
        "all_refresh_interval_min": 5,
        "debug_mode": False,
        "windows_taskbar_usage_enabled": False,
    },
    "notifications": {
        "enabled": False,
        "scope": "any",
        "thresholds": {
            "h5_warn_pct": 20,
            "weekly_warn_pct": 20,
        },
    },
    "auto_switch": {
        "enabled": False,
        "trigger_mode": "any",
        "delay_sec": 60,
        "use_h5": True,
        "use_weekly": True,
        "thresholds": {
            "h5_switch_pct": 20,
            "weekly_switch_pct": 20,
        },
        "candidate_policy": "only_selected",
        "same_principal_policy": "skip",
        "cooldown_sec": 60,
        "ranking_mode": "balanced",
        "weights": {
            "rem5h": 0.40,
            "remWeekly": 0.35,
            "reset5h": 0.15,
            "resetWeekly": 0.10,
        },
        "manual_chain": [],
    },
    "profiles": {
        "eligibility": {},
    },
}

ADD_LOGIN_LOCK = threading.Lock()
CAM_CONFIG_LOCK = threading.RLock()
CAM_LOG_LOCK = threading.RLock()
ADD_LOGIN_SESSIONS: dict[str, dict] = {}
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_JWT_LIKE_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SECRET_PAIR_RE = re.compile(r"(?i)\b(access_token|refresh_token|id_token|token|authorization|secret|password|apikey|api_key)\s*[:=]\s*([^\s,;]+)")


def _extract_device_login_hints(text: str) -> tuple[str | None, str | None]:
    url = None
    code = None
    clean = ANSI_ESCAPE_RE.sub("", text or "").replace("\r", "").strip()
    try:
        m_url = re.search(r"(https?://[^\s]+)", clean)
        if m_url:
            url = m_url.group(1).rstrip(").,;")
        m_code = re.search(r"\b([A-Z0-9]{4}(?:-[A-Z0-9]{4})+)\b", clean)
        if m_code:
            code = m_code.group(1)
    except Exception:
        pass
    return url, code


def _session_public_payload(s: dict) -> dict:
    return {
        "id": s.get("id"),
        "name": s.get("name"),
        "status": s.get("status"),
        "created_at": s.get("created_at"),
        "updated_at": s.get("updated_at"),
        "finished_at": s.get("finished_at"),
        "url": s.get("url"),
        "code": s.get("code"),
        "message": s.get("message"),
        "error": s.get("error"),
        "recent_output": list(s.get("output", []))[-80:],
    }


def _cleanup_add_login_session(s: dict) -> None:
    try:
        if not s.get("keep_temp_home", False):
            temp_home = s.get("temp_home")
            if temp_home:
                shutil.rmtree(str(temp_home), ignore_errors=True)
    except Exception:
        pass


def _auth_file_has_usage_credentials(auth_path: Path) -> bool:
    try:
        data = load_json(auth_path)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    access_token = data.get("access_token") or tokens.get("access_token")
    account_id = data.get("account_id") or tokens.get("account_id")
    return bool(access_token and account_id)


def _invalidate_add_login_usage_cache(s: dict, reason: str) -> None:
    invalidator = s.get("invalidate_usage_cache")
    if callable(invalidator):
        try:
            invalidator(reason)
        except Exception:
            pass


def _complete_add_login_session_from_auth(session_id: str) -> bool:
    with ADD_LOGIN_LOCK:
        s = ADD_LOGIN_SESSIONS.get(session_id)
        if not s or s.get("status") != "running":
            return False
        name = str(s.get("name") or "").strip()
        temp_auth = Path(str(s.get("temp_auth") or ""))
        overwrite = bool(s.get("overwrite", False))
        proc = s.get("proc")
    if not name or not temp_auth.exists() or not _auth_file_has_usage_credentials(temp_auth):
        return False

    err_text = None
    try:
        write_profile(name=name, source_auth=temp_auth, source_label=str(temp_auth), overwrite=overwrite)
    except RuntimeError as e:
        err_text = str(e)

    with ADD_LOGIN_LOCK:
        s = ADD_LOGIN_SESSIONS.get(session_id)
        if not s or s.get("status") != "running":
            return False
        if err_text:
            s["status"] = "failed"
            s["error"] = err_text
            cam_log("error", "login session profile update failed", {"session_id": session_id, "profile": name, "error": err_text})
        else:
            active_synced = False
            try:
                context = _build_usage_profile_context(config=load_cam_config())
                current_profile = str(context.get("current_profile") or "").strip()
            except Exception:
                current_profile = ""
            if current_profile and current_profile == name:
                try:
                    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _copy_auth_file_with_repair(temp_auth, AUTH_FILE)
                    _set_private_permissions(AUTH_FILE)
                    active_synced = True
                except Exception:
                    pass
            s["status"] = "completed"
            s["message"] = f"profile '{name}' added"
            _invalidate_add_login_usage_cache(s, "local-add-session")
            cam_log("info", "login session profile updated", {"session_id": session_id, "profile": name, "active_synced": active_synced})
        s["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        s["updated_at"] = s["finished_at"]
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
        _cleanup_add_login_session(s)
    return err_text is None


def _watch_add_login_auth(session_id: str, timeout: int) -> None:
    deadline = time.time() + max(1, int(timeout))
    while time.time() < deadline:
        if _complete_add_login_session_from_auth(session_id):
            return
        with ADD_LOGIN_LOCK:
            s = ADD_LOGIN_SESSIONS.get(session_id)
            if not s or s.get("status") != "running":
                return
        time.sleep(0.35)


def _run_add_login_session(session_id: str) -> None:
    with ADD_LOGIN_LOCK:
        session = ADD_LOGIN_SESSIONS.get(session_id)
        if not session:
            return
        proc = session.get("proc")
        temp_auth = session.get("temp_auth")
        name = session.get("name")
        overwrite = bool(session.get("overwrite", False))
    if not proc:
        return
    try:
        stream = proc.stdout
        if stream is not None:
            for raw in stream:
                line = ANSI_ESCAPE_RE.sub("", (raw or "")).replace("\r", "").rstrip("\n")
                if not line:
                    continue
                u, c = _extract_device_login_hints(line)
                with ADD_LOGIN_LOCK:
                    s = ADD_LOGIN_SESSIONS.get(session_id)
                    if not s:
                        continue
                    out = s.setdefault("output", [])
                    out.append(line)
                    if len(out) > 600:
                        del out[:-300]
                    if u and not s.get("url"):
                        s["url"] = u
                    if c and not s.get("code"):
                        s["code"] = c
                    s["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        rc = proc.wait(timeout=1)
    except Exception as e:
        with ADD_LOGIN_LOCK:
            s = ADD_LOGIN_SESSIONS.get(session_id)
            if s:
                s["status"] = "failed"
                s["error"] = f"login process error: {e}"
                s["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
                s["updated_at"] = s["finished_at"]
                _cleanup_add_login_session(s)
        return

    with ADD_LOGIN_LOCK:
        s = ADD_LOGIN_SESSIONS.get(session_id)
        if not s:
            return
        if s.get("status") == "canceled":
            s["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
            s["updated_at"] = s["finished_at"]
            _cleanup_add_login_session(s)
            return
        if s.get("status") == "completed":
            return
        if rc != 0:
            tail = ""
            out_lines = s.get("output") or []
            if isinstance(out_lines, list):
                for item in reversed(out_lines):
                    if isinstance(item, str) and item.strip():
                        tail = item.strip()
                        break
            reason = f"login command failed with exit code {rc}"
            if tail:
                reason = f"{reason}: {tail}"
            s["status"] = "failed"
            s["error"] = reason
            s["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
            s["updated_at"] = s["finished_at"]
            _cleanup_add_login_session(s)
            return
        if not temp_auth or not Path(temp_auth).exists():
            s["status"] = "failed"
            s["error"] = f"login finished but auth file not found at {temp_auth}"
            s["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
            s["updated_at"] = s["finished_at"]
            _cleanup_add_login_session(s)
            return
    # write profile outside lock
    if _complete_add_login_session_from_auth(session_id):
        return
    err_text = None
    try:
        write_profile(name=name, source_auth=Path(temp_auth), source_label=str(temp_auth), overwrite=overwrite)
    except RuntimeError as e:
        err_text = str(e)
    with ADD_LOGIN_LOCK:
        s = ADD_LOGIN_SESSIONS.get(session_id)
        if not s:
            return
        if err_text:
            s["status"] = "failed"
            s["error"] = err_text
            cam_log("error", "login session profile update failed", {"session_id": session_id, "profile": name, "error": err_text})
        else:
            active_synced = False
            # If this is the currently active profile, update live auth.json too.
            try:
                context = _build_usage_profile_context(config=load_cam_config())
                current_profile = str(context.get("current_profile") or "").strip()
            except Exception:
                current_profile = ""
            if current_profile and current_profile == str(name).strip():
                try:
                    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _copy_auth_file_with_repair(Path(temp_auth), AUTH_FILE)
                    _set_private_permissions(AUTH_FILE)
                    active_synced = True
                except Exception:
                    # Keep profile save successful; UI can still switch to this profile if needed.
                    pass
            s["status"] = "completed"
            s["message"] = f"profile '{name}' added"
            # Clear stale usage/auth snapshots so the UI can detect fresh auth immediately.
            _invalidate_add_login_usage_cache(s, "local-add-session")
            cam_log("info", "login session profile updated", {"session_id": session_id, "profile": name, "active_synced": active_synced})
        s["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        s["updated_at"] = s["finished_at"]
        _cleanup_add_login_session(s)


def start_add_login_session(
    name: str,
    timeout: int,
    overwrite: bool,
    keep_temp_home: bool,
    device_auth: bool,
    invalidate_usage_cache_fn=None,
) -> dict:
    ensure_dirs()
    _validate_target_profile_name(name, overwrite=overwrite)
    try:
        login_cmd = resolve_add_login_command(device_auth=device_auth)
    except RuntimeError as e:
        raise RuntimeError(str(e)) from e

    temp_home = Path(tempfile.mkdtemp(prefix="codex-account-add-", dir=str(ensure_tmp_dir())))
    temp_auth = temp_home / "auth.json"
    env = os.environ.copy()
    env["CODEX_HOME"] = str(temp_home)

    try:
        proc = subprocess.Popen(
            login_cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        raise RuntimeError(f"failed to start login session command: {e}") from e
    session_id = secrets.token_hex(8)
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    session = {
        "id": session_id,
        "name": name,
        "status": "running",
        "created_at": now_iso,
        "updated_at": now_iso,
        "finished_at": None,
        "url": None,
        "code": None,
        "message": "waiting for device-auth link",
        "error": None,
        "output": [],
        "proc": proc,
        "temp_home": str(temp_home),
        "temp_auth": str(temp_auth),
        "overwrite": bool(overwrite),
        "keep_temp_home": bool(keep_temp_home),
        "timeout": int(timeout),
        "invalidate_usage_cache": invalidate_usage_cache_fn,
    }
    with ADD_LOGIN_LOCK:
        ADD_LOGIN_SESSIONS[session_id] = session
    t = threading.Thread(target=_run_add_login_session, args=(session_id,), daemon=True)
    t.start()
    threading.Thread(target=_watch_add_login_auth, args=(session_id, int(timeout)), daemon=True).start()
    def _timeout_watchdog(sid: str, sec: int):
        time.sleep(max(1, sec))
        with ADD_LOGIN_LOCK:
            ss = ADD_LOGIN_SESSIONS.get(sid)
            if not ss or ss.get("status") != "running":
                return
            p = ss.get("proc")
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass
            ss["status"] = "failed"
            ss["error"] = f"login timed out after {sec} seconds"
            ss["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
            ss["updated_at"] = ss["finished_at"]
            _cleanup_add_login_session(ss)
    threading.Thread(target=_timeout_watchdog, args=(session_id, int(timeout)), daemon=True).start()
    return _session_public_payload(session)


def get_add_login_session(session_id: str) -> dict | None:
    with ADD_LOGIN_LOCK:
        s = ADD_LOGIN_SESSIONS.get(session_id)
        if not s:
            return None
        return _session_public_payload(s)


def cancel_add_login_session(session_id: str) -> dict | None:
    with ADD_LOGIN_LOCK:
        s = ADD_LOGIN_SESSIONS.get(session_id)
        if not s:
            return None
        proc = s.get("proc")
        if s.get("status") == "running" and proc:
            try:
                proc.terminate()
            except Exception:
                pass
        s["status"] = "canceled"
        s["message"] = "login canceled by user"
        s["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        s["finished_at"] = s["updated_at"]
        _cleanup_add_login_session(s)
        return _session_public_payload(s)


def print_json(payload) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_dirs() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_HOMES_DIR.mkdir(parents=True, exist_ok=True)
    CAM_DIR.mkdir(parents=True, exist_ok=True)


def ensure_tmp_dir() -> Path:
    tmp_dir = CODEX_HOME / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir


def ensure_cam_tmp_dir() -> Path:
    ensure_dirs()
    tmp_dir = CAM_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir


def _cleanup_expired_export_sessions() -> None:
    now = time.time()
    with EXPORT_SESSION_LOCK:
        expired = [sid for sid, entry in EXPORT_SESSIONS.items() if now - float(entry.get("created_ts") or 0.0) > EXPORT_SESSION_TTL_SEC]
        for sid in expired:
            entry = EXPORT_SESSIONS.pop(sid, None) or {}
            path = entry.get("path")
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass


def _cleanup_expired_import_analyses() -> None:
    now = time.time()
    with IMPORT_ANALYSIS_LOCK:
        expired = [sid for sid, entry in IMPORT_ANALYSES.items() if now - float(entry.get("created_ts") or 0.0) > IMPORT_ANALYSIS_TTL_SEC]
        for sid in expired:
            entry = IMPORT_ANALYSES.pop(sid, None) or {}
            path = entry.get("path")
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass


def _redact_log_text(value: str) -> str:
    if not value:
        return value
    out = _BEARER_RE.sub("Bearer [REDACTED]", value)
    out = _JWT_LIKE_RE.sub("[REDACTED_JWT]", out)
    out = _SECRET_PAIR_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", out)
    return out


def _sanitize_log_value(value, depth: int = 0):
    if value is None:
        return None
    if depth > 4:
        return "[depth-limit]"
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_log_text(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_log_value(x, depth + 1) for x in value[:50]]
    if isinstance(value, dict):
        out = {}
        idx = 0
        for k, v in value.items():
            if idx >= 80:
                out["__truncated__"] = True
                break
            key = str(k)
            if key.lower() in {"access_token", "refresh_token", "id_token", "token", "authorization", "secret", "password", "apikey", "api_key", "session", "cookie"}:
                out[key] = "[REDACTED]"
            else:
                out[key] = _sanitize_log_value(v, depth + 1)
            idx += 1
        return out
    return _redact_log_text(str(value))


def _rotate_cam_log_if_needed(max_bytes: int = CAM_LOG_MAX_BYTES, backups: int = CAM_LOG_BACKUPS) -> None:
    try:
        if not CAM_LOG_FILE.exists():
            return
        if CAM_LOG_FILE.stat().st_size < max(1024, int(max_bytes)):
            return
        keep = max(1, int(backups))
        oldest = CAM_LOG_FILE.with_name(f"{CAM_LOG_FILE.name}.{keep}")
        try:
            if oldest.exists():
                oldest.unlink()
        except Exception:
            pass
        for idx in range(keep - 1, 0, -1):
            src = CAM_LOG_FILE.with_name(f"{CAM_LOG_FILE.name}.{idx}")
            dst = CAM_LOG_FILE.with_name(f"{CAM_LOG_FILE.name}.{idx + 1}")
            if src.exists():
                try:
                    os.replace(str(src), str(dst))
                except Exception:
                    pass
        first = CAM_LOG_FILE.with_name(f"{CAM_LOG_FILE.name}.1")
        try:
            os.replace(str(CAM_LOG_FILE), str(first))
        except Exception:
            return
    except Exception:
        pass


def cam_log(level: str, message: str, details=None, echo: bool = False) -> None:
    try:
        with CAM_LOG_LOCK:
            ensure_dirs()
            _rotate_cam_log_if_needed()
            payload = {
                "ts": dt.datetime.now().isoformat(),
                "level": str(level).lower(),
                "message": _redact_log_text(str(message)),
                "details": _sanitize_log_value(details if details is not None else {}),
                "pid": os.getpid(),
                "thread": threading.current_thread().name,
            }
            with CAM_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            _set_private_permissions(CAM_LOG_FILE)
        if echo:
            print(f"[cam:{payload['level']}] {payload['message']}")
    except Exception:
        pass


def read_log_tail(max_lines: int = 300):
    try:
        if not CAM_LOG_FILE.exists():
            return []
        ring: collections.deque[str] = collections.deque(maxlen=max(1, int(max_lines)))
        with CAM_LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                ring.append(line.rstrip("\n"))
        lines = list(ring)
        rows = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"ts": None, "level": "raw", "message": line, "details": {}})
        return rows
    except Exception:
        return []


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(str(tmp_path), str(path))
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def clamp_int(value, default: int, minimum: int = 0, maximum: int = 100000) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(minimum, min(maximum, n))


def clamp_float(value, default: float, minimum: float = 0.0, maximum: float = 1e9) -> float:
    try:
        n = float(value)
    except Exception:
        n = default
    return max(minimum, min(maximum, n))


def sanitize_cam_config(raw: dict) -> dict:
    cfg = copy.deepcopy(DEFAULT_CAM_CONFIG)
    raw_ui = raw.get("ui", {}) if isinstance(raw, dict) and isinstance(raw.get("ui"), dict) else {}
    if isinstance(raw, dict):
        deep_merge(cfg, raw)

    ui = cfg.get("ui", {})
    ui["theme"] = ui.get("theme") if ui.get("theme") in ("dark", "light", "auto") else "auto"
    ui["advanced_mode"] = bool(ui.get("advanced_mode", False))
    legacy_auto_refresh = bool(raw_ui.get("auto_refresh", True))
    legacy_refresh_interval = clamp_int(raw_ui.get("refresh_interval_sec"), 5, minimum=1, maximum=3600)
    ui["current_auto_refresh_enabled"] = bool(raw_ui.get("current_auto_refresh_enabled", legacy_auto_refresh))
    ui["current_refresh_interval_sec"] = clamp_int(raw_ui.get("current_refresh_interval_sec"), legacy_refresh_interval, minimum=1, maximum=3600)
    ui["all_auto_refresh_enabled"] = bool(raw_ui.get("all_auto_refresh_enabled", ui.get("all_auto_refresh_enabled", False)))
    ui["all_refresh_interval_min"] = clamp_int(raw_ui.get("all_refresh_interval_min"), 5, minimum=1, maximum=60)
    ui.pop("auto_refresh", None)
    ui.pop("refresh_interval_sec", None)
    ui["debug_mode"] = bool(ui.get("debug_mode", False))
    ui["windows_taskbar_usage_enabled"] = bool(ui.get("windows_taskbar_usage_enabled", False))
    cfg["ui"] = ui

    notif = cfg.get("notifications", {})
    notif["enabled"] = bool(notif.get("enabled", False))
    notif["scope"] = notif.get("scope") if notif.get("scope") in ("any", "5h", "weekly") else "any"
    notif.pop("alarm_preset", None)
    thresholds = notif.get("thresholds", {})
    notif["thresholds"] = {
        "h5_warn_pct": clamp_int(thresholds.get("h5_warn_pct"), 20, minimum=0, maximum=100),
        "weekly_warn_pct": clamp_int(thresholds.get("weekly_warn_pct"), 20, minimum=0, maximum=100),
    }
    cfg["notifications"] = notif

    auto = cfg.get("auto_switch", {})
    auto["enabled"] = bool(auto.get("enabled", False))
    auto["trigger_mode"] = auto.get("trigger_mode") if auto.get("trigger_mode") in ("any", "all") else "any"
    auto["delay_sec"] = clamp_int(auto.get("delay_sec"), 60, minimum=0, maximum=3600)
    auto["use_h5"] = True
    auto["use_weekly"] = True
    ath = auto.get("thresholds", {})
    auto["thresholds"] = {
        "h5_switch_pct": clamp_int(ath.get("h5_switch_pct"), 20, minimum=0, maximum=100),
        "weekly_switch_pct": clamp_int(ath.get("weekly_switch_pct"), 20, minimum=0, maximum=100),
    }
    auto["candidate_policy"] = "only_selected"
    auto["same_principal_policy"] = "skip" if auto.get("same_principal_policy") != "allow" else "allow"
    auto["cooldown_sec"] = clamp_int(auto.get("cooldown_sec"), 60, minimum=0, maximum=3600)
    auto["ranking_mode"] = auto.get("ranking_mode") if auto.get("ranking_mode") in ("balanced", "max_5h", "max_weekly", "manual") else "balanced"
    w = auto.get("weights", {})
    rem5h = clamp_float(w.get("rem5h"), 0.40, minimum=0.0, maximum=1.0)
    remw = clamp_float(w.get("remWeekly"), 0.35, minimum=0.0, maximum=1.0)
    r5 = clamp_float(w.get("reset5h"), 0.15, minimum=0.0, maximum=1.0)
    rw = clamp_float(w.get("resetWeekly"), 0.10, minimum=0.0, maximum=1.0)
    total = rem5h + remw + r5 + rw
    if total <= 0:
        rem5h, remw, r5, rw = 0.40, 0.35, 0.15, 0.10
        total = 1.0
    auto["weights"] = {
        "rem5h": rem5h / total,
        "remWeekly": remw / total,
        "reset5h": r5 / total,
        "resetWeekly": rw / total,
    }
    raw_chain = auto.get("manual_chain", [])
    manual_chain = []
    if isinstance(raw_chain, list):
        seen_chain = set()
        for item in raw_chain:
            if not isinstance(item, str):
                continue
            name = item.strip()
            if not name or name in seen_chain:
                continue
            seen_chain.add(name)
            manual_chain.append(name)
    auto["manual_chain"] = manual_chain
    cfg["auto_switch"] = auto

    profiles = cfg.get("profiles", {})
    eligibility = profiles.get("eligibility", {})
    if not isinstance(eligibility, dict):
        eligibility = {}
    clean_eligibility = {}
    for k, v in eligibility.items():
        if isinstance(k, str) and k.strip():
            clean_eligibility[k.strip()] = bool(v)
    profiles["eligibility"] = clean_eligibility
    cfg["profiles"] = profiles
    meta = cfg.get("_meta", {})
    if not isinstance(meta, dict):
        meta = {}
    meta["revision"] = clamp_int(meta.get("revision", 1), 1, minimum=1, maximum=2_000_000_000)
    meta["updated_at"] = str(meta.get("updated_at") or dt.datetime.now().isoformat())
    cfg["_meta"] = meta
    return cfg


def load_cam_config() -> dict:
    with CAM_CONFIG_LOCK:
        ensure_dirs()
        if not CAM_CONFIG_FILE.exists():
            cfg = sanitize_cam_config({})
            atomic_write_json(CAM_CONFIG_FILE, cfg)
            return cfg
        try:
            raw = load_json(CAM_CONFIG_FILE)
        except Exception:
            raw = {}
        cfg = sanitize_cam_config(raw if isinstance(raw, dict) else {})
        return cfg


def save_cam_config(cfg: dict) -> dict:
    with CAM_CONFIG_LOCK:
        norm = sanitize_cam_config(cfg if isinstance(cfg, dict) else {})
        meta = norm.setdefault("_meta", {})
        prev_rev = clamp_int(meta.get("revision", 1), 1, minimum=1, maximum=2_000_000_000)
        meta["revision"] = prev_rev + 1
        meta["updated_at"] = dt.datetime.now().isoformat()
        atomic_write_json(CAM_CONFIG_FILE, norm)
        return norm


def update_cam_config(patch: dict, base_revision: int | None = None) -> dict:
    with CAM_CONFIG_LOCK:
        cfg = load_cam_config()
        if not isinstance(patch, dict):
            return cfg
        if base_revision is not None:
            cur_rev = clamp_int(((cfg.get("_meta") or {}).get("revision")), 1, minimum=1, maximum=2_000_000_000)
            if int(base_revision) != int(cur_rev):
                raise RuntimeError(f"stale config revision (expected {base_revision}, current {cur_rev})")
        deep_merge(cfg, patch)
        return save_cam_config(cfg)


def decode_jwt_payload(token: str):
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        padding = "=" * ((4 - len(payload) % 4) % 4)
        raw = base64.urlsafe_b64decode(payload + padding)
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None


def format_usage_cell(remaining_percent, resets_at):
    if remaining_percent is None:
        return "-"
    pct = int(round(max(0.0, min(100.0, float(remaining_percent)))))
    if resets_at is None:
        return f"{pct}%"
    try:
        reset_dt = dt.datetime.fromtimestamp(int(resets_at))
        now_dt = dt.datetime.now()
        if reset_dt.date() == now_dt.date():
            return f"{pct}% ({reset_dt.strftime('%H:%M')})"
        return f"{pct}% ({reset_dt.strftime('%H:%M on %d %b')})"
    except Exception:
        return f"{pct}%"


def extract_usage_windows(payload):
    if not isinstance(payload, dict):
        return None, None

    candidate = None
    if any(k in payload for k in ("primary", "secondary")):
        candidate = payload
    elif isinstance(payload.get("rate_limits"), dict):
        candidate = payload.get("rate_limits")
    elif isinstance(payload.get("usage"), dict) and isinstance(payload["usage"].get("rate_limits"), dict):
        candidate = payload["usage"]["rate_limits"]
    elif isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("rate_limits"), dict):
        candidate = payload["data"]["rate_limits"]
    elif isinstance(payload.get("rate_limit"), dict):
        candidate = payload.get("rate_limit")

    if candidate is None:
        return None, None

    primary = candidate.get("primary")
    secondary = candidate.get("secondary")
    if not isinstance(primary, dict):
        primary = candidate.get("primary_window")
    if not isinstance(secondary, dict):
        secondary = candidate.get("secondary_window")
    windows = []
    if isinstance(primary, dict):
        windows.append(primary)
    if isinstance(secondary, dict):
        windows.append(secondary)

    def rem(window):
        used = window.get("used_percent")
        if used is None:
            return None
        try:
            return 100.0 - float(used)
        except Exception:
            return None

    def reset_at(window):
        if not isinstance(window, dict):
            return None
        v = window.get("resets_at")
        if v is None:
            v = window.get("reset_at")
        if v is None:
            after = window.get("reset_after_seconds")
            if after is not None:
                try:
                    return int(time.time() + float(after))
                except Exception:
                    return None
        return v

    usage_5h = None
    usage_weekly = None
    def window_minutes(window):
        minutes = window.get("window_minutes")
        if minutes is not None:
            return minutes
        sec = window.get("limit_window_seconds")
        if sec is None:
            return None
        try:
            return int(round(float(sec) / 60.0))
        except Exception:
            return None

    for w in windows:
        minutes = window_minutes(w)
        if minutes == 300:
            usage_5h = (rem(w), reset_at(w))
        elif minutes == 10080:
            usage_weekly = (rem(w), reset_at(w))

    if usage_5h is None and isinstance(primary, dict):
        usage_5h = (rem(primary), reset_at(primary))
    if usage_weekly is None and isinstance(secondary, dict):
        usage_weekly = (rem(secondary), reset_at(secondary))

    return usage_5h, usage_weekly


def fetch_usage_from_auth(auth_path: Path, timeout_sec: int = 7):
    try:
        data = load_json(auth_path)
    except Exception as e:
        return None, None, None, None, f"bad auth json: {e}"

    tokens = data.get("tokens", {}) if isinstance(data.get("tokens"), dict) else {}
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not access_token or not account_id:
        return None, None, None, None, "missing access_token/account_id"

    req = urllib.request.Request(
        url="https://chatgpt.com/backend-api/wham/usage",
        method="GET",
        headers={
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": str(account_id),
            "User-Agent": "Mozilla/5.0 codex-account-manager",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
    except urllib.error.HTTPError as e:
        return None, None, None, None, f"http {e.code}"
    except Exception as e:
        return None, None, None, None, f"request failed: {e}"

    usage_5h, usage_weekly = extract_usage_windows(payload)
    plan_type = None
    is_paid = None
    maybe_plan = payload.get("plan_type") if isinstance(payload, dict) else None
    if isinstance(maybe_plan, str) and maybe_plan.strip():
        plan_type = maybe_plan.strip()
        normalized = plan_type.lower()
        free_markers = {"free", "chatgptfreeplan", "none", "unknown", "basic"}
        is_paid = normalized not in free_markers and "free" not in normalized
    return usage_5h, usage_weekly, plan_type, is_paid, None


def account_hint_from_auth(path: Path) -> str:
    try:
        data = load_json(path)
    except Exception:
        return "unknown"

    hints = []
    account_id = data.get("account_id")
    if not account_id and isinstance(data.get("tokens"), dict):
        account_id = data["tokens"].get("account_id")
    if account_id:
        hints.append(f"id:{account_id}")

    id_token = data.get("id_token")
    if not id_token and isinstance(data.get("tokens"), dict):
        id_token = data["tokens"].get("id_token")
    if isinstance(id_token, str) and id_token:
        payload = decode_jwt_payload(id_token)
        if payload:
            email = payload.get("email")
            if email:
                hints.insert(0, str(email))

    return " | ".join(hints) if hints else "unknown"


def account_email_from_auth(path: Path) -> str | None:
    try:
        data = load_json(path)
    except Exception:
        return None
    id_token = data.get("id_token")
    if not id_token and isinstance(data.get("tokens"), dict):
        id_token = data["tokens"].get("id_token")
    if isinstance(id_token, str) and id_token:
        payload = decode_jwt_payload(id_token) or {}
        email = payload.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    return None


def _normalized_email(value: str | None) -> str:
    return (str(value or "")).strip().lower()


def _existing_profile_dirs() -> list[Path]:
    ensure_dirs()
    return sorted([p for p in PROFILES_DIR.iterdir() if p.is_dir()])


def _find_conflicting_profile_name(name: str) -> str | None:
    target_norm = (name or "").strip().lower()
    if not target_norm:
        return None
    for p in _existing_profile_dirs():
        if p.name.lower() == target_norm:
            return p.name
    return None


def _validate_target_profile_name(name: str, overwrite: bool = False) -> None:
    normalized = (name or "").strip()
    if not normalized:
        raise RuntimeError("profile name is required")
    conflicting = _find_conflicting_profile_name(normalized)
    if not conflicting:
        return
    if conflicting != normalized:
        raise RuntimeError(f"Profile name '{normalized}' conflicts with existing profile '{conflicting}' (case-insensitive duplicate).")
    if not overwrite:
        raise RuntimeError(f"Profile '{normalized}' already exists. Use --force to overwrite.")


def _find_duplicate_email_profile(source_auth: Path, exclude_profile_name: str = "") -> tuple[str, str] | None:
    source_email = _normalized_email(account_email_from_auth(source_auth))
    if not source_email:
        return None
    exclude_norm = (exclude_profile_name or "").strip().lower()
    for p in _existing_profile_dirs():
        if exclude_norm and p.name.lower() == exclude_norm:
            continue
        candidate_auth = p / "auth.json"
        if not candidate_auth.exists():
            continue
        candidate_email = _normalized_email(account_email_from_auth(candidate_auth))
        if candidate_email and candidate_email == source_email:
            return p.name, source_email
    return None


def _account_id_from_data(data: dict | None):
    if not isinstance(data, dict):
        return None
    account_id = data.get("account_id")
    if not account_id and isinstance(data.get("tokens"), dict):
        account_id = data["tokens"].get("account_id")
    return str(account_id) if account_id else None


def _principal_id_from_data(data: dict | None):
    if not isinstance(data, dict):
        return None
    id_token = data.get("id_token")
    if not id_token and isinstance(data.get("tokens"), dict):
        id_token = data["tokens"].get("id_token")
    if isinstance(id_token, str) and id_token:
        payload = decode_jwt_payload(id_token) or {}
        sub = payload.get("sub")
        if sub:
            return f"sub:{sub}"
        oid = payload.get("oid")
        if oid:
            return f"oid:{oid}"
    account_id = _account_id_from_data(data)
    if account_id:
        return f"account_id:{account_id}"
    return None


def account_id_from_auth(path: Path):
    try:
        data = load_json(path)
    except Exception:
        return None
    return _account_id_from_data(data)


def principal_id_from_auth(path: Path):
    try:
        data = load_json(path)
    except Exception:
        return None
    return _principal_id_from_data(data)


def profile_principal_id(name: str):
    auth_path = PROFILES_DIR / name / "auth.json"
    if not auth_path.exists():
        return None
    return principal_id_from_auth(auth_path)


def find_same_principal_profiles(principal_id: str, exclude_name: str = ""):
    if not principal_id:
        return []
    matches = []
    for p in sorted([x for x in PROFILES_DIR.iterdir() if x.is_dir()]):
        if exclude_name and p.name == exclude_name:
            continue
        pid = profile_principal_id(p.name)
        if pid == principal_id:
            matches.append(p.name)
    return matches


def find_same_email_profiles(email: str, exclude_name: str = "") -> list[str]:
    target = (email or "").strip().lower()
    if not target:
        return []
    matches: list[str] = []
    for p in sorted([x for x in PROFILES_DIR.iterdir() if x.is_dir()]):
        if exclude_name and p.name == exclude_name:
            continue
        auth_path = p / "auth.json"
        if not auth_path.exists():
            continue
        p_email = account_email_from_auth(auth_path)
        if p_email and p_email == target:
            matches.append(p.name)
    return matches


def ensure_profile_exists(name: str) -> Path:
    source_auth = PROFILES_DIR / name / "auth.json"
    if not source_auth.exists():
        raise RuntimeError(f"profile '{name}' not found: {source_auth}")
    return source_auth


def prepare_profile_home(name: str) -> Path:
    source_auth = ensure_profile_exists(name)
    profile_home = PROFILE_HOMES_DIR / name
    profile_home.mkdir(parents=True, exist_ok=True)
    target_auth = profile_home / "auth.json"
    _copy_auth_file_with_repair(source_auth, target_auth)
    _set_private_permissions(target_auth)
    return profile_home


def _platform_process_candidates() -> dict[str, list[str]]:
    if sys.platform == "darwin":
        # On macOS, avoid broad "codex" process matches because they can include
        # non-app helper/CLI processes and make app restart behavior unstable.
        return {
            "Codex": [
                "/Applications/Codex.app/Contents/MacOS/Codex",
            ],
            "CodexBar": [
                "/Applications/CodexBar.app/Contents/MacOS/CodexBar",
            ],
        }
    if sys.platform.startswith("win"):
        return {
            "Codex": [
                "Codex.exe",
                "codex.exe",
            ],
            "CodexBar": [
                "CodexBar.exe",
                "codexbar.exe",
            ],
        }
    return {
        "Codex": [
            "codex",
        ],
        "CodexBar": [
            "codexbar",
        ],
    }


def _proc_running(pattern: str) -> bool:
    try:
        if sys.platform.startswith("win"):
            image = Path(pattern).name.lower()
            if not image.endswith(".exe"):
                image = f"{image}.exe"
            p = _subprocess_run(
                ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {image}"],
                capture_output=True,
                text=True,
            )
            if p.returncode != 0:
                return False
            return image in p.stdout.lower()
        if shutil.which("pgrep"):
            p = _subprocess_run(
                ["pgrep", "-f", pattern],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return p.returncode == 0
    except Exception:
        return False
    return False


def _macos_app_is_running(app_name: str) -> bool:
    if sys.platform != "darwin":
        return False
    target = str(app_name or "").strip()
    if not target:
        return False
    script = f'application "{target}" is running'
    try:
        proc = _subprocess_run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    return (proc.stdout or "").strip().lower() == "true"


def detect_running_app_name():
    candidates = _platform_process_candidates()
    for app_name in APP_CANDIDATES:
        if sys.platform == "darwin" and _macos_app_is_running(app_name):
            return app_name
        for proc_pattern in candidates.get(app_name, []):
            if _proc_running(proc_pattern):
                return app_name
    return None


def codex_running() -> bool:
    try:
        return detect_running_app_name() is not None
    except Exception:
        return False


def stop_codex() -> bool:
    candidates = _platform_process_candidates()
    touched = False
    if sys.platform == "darwin":
        for app_name in APP_CANDIDATES:
            _subprocess_run(["osascript", "-e", f'tell application "{app_name}" to quit'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            touched = True
        for _ in range(40):
            if not codex_running():
                break
            time.sleep(0.15)
        if codex_running() and shutil.which("killall"):
            # Fallback only to strict app binary names on macOS.
            for app_binary in ("Codex", "CodexBar"):
                _subprocess_run(["killall", "-q", app_binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                touched = True
            for _ in range(20):
                if not codex_running():
                    break
                time.sleep(0.15)
        return touched
    for app_name in APP_CANDIDATES:
        for proc_pattern in candidates.get(app_name, []):
            if sys.platform.startswith("win"):
                image = Path(proc_pattern).name
                if not image.lower().endswith(".exe"):
                    image = f"{image}.exe"
                _subprocess_run(["taskkill", "/F", "/T", "/IM", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                touched = True
            elif shutil.which("pkill"):
                _subprocess_run(["pkill", "-f", proc_pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                touched = True
            elif shutil.which("killall"):
                _subprocess_run(["killall", "-q", Path(proc_pattern).name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                touched = True
    if sys.platform.startswith("win"):
        # Broader fallback for Store/app-hosted builds that may not run under Codex.exe image names.
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            script = (
                "$ErrorActionPreference='SilentlyContinue';"
                "$targets=Get-Process | Where-Object {"
                "$n=$_.ProcessName.ToLower();"
                "$path='';"
                "try { $path=$_.Path } catch {};"
                "$p=$path.ToLower();"
                "$n -like 'codex*' -or $n -like 'codexbar*' -or $n -like 'chatgpt*' -or "
                "$p -like '*openai*codex*' -or $p -like '*chatgpt*'"
                "};"
                "foreach($t in $targets){"
                "try { taskkill /F /T /PID $t.Id | Out-Null } catch {"
                "  try { Stop-Process -Id $t.Id -Force -ErrorAction SilentlyContinue } catch {}"
                "}"
                "}"
            )
            try:
                _subprocess_run([ps, "-NoProfile", "-Command", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                touched = True
            except Exception:
                pass
    for _ in range(20):
        if not codex_running():
            break
        time.sleep(0.15)
    return touched


def _windows_force_kill_codex_processes() -> int:
    if not sys.platform.startswith("win"):
        return 0
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return 0
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$targets=Get-Process | Where-Object {"
        "$n=$_.ProcessName.ToLower();"
        "$path='';"
        "try { $path=$_.Path } catch {};"
        "$p=$path.ToLower();"
        "$n -like 'codex*' -or $n -like 'codexbar*' -or $n -like 'chatgpt*' -or $n -like 'openai*' -or "
        "$p -like '*openai*codex*' -or $p -like '*chatgpt*'"
        "};"
        "$k=0;"
        "foreach($t in $targets){"
        "  try { Stop-Process -Id $t.Id -Force -ErrorAction Stop; $k++ } catch {}"
        "};"
        "Write-Output $k"
    )
    try:
        proc = _subprocess_run([ps, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=6)
        if proc.returncode != 0:
            return 0
        out = (proc.stdout or "").strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return 0


def _windows_graceful_close_codex_windows() -> tuple[int, int]:
    if not sys.platform.startswith("win"):
        return 0, 0
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return 0, 0
    # Close top-level Codex/ChatGPT windows gracefully, then report remaining windowed processes.
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$all=Get-Process | Where-Object {"
        "$n=$_.ProcessName.ToLower();"
        "$path='';"
        "try { $path=$_.Path } catch {};"
        "$p=$path.ToLower();"
        "$n -like 'codex*' -or $n -like 'codexbar*' -or $n -like 'chatgpt*' -or "
        "$p -like '*openai*codex*' -or $p -like '*chatgpt*'"
        "};"
        "$wins=@($all | Where-Object { $_.MainWindowHandle -ne 0 });"
        "$attempt=[int]$wins.Count;"
        "foreach($w in $wins){"
        "  try { [void]$w.CloseMainWindow() } catch {}"
        "};"
        "Start-Sleep -Milliseconds 900;"
        "$all2=Get-Process | Where-Object {"
        "$n=$_.ProcessName.ToLower();"
        "$path='';"
        "try { $path=$_.Path } catch {};"
        "$p=$path.ToLower();"
        "$n -like 'codex*' -or $n -like 'codexbar*' -or $n -like 'chatgpt*' -or "
        "$p -like '*openai*codex*' -or $p -like '*chatgpt*'"
        "};"
        "$alive=[int](@($all2 | Where-Object { $_.MainWindowHandle -ne 0 }).Count);"
        "Write-Output ($attempt.ToString() + ',' + $alive.ToString())"
    )
    try:
        proc = _subprocess_run([ps, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=7)
        if proc.returncode != 0:
            return 0, 0
        raw = (proc.stdout or "").strip().splitlines()
        line = raw[-1].strip() if raw else "0,0"
        left, right = (line.split(",", 1) + ["0"])[:2]
        attempted = int(left.strip()) if left.strip().isdigit() else 0
        alive = int(right.strip()) if right.strip().isdigit() else 0
        return attempted, alive
    except Exception:
        return 0, 0


def _configured_codex_app_path() -> Path | None:
    cfg = _codex_project_config()
    if sys.platform == "darwin":
        key = "app_path_macos"
    elif sys.platform.startswith("win"):
        key = "app_path_windows"
    else:
        key = "app_path_linux"
    raw = _config_str(cfg, key)
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.exists() else None


def _log_runtime_safe(level: str, message: str, details=None) -> None:
    try:
        log_runtime(level, message, details)
    except Exception:
        pass


def _detect_running_codex_executable_windows() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return None
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$p=Get-Process | Where-Object {"
        "$n=$_.ProcessName.ToLower();"
        "$n -eq 'codex' -or $n -eq 'codexbar' -or $n -like 'codex*'"
        "} | Select-Object -First 1 -ExpandProperty Path;"
        "if($p){Write-Output $p}"
    )
    try:
        proc = _subprocess_run([ps, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    path = (proc.stdout or "").strip().strip('"')
    if not path:
        return None
    p = Path(path)
    return str(p) if p.exists() else None


def _start_windows_appsfolder_codex() -> bool:
    if not sys.platform.startswith("win"):
        return False
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return False
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$app=Get-StartApps | Where-Object { $_.Name -like '*Codex*' } | Select-Object -First 1;"
        "if(-not $app){ exit 1 }"
        "Start-Process ('shell:AppsFolder\\\\' + $app.AppID) | Out-Null;"
        "exit 0"
    )
    try:
        proc = _subprocess_run([ps, "-NoProfile", "-Command", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
    except Exception:
        return False
    return proc.returncode == 0


def start_codex(preferred_app_name: str = "", preferred_exec_path: str = "") -> bool:
    app_order = []
    if preferred_app_name:
        app_order.append(preferred_app_name)
    app_order.extend([x for x in APP_CANDIDATES if x != preferred_app_name])
    configured = _configured_codex_app_path()
    if configured:
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen([str(configured)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            else:
                subprocess.Popen([str(configured)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            _log_runtime_safe("info", "codex.start success configured", {"path": str(configured)})
            return True
        except Exception as e:
            _log_runtime_safe("warn", "codex.start failed configured", {"path": str(configured), "error": str(e)})
    if sys.platform.startswith("win"):
        launchers: list[str] = []
        launch_errors: list[dict] = []
        if preferred_exec_path:
            launchers.append(str(preferred_exec_path))
        try:
            launchers.append(resolve_codex_cli())
        except Exception:
            pass
        for candidate in ("codex", "Codex.exe", "codex.exe"):
            hit = shutil.which(candidate)
            if hit:
                launchers.append(hit)
        seen: set[str] = set()
        for launcher in launchers:
            key = str(launcher).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                subprocess.Popen(
                    [launcher],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                _log_runtime_safe("info", "codex.start success launcher", {"launcher": launcher})
                return True
            except Exception as e:
                launch_errors.append({"launcher": launcher, "error": str(e)})
                continue
        if _start_windows_appsfolder_codex():
            _log_runtime_safe("info", "codex.start success appsfolder", {})
            return True
        _log_runtime_safe("warn", "codex.start failed windows", {"attempts": launch_errors})
        return False
    if sys.platform == "darwin":
        for app_name in app_order:
            for _ in range(3):
                p = _subprocess_run(["open", "-a", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if p.returncode == 0:
                    return True
                time.sleep(0.35)
        return False
    codex_bin = shutil.which("codex")
    if codex_bin:
        try:
            subprocess.Popen([codex_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except Exception:
            return False
    return False


def _codex_cli_fallback_candidates() -> list[Path]:
    out = []
    cfg = _codex_project_config()
    cfg_cli = _config_str(cfg, "cli_path")
    if cfg_cli:
        out.append(Path(cfg_cli).expanduser())
    if sys.platform == "darwin":
        out.append(Path("/Applications/Codex.app/Contents/Resources/codex"))
    elif sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA")
        appdata = os.environ.get("APPDATA")
        pfiles = os.environ.get("ProgramFiles")
        pfiles_x86 = os.environ.get("ProgramFiles(x86)")
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            # Prefer user-local runnable copies before protected WindowsApps binaries.
            user_root = Path(user_profile)
            out.append(user_root / ".codex" / ".sandbox-bin" / "codex.exe")
            for pattern in [
                ".vscode/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe",
                ".cursor/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe",
                ".windsurf/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe",
                ".trae/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe",
                ".antigravity/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe",
            ]:
                try:
                    hits = sorted(user_root.glob(pattern), reverse=True)
                    out.extend(hits)
                except Exception:
                    pass
        for base in [local, pfiles, pfiles_x86]:
            if base:
                out.append(Path(base) / "Codex" / "codex.exe")
                out.append(Path(base) / "Codex" / "bin" / "codex.exe")
                out.append(Path(base) / "Codex" / "codex.cmd")
                out.append(Path(base) / "Codex" / "bin" / "codex.cmd")
                out.append(Path(base) / "Programs" / "Codex" / "codex.exe")
                out.append(Path(base) / "Programs" / "Codex" / "resources" / "codex.exe")
                out.append(Path(base) / "Programs" / "Codex" / "resources" / "bin" / "codex.exe")
        if appdata:
            out.append(Path(appdata) / "npm" / "codex.cmd")
            out.append(Path(appdata) / "npm" / "codex.bat")
        if user_profile:
            out.append(Path(user_profile) / "scoop" / "shims" / "codex.cmd")
            out.append(Path(user_profile) / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "codex.exe")
        for base in [local, pfiles, pfiles_x86]:
            if base:
                out.append(Path(base) / "Microsoft" / "WindowsApps" / "codex.exe")
    else:
        out.extend(
            [
                Path.home() / ".local" / "bin" / "codex",
                Path("/usr/local/bin/codex"),
                Path("/usr/bin/codex"),
            ]
        )
    return out


def _resolve_codex_cli_from_where_windows() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    where_exe = shutil.which("where")
    if not where_exe:
        return None
    try:
        proc = _subprocess_run(
            [where_exe, "codex"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        candidate = line.strip().strip('"')
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists():
            return str(p)
    return None


def _resolve_codex_cli_from_powershell_command_windows() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return None
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$names=@('codex','codex.exe','codex.cmd','codex.bat');"
        "foreach($n in $names){"
        "$c=Get-Command $n -All | Select-Object -First 1;"
        "if($c -and $c.Source){Write-Output $c.Source; break}"
        "}"
    )
    try:
        proc = _subprocess_run(
            [ps, "-NoProfile", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    candidate = (proc.stdout or "").strip().strip('"')
    if not candidate:
        return None
    p = Path(candidate)
    return str(p) if p.exists() else None


def _resolve_codex_cli_from_app_paths_registry_windows() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    reg_exe = shutil.which("reg")
    if not reg_exe:
        return None
    keys = [
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\codex.exe",
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\codex.exe",
    ]
    for key in keys:
        try:
            proc = _subprocess_run(
                [reg_exe, "query", key, "/ve"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            )
        except Exception:
            continue
        if proc.returncode != 0:
            continue
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "REG_SZ" not in line:
                continue
            value = line.split("REG_SZ", 1)[-1].strip().strip('"')
            if value and Path(value).exists():
                return value
    return None


def _resolve_codex_cli_from_appx_windows() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return None
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$pkg=Get-AppxPackage -Name *Codex* | Select-Object -First 1;"
        "if($pkg -and $pkg.InstallLocation){Write-Output $pkg.InstallLocation}"
    )
    try:
        proc = _subprocess_run(
            [ps, "-NoProfile", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=4,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    base = (proc.stdout or "").strip().strip('"')
    if not base:
        return None
    for candidate in (
        Path(base) / "app" / "resources" / "codex.exe",
        Path(base) / "app" / "resources" / "codex.EXE",
        Path(base) / "codex.exe",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def _can_invoke_codex_cli(path: str) -> bool:
    try:
        _subprocess_run(
            [path, "--help"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return True
    except subprocess.TimeoutExpired:
        return True
    except PermissionError:
        return False
    except OSError:
        return False
    except Exception:
        return True


def _normalize_working_codex_cli(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path).expanduser()
    if not p.exists():
        return None
    candidate = str(p)
    if not sys.platform.startswith("win"):
        return candidate
    if _can_invoke_codex_cli(candidate):
        return candidate
    # Windows Store installs may expose a non-invocable internal path; prefer launcher alias.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        alias = Path(local) / "Microsoft" / "WindowsApps" / "codex.exe"
        if alias.exists() and _can_invoke_codex_cli(str(alias)):
            return str(alias)
    return None


def resolve_codex_cli() -> str:
    env_cli = os.environ.get("CODEX_CLI_PATH")
    if env_cli:
        p = Path(env_cli).expanduser()
        if p.exists():
            return str(p)
    for candidate in ("codex", "codex.exe", "codex.cmd", "codex.bat"):
        hit = _normalize_working_codex_cli(shutil.which(candidate))
        if hit:
            return hit
    where_hit = _normalize_working_codex_cli(_resolve_codex_cli_from_where_windows())
    if where_hit:
        return where_hit
    ps_hit = _normalize_working_codex_cli(_resolve_codex_cli_from_powershell_command_windows())
    if ps_hit:
        return ps_hit
    reg_hit = _normalize_working_codex_cli(_resolve_codex_cli_from_app_paths_registry_windows())
    if reg_hit:
        return reg_hit
    appx_hit = _normalize_working_codex_cli(_resolve_codex_cli_from_appx_windows())
    if appx_hit:
        return appx_hit
    for fallback in _codex_cli_fallback_candidates():
        hit = _normalize_working_codex_cli(str(fallback))
        if hit:
            return hit
    if sys.platform.startswith("win"):
        hint = "Install Codex CLI and ensure 'codex' or 'codex.exe' is in PATH (Windows Store: %LOCALAPPDATA%\\\\Microsoft\\\\WindowsApps\\\\codex.exe), or set CODEX_CLI_PATH."
    elif sys.platform == "darwin":
        hint = "Install Codex CLI and ensure 'codex' is in PATH, or set CODEX_CLI_PATH."
    else:
        hint = "Install Codex CLI and ensure 'codex' is in PATH (for example ~/.local/bin), or set CODEX_CLI_PATH."
    raise RuntimeError(f"Could not find 'codex' CLI. {hint}")


def resolve_codex_auth_runner():
    direct = shutil.which("codex-auth")
    if direct:
        return [direct]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", "@loongphy/codex-auth"]
    raise RuntimeError("Could not find 'codex-auth' or 'npx'. Install with: npm i -g @loongphy/codex-auth")


def resolve_add_login_command(device_auth: bool) -> list[str]:
    errors: list[str] = []
    try:
        codex_cli = resolve_codex_cli()
        cmd = [codex_cli, "login"]
        if device_auth:
            cmd.append("--device-auth")
        return cmd
    except Exception as e:
        errors.append(str(e))
    if sys.platform.startswith("win"):
        raise RuntimeError(
            "Could not start login flow on Windows. Add Account requires a runnable Codex CLI for fresh login. "
            "Set CODEX_CLI_PATH to a working codex executable, or set 'codex.cli_path' in config.json. "
            f"Details: {' | '.join([x for x in errors if x])}"
        )
    try:
        runner = resolve_codex_auth_runner()
        cmd = runner + ["login"]
        if device_auth:
            cmd.append("--device-auth")
        return cmd
    except Exception as e:
        errors.append(str(e))
    joined = " | ".join([x for x in errors if x]) or "no available login runner"
    raise RuntimeError(f"Could not start login flow. {joined}")


def _try_fallback_add_from_current_auth(name: str, overwrite: bool, reason: str = "") -> tuple[bool, str]:
    if not AUTH_FILE.exists():
        if reason:
            return False, f"{reason}. Also no active auth found at {AUTH_FILE}."
        return False, f"No active auth found at {AUTH_FILE}."
    try:
        write_profile(name=name, source_auth=AUTH_FILE, source_label=str(AUTH_FILE), overwrite=overwrite)
        msg = "codex login runner unavailable; saved active auth as profile"
        if reason:
            msg = f"{msg} ({reason})"
        return True, msg
    except RuntimeError as e:
        if reason:
            return False, f"{reason}. Fallback save failed: {e}"
        return False, f"Fallback save failed: {e}"


def run_codex_auth(args) -> int:
    try:
        runner = resolve_codex_auth_runner()
    except RuntimeError as e:
        print(f"error: {e}")
        return 1
    cmd = runner + args
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return _subprocess_call(cmd, **kwargs)


def run_codex_auth_capture(args, timeout_sec: int | None = 6):
    try:
        runner = resolve_codex_auth_runner()
    except RuntimeError as e:
        return {
            "ok": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": 1,
        }
    cmd = runner + args
    try:
        kwargs = {"capture_output": True, "text": True}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if timeout_sec is not None:
            kwargs["timeout"] = timeout_sec
        proc = _subprocess_run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "codex-auth timed out",
            "stdout": "",
            "stderr": "codex-auth timed out",
            "exit_code": 124,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"failed to run codex-auth: {e}",
            "stdout": "",
            "stderr": "",
            "exit_code": 1,
        }
    return {
        "ok": proc.returncode == 0,
        "error": None,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
    }




def parse_status_output(text: str):
    status = {
        "auto_switch": None,
        "service": None,
        "thresholds": {"h5": None, "weekly": None},
        "usage_mode": None,
        "account_mode": None,
        "raw": text,
    }
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = [x.strip() for x in line.split(":", 1)]
        if key == "auto-switch":
            if value.upper() == "ON":
                status["auto_switch"] = True
            elif value.upper() == "OFF":
                status["auto_switch"] = False
            else:
                status["auto_switch"] = value
        elif key == "service":
            status["service"] = value
        elif key == "thresholds":
            m = re.search(r"5h<(\d+)%\s*,\s*weekly<(\d+)%", value)
            if m:
                status["thresholds"]["h5"] = int(m.group(1))
                status["thresholds"]["weekly"] = int(m.group(2))
        elif key == "usage":
            status["usage_mode"] = value
        elif key == "account":
            status["account_mode"] = value
    return status


def write_profile(name: str, source_auth: Path, source_label: str, overwrite: bool) -> None:
    name = (name or "").strip()
    _validate_target_profile_name(name, overwrite=overwrite)
    target_dir = PROFILES_DIR / name

    duplicate_email = _find_duplicate_email_profile(source_auth, exclude_profile_name=name if overwrite else "")
    if duplicate_email:
        conflict_name, duplicate_email_text = duplicate_email
        raise RuntimeError(
            f"Profile '{conflict_name}' already uses email '{duplicate_email_text}'. Duplicate account emails are not allowed."
        )

    source_email = account_email_from_auth(source_auth)
    if source_email:
        dup = find_same_email_profiles(source_email, exclude_name=name)
        if dup:
            raise RuntimeError(
                f"Email '{source_email}' already exists in profile(s): {', '.join(dup)}. Use that profile instead."
            )

    target_dir.mkdir(parents=True, exist_ok=True)
    target_auth = target_dir / "auth.json"
    _copy_auth_file_with_repair(source_auth, target_auth)
    _set_private_permissions(target_auth)

    meta = {
        "name": name,
        "saved_at": dt.datetime.now().isoformat(),
        "account_hint": account_hint_from_auth(target_auth),
        "source_auth": source_label,
    }
    with (target_dir / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"saved profile '{name}' -> {target_auth}")
    print(f"account: {meta['account_hint']}")


def _profile_archive_filename() -> str:
    return f"codex-account-profiles-{now_stamp()}{PROFILE_ARCHIVE_EXT}"


def _sanitize_profile_archive_filename(raw: str | None) -> str | None:
    name = str(raw or "").strip()
    if not name:
        return None
    name = name.replace("\\", "/").split("/")[-1].strip()
    suffix = PROFILE_ARCHIVE_EXT if name.lower().endswith(PROFILE_ARCHIVE_EXT) else ""
    stem = name[: -len(PROFILE_ARCHIVE_EXT)] if suffix else name
    stem = re.sub(r"\s+", "-", stem)
    stem = re.sub(r"[^A-Za-z0-9._+-]", "-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip(" ._-")
    if not stem:
        return None
    return f"{stem}{suffix or PROFILE_ARCHIVE_EXT}"


def _archive_profile_entry(name: str) -> dict:
    profile_dir = PROFILES_DIR / name
    auth_path = profile_dir / "auth.json"
    meta_path = profile_dir / "meta.json"
    if not auth_path.exists():
        raise RuntimeError(f"profile '{name}' is missing auth.json")
    if not meta_path.exists():
        raise RuntimeError(f"profile '{name}' is missing meta.json")
    return {
        "name": name,
        "account_hint": account_hint_from_auth(auth_path),
        "files": ["auth.json", "meta.json"],
    }


def _resolve_export_profile_names(names: list[str] | None = None) -> list[str]:
    ensure_dirs()
    if not names:
        resolved = [p.name for p in _existing_profile_dirs()]
        if not resolved:
            raise RuntimeError("no profiles available to export")
        return resolved
    clean: list[str] = []
    seen = set()
    for raw in names:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ensure_profile_exists(name)
        clean.append(name)
    if not clean:
        raise RuntimeError("at least one profile name is required")
    return clean


def create_profiles_archive(output_path: Path, profile_names: list[str] | None = None) -> dict:
    ensure_dirs()
    chosen = _resolve_export_profile_names(profile_names)
    manifest = {
        "format": "codex-account-profiles",
        "version": PROFILE_ARCHIVE_VERSION,
        "exported_at": dt.datetime.now().isoformat(),
        "app_version": APP_VERSION,
        "profiles": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in chosen:
            entry = _archive_profile_entry(name)
            manifest["profiles"].append(entry)
            profile_dir = PROFILES_DIR / name
            zf.write(profile_dir / "auth.json", arcname=f"profiles/{name}/auth.json")
            zf.write(profile_dir / "meta.json", arcname=f"profiles/{name}/meta.json")
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    _set_private_permissions(output_path)
    return {
        "path": str(output_path),
        "filename": output_path.name,
        "profiles": [dict(item) for item in manifest["profiles"]],
        "count": len(chosen),
        "manifest": manifest,
    }


def _read_profile_archive(archive_path: Path) -> tuple[dict, list[dict]]:
    if not archive_path.exists():
        raise RuntimeError(f"archive not found: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except KeyError:
                raise RuntimeError("archive is missing manifest.json")
            except Exception as e:
                raise RuntimeError(f"archive manifest is invalid: {e}")
            if not isinstance(manifest, dict):
                raise RuntimeError("archive manifest must be an object")
            if manifest.get("format") != "codex-account-profiles":
                raise RuntimeError("archive format is not supported")
            version = manifest.get("version")
            if int(version or 0) != PROFILE_ARCHIVE_VERSION:
                raise RuntimeError(f"unsupported archive version: {version}")
            rows = manifest.get("profiles")
            if not isinstance(rows, list) or not rows:
                raise RuntimeError("archive does not contain any profiles")
            entries: list[dict] = []
            for item in rows:
                if not isinstance(item, dict):
                    raise RuntimeError("archive manifest has an invalid profile entry")
                name = str(item.get("name") or "").strip()
                if not name:
                    raise RuntimeError("archive manifest contains a profile without a name")
                auth_member = f"profiles/{name}/auth.json"
                meta_member = f"profiles/{name}/meta.json"
                try:
                    auth_bytes = zf.read(auth_member)
                except KeyError:
                    raise RuntimeError(f"archive is missing {auth_member}")
                try:
                    meta_bytes = zf.read(meta_member)
                except KeyError:
                    raise RuntimeError(f"archive is missing {meta_member}")
                try:
                    auth_data = json.loads(auth_bytes.decode("utf-8"))
                except Exception as e:
                    raise RuntimeError(f"profile '{name}' has invalid auth.json: {e}")
                try:
                    meta_data = json.loads(meta_bytes.decode("utf-8"))
                except Exception as e:
                    raise RuntimeError(f"profile '{name}' has invalid meta.json: {e}")
                entries.append(
                    {
                        "name": name,
                        "auth_bytes": auth_bytes,
                        "meta_bytes": meta_bytes,
                        "auth_data": auth_data,
                        "meta_data": meta_data,
                        "account_hint": str(item.get("account_hint") or account_hint_from_auth_bytes(auth_data)),
                        "principal_id": _principal_id_from_data(auth_data),
                        "email": _normalized_email(_email_from_auth_data(auth_data)),
                    }
                )
            return manifest, entries
    except zipfile.BadZipFile:
        raise RuntimeError("archive is not a valid zip file")


def _email_from_auth_data(data: dict | None) -> str | None:
    if not isinstance(data, dict):
        return None
    id_token = data.get("id_token")
    if not id_token and isinstance(data.get("tokens"), dict):
        id_token = data["tokens"].get("id_token")
    if isinstance(id_token, str) and id_token:
        payload = decode_jwt_payload(id_token) or {}
        email = payload.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    return None


def account_hint_from_auth_bytes(data: dict | None) -> str:
    if not isinstance(data, dict):
        return "unknown"
    hints: list[str] = []
    account_id = _account_id_from_data(data)
    if account_id:
        hints.append(f"id:{account_id}")
    email = _email_from_auth_data(data)
    if email:
        hints.insert(0, email)
    return " | ".join(hints) if hints else "unknown"


def analyze_profiles_archive(archive_path: Path) -> dict:
    ensure_dirs()
    manifest, entries = _read_profile_archive(archive_path)
    results: list[dict] = []
    for entry in entries:
        name = str(entry["name"])
        problems: list[str] = []
        status = "ready"
        existing_name = _find_conflicting_profile_name(name)
        email = _normalized_email(entry.get("email"))
        principal_id = str(entry.get("principal_id") or "").strip()
        email_conflict = None
        principal_conflicts: list[str] = []
        if existing_name:
            status = "name_conflict"
            problems.append(f"profile name '{existing_name}' already exists")
        if email:
            dup = find_same_email_profiles(email, exclude_name=name if existing_name == name else "")
            if dup:
                email_conflict = dup[0]
                if status == "ready":
                    status = "account_conflict"
                problems.append(f"email '{email}' already exists in profile '{email_conflict}'")
        if principal_id:
            principal_conflicts = find_same_principal_profiles(principal_id, exclude_name=name if existing_name == name else "")
        action = "import"
        if status in {"name_conflict", "account_conflict"}:
            action = "skip"
        results.append(
            {
                "name": name,
                "account_hint": entry.get("account_hint") or "unknown",
                "status": status,
                "problems": problems,
                "action": action,
                "rename_to": "",
                "existing_name": existing_name or "",
                "email_conflict": email_conflict or "",
                "principal_conflicts": principal_conflicts,
            }
        )
    return {
        "manifest": manifest,
        "profiles": results,
        "summary": {
            "total": len(results),
            "ready": sum(1 for item in results if item["status"] == "ready"),
            "conflicts": sum(1 for item in results if item["status"] in {"name_conflict", "account_conflict"}),
        },
    }


def _copy_profile_from_import_entry(entry: dict, target_name: str, overwrite: bool) -> tuple[str, bool]:
    target_name = str(target_name or "").strip()
    _validate_target_profile_name(target_name, overwrite=overwrite)
    target_dir = PROFILES_DIR / target_name
    if overwrite and target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    auth_path = target_dir / "auth.json"
    meta_path = target_dir / "meta.json"
    auth_path.write_bytes(entry["auth_bytes"])
    _set_private_permissions(auth_path)
    meta = dict(entry.get("meta_data") or {})
    meta["name"] = target_name
    if not meta.get("saved_at"):
        meta["saved_at"] = dt.datetime.now().isoformat()
    meta["account_hint"] = account_hint_from_auth(auth_path)
    meta["source_auth"] = f"imported:{entry.get('archive_filename') or 'archive'}"
    meta["imported_at"] = dt.datetime.now().isoformat()
    atomic_write_json(meta_path, meta)
    _set_private_permissions(meta_path)
    return target_name, overwrite


def apply_profiles_import(archive_path: Path, plan_rows: list[dict]) -> dict:
    ensure_dirs()
    _, entries = _read_profile_archive(archive_path)
    entry_map = {str(entry["name"]): entry for entry in entries}
    results = []
    counts = {"total": 0, "imported": 0, "skipped": 0, "overwritten": 0, "failed": 0}
    for row in plan_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        action = str(row.get("action") or "skip").strip().lower()
        counts["total"] += 1
        entry = entry_map.get(name)
        if not entry:
            counts["failed"] += 1
            results.append({"name": name, "status": "failed", "message": "profile was not found in analysis set"})
            continue
        if action == "skip":
            counts["skipped"] += 1
            results.append({"name": name, "status": "skipped", "message": "skipped by user"})
            continue
        target_name = name
        overwrite = False
        if action == "rename":
            target_name = str(row.get("rename_to") or "").strip()
            if not target_name:
                counts["failed"] += 1
                results.append({"name": name, "status": "failed", "message": "rename target is required"})
                continue
        elif action == "overwrite":
            overwrite = True
        elif action != "import":
            counts["failed"] += 1
            results.append({"name": name, "status": "failed", "message": f"unsupported action '{action}'"})
            continue
        try:
            final_name, did_overwrite = _copy_profile_from_import_entry(entry, target_name=target_name, overwrite=overwrite)
            counts["imported"] += 1
            if did_overwrite:
                counts["overwritten"] += 1
            results.append({"name": name, "target_name": final_name, "status": "imported", "overwritten": did_overwrite})
        except Exception as e:
            counts["failed"] += 1
            results.append({"name": name, "status": "failed", "message": str(e)})
    return {"results": results, "summary": counts}


def prepare_profiles_export(profile_names: list[str] | None = None, filename: str | None = None) -> dict:
    _cleanup_expired_export_sessions()
    tmp_dir = ensure_cam_tmp_dir()
    archive_filename = _sanitize_profile_archive_filename(filename) or _profile_archive_filename()
    archive_path = tmp_dir / f"{secrets.token_hex(8)}-{archive_filename}"
    payload = create_profiles_archive(archive_path, profile_names=profile_names)
    payload["filename"] = archive_filename
    session_id = secrets.token_urlsafe(18)
    with EXPORT_SESSION_LOCK:
        EXPORT_SESSIONS[session_id] = {
            "path": payload["path"],
            "filename": archive_filename,
            "created_ts": time.time(),
            "count": payload["count"],
        }
    return {
        "export_id": session_id,
        "filename": archive_filename,
        "count": payload["count"],
        "profiles": payload["profiles"],
    }


def get_export_session(export_id: str) -> dict | None:
    _cleanup_expired_export_sessions()
    with EXPORT_SESSION_LOCK:
        entry = EXPORT_SESSIONS.get(export_id)
        return dict(entry) if isinstance(entry, dict) else None


def store_import_analysis(archive_filename: str, archive_bytes: bytes) -> dict:
    _cleanup_expired_import_analyses()
    tmp_dir = ensure_cam_tmp_dir()
    suffix = PROFILE_ARCHIVE_EXT if str(archive_filename or "").endswith(PROFILE_ARCHIVE_EXT) else f"-upload{PROFILE_ARCHIVE_EXT}"
    fd, tmp_path = tempfile.mkstemp(prefix="profile-import-", suffix=suffix, dir=str(tmp_dir))
    os.close(fd)
    archive_path = Path(tmp_path)
    try:
        archive_path.write_bytes(archive_bytes)
        _set_private_permissions(archive_path)
        analysis = analyze_profiles_archive(archive_path)
    except Exception:
        try:
            archive_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    analysis_id = secrets.token_urlsafe(18)
    with IMPORT_ANALYSIS_LOCK:
        IMPORT_ANALYSES[analysis_id] = {
            "path": str(archive_path),
            "created_ts": time.time(),
            "filename": archive_filename or archive_path.name,
            "profiles": analysis.get("profiles") or [],
        }
    return {
        "analysis_id": analysis_id,
        "filename": archive_filename or archive_path.name,
        "manifest": analysis["manifest"],
        "profiles": analysis["profiles"],
        "summary": analysis["summary"],
    }


def load_import_analysis(analysis_id: str) -> dict | None:
    _cleanup_expired_import_analyses()
    with IMPORT_ANALYSIS_LOCK:
        entry = IMPORT_ANALYSES.get(analysis_id)
        return copy.deepcopy(entry) if isinstance(entry, dict) else None


def clear_import_analysis(analysis_id: str) -> None:
    with IMPORT_ANALYSIS_LOCK:
        entry = IMPORT_ANALYSES.pop(analysis_id, None) or {}
    path = entry.get("path")
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


def cmd_export_profiles(profile_names: list[str] | None = None, output: str | None = None) -> int:
    try:
        filename = str(output or "").strip() or _profile_archive_filename()
        output_path = Path(filename).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        payload = create_profiles_archive(output_path, profile_names=profile_names)
        print(f"exported {payload['count']} profile(s) -> {output_path}")
        return 0
    except Exception as e:
        print(f"error: {e}")
        return 1


def cmd_import_profiles(archive_path: str, apply: bool = False, overwrite: bool = False) -> int:
    try:
        src = Path(archive_path).expanduser()
        analysis = analyze_profiles_archive(src)
        print_json(analysis)
        if not apply:
            return 0
        rows = []
        for item in analysis["profiles"]:
            action = "import"
            if item["status"] in {"name_conflict", "account_conflict"}:
                action = "overwrite" if overwrite else "skip"
            rows.append({"name": item["name"], "action": action})
        result = apply_profiles_import(src, rows)
        print_json(result)
        return 0 if int((result.get("summary") or {}).get("failed") or 0) == 0 else 1
    except Exception as e:
        print(f"error: {e}")
        return 1


def sync_profile_auth_snapshot(
    name: str,
    source_auth: Path,
    source_label: str | None = None,
    expected_principal_id: str | None = None,
) -> bool:
    name = (name or "").strip()
    if not name or not source_auth.exists():
        return False
    target_dir = PROFILES_DIR / name
    if not target_dir.exists():
        return False
    target_auth = target_dir / "auth.json"
    expected_pid = str(expected_principal_id or "").strip()
    source_data: dict | None = None
    target_data: dict | None = None
    try:
        source_data = load_json(source_auth)
        source_canonical = json.dumps(source_data, sort_keys=True, separators=(",", ":"))
    except Exception:
        return False
    try:
        target_data = load_json(target_auth) if target_auth.exists() else None
        target_canonical = json.dumps(target_data, sort_keys=True, separators=(",", ":")) if target_data else None
    except Exception:
        target_canonical = None
        target_data = None
    source_pid = str(_principal_id_from_data(source_data) or "").strip()
    target_pid = str(_principal_id_from_data(target_data) or "").strip()
    if expected_pid and source_pid and source_pid != expected_pid:
        # Guard against stale "current profile" detection races that can overwrite
        # the wrong saved profile snapshot during concurrent switch + refresh.
        return False
    if source_pid and target_pid and source_pid != target_pid:
        # Snapshot sync is for token refresh on the same account identity only.
        return False
    if target_canonical == source_canonical:
        return False
    shutil.copy2(source_auth, target_auth)
    _set_private_permissions(target_auth)

    meta_path = target_dir / "meta.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            loaded = load_json(meta_path)
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:
            meta = {}
    meta["name"] = name
    meta["account_hint"] = account_hint_from_auth(target_auth)
    meta["source_auth"] = source_label or str(source_auth)
    meta["last_synced_at"] = dt.datetime.now().isoformat()
    if not meta.get("saved_at"):
        meta["saved_at"] = dt.datetime.now().isoformat()
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return True


def cmd_save(name: str, overwrite: bool) -> int:
    ensure_dirs()
    if not AUTH_FILE.exists():
        print(f"error: auth file not found: {AUTH_FILE}")
        return 1
    try:
        write_profile(name=name, source_auth=AUTH_FILE, source_label=str(AUTH_FILE), overwrite=overwrite)
        new_id = profile_principal_id(name)
        same = find_same_principal_profiles(new_id, exclude_name=name)
        if same:
            print(f"warning: profile '{name}' has same principal id as: {', '.join(same)}")
            print("warning: switching between these profiles will not switch to a different canonical account")
    except RuntimeError as e:
        print(f"error: {e}")
        return 1
    return 0


def cmd_add(name: str, timeout: int, overwrite: bool, keep_temp_home: bool, device_auth: bool) -> int:
    ensure_dirs()
    try:
        _validate_target_profile_name(name, overwrite=overwrite)
    except RuntimeError as e:
        print(f"error: {e}")
        return 1
    tmp_root = CODEX_HOME / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        login_cmd = resolve_add_login_command(device_auth=device_auth)
    except RuntimeError as e:
        print(f"error: {e}")
        return 1

    temp_home = Path(tempfile.mkdtemp(prefix="codex-account-add-", dir=str(tmp_root)))
    temp_auth = temp_home / "auth.json"

    env = os.environ.copy()
    env["CODEX_HOME"] = str(temp_home)

    print("Starting isolated login flow...")
    if device_auth:
        print("Using device-auth flow for manual account selection.")
    else:
        print("Complete login in your browser, then return to terminal.")
    print(f"temp CODEX_HOME: {temp_home}")

    try:
        proc = _subprocess_run(login_cmd, env=env, timeout=timeout)
        if proc.returncode != 0:
            reason = f"login command failed with exit code {proc.returncode}"
            print(f"error: {reason}")
            return 1

        if not temp_auth.exists():
            print(f"error: login finished but auth file not found at {temp_auth}")
            return 1

        try:
            write_profile(name=name, source_auth=temp_auth, source_label=str(temp_auth), overwrite=overwrite)
            new_id = profile_principal_id(name)
            same = find_same_principal_profiles(new_id, exclude_name=name)
            if same:
                print(f"warning: profile '{name}' has same principal id as: {', '.join(same)}")
                print("warning: switching between these profiles will not switch to a different canonical account")
        except RuntimeError as e:
            print(f"error: {e}")
            return 1

        return 0
    except subprocess.TimeoutExpired:
        print(f"error: login timed out after {timeout} seconds")
        return 1
    finally:
        if keep_temp_home:
            print(f"kept temp home: {temp_home}")
        else:
            shutil.rmtree(temp_home, ignore_errors=True)


def collect_list_data(config: dict | None = None):
    ensure_dirs()
    profiles = sorted([p for p in PROFILES_DIR.iterdir() if p.is_dir()])
    if not profiles:
        return []
    cfg = config if isinstance(config, dict) else load_cam_config()
    eligibility = ((cfg.get("profiles") or {}).get("eligibility") or {})
    id_groups = {}
    for p in profiles:
        pid = profile_principal_id(p.name)
        if pid:
            id_groups.setdefault(pid, []).append(p.name)
    rows = []
    for p in profiles:
        meta_path = p / "meta.json"
        auth_path = p / "auth.json"
        pid = profile_principal_id(p.name)
        same_principal_with = []
        if pid and len(id_groups.get(pid, [])) > 1:
            same_principal_with = [x for x in id_groups[pid] if x != p.name]
        saved_at = None
        hint = None
        if meta_path.exists():
            try:
                meta = load_json(meta_path)
                hint = meta.get("account_hint", "unknown")
                saved_at = meta.get("saved_at", "unknown")
            except Exception:
                pass
        if hint is None:
            hint = account_hint_from_auth(auth_path) if auth_path.exists() else "missing auth"
        rows.append(
            {
                "name": p.name,
                "account_hint": hint,
                "saved_at": saved_at,
                "account_id": account_id_from_auth(auth_path),
                "same_principal": len(same_principal_with) > 0,
                "same_principal_with": same_principal_with,
                "auto_switch_eligible": bool(eligibility.get(p.name, False)),
            }
        )
    return rows


def cmd_list(as_json: bool = False) -> int:
    rows = collect_list_data()
    if not rows:
        if as_json:
            print_json({"profiles": []})
        else:
            print("no profiles yet")
        return 0
    if as_json:
        print_json({"profiles": rows})
        return 0
    for row in rows:
        same_note = ""
        if row["same_principal_with"]:
            same_note = f" [same principal as: {', '.join(row['same_principal_with'])}]"
        if row["saved_at"]:
            print(f"- {row['name']}: {row['account_hint']} (saved {row['saved_at']}){same_note}")
        else:
            print(f"- {row['name']}: {row['account_hint']}{same_note}")
    return 0


def _build_usage_profile_context(config: dict | None = None):
    ensure_dirs()
    profiles = sorted([p for p in PROFILES_DIR.iterdir() if p.is_dir()])
    cfg = config if isinstance(config, dict) else load_cam_config()
    eligibility = ((cfg.get("profiles") or {}).get("eligibility") or {})

    def canonical_auth(path: Path):
        try:
            data = load_json(path)
            return json.dumps(data, sort_keys=True, separators=(",", ":"))
        except Exception:
            return None

    active_canonical = canonical_auth(AUTH_FILE) if AUTH_FILE.exists() else None
    active_principal_id = None
    active_email = ""
    if AUTH_FILE.exists():
        try:
            active_data = load_json(AUTH_FILE)
            active_principal_id = _principal_id_from_data(active_data)
            tokens = active_data.get("tokens", {}) if isinstance(active_data.get("tokens"), dict) else {}
            id_token = tokens.get("id_token") or active_data.get("id_token")
            if isinstance(id_token, str) and id_token:
                payload = decode_jwt_payload(id_token) or {}
                maybe_email = payload.get("email")
                if maybe_email:
                    active_email = str(maybe_email).strip().lower()
        except Exception:
            active_principal_id = None
            active_email = ""
    principal_counts: dict[str, int] = {}
    profile_meta: dict[str, dict] = {}
    for p in profiles:
        auth_path = p / "auth.json"
        entry = {
            "canonical": None,
            "principal_id": None,
            "account_id": "-",
            "email": "-",
            "raw_data": None,
        }
        try:
            data = load_json(auth_path)
            entry["raw_data"] = data
            entry["canonical"] = json.dumps(data, sort_keys=True, separators=(",", ":"))
            entry["principal_id"] = _principal_id_from_data(data)
            entry["account_id"] = _account_id_from_data(data) or "-"
            tokens = data.get("tokens", {}) if isinstance(data.get("tokens"), dict) else {}
            id_token = tokens.get("id_token") or data.get("id_token")
            if isinstance(id_token, str) and id_token:
                payload = decode_jwt_payload(id_token) or {}
                maybe_email = payload.get("email")
                if maybe_email:
                    entry["email"] = str(maybe_email)
        except Exception:
            pass
        pid = entry["principal_id"]
        if pid:
            principal_counts[pid] = principal_counts.get(pid, 0) + 1
        profile_meta[p.name] = entry

    current_profile = None
    for p in profiles:
        profile_canonical = (profile_meta.get(p.name) or {}).get("canonical")
        if active_canonical is not None and profile_canonical and profile_canonical == active_canonical:
            current_profile = p.name
            break
    if current_profile is None and active_principal_id:
        for p in profiles:
            if str((profile_meta.get(p.name) or {}).get("principal_id") or "") == str(active_principal_id):
                current_profile = p.name
                break
    if current_profile is None and active_email:
        for p in profiles:
            profile_email = str((profile_meta.get(p.name) or {}).get("email") or "").strip().lower()
            if profile_email and profile_email == active_email:
                current_profile = p.name
                break

    return {
        "profiles": profiles,
        "cfg": cfg,
        "eligibility": eligibility,
        "profile_meta": profile_meta,
        "principal_counts": principal_counts,
        "current_profile": current_profile,
    }


def _build_usage_profile_row(profile_dir: Path, context: dict, timeout_sec: int) -> dict:
    cfg = context.get("cfg") or {}
    eligibility = context.get("eligibility") or {}
    profile_meta = context.get("profile_meta") or {}
    principal_counts = context.get("principal_counts") or {}
    current_profile = str(context.get("current_profile") or "")
    p = profile_dir
    auth_path = p / "auth.json"
    if current_profile and p.name == current_profile and AUTH_FILE.exists():
        # The active Codex session may refresh tokens after a switch, so the live auth
        # file is more accurate than the saved profile snapshot for the current row.
        auth_path = AUTH_FILE
    meta_path = p / "meta.json"
    entry = profile_meta.get(p.name) or {}
    display_email = entry.get("email", "-")
    saved_at = None
    if meta_path.exists():
        try:
            meta = load_json(meta_path)
            saved_at = meta.get("saved_at")
        except Exception:
            saved_at = None
    account_id = str(entry.get("account_id", "-") or "-")
    principal_id = entry.get("principal_id")
    usage_5h, usage_weekly, plan_type, is_paid, err = fetch_usage_from_auth(auth_path, timeout_sec=timeout_sec)
    if current_profile and p.name == current_profile and auth_path == AUTH_FILE and err is None:
        try:
            sync_profile_auth_snapshot(
                p.name,
                AUTH_FILE,
                str(AUTH_FILE),
                expected_principal_id=str(entry.get("principal_id") or ""),
            )
        except Exception:
            pass
    cell_5h = format_usage_cell(*(usage_5h or (None, None)))
    cell_weekly = format_usage_cell(*(usage_weekly or (None, None)))
    same = bool(principal_id and int(principal_counts.get(str(principal_id), 0)) > 1)
    return {
        "name": p.name,
        "email": display_email,
        "account_id": account_id,
        "usage_5h": {
            "remaining_percent": usage_5h[0] if usage_5h else None,
            "resets_at": usage_5h[1] if usage_5h else None,
            "text": cell_5h,
        },
        "usage_weekly": {
            "remaining_percent": usage_weekly[0] if usage_weekly else None,
            "resets_at": usage_weekly[1] if usage_weekly else None,
            "text": cell_weekly,
        },
        "plan_type": plan_type,
        "is_paid": is_paid,
        "is_current": bool(current_profile and p.name == current_profile),
        "same_principal": same,
        "error": err or None,
        "saved_at": saved_at,
        "auto_switch_eligible": bool(eligibility.get(p.name, False)),
    }


def collect_usage_local_data(timeout_sec: int, config: dict | None = None, profile_names: list[str] | None = None):
    context = _build_usage_profile_context(config=config)
    profiles = context.get("profiles") or []
    current_profile = context.get("current_profile")
    if not profiles:
        return {"refreshed_at": dt.datetime.now().isoformat(), "current_profile": None, "profiles": []}
    selected_names = None
    if profile_names is not None:
        selected_names = {str(name).strip() for name in profile_names if str(name).strip()}
    selected_profiles = [p for p in profiles if selected_names is None or p.name in selected_names]
    json_rows = []
    for p in selected_profiles:
        json_rows.append(_build_usage_profile_row(p, context, timeout_sec))
    return {"refreshed_at": dt.datetime.now().isoformat(), "current_profile": current_profile, "profiles": json_rows}


def _native_notification_test_base_url(host: str, port: int) -> str:
    return f"http://{host}:{int(port)}/"


def run_native_notification_test(host: str, port: int, timeout_sec: int = 7) -> dict:
    cfg = load_cam_config()
    usage_payload = collect_usage_local_data(timeout_sec=timeout_sec, config=cfg)
    return native_notifications.send_native_test_notification(
        usage_payload=usage_payload,
        base_url=_native_notification_test_base_url(host, port),
    )


def cmd_usage_local(timeout_sec: int, as_json: bool = False) -> int:
    payload = collect_usage_local_data(timeout_sec)
    if as_json:
        print_json(payload)
        return 0
    if not payload["profiles"]:
        print("no profiles yet")
        return 0

    use_color = sys.stdout.isatty()
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def visible_len(s: str) -> int:
        return len(ansi_re.sub("", s))

    def pad_cell(s: str, width: int) -> str:
        return s + (" " * max(0, width - visible_len(s)))

    def colorize_usage(cell: str) -> str:
        if not use_color:
            return cell
        m = re.match(r"^(\d+)%", cell)
        if not m:
            return cell
        pct = int(m.group(1))
        if pct < 25:
            return f"\033[1;31m{cell}\033[0m"
        if pct < 50:
            return f"\033[1;38;5;208m{cell}\033[0m"
        if pct < 75:
            return f"\033[1;33m{cell}\033[0m"
        return f"\033[1;32m{cell}\033[0m"

    header = f"{'CUR':<4} {'PROFILE':<14} {'EMAIL':<31} {'5H':<16} {'WEEKLY':<16} {'ID':<36}"
    print(header)
    print("-" * len(header))
    same_principal_profiles = []
    for item in payload["profiles"]:
        em = item["email"] if len(item["email"]) <= 31 else item["email"][:28] + "..."
        aid = item["account_id"] if len(item["account_id"]) <= 36 else item["account_id"][:33] + "..."
        cur = "*" if item["is_current"] else ""
        cell_5h = colorize_usage(item["usage_5h"]["text"])
        cell_weekly = colorize_usage(item["usage_weekly"]["text"])
        if item["same_principal"]:
            same_principal_profiles.append(item["name"])
        row = " ".join(
            [
                pad_cell(cur, 4),
                pad_cell(item["name"], 14),
                pad_cell(em, 31),
                pad_cell(cell_5h, 16),
                pad_cell(cell_weekly, 16),
                pad_cell(aid, 36),
            ]
        )
        print(row)
        if item["error"]:
            print(f"{'':<4} {'':<14} {'':<31} {'':<16} {'':<16} {'':<36} error: {item['error']}")
    if same_principal_profiles:
        uniq = ", ".join(sorted(set(same_principal_profiles)))
        print(f"\nwarning: same principal id detected for profiles: {uniq}")
    return 0


def cmd_usage_local_watch(timeout_sec: int, interval_sec: float) -> int:
    if interval_sec <= 0:
        print("error: --interval must be > 0")
        return 1
    try:
        while True:
            if sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            rc = cmd_usage_local(timeout_sec)
            if rc != 0:
                return rc
            ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[watch] refreshed at {ts} | next update in {interval_sec:.1f}s (Ctrl+C to stop)")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\nStopped usage watch.")
        return 0


def collect_current_data():
    if not AUTH_FILE.exists():
        return {"ok": False, "error": f"no active auth file at {AUTH_FILE}"}
    hint = account_hint_from_auth(AUTH_FILE)
    return {
        "ok": True,
        "account_hint": hint,
        "account_id": account_id_from_auth(AUTH_FILE),
    }


def cmd_current(as_json: bool = False) -> int:
    payload = collect_current_data()
    if not payload["ok"]:
        if as_json:
            print_json({"error": payload["error"]})
        else:
            print(payload["error"])
        return 1
    if as_json:
        print_json({"account_hint": payload["account_hint"], "account_id": payload["account_id"]})
        return 0
    print(payload["account_hint"])
    return 0


def cmd_switch(name: str, restart_codex: bool) -> int:
    ensure_dirs()
    try:
        source_auth = ensure_profile_exists(name)
    except RuntimeError as e:
        print(f"error: {e}")
        _log_runtime_safe("error", "switch failed missing profile", {"name": name, "error": str(e)})
        return 1

    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)

    running_app = None
    running_exec_path = ""
    if restart_codex:
        try:
            running_app = detect_running_app_name()
        except Exception:
            running_app = None
        if sys.platform.startswith("win"):
            try:
                running_exec_path = _detect_running_codex_executable_windows() or ""
            except Exception:
                running_exec_path = ""
    _log_runtime_safe(
        "info",
        "switch begin",
        {"name": name, "restart_codex": bool(restart_codex), "running_app": running_app, "running_exec_path": running_exec_path},
    )
    if restart_codex and running_app:
        try:
            stop_codex()
            _log_runtime_safe("info", "switch stop_codex requested", {"running_app": running_app})
        except Exception:
            pass

    if AUTH_FILE.exists():
        backup = BACKUPS_DIR / f"auth-{now_stamp()}.json"
        shutil.copy2(AUTH_FILE, backup)
        _set_private_permissions(backup)

    try:
        shutil.copy2(source_auth, AUTH_FILE)
    except PermissionError as e:
        repaired = _ensure_windows_user_writable(AUTH_FILE)
        if repaired:
            try:
                shutil.copy2(source_auth, AUTH_FILE)
            except PermissionError as e2:
                msg = (
                    f"cannot write auth file ({AUTH_FILE}). It is locked by a running app or denied by file permissions."
                )
                print(f"error: {msg}")
                print("hint: close Codex/ChatGPT windows and verify your user has write access to auth.json")
                _log_runtime_safe("error", "switch auth copy permission denied after repair", {"name": name, "target_auth": str(AUTH_FILE), "repaired": repaired, "error": str(e2)})
                return 1
        else:
            msg = (
                f"cannot write auth file ({AUTH_FILE}). It is locked by a running app or denied by file permissions."
            )
            print(f"error: {msg}")
            print("hint: close Codex/ChatGPT windows and verify your user has write access to auth.json")
            _log_runtime_safe("error", "switch auth copy permission denied", {"name": name, "target_auth": str(AUTH_FILE), "repaired": repaired, "error": str(e)})
            return 1
    _set_private_permissions(AUTH_FILE)
    _log_runtime_safe("info", "switch auth copied", {"name": name, "source_auth": str(source_auth), "target_auth": str(AUTH_FILE)})

    print(f"switched to profile '{name}'")
    print(f"active account: {account_hint_from_auth(AUTH_FILE)}")
    switched_id = principal_id_from_auth(AUTH_FILE)
    same = find_same_principal_profiles(switched_id, exclude_name=name)
    if same:
        print(f"note: '{name}' has same principal id as: {', '.join(same)}")
        print("note: this switch may not change your effective canonical account")
        _log_runtime_safe("warn", "switch same principal", {"name": name, "same_with": same, "principal_id": switched_id})

    if restart_codex:
        started = False
        try:
            started = start_codex(preferred_app_name=running_app or "Codex", preferred_exec_path=running_exec_path)
        except Exception:
            started = False
        _log_runtime_safe("info", "switch restart result", {"name": name, "started": bool(started)})
        if started:
            print("Codex/CodexBar restart requested")
        else:
            print("warning: automatic Codex restart is unavailable on this system; start it manually if needed")
    else:
        print("start Codex manually if needed")
    return 0


def restart_codex_app(preferred_app_name: str = "", preferred_exec_path: str = "") -> bool:
    running_app = (preferred_app_name or "").strip() or None
    running_exec_path = (preferred_exec_path or "").strip()
    if not running_app:
        try:
            running_app = detect_running_app_name()
        except Exception:
            running_app = None
    if sys.platform.startswith("win") and not running_exec_path:
        try:
            running_exec_path = _detect_running_codex_executable_windows() or ""
        except Exception:
            running_exec_path = ""
    if running_app:
        try:
            stop_codex()
            _log_runtime_safe("info", "restart stop_codex requested", {"running_app": running_app})
        except Exception as e:
            _log_runtime_safe("warn", "restart stop_codex failed", {"running_app": running_app, "error": str(e)})
    started = False
    try:
        started = start_codex(preferred_app_name=running_app or "Codex", preferred_exec_path=running_exec_path)
    except Exception as e:
        _log_runtime_safe("warn", "restart start_codex exception", {"error": str(e)})
        started = False
    _log_runtime_safe(
        "info",
        "restart final result",
        {
            "started": bool(started),
            "running_app": running_app,
            "running_exec_path": running_exec_path,
            "preferred_app_name": preferred_app_name,
            "preferred_exec_path": preferred_exec_path,
        },
    )
    return started


def cmd_run(name: str, command_args) -> int:
    ensure_dirs()
    try:
        profile_home = prepare_profile_home(name)
        codex_cli = resolve_codex_cli()
    except RuntimeError as e:
        print(f"error: {e}")
        return 1

    env = os.environ.copy()
    env["CODEX_HOME"] = str(profile_home)

    if command_args and command_args[0] == "--":
        command_args = command_args[1:]
    cmd = command_args if command_args else [codex_cli]
    if cmd and cmd[0] == "codex":
        cmd = [codex_cli] + cmd[1:]

    print(f"profile home: {profile_home}")
    print(f"running: {' '.join(cmd)}")
    return _subprocess_call(cmd, env=env)


def cmd_remove(name: str) -> int:
    target_dir = PROFILES_DIR / name
    if not target_dir.exists():
        print(f"error: profile '{name}' not found")
        return 1
    shutil.rmtree(target_dir)
    print(f"removed profile '{name}'")
    return 0


def cmd_remove_all_profiles() -> int:
    ensure_dirs()
    profiles = sorted([p for p in PROFILES_DIR.iterdir() if p.is_dir()])
    if not profiles:
        print("no profiles to remove")
        return 0
    removed = 0
    for p in profiles:
        try:
            shutil.rmtree(p)
            removed += 1
        except Exception as e:
            print(f"warning: failed to remove '{p.name}': {e}")
    print(f"removed {removed} profile(s)")
    return 0


def cmd_rename(old_name: str, new_name: str, force: bool = False) -> int:
    ensure_dirs()
    src = PROFILES_DIR / old_name
    dst = PROFILES_DIR / new_name
    if not src.exists() or not src.is_dir():
        print(f"error: profile '{old_name}' not found")
        return 1
    if old_name == new_name:
        print("error: old and new profile names are the same")
        return 1
    if dst.exists():
        if not force:
            print(f"error: profile '{new_name}' already exists (use --force)")
            return 1
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))
    meta_path = dst / "meta.json"
    if meta_path.exists():
        try:
            meta = load_json(meta_path)
            meta["name"] = new_name
            with meta_path.open("w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass
    print(f"renamed profile '{old_name}' -> '{new_name}'")
    return 0


def collect_status_data():
    result = run_codex_auth_capture(["status"])
    payload = parse_status_output(result["stdout"])
    payload["ok"] = result["ok"]
    payload["exit_code"] = result["exit_code"]
    payload["error"] = result["error"]
    payload["stderr"] = result["stderr"]
    return payload


def cmd_status(as_json: bool = False) -> int:
    if not as_json:
        return run_codex_auth(["status"])
    payload = collect_status_data()
    print_json(payload)
    return 0 if payload["ok"] else 1


def detect_python_runtime() -> dict:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return {
        "available": True,
        "supported": sys.version_info >= (3, 11),
        "version": version,
        "path": sys.executable,
        "command": Path(sys.executable).name,
    }


def detect_core_runtime(command_name: str = "codex-account") -> dict:
    command_path = shutil.which(command_name)
    argv0 = str(Path(sys.argv[0]).resolve()) if sys.argv and sys.argv[0] else ""
    installed = bool(command_path or argv0)
    resolved = str(command_path or argv0)
    return {
        "installed": installed,
        "version": APP_VERSION if installed else "",
        "command_path": resolved,
        "min_supported_version": APP_VERSION,
        "meets_minimum_version": installed,
    }


def build_doctor_report(command_name: str = "codex-account", host: str = UI_DEFAULT_HOST, port: int = UI_DEFAULT_PORT) -> dict:
    python_runtime = detect_python_runtime()
    core_runtime = detect_core_runtime(command_name=command_name)
    info = read_ui_pid_info() or {}
    service_host = str(info.get("host") or host)
    service_port = int(info.get("port") or port)
    running = is_ui_healthy(service_host, service_port)
    ui_service = {
        "running": running,
        "healthy": running,
        "host": service_host,
        "port": service_port,
        "base_url": ui_url(service_host, service_port),
        "token": str(info.get("token") or ""),
        "pid": info.get("pid"),
    }
    errors = []
    if not python_runtime["available"]:
        errors.append({"code": "PYTHON_MISSING", "message": "Python runtime was not detected."})
    elif not python_runtime["supported"]:
        errors.append({"code": "PYTHON_UNSUPPORTED", "message": "Python 3.11+ is required."})
    if not core_runtime["installed"]:
        errors.append({"code": "CORE_MISSING", "message": "Codex Account Manager core is not installed."})
    return {
        "python": python_runtime,
        "core": core_runtime,
        "ui_service": ui_service,
        "errors": errors,
    }


def cmd_doctor(as_json: bool = False) -> int:
    payload = build_doctor_report()
    if as_json:
        print_json(payload)
    else:
        print_json(payload)
    return 0


def cmd_auth_passthrough(command_args) -> int:
    if command_args and command_args[0] == "--":
        command_args = command_args[1:]
    if not command_args:
        print("error: missing codex-auth args. Example: codex-account auth -- list")
        return 1
    return run_codex_auth(command_args)


def _error_type_for_code(code: str, status: int) -> str:
    c = str(code or "").upper()
    if status >= 500:
        return "internal"
    if c in {"FORBIDDEN", "UNAUTHORIZED"}:
        return "permission"
    if c.startswith("BAD_") or c.startswith("MISSING_") or c in {"NO_CANDIDATE", "RAPID_TEST_BUSY", "NOT_FOUND"}:
        return "validation"
    if c in {"COMMAND_FAILED", "START_FAILED", "BAD_CONFIG"}:
        return "transient"
    return "validation" if status < 500 else "internal"


def _json_error(code: str, message: str, status: int = 400, details=None):
    payload = {"ok": False, "error": {"code": code, "type": _error_type_for_code(code, status), "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return status, payload


def _json_ok(data):
    return 200, {"ok": True, "data": data}


def _capture_fn(fn):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn()
    return rc, out.getvalue(), err.getvalue()


def _command_result(name: str, rc: int, stdout: str, stderr: str):
    return CommandResult(command=name, exit_code=rc, stdout=stdout, stderr=stderr).to_dict()


def build_auto_switch_state_payload(runtime: dict, cfg: dict, now: float | None = None) -> dict:
    now_ts = time.time() if now is None else float(now)
    auto_cfg = cfg.get("auto_switch") or {}
    cooldown_cfg = int((cfg.get("auto_switch") or {}).get("cooldown_sec", 60))
    cooldown_sec = max(AUTO_SWITCH_MIN_INTERNAL_COOLDOWN_SEC, cooldown_cfg)
    last_sw = runtime.get("last_switch_ts")
    cooldown_until = (last_sw + cooldown_sec) if last_sw else None
    return {
        "active": bool(runtime.get("active", False)),
        "last_evaluated_at": runtime.get("last_eval_ts"),
        "last_evaluated_at_text": epoch_to_text(runtime.get("last_eval_ts")),
        "pending_warning": runtime.get("pending_warning"),
        "pending_switch_due_at": runtime.get("pending_switch_due_at"),
        "pending_switch_due_at_text": epoch_to_text(runtime.get("pending_switch_due_at")),
        "cooldown_until": cooldown_until,
        "cooldown_until_text": epoch_to_text(cooldown_until),
        "cooldown_remaining_sec": max(0, int(cooldown_until - now_ts)) if cooldown_until else 0,
        "last_switch_at": runtime.get("last_switch_ts"),
        "last_switch_at_text": epoch_to_text(runtime.get("last_switch_ts")),
        "events_count": len(runtime.get("events") or []),
        "config_enabled": bool(auto_cfg.get("enabled")),
        "config_delay_sec": int(auto_cfg.get("delay_sec", 60)),
        "rapid_test_active": bool(runtime.get("rapid_test_active", False)),
        "rapid_test_started_at": runtime.get("rapid_test_started_at"),
        "rapid_test_started_at_text": epoch_to_text(runtime.get("rapid_test_started_at")),
        "rapid_test_wait_sec": runtime.get("rapid_test_wait_sec"),
        "rapid_test_step": int(runtime.get("rapid_test_step") or 0),
        "test_run_active": bool(runtime.get("test_run_active", False)),
        "switch_in_flight": bool(runtime.get("switch_in_flight", False)),
        "switch_target": str(runtime.get("switch_target") or ""),
        "switch_started_at": runtime.get("switch_started_at") or None,
        "switch_started_at_text": epoch_to_text(runtime.get("switch_started_at")),
    }


def _normalize_release_tag(raw: str | None) -> str:
    tag = str(raw or "").strip().lower()
    if tag.startswith("release "):
        tag = tag.split(" ", 1)[1].strip()
    if tag.startswith("v"):
        tag = tag[1:]
    return re.sub(r"[^0-9a-z.+_-]", "", tag)


def _release_version_key(raw: str | None) -> tuple:
    tag = _normalize_release_tag(raw)
    if not tag:
        return (0, 0, 0, 0, 0, "")
    base = re.split(r"[-+]", tag, maxsplit=1)[0]
    nums = [int(x) for x in re.findall(r"\d+", base)]
    nums = (nums + [0, 0, 0])[:3]
    suffix = ""
    if "-" in tag:
        suffix = tag.split("-", 1)[1]
    elif "+" in tag:
        suffix = tag.split("+", 1)[1]
    suffix_rank = 1 if not suffix else 0
    suffix_nums = [int(x) for x in re.findall(r"\d+", suffix)]
    suffix_num = suffix_nums[0] if suffix_nums else 0
    return (nums[0], nums[1], nums[2], suffix_rank, suffix_num, suffix)


def _is_current_release_tag(tag: str | None) -> bool:
    return bool(_normalize_release_tag(tag) and _normalize_release_tag(tag) == _normalize_release_tag(APP_VERSION))


def _extract_release_highlights(body: str, max_items: int = 12) -> list[str]:
    out: list[str] = []
    for line in str(body or "").splitlines():
        m = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if not m:
            continue
        out.append(m.group(1).strip())
        if len(out) >= max(1, int(max_items)):
            break
    return out


def _normalize_github_release_rows(rows) -> list[dict]:
    out: list[dict] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        if bool(row.get("draft")):
            continue
        tag = str(row.get("tag_name") or row.get("name") or "").strip()
        if not tag:
            continue
        title = str(row.get("name") or tag).strip() or tag
        body = row.get("body") if isinstance(row.get("body"), str) else ""
        published_at = str(row.get("published_at") or row.get("created_at") or "").strip() or None
        url = str(row.get("html_url") or "").strip() or f"{PROJECT_RELEASES_URL}/tag/{quote(tag)}"
        out.append(
            {
                "tag": tag,
                "version": tag,
                "title": title,
                "published_at": published_at,
                "body": body,
                "highlights": _extract_release_highlights(body),
                "url": url,
                "is_prerelease": bool(row.get("prerelease")),
                "is_draft": False,
                "is_current": _is_current_release_tag(tag),
                "source": "github",
            }
        )
    out.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    return out


def _fetch_github_release_notes(timeout_sec: float = 5.0) -> list[dict]:
    req = urllib.request.Request(
        GITHUB_RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "codex-account-manager-ui",
        },
    )
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_sec))) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    return _normalize_github_release_rows(payload)


def _parse_local_release_notes(path: Path | None = None) -> list[dict]:
    source_path = path or RELEASE_NOTES_FALLBACK_FILE
    try:
        content = source_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    sections: list[tuple[str, list[str]]] = []
    current_tag = None
    current_lines: list[str] = []
    for line in content.splitlines():
        m = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if m:
            if current_tag is not None:
                sections.append((current_tag, current_lines))
            current_tag = m.group(1).strip()
            current_lines = []
            continue
        if current_tag is not None:
            current_lines.append(line)
    if current_tag is not None:
        sections.append((current_tag, current_lines))
    out: list[dict] = []
    for tag, lines in sections:
        body = "\n".join(lines).strip()
        low = str(tag).strip().lower()
        is_unreleased = low == "unreleased"
        url = None if is_unreleased else f"{PROJECT_RELEASES_URL}/tag/{quote(str(tag).strip())}"
        is_pre = any(marker in low for marker in ("alpha", "beta", "rc", "pre-release", "pre"))
        out.append(
            {
                "tag": str(tag).strip(),
                "version": str(tag).strip(),
                "title": str(tag).strip(),
                "published_at": None,
                "body": body,
                "highlights": _extract_release_highlights(body),
                "url": url,
                "is_prerelease": is_pre,
                "is_draft": False,
                "is_current": _is_current_release_tag(tag),
                "source": "local",
            }
        )
    return out


def load_release_notes_payload(
    *,
    force_refresh: bool = False,
    cache: dict | None = None,
    now_ts: float | None = None,
    fetcher=None,
    fallback_path: Path | None = None,
) -> dict:
    cache_obj = cache if isinstance(cache, dict) else {}
    now = float(now_ts if now_ts is not None else time.time())
    cached_payload = cache_obj.get("payload")
    cached_ts = float(cache_obj.get("ts") or 0.0)
    if not force_refresh and isinstance(cached_payload, dict) and (now - cached_ts) < RELEASE_NOTES_CACHE_TTL_SEC:
        return {**cached_payload, "cached": True, "cache_ttl_sec": int(RELEASE_NOTES_CACHE_TTL_SEC)}
    fetch_fn = fetcher or _fetch_github_release_notes
    fallback = fallback_path or RELEASE_NOTES_FALLBACK_FILE
    payload = None
    try:
        releases = fetch_fn()
        if not isinstance(releases, list):
            raise RuntimeError("invalid releases payload")
        if releases:
            payload = {
                "status": "synced",
                "status_text": "Synced from GitHub",
                "source": "github",
                "repo_url": PROJECT_RELEASES_URL,
                "fetched_at": dt.datetime.now().isoformat(),
                "releases": releases,
                "error": None,
            }
        else:
            raise RuntimeError("GitHub releases returned empty list")
    except Exception as e:
        fallback_releases = _parse_local_release_notes(fallback)
        if fallback_releases:
            payload = {
                "status": "fallback",
                "status_text": "Showing local fallback",
                "source": "local",
                "repo_url": PROJECT_RELEASES_URL,
                "fetched_at": dt.datetime.now().isoformat(),
                "releases": fallback_releases,
                "error": str(e),
            }
        else:
            payload = {
                "status": "failed",
                "status_text": "Failed to load release notes",
                "source": "none",
                "repo_url": PROJECT_RELEASES_URL,
                "fetched_at": dt.datetime.now().isoformat(),
                "releases": [],
                "error": str(e),
            }
    cache_obj["ts"] = now
    cache_obj["payload"] = payload
    return {**payload, "cached": False, "cache_ttl_sec": int(RELEASE_NOTES_CACHE_TTL_SEC)}


def _latest_stable_release(releases) -> dict | None:
    rows = [row for row in (releases or []) if isinstance(row, dict) and not bool(row.get("is_draft")) and not bool(row.get("is_prerelease"))]
    if not rows:
        return None
    return max(rows, key=lambda row: (_release_version_key(row.get("tag") or row.get("version")), str(row.get("published_at") or "")))


def build_update_status_payload(release_payload: dict | None) -> dict:
    payload = release_payload if isinstance(release_payload, dict) else {}
    releases = payload.get("releases")
    latest_release = _latest_stable_release(releases if isinstance(releases, list) else [])
    current_version = f"v{APP_VERSION}"
    latest_version = ""
    update_available = False
    if latest_release:
        latest_version = str(latest_release.get("tag") or latest_release.get("version") or "").strip()
        update_available = _release_version_key(latest_version) > _release_version_key(APP_VERSION)
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "status": str(payload.get("status") or ""),
        "status_text": str(payload.get("status_text") or ""),
        "source": str(payload.get("source") or ""),
        "repo_url": str(payload.get("repo_url") or PROJECT_RELEASES_URL),
        "error": payload.get("error"),
        "fetched_at": payload.get("fetched_at"),
        "latest_release": latest_release,
        "release_notes": payload,
    }


def run_app_update_command() -> dict:
    pipx_bin = shutil.which("pipx")
    command = [pipx_bin or "pipx", "upgrade", "codex-account-manager"]
    if not pipx_bin:
        return {
            "ok": False,
            "updated": False,
            "command": command,
            "stdout": "",
            "stderr": "pipx was not found in PATH. Install pipx first, then run: pipx upgrade codex-account-manager",
            "returncode": None,
        }
    try:
        proc = _subprocess_run(command, capture_output=True, text=True, timeout=900)
    except Exception as e:
        return {
            "ok": False,
            "updated": False,
            "command": command,
            "stdout": "",
            "stderr": str(e),
            "returncode": None,
        }
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "updated": ok,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": proc.returncode,
    }


def render_ui_html(default_interval: float, token: str) -> str:
    html_path = Path(__file__).parent / "web" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    html = html.replace("__INTERVAL_INT__", str(int(default_interval)))
    html = html.replace("__UI_VERSION__", APP_VERSION)
    return html


def render_ui_js(token: str) -> str:
    js_path = Path(__file__).parent / "web" / "app.js"
    js = js_path.read_text(encoding="utf-8")
    js = js.replace("__TOKEN_JSON__", json.dumps(token))
    js = js.replace("__UI_VERSION_JSON__", json.dumps(APP_VERSION))
    return js


def render_ui_css() -> str:
    css_path = Path(__file__).parent / "web" / "styles.css"
    return css_path.read_text(encoding="utf-8")


def render_ui_sw_js() -> str:
    sw_path = Path(__file__).parent / "web" / "sw.js"
    script = sw_path.read_text(encoding="utf-8")
    return script.replace("__UI_VERSION__", APP_VERSION)

def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def epoch_to_text(ts):
    if not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(float(ts)).isoformat(sep=" ", timespec="seconds")
    except Exception:
        return None


def _remaining_pct(row: dict, key: str):
    try:
        v = ((row.get(key) or {}).get("remaining_percent"))
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _reset_score(ts, window_seconds: float) -> float:
    if not ts:
        return 0.0
    try:
        remain = max(0.0, float(ts) - time.time())
    except Exception:
        return 0.0
    return max(0.0, min(100.0, (remain / max(1.0, window_seconds)) * 100.0))


def _normalized_saved_at_ts(saved_at: str | None) -> float:
    if not saved_at:
        return 0.0
    try:
        return dt.datetime.fromisoformat(saved_at).timestamp()
    except Exception:
        return 0.0


def _candidate_score(row: dict, cfg: dict) -> tuple[float, tuple]:
    auto = (cfg.get("auto_switch") or {})
    mode = auto.get("ranking_mode", "balanced")
    r5 = _remaining_pct(row, "usage_5h")
    rw = _remaining_pct(row, "usage_weekly")
    exhausted_5h = r5 is not None and float(r5) <= 0.0
    exhausted_weekly = rw is not None and float(rw) <= 0.0
    r5n = float(r5 if r5 is not None else 0.0)
    rwn = float(rw if rw is not None else 0.0)
    s5 = _reset_score(((row.get("usage_5h") or {}).get("resets_at")), 5.0 * 3600.0)
    sw = _reset_score(((row.get("usage_weekly") or {}).get("resets_at")), 7.0 * 24.0 * 3600.0)
    if mode == "max_5h":
        score = r5n
    elif mode == "max_weekly":
        score = rwn
    else:
        score = 0.40 * r5n + 0.35 * rwn + 0.15 * s5 + 0.10 * sw
    if exhausted_5h:
        score -= 1000.0
    if exhausted_weekly:
        score -= 800.0
    tie = (
        1 if not exhausted_5h else 0,
        1 if not exhausted_weekly else 0,
        rwn,
        r5n,
        _normalized_saved_at_ts(row.get("saved_at")),
        (row.get("name") or "").lower(),
    )
    return score, tie


def _trigger_breached(current_row: dict, cfg: dict) -> tuple[bool, dict]:
    auto = (cfg.get("auto_switch") or {})
    thr = (auto.get("thresholds") or {})
    mode = auto.get("trigger_mode", "any")
    use_h5 = True
    use_weekly = True
    p5 = _remaining_pct(current_row, "usage_5h")
    pw = _remaining_pct(current_row, "usage_weekly")
    h5_hit = use_h5 and p5 is not None and p5 <= float(thr.get("h5_switch_pct", 20))
    w_hit = use_weekly and pw is not None and pw <= float(thr.get("weekly_switch_pct", 20))
    active_hits = []
    if use_h5:
        active_hits.append(h5_hit)
    if use_weekly:
        active_hits.append(w_hit)
    breached = False if not active_hits else ((any(active_hits)) if mode == "any" else all(active_hits))
    return breached, {
        "use_h5": use_h5,
        "use_weekly": use_weekly,
        "h5_hit": h5_hit,
        "weekly_hit": w_hit,
        "remaining_5h": p5,
        "remaining_weekly": pw,
    }


def _choose_auto_switch_candidate(usage_payload: dict, cfg: dict):
    rows = usage_payload.get("profiles") or []
    current_name = usage_payload.get("current_profile")
    auto = (cfg.get("auto_switch") or {})
    ranking_mode = str(auto.get("ranking_mode") or "balanced")
    if ranking_mode == "manual":
        return _choose_manual_chain_target(usage_payload, cfg)
    same_policy = auto.get("same_principal_policy", "skip")
    cands = []
    cands_by_name: dict[str, dict] = {}
    for r in rows:
        name = r.get("name")
        if not name or name == current_name:
            continue
        if not bool(r.get("auto_switch_eligible")):
            continue
        if same_policy == "skip" and bool(r.get("same_principal")):
            continue
        rem_5h = _remaining_pct(r, "usage_5h")
        rem_weekly = _remaining_pct(r, "usage_weekly")
        if rem_5h is None and rem_weekly is None:
            continue
        if rem_5h is not None and rem_5h <= 0:
            continue
        if rem_weekly is not None and rem_weekly <= 0:
            continue
        score, tie = _candidate_score(r, cfg)
        cands.append((score, tie, r))
        cands_by_name[str(name)] = r
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return cands[0][2]


def _next_chain_name(chain_names: list[str], current_name: str | None, allowed_names: set[str] | None = None) -> str | None:
    if not chain_names:
        return None
    names = [str(x) for x in chain_names if str(x).strip()]
    if not names:
        return None
    allowed = set(str(x) for x in allowed_names) if isinstance(allowed_names, set) else None
    cur = str(current_name) if current_name else None

    def is_allowed(nm: str) -> bool:
        if cur and nm == cur:
            return False
        if allowed is not None and nm not in allowed:
            return False
        return True

    if cur and cur in names:
        idx = names.index(cur)
        total = len(names)
        for step in range(1, total + 1):
            cand = names[(idx + step) % total]
            if is_allowed(cand):
                return cand
        return None
    for cand in names:
        if is_allowed(cand):
            return cand
    return None


def _choose_manual_chain_target(usage_payload: dict, cfg: dict):
    rows = usage_payload.get("profiles") or []
    row_by_name: dict[str, dict] = {}
    for r in rows:
        n = r.get("name")
        if n:
            row_by_name[str(n)] = r
    queue = _manual_live_queue(usage_payload, cfg)
    if len(queue) >= 2:
        target = row_by_name.get(queue[1])
        if target:
            return target
    return None


def _manual_chain_from_cfg(cfg: dict) -> list[str]:
    auto = (cfg.get("auto_switch") or {})
    raw = auto.get("manual_chain", [])
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _ordered_chain_names(usage_payload: dict, cfg: dict) -> list[str]:
    rows = usage_payload.get("profiles") or []
    current_name = usage_payload.get("current_profile")
    if not current_name:
        for r in rows:
            if bool(r.get("is_current")) and r.get("name"):
                current_name = str(r.get("name"))
                break
    ranked: list[tuple[float, tuple, dict]] = []
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        if current_name and str(name) == current_name:
            continue
        score, tie = _candidate_score(r, cfg)
        ranked.append((score, tie, r))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    chain = ([str(current_name)] if current_name else []) + [str(x[2].get("name")) for x in ranked if x[2].get("name")]
    return chain


def _manual_live_queue(usage_payload: dict, cfg: dict) -> list[str]:
    rows = usage_payload.get("profiles") or []
    current_name = usage_payload.get("current_profile")
    if not current_name:
        for r in rows:
            if bool(r.get("is_current")) and r.get("name"):
                current_name = str(r.get("name"))
                break
    row_by_name: dict[str, dict] = {}
    for r in rows:
        n = r.get("name")
        if n:
            row_by_name[str(n)] = r
    if not row_by_name:
        return []

    manual = _manual_chain_from_cfg(cfg)
    manual = [nm for nm in manual if nm in row_by_name]

    # Keep queue anchored at current account and preserve forward manual order.
    head: list[str] = []
    dropped: list[str] = []
    if manual:
        if current_name and current_name in manual:
            idx = manual.index(current_name)
            head = manual[idx:]
            dropped = manual[:idx]
        else:
            head = list(manual)
            if current_name and current_name in row_by_name and current_name not in head:
                head.insert(0, str(current_name))
    elif current_name and current_name in row_by_name:
        head = [str(current_name)]

    seen = set()
    queue: list[str] = []
    for nm in head:
        if nm not in seen:
            seen.add(nm)
            queue.append(nm)

    # Fill any missing profile names in score order for stability.
    ranked_missing: list[tuple[float, tuple, str]] = []
    for nm, row in row_by_name.items():
        if nm in seen:
            continue
        score, tie = _candidate_score(row, cfg)
        ranked_missing.append((score, tie, nm))
    ranked_missing.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for _, _, nm in ranked_missing:
        if nm not in seen:
            seen.add(nm)
            queue.append(nm)

    # In manual mode, append one "next best" candidate after the forward queue.
    # This keeps preview dynamic after each switch: current -> next... -> best extra.
    if dropped:
        candidates: list[tuple[float, tuple, str]] = []
        auto = (cfg.get("auto_switch") or {})
        same_policy = auto.get("same_principal_policy", "skip")
        elig: set[str] = set()
        for r in rows:
            name = r.get("name")
            if not name:
                continue
            nm = str(name)
            if nm == current_name:
                continue
            if not bool(r.get("auto_switch_eligible")):
                continue
            if same_policy == "skip" and bool(r.get("same_principal")):
                continue
            rem_5h = _remaining_pct(r, "usage_5h")
            rem_weekly = _remaining_pct(r, "usage_weekly")
            if rem_5h is None and rem_weekly is None:
                continue
            if rem_5h is not None and rem_5h <= 0:
                continue
            if rem_weekly is not None and rem_weekly <= 0:
                continue
            elig.add(nm)
        for nm in dropped:
            if nm not in row_by_name or nm not in elig:
                continue
            score, tie = _candidate_score(row_by_name[nm], cfg)
            candidates.append((score, tie, nm))
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if candidates:
            best_nm = candidates[0][2]
            if best_nm in queue:
                queue.remove(best_nm)
            queue.append(best_nm)
    return queue


def _auto_switch_chain(usage_payload: dict, cfg: dict) -> list[dict]:
    rows = usage_payload.get("profiles") or []
    row_by_name: dict[str, dict] = {}
    for r in rows:
        n = r.get("name")
        if n:
            row_by_name[str(n)] = r
    ranking_mode = str(((cfg.get("auto_switch") or {}).get("ranking_mode")) or "balanced")
    if ranking_mode == "manual":
        chain_names = _manual_live_queue(usage_payload, cfg)
    else:
        chain_names = _ordered_chain_names(usage_payload, cfg)
    items: list[dict] = []
    for nm in chain_names:
        rr = row_by_name.get(nm, {})
        items.append(
            {
                "name": nm,
                "remaining_5h": _remaining_pct(rr, "usage_5h"),
                "remaining_weekly": _remaining_pct(rr, "usage_weekly"),
            }
        )
    return items


def _auto_arranged_chain(usage_payload: dict, cfg: dict) -> tuple[list[str], list[dict]]:
    rows = usage_payload.get("profiles") or []
    current_name = usage_payload.get("current_profile")
    if not current_name:
        for r in rows:
            if bool(r.get("is_current")) and r.get("name"):
                current_name = str(r.get("name"))
                break
    row_by_name: dict[str, dict] = {}
    ranked: list[tuple[float, tuple, dict]] = []
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        name_s = str(name)
        row_by_name[name_s] = r
        if current_name and name_s == str(current_name):
            continue
        score, tie = _candidate_score(r, cfg)
        ranked.append((score, tie, r))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    chain_names: list[str] = []
    if current_name and str(current_name) in row_by_name:
        chain_names.append(str(current_name))
    chain_names.extend([str(x[2].get("name")) for x in ranked if x[2].get("name")])
    items: list[dict] = []
    for nm in chain_names:
        rr = row_by_name.get(nm, {})
        items.append(
            {
                "name": nm,
                "remaining_5h": _remaining_pct(rr, "usage_5h"),
                "remaining_weekly": _remaining_pct(rr, "usage_weekly"),
            }
        )
    return chain_names, items


def cmd_ui_serve(host: str, port: int, no_open: bool, interval_sec: float, idle_timeout_sec: float, token: str) -> int:
    if interval_sec <= 0:
        print("error: --interval must be > 0")
        return 1
    if port < 0 or port > 65535:
        print("error: --port must be between 0 and 65535")
        return 1
    default_host = host or "127.0.0.1"
    if default_host in ("0.0.0.0", "::"):
        print("warning: binding to all interfaces is not recommended for local account tools")
    last_seen = {"ts": time.time()}
    runtime = {
        "next_event_id": 1,
        "events": [],
        "last_event_sig": "",
        "last_event_ts": 0.0,
        "last_event_obj": None,
        "pending_warning": None,
        "pending_switch_due_at": None,
        "pending_switch_notice_sent_for_due_at": None,
        "last_switch_ts": None,
        "last_eval_ts": None,
        "last_eval_ok": None,
        "active": False,
        "stop_event": threading.Event(),
        "rapid_test_active": False,
        "rapid_test_started_at": None,
        "rapid_test_stop": threading.Event(),
        "rapid_test_wait_sec": None,
        "rapid_test_step": 0,
        "test_run_active": False,
        "test_stop": threading.Event(),
        "switch_lock": threading.RLock(),
        "switch_in_flight": False,
        "switch_target": "",
        "switch_started_at": 0.0,
    }
    usage_cache_lock = threading.RLock()
    usage_cache: dict[str, object] = {
        "ts": 0.0,
        "payload": None,
        "cfg_hash": None,
        "timeout": None,
        "epoch": 0,
    }
    release_notes_cache_lock = threading.RLock()
    release_notes_cache: dict[str, object] = {
        "ts": 0.0,
        "payload": None,
    }
    diagnostics_service = DiagnosticsLogger(write_fn=cam_log, tail_fn=read_log_tail)
    config_service = UiConfigService(load_fn=load_cam_config, save_fn=save_cam_config, update_fn=update_cam_config)
    usage_service = UsageService(collect_fn=collect_usage_local_data)

    def is_debug_enabled() -> bool:
        try:
            cfg = load_cam_config()
            return bool(((cfg.get("ui") or {}).get("debug_mode")))
        except Exception:
            return False

    def log_runtime(level: str, message: str, details=None):
        diagnostics_service.log(level, message, details=details, echo=is_debug_enabled())

    def push_event(event_type: str, message: str, details=None):
        safe_details = details or {}
        sig = f"{str(event_type)}|{str(message)}|{json.dumps(safe_details, sort_keys=True, ensure_ascii=False, default=str)}"
        now_ts = time.time()
        last_sig = str(runtime.get("last_event_sig") or "")
        last_ts = float(runtime.get("last_event_ts") or 0.0)
        if sig == last_sig and (now_ts - last_ts) < 1.2:
            prev = runtime.get("last_event_obj")
            if isinstance(prev, dict):
                return prev
        ev = {
            "id": runtime["next_event_id"],
            "ts": int(now_ts),
            "type": event_type,
            "message": message,
            "details": safe_details,
        }
        runtime["next_event_id"] += 1
        runtime["events"].append(ev)
        if len(runtime["events"]) > 200:
            runtime["events"] = runtime["events"][-200:]
        runtime["last_event_sig"] = sig
        runtime["last_event_ts"] = now_ts
        runtime["last_event_obj"] = ev
        log_runtime("info", f"event:{event_type}", {"id": ev["id"], "message": message, "details": safe_details})
        return ev

    def _cfg_usage_cache_key(cfg: dict) -> str:
        try:
            auto = cfg.get("auto_switch") or {}
            prof = cfg.get("profiles") or {}
            sig = {
                "auto_enabled": bool(auto.get("enabled", False)),
                "ranking_mode": auto.get("ranking_mode", "balanced"),
                "manual_chain": list(auto.get("manual_chain") or []),
                "same_principal_policy": auto.get("same_principal_policy", "skip"),
                "candidate_policy": auto.get("candidate_policy", "only_selected"),
                "eligibility": dict((prof.get("eligibility") or {})),
            }
            return json.dumps(sig, sort_keys=True, separators=(",", ":"))
        except Exception:
            return "cfg:unknown"

    def collect_usage_local_data_cached(timeout_sec: int, config: dict, ttl_sec: float = 2.0, force: bool = False):
        key = _cfg_usage_cache_key(config if isinstance(config, dict) else {})
        now = time.time()
        epoch = 0
        with usage_cache_lock:
            epoch = int(usage_cache.get("epoch") or 0)
        if not force:
            with usage_cache_lock:
                cached_payload = usage_cache.get("payload")
                cached_ts = float(usage_cache.get("ts") or 0.0)
                cached_key = usage_cache.get("cfg_hash")
                cached_epoch = int(usage_cache.get("epoch") or 0)
                if cached_payload and cached_key == key and cached_epoch == epoch and (now - cached_ts) <= max(0.05, ttl_sec):
                    return cached_payload
        payload = usage_service.collect(timeout_sec=timeout_sec, config=config)
        return _store_usage_payload(payload, config, timeout_sec)

    def invalidate_usage_cache(reason: str = "") -> None:
        with usage_cache_lock:
            usage_cache["epoch"] = int(usage_cache.get("epoch") or 0) + 1
            usage_cache["ts"] = 0.0
            usage_cache["payload"] = None
            usage_cache["cfg_hash"] = None
            usage_cache["timeout"] = None
        if reason:
            log_runtime("info", "usage cache invalidated", {"reason": reason})

    def _usage_cache_payload_copy():
        with usage_cache_lock:
            payload = usage_cache.get("payload")
            return copy.deepcopy(payload) if isinstance(payload, dict) else None

    def _seed_usage_payload(config: dict) -> dict:
        context = _build_usage_profile_context(config=config)
        rows = []
        list_rows = collect_list_data(config=config)
        profile_meta = context.get("profile_meta") or {}
        current_profile = str(context.get("current_profile") or "").strip() or None
        for item in list_rows:
            account_hint = str(item.get("account_hint") or "")
            hint_left = account_hint.split("|")[0].strip()
            name = str(item.get("name") or "").strip()
            entry = profile_meta.get(name) or {}
            email = str(entry.get("email") or "").strip() or (hint_left if "@" in hint_left else "-")
            account_id = str(entry.get("account_id") or item.get("account_id") or "-")
            is_current = bool(current_profile and name == current_profile)
            rows.append(
                {
                    "name": item.get("name"),
                    "email": email,
                    "account_id": account_id,
                    "usage_5h": {"remaining_percent": None, "resets_at": None, "text": "-"},
                    "usage_weekly": {"remaining_percent": None, "resets_at": None, "text": "-"},
                    "plan_type": None,
                    "is_paid": None,
                    "is_current": is_current,
                    "same_principal": bool(item.get("same_principal")),
                    "error": None,
                    "saved_at": item.get("saved_at"),
                    "auto_switch_eligible": bool(item.get("auto_switch_eligible", False)),
                }
            )
        return {"refreshed_at": dt.datetime.now().isoformat(), "current_profile": current_profile, "profiles": rows}

    def _merge_usage_rows(base_payload: dict | None, updated_payload: dict | None, config: dict) -> dict:
        base = copy.deepcopy(base_payload) if isinstance(base_payload, dict) else _seed_usage_payload(config)
        updates = updated_payload if isinstance(updated_payload, dict) else {}
        base_rows = base.get("profiles") or []
        update_rows = updates.get("profiles") or []
        by_name = {}
        order = []
        for row in base_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            by_name[name] = copy.deepcopy(row)
            order.append(name)
        for row in update_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            if name not in by_name:
                order.append(name)
            by_name[name] = copy.deepcopy(row)
        current_profile = str((updates.get("current_profile") or base.get("current_profile") or "")).strip() or None
        rows = []
        for name in order:
            row = copy.deepcopy(by_name.get(name) or {})
            row["is_current"] = bool(current_profile and name == current_profile)
            rows.append(row)
        merged = {
            "refreshed_at": updates.get("refreshed_at") or base.get("refreshed_at") or dt.datetime.now().isoformat(),
            "current_profile": current_profile,
            "profiles": rows,
        }
        return merged

    def _store_usage_payload(payload: dict, config: dict, timeout_sec: int) -> dict:
        merged = _merge_usage_rows(None, payload, config)
        with usage_cache_lock:
            usage_cache["ts"] = time.time()
            usage_cache["payload"] = merged
            usage_cache["cfg_hash"] = _cfg_usage_cache_key(config if isinstance(config, dict) else {})
            usage_cache["timeout"] = timeout_sec
        return merged

    def refresh_usage_subset(profile_names: list[str], timeout_sec: int, config: dict) -> dict:
        partial = collect_usage_local_data(timeout_sec=timeout_sec, config=config, profile_names=profile_names)
        cached = _usage_cache_payload_copy()
        merged = _merge_usage_rows(cached, partial, config)
        with usage_cache_lock:
            usage_cache["ts"] = time.time()
            usage_cache["payload"] = merged
            usage_cache["cfg_hash"] = _cfg_usage_cache_key(config if isinstance(config, dict) else {})
            usage_cache["timeout"] = timeout_sec
        return merged

    def execute_profile_switch(
        target: str,
        restart_codex: bool,
        source: str,
        preferred_restart_app: str = "",
        preferred_restart_exec: str = "",
        schedule_deferred_restart: bool = False,
    ) -> tuple[int, str, str]:
        with runtime["switch_lock"]:
            if runtime.get("switch_in_flight"):
                active_target = str(runtime.get("switch_target") or "").strip() or "unknown"
                return 409, "", f"switch already in progress for '{active_target}'"
            runtime["switch_in_flight"] = True
            runtime["switch_target"] = target
            runtime["switch_started_at"] = time.time()
        try:
            rc, out, err = _capture_fn(lambda: cmd_switch(target, restart_codex=False))
            if rc == 0:
                invalidate_usage_cache("profile-switch")
                if restart_codex:
                    if schedule_deferred_restart:
                        def _deferred_restart():
                            try:
                                time.sleep(0.8)
                                restart_codex_app(preferred_app_name=preferred_restart_app, preferred_exec_path=preferred_restart_exec)
                            except Exception as e:
                                _log_runtime_safe("warn", "deferred restart failed", {"error": str(e), "name": target})
                        threading.Thread(target=_deferred_restart, daemon=True).start()
                    else:
                        restart_codex_app(preferred_app_name=preferred_restart_app, preferred_exec_path=preferred_restart_exec)
            return rc, out, err
        finally:
            with runtime["switch_lock"]:
                runtime["switch_in_flight"] = False
                runtime["switch_target"] = ""

    def auto_switch_state_payload(cfg: dict):
        return build_auto_switch_state_payload(runtime, cfg)

    def send_native_usage_notice(usage_payload: dict, message_prefix: str):
        if not bool(((load_cam_config().get("notifications") or {}).get("enabled", False))):
            return None
        try:
            return native_notifications.send_native_usage_notification(
                usage_payload=usage_payload,
                base_url=_native_notification_test_base_url(default_host, port),
                message_prefix=message_prefix,
            )
        except Exception as e:
            log_runtime("warn", "native notification failed", {"error": str(e), "message_prefix": message_prefix})
            return None

    def _run_rapid_test():
        runtime["rapid_test_active"] = True
        runtime["rapid_test_started_at"] = time.time()
        runtime["rapid_test_step"] = 0
        runtime["rapid_test_wait_sec"] = None
        runtime["rapid_test_stop"].clear()
        try:
            cfg = load_cam_config()
            delay_sec = int(((cfg.get("auto_switch") or {}).get("delay_sec", 60)))
            wait_sec = max(1, delay_sec + 30)
            runtime["rapid_test_wait_sec"] = wait_sec
            usage_payload = collect_usage_local_data_cached(timeout_sec=7, config=cfg, ttl_sec=0.0, force=True)
            chain_names = _ordered_chain_names(usage_payload, cfg)
            if len(chain_names) < 2:
                push_event("error", "rapid-test: need at least 2 accounts in chain")
                return
            push_event("rapid-test", "rapid test started", {"chain": chain_names, "wait_per_step_sec": wait_sec})
            max_steps = max(1, len(chain_names) - 1)
            for step in range(1, max_steps + 1):
                if runtime["rapid_test_stop"].is_set():
                    push_event("rapid-test", "rapid test stopped")
                    break
                cfg = load_cam_config()
                usage_payload = collect_usage_local_data_cached(timeout_sec=7, config=cfg, ttl_sec=0.0, force=True)
                current_name = usage_payload.get("current_profile")
                candidate = _choose_manual_chain_target(usage_payload, cfg)
                if not candidate:
                    push_event("error", "rapid-test: no manual chain target found", {"current": current_name})
                    break
                target = str(candidate.get("name") or "").strip()
                if not target:
                    push_event("error", "rapid-test: invalid target")
                    break
                runtime["rapid_test_step"] = step
                runtime["pending_warning"] = {
                    "current": current_name,
                    "detail": {"rapid_test": True, "target": target, "step": step, "wait_sec": wait_sec},
                    "created_at": time.time(),
                }
                runtime["pending_switch_due_at"] = time.time() + wait_sec
                runtime["pending_switch_notice_sent_for_due_at"] = None
                push_event("rapid-test", f"step {step}: switching '{current_name}' -> '{target}' in {wait_sec}s", {"step": step, "current": current_name, "target": target})
                while not runtime["rapid_test_stop"].is_set():
                    due = float(runtime.get("pending_switch_due_at") or 0.0)
                    now_tick = time.time()
                    if runtime.get("pending_switch_notice_sent_for_due_at") != due:
                        notice_at = due - 30.0
                        if now_tick >= notice_at:
                            runtime["pending_switch_notice_sent_for_due_at"] = due
                            send_native_usage_notice(
                                usage_payload,
                                "Auto switch starts in about 30 seconds",
                            )
                    if due <= 0.0 or now_tick >= due:
                        break
                    if runtime["stop_event"].wait(0.25):
                        runtime["rapid_test_stop"].set()
                        break
                if runtime["rapid_test_stop"].is_set():
                    push_event("rapid-test", "rapid test stopped")
                    break
                rc, out, err = execute_profile_switch(
                    target=target,
                    restart_codex=True,
                    source="rapid-test",
                    schedule_deferred_restart=False,
                )
                if rc == 0:
                    runtime["last_switch_ts"] = time.time()
                    push_event("switch", f"rapid-test switched to '{target}'", {"target": target, "step": step, "stdout": out.strip()})
                else:
                    push_event("error", f"rapid-test failed to switch '{target}'", {"target": target, "step": step, "stdout": out.strip(), "stderr": err.strip()})
                    break
                runtime["pending_warning"] = None
                runtime["pending_switch_due_at"] = None
                runtime["pending_switch_notice_sent_for_due_at"] = None
        except Exception as e:
            push_event("error", f"rapid-test exception: {e}")
        finally:
            runtime["rapid_test_active"] = False
            runtime["rapid_test_started_at"] = None
            runtime["rapid_test_step"] = 0
            runtime["rapid_test_wait_sec"] = None
            runtime["pending_warning"] = None
            runtime["pending_switch_due_at"] = None
            runtime["pending_switch_notice_sent_for_due_at"] = None
            runtime["rapid_test_stop"].clear()

    def auto_switch_tick():
        while not runtime["stop_event"].is_set():
            if runtime.get("rapid_test_active"):
                runtime["last_eval_ts"] = time.time()
                runtime["last_eval_ok"] = True
                runtime["stop_event"].wait(0.5)
                continue
            cfg = load_cam_config()
            runtime["active"] = bool((cfg.get("auto_switch") or {}).get("enabled", False))
            now = time.time()
            runtime["last_eval_ts"] = now
            if not runtime["active"]:
                runtime["pending_warning"] = None
                runtime["pending_switch_due_at"] = None
                runtime["last_eval_ok"] = True
                runtime["stop_event"].wait(1.5)
                continue
            try:
                usage_payload = collect_usage_local_data_cached(timeout_sec=5, config=cfg, ttl_sec=2.0)
                current_name = usage_payload.get("current_profile")
                current_row = None
                for r in usage_payload.get("profiles", []):
                    if r.get("name") == current_name:
                        current_row = r
                        break
                if not current_row:
                    runtime["last_eval_ok"] = False
                    push_event("error", "auto-switch: no current profile detected")
                    runtime["stop_event"].wait(5.0)
                    continue
                breached, detail = _trigger_breached(current_row, cfg)
                if not breached:
                    if runtime["pending_warning"] is not None:
                        push_event("cancel", "auto-switch warning canceled (threshold recovered)", {"current": current_name})
                    runtime["pending_warning"] = None
                    runtime["pending_switch_due_at"] = None
                    runtime["pending_switch_notice_sent_for_due_at"] = None
                    runtime["last_eval_ok"] = True
                    runtime["stop_event"].wait(5.0)
                    continue
                auto_cfg = cfg.get("auto_switch") or {}
                delay_sec = int(auto_cfg.get("delay_sec", 60))
                cooldown_cfg = int(auto_cfg.get("cooldown_sec", 60))
                cooldown_sec = max(AUTO_SWITCH_MIN_INTERNAL_COOLDOWN_SEC, cooldown_cfg)
                if runtime["pending_warning"] is None:
                    runtime["pending_warning"] = {"current": current_name, "detail": detail, "created_at": now}
                    runtime["pending_switch_due_at"] = now + delay_sec
                    runtime["pending_switch_notice_sent_for_due_at"] = None
                    push_event("warning", f"usage threshold reached for '{current_name}'", detail)
                    send_native_usage_notice(
                        usage_payload,
                        "Usage warning",
                    )
                    runtime["last_eval_ok"] = True
                    runtime["stop_event"].wait(1.0)
                    continue
                due = runtime.get("pending_switch_due_at") or now
                if runtime.get("pending_switch_notice_sent_for_due_at") != due:
                    notice_at = due - 30.0
                    if now >= notice_at:
                        runtime["pending_switch_notice_sent_for_due_at"] = due
                        send_native_usage_notice(
                            usage_payload,
                            "Auto switch starts in about 30 seconds",
                        )
                if now < due:
                    runtime["last_eval_ok"] = True
                    runtime["stop_event"].wait(1.0)
                    continue
                if runtime.get("last_switch_ts") and (now - runtime["last_switch_ts"]) < cooldown_sec:
                    runtime["last_eval_ok"] = True
                    runtime["stop_event"].wait(1.0)
                    continue
                candidate = _choose_auto_switch_candidate(usage_payload, cfg)
                if not candidate:
                    push_event("error", "auto-switch: no target found in switch chain", {"current": current_name})
                    runtime["pending_warning"] = None
                    runtime["pending_switch_due_at"] = None
                    runtime["pending_switch_notice_sent_for_due_at"] = None
                    runtime["last_eval_ok"] = False
                    runtime["stop_event"].wait(3.0)
                    continue
                rc, out, err = execute_profile_switch(
                    target=str(candidate.get("name")),
                    restart_codex=True,
                    source="auto-switch",
                    schedule_deferred_restart=False,
                )
                if rc == 0:
                    runtime["last_switch_ts"] = now
                    push_event("switch", f"auto-switched to '{candidate.get('name')}'", {"target": candidate.get("name"), "stdout": out.strip()})
                else:
                    push_event("error", f"auto-switch failed for '{candidate.get('name')}'", {"target": candidate.get("name"), "stdout": out.strip(), "stderr": err.strip()})
                runtime["pending_warning"] = None
                runtime["pending_switch_due_at"] = None
                runtime["pending_switch_notice_sent_for_due_at"] = None
                runtime["last_eval_ok"] = (rc == 0)
            except Exception as e:
                runtime["last_eval_ok"] = False
                push_event("error", f"auto-switch exception: {e}")
            runtime["stop_event"].wait(2.0)

    class UIHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _reply(self, status_code: int, payload, content_type: str = "application/json; charset=utf-8"):
            raw = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(raw)

        def _api(self):
            parsed = urlparse(self.path)
            path = parsed.path
            q = parse_qs(parsed.query)
            last_seen["ts"] = time.time()
            body = {}
            if self.command == "POST":
                header_token = self.headers.get("X-Codex-Token", "")
                if header_token != token:
                    log_runtime("warn", "forbidden POST token mismatch", {"path": path})
                    return _json_error("FORBIDDEN", "invalid session token", 403)
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                except Exception:
                    n = 0
                if n > 0:
                    try:
                        body = json.loads(self.rfile.read(n).decode("utf-8"))
                    except Exception:
                        return _json_error("BAD_JSON", "request body must be valid JSON")
                if not isinstance(body, dict):
                    return _json_error("BAD_JSON", "request body must be a JSON object")

            def bool_value(v, default=False):
                if v is None:
                    return default
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                if isinstance(v, str):
                    return v.strip().lower() in ("1", "true", "yes", "on")
                return default

            def int_value(v, default, minimum=0):
                try:
                    x = int(v)
                    return max(minimum, x)
                except Exception:
                    return default

            if self.command == "GET" and path == "/api/status":
                return _json_ok(collect_status_data())
            if self.command == "GET" and path == "/api/health":
                return _json_ok({"healthy": True, "service": "codex-account-ui", "version": UI_BUILD_VERSION})
            if self.command == "GET" and path == "/api/ui-config":
                return _json_ok(config_service.load())
            if self.command == "GET" and path == "/api/auto-switch/state":
                return _json_ok(auto_switch_state_payload(config_service.load()))
            if self.command == "GET" and path == "/api/auto-switch/chain":
                cfg = load_cam_config()
                usage_payload = collect_usage_local_data_cached(timeout_sec=7, config=cfg, ttl_sec=3.0)
                chain_items = _auto_switch_chain(usage_payload, cfg)
                chain_names = [str(x.get("name")) for x in chain_items if x.get("name")]
                manual_chain = _manual_chain_from_cfg(cfg)
                return _json_ok(
                    {
                        "chain": chain_names,
                        "items": chain_items,
                        "manual_chain": manual_chain,
                        "chain_text": " -> ".join(chain_names) if chain_names else "-",
                    }
                )
            if self.command == "GET" and path == "/api/events":
                since_id = 0
                if "since_id" in q:
                    try:
                        since_id = int(float(q["since_id"][0]))
                    except Exception:
                        since_id = 0
                rows = [ev for ev in runtime["events"] if int(ev.get("id", 0)) > since_id]
                return _json_ok({"events": rows})
            if self.command == "GET" and path == "/api/debug/logs":
                req_token = (q.get("token", [""])[0] or "").strip()
                if req_token != token:
                    return _json_error("FORBIDDEN", "invalid session token", 403)
                tail = 200
                if "tail" in q:
                    try:
                        tail = max(20, min(2000, int(float(q["tail"][0]))))
                    except Exception:
                        tail = 200
                return _json_ok({"path": str(CAM_LOG_FILE), "logs": diagnostics_service.tail(tail)})
            if self.command == "GET" and path == "/api/release-notes":
                force = bool_value((q.get("force", ["false"])[0]), False)
                with release_notes_cache_lock:
                    payload = load_release_notes_payload(force_refresh=force, cache=release_notes_cache)
                return _json_ok(payload)
            if self.command == "GET" and path == "/api/app-update-status":
                force = bool_value((q.get("force", ["false"])[0]), False)
                with release_notes_cache_lock:
                    payload = load_release_notes_payload(force_refresh=force, cache=release_notes_cache)
                return _json_ok(build_update_status_payload(payload))
            if self.command == "GET" and path == "/api/adv/status":
                return _json_ok(collect_status_data())
            if self.command == "GET" and path == "/api/list":
                cfg = load_cam_config()
                return _json_ok({"profiles": collect_list_data(config=cfg)})
            if self.command == "GET" and path == "/api/current":
                data = collect_current_data()
                if not data["ok"]:
                    return _json_error("NO_ACTIVE_AUTH", data["error"], 404)
                return _json_ok(data)
            if self.command == "GET" and path == "/api/usage-local":
                timeout = 7
                if "timeout" in q:
                    try:
                        timeout = max(1, int(float(q["timeout"][0])))
                    except Exception:
                        return _json_error("BAD_TIMEOUT", "timeout must be a positive number")
                cfg = load_cam_config()
                force = bool_value((q.get("force", ["false"])[0]), False)
                usage_started = time.time()
                result = collect_usage_local_data_cached(timeout, config=cfg, ttl_sec=2.0, force=force)
                duration_ms = int((time.time() - usage_started) * 1000)
                error_rows = 0
                profile_rows = result.get("profiles", []) if isinstance(result, dict) else []
                for row in profile_rows if isinstance(profile_rows, list) else []:
                    err_val = row.get("error") if isinstance(row, dict) else None
                    if isinstance(err_val, str) and err_val.strip():
                        error_rows += 1
                if duration_ms >= 1200:
                    log_runtime(
                        "warn",
                        "usage-local slow response",
                        {"duration_ms": duration_ms, "timeout_sec": timeout, "force": force, "profiles": len(profile_rows) if isinstance(profile_rows, list) else 0, "error_rows": error_rows},
                    )
                elif error_rows:
                    log_runtime(
                        "warn",
                        "usage-local row errors",
                        {"duration_ms": duration_ms, "timeout_sec": timeout, "force": force, "profiles": len(profile_rows) if isinstance(profile_rows, list) else 0, "error_rows": error_rows},
                    )
                return _json_ok(result)
            if self.command == "GET" and path == "/api/usage-local/current":
                timeout = 7
                if "timeout" in q:
                    try:
                        timeout = max(1, int(float(q["timeout"][0])))
                    except Exception:
                        return _json_error("BAD_TIMEOUT", "timeout must be a positive number")
                cfg = load_cam_config()
                context = _build_usage_profile_context(config=cfg)
                current_name = str(context.get("current_profile") or "").strip()
                if not current_name:
                    cached = _usage_cache_payload_copy() or _seed_usage_payload(cfg)
                    return _json_ok(cached)
                result = refresh_usage_subset([current_name], timeout_sec=timeout, config=cfg)
                return _json_ok(result)
            if self.command == "GET" and path == "/api/usage-local/profile":
                timeout = 7
                if "timeout" in q:
                    try:
                        timeout = max(1, int(float(q["timeout"][0])))
                    except Exception:
                        return _json_error("BAD_TIMEOUT", "timeout must be a positive number")
                name = str((q.get("name", [""])[0] or "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "profile name is required")
                cfg = load_cam_config()
                if not any(p.name == name for p in _existing_profile_dirs()):
                    return _json_error("NOT_FOUND", f"profile '{name}' not found", 404)
                result = refresh_usage_subset([name], timeout_sec=timeout, config=cfg)
                return _json_ok(result)
            if self.command == "GET" and path == "/api/adv/list":
                args = ["list"]
                if bool_value((q.get("debug", ["false"])[0]), False):
                    args.append("--debug")
                r = run_codex_auth_capture(args, timeout_sec=25)
                payload = _command_result("adv.list", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced list failed", 400, payload)
                return _json_ok(payload)
            if self.command == "GET" and path == "/api/ping":
                req_token = (q.get("token", [""])[0] or "").strip()
                if req_token != token:
                    return _json_error("FORBIDDEN", "invalid session token", 403)
                return _json_ok({"pong": True})
            if self.command == "POST" and path == "/api/local/export/prepare":
                scope = str(body.get("scope", "all") or "all").strip().lower()
                if scope not in {"all", "selected"}:
                    return _json_error("BAD_SCOPE", "scope must be 'all' or 'selected'")
                names = None
                filename = str(body.get("filename", "") or "").strip()
                if scope == "selected":
                    raw_names = body.get("names")
                    if not isinstance(raw_names, list):
                        return _json_error("BAD_NAMES", "selected export requires a names array")
                    names = [str(item or "").strip() for item in raw_names if str(item or "").strip()]
                    if not names:
                        return _json_error("BAD_NAMES", "at least one profile name is required for selected export")
                try:
                    payload = prepare_profiles_export(names, filename=filename)
                except Exception as e:
                    return _json_error("EXPORT_FAILED", str(e), 400)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/import/analyze":
                filename = str(body.get("filename", "") or "").strip()
                content_b64 = str(body.get("content_b64", "") or "").strip()
                if not content_b64:
                    return _json_error("MISSING_CONTENT", "content_b64 is required")
                try:
                    archive_bytes = base64.b64decode(content_b64, validate=True)
                except Exception:
                    return _json_error("BAD_CONTENT", "content_b64 must be valid base64 data")
                try:
                    payload = store_import_analysis(filename, archive_bytes)
                except Exception as e:
                    return _json_error("IMPORT_ANALYZE_FAILED", str(e), 400)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/import/apply":
                analysis_id = str(body.get("analysis_id", "") or "").strip()
                rows = body.get("profiles")
                if not analysis_id:
                    return _json_error("MISSING_ID", "analysis_id is required")
                if not isinstance(rows, list):
                    return _json_error("BAD_PROFILES", "profiles must be an array")
                stored = load_import_analysis(analysis_id)
                if not stored:
                    return _json_error("NOT_FOUND", "import analysis not found or expired", 404)
                try:
                    payload = apply_profiles_import(Path(stored["path"]), rows)
                except Exception as e:
                    return _json_error("IMPORT_APPLY_FAILED", str(e), 400)
                invalidate_usage_cache("local-import-profiles")
                clear_import_analysis(analysis_id)
                return _json_ok(payload)
            if self.command == "GET" and path == "/api/local/add/session":
                sid = str((q.get("id", [""])[0] or "")).strip()
                if not sid:
                    return _json_error("MISSING_ID", "session id is required")
                payload = get_add_login_session(sid)
                if not payload:
                    return _json_error("NOT_FOUND", "session not found", 404)
                return _json_ok(payload)
            if self.command == "POST" and path in ("/api/switch", "/api/local/switch"):
                name = str(body.get("name", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "profile name is required")
                restart = not bool_value(body.get("no_restart"), False)
                close_only = bool_value(body.get("close_only"), False)
                if close_only:
                    restart = False
                preferred_restart_app = ""
                preferred_restart_exec = ""
                if restart:
                    try:
                        preferred_restart_app = detect_running_app_name() or ""
                    except Exception:
                        preferred_restart_app = ""
                if restart and sys.platform.startswith("win"):
                    try:
                        preferred_restart_exec = _detect_running_codex_executable_windows() or ""
                    except Exception:
                        preferred_restart_exec = ""
                if close_only:
                    try:
                        stop_codex()
                        _log_runtime_safe(
                            "info",
                            "switch close_only stop requested",
                            {"name": name, "preferred_restart_app": preferred_restart_app, "preferred_restart_exec": preferred_restart_exec},
                        )
                    except Exception as e:
                        _log_runtime_safe("warn", "switch close_only stop failed", {"name": name, "error": str(e)})
                # Apply profile switch first, then restart asynchronously so the HTTP request can complete.
                rc, out, err = execute_profile_switch(
                    target=name,
                    restart_codex=restart,
                    source="manual-switch",
                    preferred_restart_app=preferred_restart_app,
                    preferred_restart_exec=preferred_restart_exec,
                    schedule_deferred_restart=bool(restart),
                )
                payload = _command_result("local.switch", rc, out, err)
                if rc != 0:
                    if rc == 409:
                        return _json_error("CONFLICT", "switch is already in progress", 409, payload)
                    return _json_error("COMMAND_FAILED", "local switch failed", 400, payload)
                if restart:
                    _log_runtime_safe(
                        "info",
                        "switch deferred restart scheduled",
                        {"name": name, "preferred_restart_app": preferred_restart_app, "preferred_restart_exec": preferred_restart_exec},
                    )
                push_event("switch-manual", f"manually switched to '{name}'")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/ui-config":
                patch = body if isinstance(body, dict) else {}
                base_revision = None
                if isinstance(body, dict) and body.get("base_revision") is not None:
                    try:
                        base_revision = int(body.get("base_revision"))
                    except Exception:
                        return _json_error("BAD_REVISION", "base_revision must be an integer", 400)
                if isinstance(patch, dict) and "base_revision" in patch:
                    patch = {k: v for k, v in patch.items() if k != "base_revision"}
                try:
                    cfg = config_service.patch(patch, base_revision=base_revision)
                except Exception as e:
                    if "stale config revision" in str(e).lower():
                        return _json_error("STALE_CONFIG", str(e), 409)
                    log_runtime("error", "config update failed", {"error": str(e)})
                    return _json_error("BAD_CONFIG", f"failed to update config: {e}", 400)
                invalidate_usage_cache("ui-config")
                log_runtime("info", "config updated", {"patch": patch})
                return _json_ok(cfg)
            if self.command == "POST" and path == "/api/notifications/test":
                delay_sec = int_value(body.get("delay_sec"), 5, minimum=0)
                ev = push_event("notify-test", f"test notification requested (delay {delay_sec}s)", {"delay_sec": delay_sec})
                return _json_ok({"event": ev})
            if self.command == "POST" and path == "/api/notifications/native-test":
                try:
                    payload = run_native_notification_test(host=default_host, port=port, timeout_sec=7)
                except RuntimeError as e:
                    return _json_error("NATIVE_NOTIFICATION_FAILED", str(e), 400)
                except Exception as e:
                    return _json_error("NATIVE_NOTIFICATION_FAILED", str(e), 500)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/auto-switch/enable":
                enabled = bool_value(body.get("enabled"), False)
                cfg = config_service.patch({"auto_switch": {"enabled": enabled}})
                invalidate_usage_cache("auto-switch-enable")
                push_event("auto-switch-toggle", f"auto-switch set to {'enabled' if enabled else 'disabled'}")
                return _json_ok({"enabled": enabled, "config": cfg})
            if self.command == "POST" and path == "/api/auto-switch/stop":
                cfg = config_service.patch({"auto_switch": {"enabled": False}})
                invalidate_usage_cache("auto-switch-stop")
                runtime["rapid_test_stop"].set()
                runtime["test_stop"].set()
                runtime["pending_warning"] = None
                runtime["pending_switch_due_at"] = None
                runtime["last_switch_ts"] = None
                push_event("auto-switch-stop", "auto-switch force-stopped and pending state cleared")
                return _json_ok({"enabled": False, "runtime": auto_switch_state_payload(load_cam_config()), "config": cfg})
            if self.command == "POST" and path == "/api/auto-switch/stop-tests":
                runtime["rapid_test_stop"].set()
                runtime["test_stop"].set()
                push_event("auto-switch-stop-tests", "test flows stop requested")
                return _json_ok({"stopped": True, "runtime": auto_switch_state_payload(load_cam_config())})
            if self.command == "POST" and path == "/api/system/kill-all":
                cfg = config_service.patch({"auto_switch": {"enabled": False}})
                invalidate_usage_cache("system-kill-all")
                runtime["rapid_test_stop"].set()
                runtime["test_stop"].set()
                runtime["pending_warning"] = None
                runtime["pending_switch_due_at"] = None
                runtime["last_switch_ts"] = None
                runtime["stop_event"].set()
                push_event("system-kill-all", "kill-all requested from UI")

                current_pid = os.getpid()
                target_port = int(port)
                candidate_pids: set[int] = set()
                info = read_ui_pid_info() or {}
                pid_from_file = info.get("pid")
                if isinstance(pid_from_file, int) and pid_from_file > 0:
                    candidate_pids.add(pid_from_file)
                for listener_pid in _pids_listening_on_port(target_port):
                    if isinstance(listener_pid, int) and listener_pid > 0:
                        candidate_pids.add(listener_pid)

                def _deferred_shutdown():
                    time.sleep(0.45)
                    try:
                        _kill_cam_processes(exclude_pids={current_pid})
                    except Exception:
                        pass
                    for pid in sorted(candidate_pids):
                        if pid == current_pid:
                            continue
                        try:
                            stop_ui_process(int(pid))
                        except Exception:
                            pass
                    try:
                        clear_ui_pid_info()
                    except Exception:
                        pass
                    try:
                        if sys.platform.startswith("win"):
                            subprocess.run(["taskkill", "/PID", str(current_pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            os.kill(current_pid, signal.SIGTERM)
                    except Exception:
                        pass
                    time.sleep(0.3)
                    os._exit(0)

                threading.Thread(target=_deferred_shutdown, daemon=True).start()
                return _json_ok({"scheduled": True, "will_close_page": True, "port": target_port, "config": cfg})
            if self.command == "POST" and path == "/api/system/restart":
                push_event("system-restart", "ui-service restart requested from UI")
                cmd = _build_ui_restart_helper_command(
                    str(host or UI_DEFAULT_HOST),
                    int(port or UI_DEFAULT_PORT),
                    float(interval_sec),
                    float(idle_timeout_sec),
                )
                try:
                    popen_kwargs = {
                        "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL,
                    }
                    if sys.platform.startswith("win"):
                        popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                        )
                    else:
                        popen_kwargs["start_new_session"] = True
                    subprocess.Popen(cmd, **popen_kwargs)
                except Exception as e:
                    _log_runtime_safe("error", "ui restart spawn failed", {"error": str(e)})
                    return _json_error("RESTART_FAILED", f"failed to schedule restart: {e}", 500)
                return _json_ok({"restarting": True, "reload_after_ms": 1200})
            if self.command == "POST" and path == "/api/system/update":
                result = run_app_update_command()
                if not result.get("ok"):
                    return _json_ok(
                        {
                            "updated": False,
                            "error": str(result.get("stderr") or "update failed"),
                            "stdout": result.get("stdout", ""),
                            "stderr": result.get("stderr", ""),
                            "command": result.get("command", []),
                            "returncode": result.get("returncode"),
                        }
                    )
                with release_notes_cache_lock:
                    payload = load_release_notes_payload(force_refresh=True, cache=release_notes_cache)
                return _json_ok(
                    {
                        "updated": True,
                        "stdout": result.get("stdout", ""),
                        "stderr": result.get("stderr", ""),
                        "command": result.get("command", []),
                        "returncode": result.get("returncode"),
                        "update_status": build_update_status_payload(payload),
                    }
                )
            if self.command == "POST" and path == "/api/auto-switch/rapid-test":
                if runtime.get("rapid_test_active"):
                    return _json_error("RAPID_TEST_BUSY", "rapid test is already running", 409)
                t = threading.Thread(target=_run_rapid_test, daemon=True)
                t.start()
                return _json_ok({"started": True, "wait_per_step_sec": None, "message": "rapid test started"})
            if self.command == "POST" and path == "/api/auto-switch/account-eligibility":
                name = str(body.get("name", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "name is required")
                eligible = bool_value(body.get("eligible"), False)
                cfg = load_cam_config()
                profiles = cfg.setdefault("profiles", {})
                eligibility = profiles.setdefault("eligibility", {})
                eligibility[name] = eligible
                cfg = save_cam_config(cfg)
                invalidate_usage_cache("account-eligibility")
                return _json_ok({"name": name, "eligible": eligible, "config": cfg})
            if self.command == "POST" and path == "/api/auto-switch/chain":
                incoming = body.get("chain")
                if not isinstance(incoming, list):
                    return _json_error("BAD_CHAIN", "chain must be an array of profile names")
                clean_chain: list[str] = []
                seen_chain = set()
                for item in incoming:
                    if not isinstance(item, str):
                        continue
                    name = item.strip()
                    if not name or name in seen_chain:
                        continue
                    seen_chain.add(name)
                    clean_chain.append(name)
                cfg = load_cam_config()
                auto = cfg.setdefault("auto_switch", {})
                auto["ranking_mode"] = "manual"
                auto["manual_chain"] = clean_chain
                cfg = save_cam_config(cfg)
                invalidate_usage_cache("auto-switch-chain")
                chain_names = list(clean_chain)
                chain_items = [{"name": n, "remaining_5h": None, "remaining_weekly": None} for n in chain_names]
                push_event("auto-switch-chain", "auto-switch chain order updated", {"chain": clean_chain, "ranking_mode": "manual"})
                return _json_ok(
                    {
                        "manual_chain": clean_chain,
                        "chain": chain_names,
                        "items": chain_items,
                        "chain_text": " -> ".join(chain_names) if chain_names else "-",
                        "config": cfg,
                    }
                )
            if self.command == "POST" and path == "/api/auto-switch/auto-arrange":
                cfg = load_cam_config()
                usage_payload = collect_usage_local_data(timeout_sec=7, config=cfg)
                chain_names, chain_items = _auto_arranged_chain(usage_payload, cfg)
                auto = cfg.setdefault("auto_switch", {})
                auto["ranking_mode"] = "balanced"
                auto["manual_chain"] = chain_names
                cfg = save_cam_config(cfg)
                invalidate_usage_cache("auto-arrange")
                push_event(
                    "auto-switch-chain",
                    "auto-arranged switch chain",
                    {"chain": chain_names, "ranking_mode": (auto.get("ranking_mode") or "balanced")},
                )
                return _json_ok(
                    {
                        "manual_chain": chain_names,
                        "chain": chain_names,
                        "items": chain_items,
                        "chain_text": " -> ".join(chain_names) if chain_names else "-",
                        "config": cfg,
                    }
                )
            if self.command == "POST" and path == "/api/auto-switch/run-once":
                cfg = load_cam_config()
                usage_payload = collect_usage_local_data(timeout_sec=7, config=cfg)
                candidate = _choose_auto_switch_candidate(usage_payload, cfg)
                if not candidate:
                    return _json_error("NO_CANDIDATE", "no eligible candidate for auto-switch", 400)
                target = str(candidate.get("name"))
                rc, out, err = execute_profile_switch(
                    target=target,
                    restart_codex=True,
                    source="auto-switch-run-once",
                    schedule_deferred_restart=False,
                )
                payload = _command_result("auto_switch.run_once", rc, out, err)
                if rc != 0:
                    if rc == 409:
                        return _json_error("CONFLICT", "switch is already in progress", 409, payload)
                    push_event("error", f"auto-switch run-once failed for '{target}'", {"stderr": err.strip()})
                    return _json_error("COMMAND_FAILED", "auto-switch run-once failed", 400, payload)
                runtime["last_switch_ts"] = time.time()
                push_event("switch", f"auto-switch run-once switched to '{target}'")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/auto-switch/run-switch":
                cfg = load_cam_config()
                usage_payload = collect_usage_local_data(timeout_sec=7, config=cfg)
                candidate = _choose_auto_switch_candidate(usage_payload, cfg)
                if not candidate:
                    return _json_error("NO_CANDIDATE", "no target found in switch chain", 400)
                target = str(candidate.get("name"))
                rc, out, err = execute_profile_switch(
                    target=target,
                    restart_codex=True,
                    source="auto-switch-run-switch",
                    schedule_deferred_restart=False,
                )
                payload = _command_result("auto_switch.run_switch", rc, out, err)
                if rc != 0:
                    if rc == 409:
                        return _json_error("CONFLICT", "switch is already in progress", 409, payload)
                    push_event("error", f"manual run-switch failed for '{target}'", {"stderr": err.strip()})
                    return _json_error("COMMAND_FAILED", "manual run-switch failed", 400, payload)
                runtime["last_switch_ts"] = time.time()
                push_event("switch-manual", f"manual run-switch switched to '{target}'")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/auto-switch/test":
                timeout_sec = min(180, int_value(body.get("timeout_sec"), 30, minimum=5))
                threshold_raw = body.get("threshold_5h")
                threshold_5h = None
                if threshold_raw not in (None, ""):
                    try:
                        threshold_5h = max(0, min(100, int(float(threshold_raw))))
                    except Exception:
                        return _json_error("BAD_THRESHOLD", "threshold_5h must be a number between 0 and 100")
                cfg_before = load_cam_config()
                auto_before = copy.deepcopy(cfg_before.get("auto_switch") or {})
                start_id = int(runtime.get("next_event_id", 1)) - 1
                runtime["test_run_active"] = True
                runtime["test_stop"].clear()
                push_event("auto-switch-test", "auto-switch test started", {"threshold_5h": threshold_5h, "timeout_sec": timeout_sec})
                try:
                    cfg_test = load_cam_config()
                    auto_test = cfg_test.setdefault("auto_switch", {})
                    auto_test["enabled"] = True
                    auto_test["delay_sec"] = 0
                    auto_test["cooldown_sec"] = 0
                    runtime["last_switch_ts"] = None
                    if threshold_5h is not None:
                        thr = auto_test.setdefault("thresholds", {})
                        thr["h5_switch_pct"] = threshold_5h
                    save_cam_config(cfg_test)
                    deadline = time.time() + timeout_sec
                    switched_ev = None
                    while time.time() < deadline:
                        if runtime["test_stop"].is_set():
                            push_event("auto-switch-test", "auto-switch test stopped by user")
                            return _json_ok(
                                {
                                    "switched": False,
                                    "stopped": True,
                                    "event": None,
                                    "events": [ev for ev in runtime["events"] if int(ev.get("id", 0)) > start_id][-30:],
                                    "used_threshold_5h": threshold_5h,
                                    "timeout_sec": timeout_sec,
                                }
                            )
                        for ev in runtime["events"]:
                            eid = int(ev.get("id", 0))
                            if eid <= start_id:
                                continue
                            if str(ev.get("type")) == "switch" and "auto-switched to" in str(ev.get("message", "")):
                                switched_ev = ev
                                break
                        if switched_ev:
                            break
                        runtime["stop_event"].wait(0.5)
                    events_after = [ev for ev in runtime["events"] if int(ev.get("id", 0)) > start_id]
                    if switched_ev:
                        push_event("auto-switch-test", "auto-switch test passed", {"event_id": switched_ev.get("id"), "message": switched_ev.get("message")})
                        return _json_ok(
                            {
                                "switched": True,
                                "event": switched_ev,
                                "events": events_after[-30:],
                                "used_threshold_5h": threshold_5h,
                                "timeout_sec": timeout_sec,
                            }
                        )
                    push_event("auto-switch-test", "auto-switch test timed out", {"timeout_sec": timeout_sec})
                    return _json_ok(
                        {
                            "switched": False,
                            "event": None,
                            "events": events_after[-30:],
                            "used_threshold_5h": threshold_5h,
                            "timeout_sec": timeout_sec,
                        }
                    )
                finally:
                    cfg_restore = load_cam_config()
                    cfg_restore["auto_switch"] = auto_before
                    save_cam_config(cfg_restore)
                    runtime["test_run_active"] = False
                    runtime["test_stop"].clear()
            if self.command == "POST" and path == "/api/local/save":
                name = str(body.get("name", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "name is required")
                force = bool_value(body.get("force"), False)
                rc, out, err = _capture_fn(lambda: cmd_save(name, overwrite=force))
                payload = _command_result("local.save", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local save failed", 400, payload)
                invalidate_usage_cache("local-save")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/add":
                name = str(body.get("name", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "name is required")
                timeout = int_value(body.get("timeout"), 300, minimum=1)
                force = bool_value(body.get("force"), False)
                device_auth = bool_value(body.get("device_auth"), False)
                keep_temp = bool_value(body.get("keep_temp_home"), False)
                rc, out, err = _capture_fn(lambda: cmd_add(name, timeout, force, keep_temp, device_auth))
                payload = _command_result("local.add", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local add failed", 400, payload)
                invalidate_usage_cache("local-add")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/add/start":
                name = str(body.get("name", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "name is required")
                timeout = int_value(body.get("timeout"), 600, minimum=30)
                force = bool_value(body.get("force"), False)
                keep_temp = bool_value(body.get("keep_temp_home"), False)
                device_auth = bool_value(body.get("device_auth"), True)
                try:
                    payload = start_add_login_session(
                        name=name,
                        timeout=timeout,
                        overwrite=force,
                        keep_temp_home=keep_temp,
                        device_auth=device_auth,
                        invalidate_usage_cache_fn=invalidate_usage_cache,
                    )
                except RuntimeError as e:
                    return _json_error("START_FAILED", str(e), 400)
                except Exception as e:
                    return _json_error("START_FAILED", f"failed to start login session: {e}", 500)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/add/cancel":
                sid = str(body.get("id", "")).strip()
                if not sid:
                    return _json_error("MISSING_ID", "session id is required")
                payload = cancel_add_login_session(sid)
                if not payload:
                    return _json_error("NOT_FOUND", "session not found", 404)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/remove":
                name = str(body.get("name", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "name is required")
                rc, out, err = _capture_fn(lambda: cmd_remove(name))
                payload = _command_result("local.remove", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local remove failed", 400, payload)
                invalidate_usage_cache("local-remove")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/remove-all":
                rc, out, err = _capture_fn(cmd_remove_all_profiles)
                payload = _command_result("local.remove_all", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local remove all failed", 400, payload)
                invalidate_usage_cache("local-remove-all")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/rename":
                old_name = str(body.get("old_name", "")).strip()
                new_name = str(body.get("new_name", "")).strip()
                if not old_name or not new_name:
                    return _json_error("MISSING_NAME", "old_name and new_name are required")
                force = bool_value(body.get("force"), False)
                rc, out, err = _capture_fn(lambda: cmd_rename(old_name, new_name, force))
                payload = _command_result("local.rename", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local rename failed", 400, payload)
                invalidate_usage_cache("local-rename")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/run":
                name = str(body.get("name", "")).strip()
                cmdline = str(body.get("cmdline", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "name is required")
                args = shlex.split(cmdline) if cmdline else []
                rc, out, err = _capture_fn(lambda: cmd_run(name, args))
                payload = _command_result("local.run", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local run failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/login":
                args = ["login"]
                if bool_value(body.get("device_auth"), False):
                    args.append("--device-auth")
                timeout = int_value(body.get("timeout"), 600, minimum=1)
                r = run_codex_auth_capture(args, timeout_sec=timeout)
                payload = _command_result("adv.login", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced login failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/switch":
                args = ["switch"]
                query = str(body.get("query", "")).strip()
                if query:
                    args.append(query)
                r = run_codex_auth_capture(args, timeout_sec=60)
                payload = _command_result("adv.switch", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced switch failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/remove":
                args = ["remove"]
                if bool_value(body.get("all"), False):
                    args.append("--all")
                else:
                    query = str(body.get("query", "")).strip()
                    if query:
                        args.append(query)
                r = run_codex_auth_capture(args, timeout_sec=60)
                payload = _command_result("adv.remove", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced remove failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/import":
                args = ["import"]
                if bool_value(body.get("cpa"), False):
                    args.append("--cpa")
                if bool_value(body.get("purge"), False):
                    args.append("--purge")
                path_arg = str(body.get("path", "")).strip()
                if path_arg:
                    args.append(path_arg)
                alias = str(body.get("alias", "")).strip()
                if alias:
                    args.extend(["--alias", alias])
                r = run_codex_auth_capture(args, timeout_sec=120)
                payload = _command_result("adv.import", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced import failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/config":
                scope = str(body.get("scope", "")).strip()
                if scope not in ("auto", "api"):
                    return _json_error("BAD_SCOPE", "scope must be 'auto' or 'api'")
                args = ["config", scope]
                action = str(body.get("action", "")).strip()
                if action in ("enable", "disable"):
                    args.append(action)
                if scope == "auto":
                    if body.get("threshold_5h") is not None:
                        args.extend(["--5h", str(int_value(body.get("threshold_5h"), 10, minimum=0))])
                    if body.get("threshold_weekly") is not None:
                        args.extend(["--weekly", str(int_value(body.get("threshold_weekly"), 5, minimum=0))])
                r = run_codex_auth_capture(args, timeout_sec=30)
                payload = _command_result("adv.config", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced config failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/daemon":
                mode = str(body.get("mode", "once")).strip()
                if mode not in ("watch", "once"):
                    return _json_error("BAD_MODE", "mode must be 'watch' or 'once'")
                r = run_codex_auth_capture(["daemon", f"--{mode}"], timeout_sec=90)
                payload = _command_result("adv.daemon", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced daemon failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/clean":
                r = run_codex_auth_capture(["clean"], timeout_sec=60)
                payload = _command_result("adv.clean", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced clean failed", 400, payload)
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/adv/auth":
                argv = body.get("args")
                if isinstance(argv, str):
                    argv = shlex.split(argv)
                if not isinstance(argv, list) or not argv:
                    return _json_error("BAD_ARGS", "args must be a non-empty array or command string")
                argv = [str(x) for x in argv if str(x).strip()]
                if not argv:
                    return _json_error("BAD_ARGS", "args must be a non-empty array or command string")
                timeout = int_value(body.get("timeout"), 60, minimum=1)
                r = run_codex_auth_capture(argv, timeout_sec=timeout)
                payload = _command_result("adv.auth", r["exit_code"], r["stdout"], r["stderr"])
                if not r["ok"]:
                    return _json_error("COMMAND_FAILED", "advanced auth failed", 400, payload)
                return _json_ok(payload)
            return _json_error("NOT_FOUND", "endpoint not found", 404)

        def do_GET(self):
            req_started = time.time()
            req_id = secrets.token_hex(6)
            parsed = urlparse(self.path)
            last_seen["ts"] = time.time()
            if parsed.path == "/api/local/export/download":
                q = parse_qs(parsed.query)
                req_token = (q.get("token", [""])[0] or "").strip()
                if req_token != token:
                    self._reply(403, {"ok": False, "error": {"code": "FORBIDDEN", "message": "invalid session token"}})
                    return
                export_id = str((q.get("id", [""])[0] or "")).strip()
                if not export_id:
                    self._reply(400, {"ok": False, "error": {"code": "MISSING_ID", "message": "export id is required"}})
                    return
                entry = get_export_session(export_id)
                if not entry:
                    self._reply(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "export download is missing or expired"}})
                    return
                archive_path = Path(str(entry.get("path") or ""))
                if not archive_path.exists():
                    self._reply(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "export archive not found"}})
                    return
                raw = archive_path.read_bytes()
                filename = str(entry.get("filename") or archive_path.name or _profile_archive_filename())
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                self.wfile.write(raw)
                return
            if parsed.path == "/styles.css":
                self._reply(200, render_ui_css(), "text/css; charset=utf-8")
                return
            if parsed.path == "/app.js":
                js = render_ui_js(token)
                self._reply(200, js, "application/javascript; charset=utf-8")
                return
            if parsed.path == "/" or parsed.path == "/index.html":
                html = render_ui_html(interval_sec, token)
                self._reply(200, html, "text/html; charset=utf-8")
                return
            if parsed.path == "/app-icon.svg":
                self._reply(200, load_app_icon_svg(), "image/svg+xml; charset=utf-8")
                return
            if parsed.path == "/sw.js":
                script = render_ui_sw_js()
                self._reply(200, script, "application/javascript; charset=utf-8")
                return
            if parsed.path.startswith("/api/"):
                status_code, payload = self._api()
                if isinstance(payload, dict):
                    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                    meta["request_id"] = req_id
                    meta["duration_ms"] = int((time.time() - req_started) * 1000)
                    payload["meta"] = meta
                self._reply(status_code, payload)
                return
            self._reply(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "not found"}})

        def do_POST(self):
            req_started = time.time()
            req_id = secrets.token_hex(6)
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                status_code, payload = self._api()
                if isinstance(payload, dict):
                    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                    meta["request_id"] = req_id
                    meta["duration_ms"] = int((time.time() - req_started) * 1000)
                    payload["meta"] = meta
                self._reply(status_code, payload)
                return
            self._reply(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "not found"}})

    try:
        server = ThreadingHTTPServer((default_host, port), UIHandler)
    except Exception as e:
        log_runtime("error", "server startup failed", {"host": default_host, "port": port, "error": str(e)})
        print(f"error: failed to start UI server on {default_host}:{port}: {e}")
        return 1

    actual_host, actual_port = server.server_address[0], server.server_address[1]
    url = f"http://{actual_host}:{actual_port}/"
    auto_thread = threading.Thread(target=auto_switch_tick, daemon=True)
    auto_thread.start()
    write_ui_pid_info(actual_host, actual_port, os.getpid(), token)
    log_runtime("info", "ui service started", {"host": actual_host, "port": actual_port, "pid": os.getpid(), "version": UI_BUILD_VERSION})
    print(f"UI running at: {url}")
    print("Press Ctrl+C to stop.")

    if idle_timeout_sec > 0:
        def watchdog():
            while True:
                time.sleep(2.0)
                if time.time() - last_seen["ts"] > idle_timeout_sec:
                    try:
                        server.shutdown()
                    except Exception:
                        pass
                    break

        t = threading.Thread(target=watchdog, daemon=True)
        t.start()

    if not no_open:
        try:
            webbrowser.open(f"{url}?v={UI_BUILD_VERSION}")
        except Exception as e:
            print(f"warning: could not open browser automatically: {e}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nUI stopped.")
    finally:
        runtime["stop_event"].set()
        try:
            auto_thread.join(timeout=1.0)
        except Exception:
            pass
        log_runtime("info", "ui service stopped", {"pid": os.getpid()})
        server.server_close()
        info = read_ui_pid_info() or {}
        if info.get("pid") == os.getpid():
            clear_ui_pid_info()
    return 0


def ui_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/"


def ui_open_url(host: str, port: int) -> str:
    return f"{ui_url(host, port)}?v={UI_BUILD_VERSION}"


def is_ui_healthy(host: str, port: int, timeout_sec: float = 1.2) -> bool:
    paths = ["api/health", "api/status"]
    for p in paths:
        try:
            req = urllib.request.Request(url=ui_url(host, port) + p, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                payload = json.loads(raw)
                if bool(payload.get("ok")):
                    return True
        except Exception:
            continue
    return False


def ensure_ui_state_dir() -> None:
    UI_STATE_DIR.mkdir(parents=True, exist_ok=True)


def write_ui_pid_info(host: str, port: int, pid: int, token: str) -> None:
    ensure_ui_state_dir()
    data = {
        "host": host,
        "port": port,
        "pid": pid,
        "token": token,
        "started_at": dt.datetime.now().isoformat(),
    }
    with UI_PID_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _set_private_permissions(UI_PID_FILE)


def read_ui_pid_info():
    try:
        if not UI_PID_FILE.exists():
            return None
        return load_json(UI_PID_FILE)
    except Exception:
        return None


def clear_ui_pid_info() -> None:
    try:
        if UI_PID_FILE.exists():
            UI_PID_FILE.unlink()
    except Exception:
        pass


def stop_ui_process(pid: int) -> bool:
    try:
        if sys.platform.startswith("win"):
            proc = _subprocess_run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return proc.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def _kill_cam_processes(exclude_pids: set[int] | None = None) -> int:
    excludes = set(exclude_pids or set())
    killed = 0
    if sys.platform.startswith("win"):
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            return 0
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "$targets=Get-CimInstance Win32_Process | Where-Object {"
            "$cmd=($_.CommandLine + '').ToLower();"
            "$cmd -like '*codex_account_manager*' -or $cmd -like '*bin\\\\codex-account*' -or $cmd -like '*codex-account ui*' -or $cmd -like '*codex-account ui-service*'"
            "};"
            "$k=0;"
            "foreach($t in $targets){"
            "  try { Stop-Process -Id $t.ProcessId -Force -ErrorAction Stop; $k++ } catch {}"
            "};"
            "Write-Output $k"
        )
        try:
            proc = subprocess.run([ps, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=6)
            if proc.returncode == 0:
                out = (proc.stdout or "").strip()
                return int(out) if out.isdigit() else 0
        except Exception:
            return 0
        return 0

    try:
        p = subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True, text=True, timeout=4)
        if p.returncode != 0:
            return 0
        for line in (p.stdout or "").splitlines():
            row = line.strip()
            if not row:
                continue
            parts = row.split(None, 1)
            if not parts or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            if pid in excludes or pid == os.getpid():
                continue
            cmd = parts[1].lower() if len(parts) > 1 else ""
            if (
                "codex_account_manager" in cmd
                or "bin/codex-account" in cmd
                or "codex-account ui" in cmd
                or "codex-account ui-service" in cmd
            ):
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                except Exception:
                    pass
    except Exception:
        return killed
    return killed


def wait_ui_stopped(host: str, port: int, timeout_sec: float = 6.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        if not is_ui_healthy(host, port, timeout_sec=0.6):
            return True
        time.sleep(0.2)
    return False


def wait_ui_started(host: str, port: int, timeout_sec: float = 8.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        if is_ui_healthy(host, port, timeout_sec=0.8):
            return True
        time.sleep(0.2)
    return False


def cmd_ui(host: str, port: int, no_open: bool, interval_sec: float, idle_timeout_sec: float, foreground: bool) -> int:
    use_host = host or UI_DEFAULT_HOST
    if port == 0:
        port = UI_DEFAULT_PORT

    if is_ui_healthy(use_host, port):
        print(f"UI already running at: {ui_url(use_host, port)}")
        if not no_open:
            try:
                webbrowser.open(ui_open_url(use_host, port))
            except Exception as e:
                print(f"warning: could not open browser automatically: {e}")
        return 0

    token = secrets.token_urlsafe(24)
    if foreground:
        write_ui_pid_info(use_host, port, os.getpid(), token)
        try:
            return cmd_ui_serve(
                host=use_host,
                port=port,
                no_open=no_open,
                interval_sec=interval_sec,
                idle_timeout_sec=idle_timeout_sec,
                token=token,
            )
        finally:
            clear_ui_pid_info()

    script = str(Path(__file__).resolve())
    cmd = [
        sys.executable,
        script,
        "ui",
        "--host",
        use_host,
        "--port",
        str(port),
        "--interval",
        str(interval_sec),
        "--idle-timeout",
        str(idle_timeout_sec),
        "--serve",
        "--token",
        token,
        "--no-open",
    ]
    try:
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform.startswith("win"):
            popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except Exception as e:
        print(f"error: failed to start detached UI: {e}")
        return 1

    write_ui_pid_info(use_host, port, proc.pid, token)
    if not wait_ui_started(use_host, port):
        print(f"error: UI failed to become healthy on {use_host}:{port}")
        return 1

    print(f"UI running in background at: {ui_url(use_host, port)}")
    print(f"pid: {proc.pid}")
    if idle_timeout_sec > 0:
        print(f"idle auto-stop: {idle_timeout_sec:.0f}s after last browser heartbeat")
    else:
        print("idle auto-stop: disabled (persistent background service)")
    if not no_open:
        try:
            webbrowser.open(ui_open_url(use_host, port))
        except Exception as e:
            print(f"warning: could not open browser automatically: {e}")
    return 0


def electron_app_dir(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parent.parent
    return root / "electron"


def _internet_available_for_npm(timeout_sec: float = 1.5) -> bool:
    targets = [
        ("registry.npmjs.org", 443),
        ("8.8.8.8", 53),
    ]
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout_sec):
                return True
        except OSError:
            continue
    return False


def cmd_electron(no_install: bool = False, electron_dir: Path | None = None) -> int:
    app_dir = electron_dir or electron_app_dir()
    package_json = app_dir / "package.json"
    if not package_json.exists():
        print(
            "error: Electron desktop shell is not available in this install. "
            "Run from a source checkout that contains the electron/ directory."
        )
        return 1
    if not shutil.which("npm"):
        print("error: npm is required to run the Electron desktop shell.")
        return 1

    runtime_deps = ("electron", "vite", "react", "react-dom")
    missing_deps = [dep for dep in runtime_deps if not (app_dir / "node_modules" / dep).exists()]
    if no_install and missing_deps:
        print(
            "error: Electron desktop shell dependencies are missing: "
            + ", ".join(missing_deps)
            + ". Run `codex-account electron` without --no-install first."
        )
        return 1
    if missing_deps and not no_install:
        print("Checking Electron desktop shell dependencies...")
        print(f"missing: {', '.join(missing_deps)}")
        print(f"working directory: {app_dir}")
        if not _internet_available_for_npm():
            print(
                "error: Electron dependencies are missing and no internet connection was detected. "
                "Reconnect and retry, or install the missing npm packages manually."
            )
            return 1
        print("running: npm install --foreground-scripts --progress=true --loglevel=info")
        install = _subprocess_run(
            ["npm", "install", "--foreground-scripts", "--progress=true", "--loglevel=info"],
            cwd=str(app_dir),
        )
        install_rc = int(getattr(install, "returncode", 0) or 0)
        if install_rc != 0:
            print(f"error: Electron dependency install failed with exit code {install_rc}")
            return install_rc
        print("Electron dependency check complete.")

    print("Starting Electron desktop shell...")
    dev = _subprocess_run(["npm", "run", "dev"], cwd=str(app_dir))
    return int(getattr(dev, "returncode", 0) or 0)


def _pids_listening_on_port(port: int) -> set[int]:
    pids: set[int] = set()
    if shutil.which("lsof"):
        try:
            p = _subprocess_run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
            for raw in p.stdout.splitlines():
                raw = raw.strip()
                if raw.isdigit():
                    pids.add(int(raw))
        except Exception:
            pass
    if pids:
        return pids
    if shutil.which("ss"):
        try:
            p = _subprocess_run(["ss", "-lptn", f"sport = :{port}"], capture_output=True, text=True)
            for match in re.findall(r"pid=(\d+)", p.stdout):
                pids.add(int(match))
        except Exception:
            pass
    if pids:
        return pids
    if shutil.which("netstat"):
        try:
            p = _subprocess_run(["netstat", "-nlp"], capture_output=True, text=True)
            for line in p.stdout.splitlines():
                if f":{port} " not in line:
                    continue
                m = re.search(r"\s(\d+)/", line)
                if m:
                    pids.add(int(m.group(1)))
        except Exception:
            pass
    return pids


def cmd_ui_service(action: str, host: str, port: int, no_open: bool, interval_sec: float, idle_timeout_sec: float) -> int:
    use_host = host or UI_DEFAULT_HOST
    use_port = port or UI_DEFAULT_PORT
    if action == "status":
        info = read_ui_pid_info() or {}
        running = is_ui_healthy(use_host, use_port)
        print_json(
            {
                "running": running,
                "url": ui_url(use_host, use_port),
                "pid_file": str(UI_PID_FILE),
                "pid": info.get("pid"),
            }
        )
        return 0
    if action == "start":
        return cmd_ui(
            host=use_host,
            port=use_port,
            no_open=no_open,
            interval_sec=interval_sec,
            idle_timeout_sec=idle_timeout_sec,
            foreground=False,
        )
    if action == "stop":
        info = read_ui_pid_info() or {}
        pid = info.get("pid")
        stopped = False
        if isinstance(pid, int):
            stopped = stop_ui_process(pid)
        if not stopped and sys.platform != "win32":
            for other_pid in _pids_listening_on_port(use_port):
                try:
                    os.kill(int(other_pid), signal.SIGTERM)
                    stopped = True
                except Exception:
                    pass
        ok = wait_ui_stopped(use_host, use_port)
        clear_ui_pid_info()
        if ok:
            print("UI service stopped")
            return 0
        print("error: failed to stop UI service")
        return 1
    if action == "restart":
        cmd_ui_service("stop", use_host, use_port, no_open=True, interval_sec=interval_sec, idle_timeout_sec=idle_timeout_sec)
        return cmd_ui_service("start", use_host, use_port, no_open=no_open, interval_sec=interval_sec, idle_timeout_sec=idle_timeout_sec)
    print(f"error: unknown action '{action}'")
    return 1


def _autostart_label() -> str:
    return "codex.account.manager.ui"


def _ui_service_command_base() -> list[str]:
    script_path = str(Path(__file__).resolve())
    if sys.platform.startswith("win"):
        current_python = str(sys.executable or "").strip()
        if current_python and Path(current_python).exists():
            return [current_python, script_path]
        py_launcher = shutil.which("py")
        if py_launcher:
            return [py_launcher, "-3", script_path]
        python_cmd = shutil.which("python")
        if python_cmd:
            return [python_cmd, script_path]
    current_python = str(sys.executable or "").strip()
    if current_python and Path(current_python).exists():
        return [current_python, script_path]
    python3_cmd = shutil.which("python3")
    if python3_cmd:
        return [python3_cmd, script_path]
    return ["python", script_path]


def _build_ui_service_restart_command(host: str, port: int, interval_sec: float, idle_timeout_sec: float) -> list[str]:
    return _ui_service_command_base() + [
        "ui-service",
        "restart",
        "--host",
        str(host or UI_DEFAULT_HOST),
        "--port",
        str(int(port or UI_DEFAULT_PORT)),
        "--interval",
        str(float(interval_sec)),
        "--idle-timeout",
        str(float(idle_timeout_sec)),
        "--no-open",
    ]


def _build_ui_restart_helper_command(host: str, port: int, interval_sec: float, idle_timeout_sec: float) -> list[str]:
    helper_code = (
        "import subprocess,time,sys; "
        "time.sleep(0.45); "
        "sys.exit(subprocess.call(sys.argv[1:]))"
    )
    restart_cmd = _build_ui_service_restart_command(host, port, interval_sec, idle_timeout_sec)
    return [
        restart_cmd[0],
        "-c",
        helper_code,
        *restart_cmd,
    ]


def _autostart_command(no_open: bool = True) -> list[str]:
    cmd = _ui_service_command_base() + ["ui-service", "start"]
    if no_open:
        cmd.append("--no-open")
    return cmd


def _linux_systemd_user_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    try:
        proc = _subprocess_run(["systemctl", "--user", "list-unit-files"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc.returncode == 0
    except Exception:
        return False


def _linux_xdg_autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / "codex-account-ui.desktop"


def cmd_ui_autostart(action: str, host: str, port: int) -> int:
    label = _autostart_label()
    cmd = _autostart_command(no_open=True) + ["--host", host or UI_DEFAULT_HOST, "--port", str(port or UI_DEFAULT_PORT)]

    if sys.platform == "darwin":
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_path = plist_dir / f"{label}.plist"
        if action == "install":
            plist_dir.mkdir(parents=True, exist_ok=True)
            plist = f'''<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>Label</key><string>{label}</string><key>ProgramArguments</key><array>{''.join([f'<string>{x}</string>' for x in cmd])}</array><key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>\n'''
            plist_path.write_text(plist, encoding="utf-8")
            _subprocess_run(["launchctl", "unload", str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _subprocess_run(["launchctl", "load", str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"autostart installed: {plist_path}")
            return 0
        if action == "uninstall":
            _subprocess_run(["launchctl", "unload", str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if plist_path.exists():
                plist_path.unlink()
            print("autostart uninstalled")
            return 0
        if action == "status":
            installed = plist_path.exists()
            print_json({"installed": installed, "path": str(plist_path)})
            return 0

    if sys.platform.startswith("win"):
        task = "CodexAccountManagerUI"
        if action == "install":
            tr = subprocess.list2cmdline(cmd)
            rc = _subprocess_run(["schtasks", "/Create", "/TN", task, "/TR", tr, "/SC", "ONLOGON", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            if rc == 0:
                print("autostart installed")
                return 0
            print("error: failed to install windows autostart")
            return 1
        if action == "uninstall":
            _subprocess_run(["schtasks", "/Delete", "/TN", task, "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("autostart uninstalled")
            return 0
        if action == "status":
            rc = _subprocess_run(["schtasks", "/Query", "/TN", task], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            print_json({"installed": rc == 0, "task": task})
            return 0

    if action in ("install", "uninstall", "status"):
        if _linux_systemd_user_available():
            service_dir = Path.home() / ".config" / "systemd" / "user"
            service_path = service_dir / "codex-account-ui.service"
            if action == "install":
                service_dir.mkdir(parents=True, exist_ok=True)
                exec_cmd = " ".join([shlex.quote(x) for x in cmd])
                service_path.write_text(
                    f"[Unit]\nDescription=Codex Account Manager UI\n\n[Service]\nType=simple\nExecStart={exec_cmd}\nRestart=always\n\n[Install]\nWantedBy=default.target\n",
                    encoding="utf-8",
                )
                _subprocess_run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _subprocess_run(["systemctl", "--user", "enable", "--now", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"autostart installed: {service_path}")
                return 0
            if action == "uninstall":
                _subprocess_run(["systemctl", "--user", "disable", "--now", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if service_path.exists():
                    service_path.unlink()
                _subprocess_run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("autostart uninstalled")
                return 0
            if action == "status":
                enabled = _subprocess_run(["systemctl", "--user", "is-enabled", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                active = _subprocess_run(["systemctl", "--user", "is-active", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                print_json({"installed": service_path.exists(), "enabled": enabled, "active": active, "backend": "systemd", "path": str(service_path)})
                return 0

        desktop_path = _linux_xdg_autostart_path()
        if action == "install":
            desktop_path.parent.mkdir(parents=True, exist_ok=True)
            exec_cmd = " ".join([shlex.quote(x) for x in cmd])
            desktop_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Codex Account Manager UI\n"
                "Comment=Start Codex Account Manager UI service\n"
                f"Exec={exec_cmd}\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n",
                encoding="utf-8",
            )
            print(f"autostart installed: {desktop_path}")
            return 0
        if action == "uninstall":
            if desktop_path.exists():
                desktop_path.unlink()
            print("autostart uninstalled")
            return 0
        if action == "status":
            print_json({"installed": desktop_path.exists(), "backend": "xdg", "path": str(desktop_path)})
            return 0

    print(f"error: unsupported autostart action '{action}'")
    return 1


def cmd_autoswitch(action: str) -> int:
    cfg = load_cam_config()
    if action == "status":
        print_json({"enabled": bool(((cfg.get("auto_switch") or {}).get("enabled"))), "config": cfg.get("auto_switch", {})})
        return 0
    if action == "enable":
        cfg = update_cam_config({"auto_switch": {"enabled": True}})
        print("auto-switch enabled")
        print_json(cfg.get("auto_switch", {}))
        return 0
    if action == "disable":
        cfg = update_cam_config({"auto_switch": {"enabled": False}})
        print("auto-switch disabled")
        print_json(cfg.get("auto_switch", {}))
        return 0
    if action == "stop":
        cfg = update_cam_config({"auto_switch": {"enabled": False}})
        print("auto-switch force-stopped (disabled and pending runtime should clear in UI)")
        print_json(cfg.get("auto_switch", {}))
        return 0
    if action == "run-once":
        usage_payload = collect_usage_local_data(timeout_sec=7, config=cfg)
        candidate = _choose_auto_switch_candidate(usage_payload, cfg)
        if not candidate:
            print("error: no eligible auto-switch candidate found")
            return 1
        return cmd_switch(str(candidate.get("name")), restart_codex=True)
    print(f"error: unknown autoswitch action '{action}'")
    return 1


def cmd_notify(action: str) -> int:
    if action == "test":
        print("notification test event can be triggered from web UI via /api/notifications/test")
        return 0
    print(f"error: unknown notify action '{action}'")
    return 1


class FriendlyArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse exits
        text = (message or "invalid arguments").strip()
        self.print_usage(sys.stderr)
        print(f"\nerror: {text}", file=sys.stderr)

        if "invalid choice" in text and "choose from" in text:
            bad = self._extract_invalid_choice(text)
            commands = self._known_commands()
            if bad and commands:
                matches = difflib.get_close_matches(bad, commands, n=3, cutoff=0.4)
                if matches:
                    print("Did you mean:", file=sys.stderr)
                    for item in matches:
                        print(f"  {item}", file=sys.stderr)

        cmd = Path(self.prog).name or self.prog
        print(f"Run '{cmd} --help' to see available commands.", file=sys.stderr)
        if " " in self.prog:
            print(f"Run '{self.prog} --help' to see command options and examples.", file=sys.stderr)
            print("", file=sys.stderr)
            self.print_help(sys.stderr)
        self.exit(2)

    def _known_commands(self) -> list[str]:
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                return sorted(action.choices.keys())
        return []

    @staticmethod
    def _extract_invalid_choice(message: str) -> str | None:
        m = re.search(r"invalid choice: '([^']+)'", message)
        if m:
            return m.group(1).strip()
        return None


def _print_default_overview(parser: argparse.ArgumentParser) -> None:
    print(f"codex-account v{APP_VERSION}")
    print("Most useful commands:")
    print("  codex-account add work --device-auth")
    print("  codex-account list")
    print("  codex-account switch work")
    print("  codex-account current")
    print("  codex-account add <name> --device-auth")
    print("  codex-account usage-local --watch --interval 3")
    print("  codex-account ui --no-open")
    print("  codex-account ui-service status")
    print("")
    parser.print_help()


def main() -> int:
    parser = FriendlyArgumentParser(
        description="Local Codex account profile switcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick start:\n"
            "  1) Add an account profile:\n"
            "     codex-account add work --device-auth\n"
            "  2) Check saved profiles:\n"
            "     codex-account list\n"
            "  3) Switch active account:\n"
            "     codex-account switch work\n"
            "  4) Verify active account:\n"
            "     codex-account current\n"
            "\n"
            "Run 'codex-account <command> --help' for command-specific examples."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser(
        "save",
        help="Save current ~/.codex/auth.json as a named profile",
        description="Save the current active auth file as a reusable local profile.",
    )
    p_save.add_argument("name")
    p_save.add_argument("--force", action="store_true", help="Overwrite existing profile")

    p_add = sub.add_parser(
        "add",
        help="Run fresh browser login and save it directly as a profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create a new profile by logging in with a temporary isolated CODEX_HOME.\n"
            "Recommended for clean account onboarding."
        ),
        epilog=(
            "Examples:\n"
            "  codex-account add work --device-auth\n"
            "  codex-account add personal --timeout 600\n"
            "  codex-account add team --force\n"
            "\n"
            "After add completes, switch to it with:\n"
            "  codex-account switch <name>"
        ),
    )
    p_add.add_argument("name")
    p_add.add_argument("--timeout", type=int, default=300, help="Login timeout in seconds (default: 300)")
    p_add.add_argument("--force", action="store_true", help="Overwrite existing profile")
    p_add.add_argument("--keep-temp-home", action="store_true", help="Keep temporary CODEX_HOME for debugging")
    p_add.add_argument("--device-auth", action="store_true", help="Use device auth flow to reduce browser cookie auto-selection")

    p_list = sub.add_parser("list", help="List saved profiles", description="List all saved local profiles.")
    p_list.add_argument("--json", action="store_true", help="Output structured JSON")
    p_usage_local = sub.add_parser("usage-local", help="Show usage per local profile (no dedupe)")
    p_usage_local.add_argument("--timeout", type=int, default=7, help="API timeout seconds per profile (default: 7)")
    p_usage_local.add_argument("--watch", action="store_true", help="Continuously refresh usage table")
    p_usage_local.add_argument("--interval", type=float, default=5.0, help="Watch refresh interval seconds (default: 5)")
    p_usage_local.add_argument("--json", action="store_true", help="Output structured JSON")
    p_usage = sub.add_parser("usage", help="Alias wrapper for usage commands")
    p_usage.add_argument("scope", nargs="?", default="local", choices=["local"], help="Usage scope (default: local)")
    p_usage.add_argument("--timeout", type=int, default=7, help="API timeout seconds per profile (default: 7)")
    p_usage.add_argument("--watch", action="store_true", help="Continuously refresh usage table")
    p_usage.add_argument("--interval", type=float, default=5.0, help="Watch refresh interval seconds (default: 5)")
    p_usage.add_argument("--json", action="store_true", help="Output structured JSON")
    p_current = sub.add_parser("current", help="Show current active account hint", description="Show the currently active account/profile hint.")
    p_current.add_argument("--json", action="store_true", help="Output structured JSON")

    p_switch = sub.add_parser(
        "switch",
        help="Switch active ~/.codex/auth.json to a saved profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Activate a saved profile by replacing ~/.codex/auth.json with that profile.\n"
            "By default, Codex app restart hooks are attempted after switching."
        ),
        epilog=(
            "Examples:\n"
            "  codex-account switch work\n"
            "  codex-account switch personal --no-restart\n"
            "\n"
            "Find available profile names first:\n"
            "  codex-account list"
        ),
    )
    p_switch.add_argument("name")
    p_switch.add_argument("--no-restart", action="store_true", help="Do not restart Codex after switch")

    p_run = sub.add_parser("run", help="Run codex (or any command) with an isolated profile CODEX_HOME")
    p_run.add_argument("name")
    p_run.add_argument("command", nargs=argparse.REMAINDER, help="Command to run, e.g. -- codex or -- codex -p ...")

    p_remove = sub.add_parser("remove", help="Remove a saved profile")
    p_remove.add_argument("name")
    p_rename = sub.add_parser("rename", help="Rename a saved profile")
    p_rename.add_argument("old_name")
    p_rename.add_argument("new_name")
    p_rename.add_argument("--force", action="store_true", help="Overwrite destination if it exists")
    p_export_profiles = sub.add_parser("export-profiles", help="Export saved local profiles into a migration archive")
    p_export_profiles.add_argument("names", nargs="*", help="Optional profile names to export. Omit to export all profiles.")
    p_export_profiles.add_argument("-o", "--output", help=f"Output archive path (default: ./{_profile_archive_filename()})")
    p_import_profiles = sub.add_parser("import-profiles", help="Analyze or apply a local profile migration archive")
    p_import_profiles.add_argument("archive", help=f"Path to a {PROFILE_ARCHIVE_EXT} archive")
    p_import_profiles.add_argument("--apply", action="store_true", help="Apply the import after analysis")
    p_import_profiles.add_argument("--overwrite", action="store_true", help="When used with --apply, overwrite conflicting profiles instead of skipping them")

    # codex-auth feature wrappers
    p_status = sub.add_parser("status", help="(Advanced) codex-auth status")
    p_status.add_argument("--json", action="store_true", help="Output structured JSON")

    p_doctor = sub.add_parser("doctor", help="Report local desktop runtime diagnostics")
    p_doctor.add_argument("--json", action="store_true", help="Output structured JSON")

    p_login_adv = sub.add_parser("login", help="(Advanced) codex-auth login wrapper")
    p_login_adv.add_argument("--device-auth", action="store_true", help="Use device auth flow")

    p_import_adv = sub.add_parser("import", help="(Advanced) codex-auth import wrapper")
    p_import_adv.add_argument("path", nargs="?", help="Path to auth file or directory")
    p_import_adv.add_argument("--alias", dest="alias_value", help="Alias for single-file import")
    p_import_adv.add_argument("--cpa", action="store_true", help="Import CLIProxyAPI format")
    p_import_adv.add_argument("--purge", action="store_true", help="Rebuild registry from auth snapshots")

    p_switch_adv = sub.add_parser("switch-adv", help="(Advanced) codex-auth switch wrapper")
    p_switch_adv.add_argument("query", nargs="?", help="Optional query/keyword")

    p_list_adv = sub.add_parser("list-adv", help="(Advanced) codex-auth list wrapper")
    p_list_adv.add_argument("--debug", action="store_true", help="Show debug columns")

    p_remove_adv = sub.add_parser("remove-adv", help="(Advanced) codex-auth remove wrapper")
    p_remove_adv.add_argument("query", nargs="?", help="Optional query/keyword")
    p_remove_adv.add_argument("--all", action="store_true", help="Remove all managed accounts")

    p_config_adv = sub.add_parser("config", help="(Advanced) codex-auth config wrapper")
    p_config_adv.add_argument("scope", choices=["auto", "api"])
    p_config_adv.add_argument("action", nargs="?", help="enable|disable for scope")
    p_config_adv.add_argument("--5h", dest="threshold_5h", type=int, help="5h threshold percent")
    p_config_adv.add_argument("--weekly", dest="threshold_weekly", type=int, help="weekly threshold percent")

    p_daemon_adv = sub.add_parser("daemon", help="(Advanced) codex-auth daemon wrapper")
    mode = p_daemon_adv.add_mutually_exclusive_group(required=True)
    mode.add_argument("--watch", action="store_true")
    mode.add_argument("--once", action="store_true")

    sub.add_parser("clean", help="(Advanced) codex-auth clean")

    p_auth = sub.add_parser("auth", help="(Advanced) raw codex-auth passthrough")
    p_auth.add_argument("command", nargs=argparse.REMAINDER, help="Pass raw args after --, e.g. auth -- list --debug")

    p_ui = sub.add_parser("ui", help="Run local lightweight web UI")
    p_ui.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_ui.add_argument("--port", type=int, default=4673, help="Bind port (default: 4673)")
    p_ui.add_argument("--no-open", action="store_true", help="Do not open browser automatically")
    p_ui.add_argument("--interval", type=float, default=5.0, help="Default UI refresh interval seconds (default: 5)")
    p_ui.add_argument("--idle-timeout", type=float, default=0.0, help="Auto-stop background UI after inactivity seconds (0 disables, default: 0)")
    p_ui.add_argument("--foreground", action="store_true", help="Keep UI server attached to this terminal")
    p_ui.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    p_ui.add_argument("--token", default="", help=argparse.SUPPRESS)
    p_ui.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)
    p_ui.add_argument("--build", action="store_true", help=argparse.SUPPRESS)
    p_ui.add_argument("--check", action="store_true", help=argparse.SUPPRESS)
    p_ui.add_argument("--no-install", action="store_true", help=argparse.SUPPRESS)

    p_electron = sub.add_parser("electron", help="Run optional Electron desktop shell")
    p_electron.add_argument("--no-install", action="store_true", help="Skip npm install even when Electron dependencies are missing")

    p_ui_service = sub.add_parser("ui-service", help="Manage background UI service")
    p_ui_service.add_argument("action", choices=["start", "stop", "restart", "status"])
    p_ui_service.add_argument("--host", default=UI_DEFAULT_HOST, help=f"Bind host (default: {UI_DEFAULT_HOST})")
    p_ui_service.add_argument("--port", type=int, default=UI_DEFAULT_PORT, help=f"Bind port (default: {UI_DEFAULT_PORT})")
    p_ui_service.add_argument("--no-open", action="store_true", help="Do not open browser when starting service")
    p_ui_service.add_argument("--interval", type=float, default=5.0, help="Default UI refresh interval seconds")
    p_ui_service.add_argument("--idle-timeout", type=float, default=0.0, help="Idle timeout seconds (0 disables)")

    p_ui_autostart = sub.add_parser("ui-autostart", help="Install/uninstall/status for OS startup integration")
    p_ui_autostart.add_argument("action", choices=["install", "uninstall", "status"])
    p_ui_autostart.add_argument("--host", default=UI_DEFAULT_HOST, help=f"Bind host (default: {UI_DEFAULT_HOST})")
    p_ui_autostart.add_argument("--port", type=int, default=UI_DEFAULT_PORT, help=f"Bind port (default: {UI_DEFAULT_PORT})")

    p_autoswitch = sub.add_parser("autoswitch", help="Manage auto-switch config and run-once action")
    p_autoswitch.add_argument("action", choices=["status", "enable", "disable", "stop", "run-once"])

    p_notify = sub.add_parser("notify", help="Notification helper commands")
    p_notify.add_argument("action", choices=["test"])

    if len(sys.argv) <= 1:
        _print_default_overview(parser)
        return 0

    args = parser.parse_args()

    if args.cmd == "save":
        return cmd_save(args.name, overwrite=args.force)
    if args.cmd == "add":
        return cmd_add(
            args.name,
            timeout=args.timeout,
            overwrite=args.force,
            keep_temp_home=args.keep_temp_home,
            device_auth=args.device_auth,
        )
    if args.cmd == "list":
        return cmd_list(as_json=args.json)
    if args.cmd == "usage-local":
        if args.watch and args.json:
            print("error: --watch cannot be combined with --json")
            return 1
        if args.watch:
            return cmd_usage_local_watch(args.timeout, args.interval)
        return cmd_usage_local(args.timeout, as_json=args.json)
    if args.cmd == "usage":
        if args.watch and args.json:
            print("error: --watch cannot be combined with --json")
            return 1
        if args.watch:
            return cmd_usage_local_watch(args.timeout, args.interval)
        return cmd_usage_local(args.timeout, as_json=args.json)
    if args.cmd == "current":
        return cmd_current(as_json=args.json)
    if args.cmd == "switch":
        return cmd_switch(args.name, restart_codex=not args.no_restart)
    if args.cmd == "run":
        return cmd_run(args.name, args.command)
    if args.cmd == "remove":
        return cmd_remove(args.name)
    if args.cmd == "rename":
        return cmd_rename(args.old_name, args.new_name, force=args.force)
    if args.cmd == "export-profiles":
        return cmd_export_profiles(profile_names=args.names, output=args.output)
    if args.cmd == "import-profiles":
        return cmd_import_profiles(args.archive, apply=args.apply, overwrite=args.overwrite)
    if args.cmd == "status":
        return cmd_status(as_json=args.json)
    if args.cmd == "doctor":
        return cmd_doctor(as_json=args.json)
    if args.cmd == "login":
        cmd = ["login"]
        if args.device_auth:
            cmd.append("--device-auth")
        return run_codex_auth(cmd)
    if args.cmd == "import":
        cmd = ["import"]
        if args.cpa:
            cmd.append("--cpa")
        if args.purge:
            cmd.append("--purge")
        if args.path:
            cmd.append(args.path)
        if args.alias_value:
            cmd.extend(["--alias", args.alias_value])
        return run_codex_auth(cmd)
    if args.cmd == "switch-adv":
        cmd = ["switch"]
        if args.query:
            cmd.append(args.query)
        return run_codex_auth(cmd)
    if args.cmd == "list-adv":
        cmd = ["list"]
        if args.debug:
            cmd.append("--debug")
        return run_codex_auth(cmd)
    if args.cmd == "remove-adv":
        cmd = ["remove"]
        if args.all:
            cmd.append("--all")
        elif args.query:
            cmd.append(args.query)
        return run_codex_auth(cmd)
    if args.cmd == "config":
        cmd = ["config", args.scope]
        if args.scope == "auto":
            if args.action in ("enable", "disable"):
                cmd.append(args.action)
            if args.threshold_5h is not None:
                cmd.extend(["--5h", str(args.threshold_5h)])
            if args.threshold_weekly is not None:
                cmd.extend(["--weekly", str(args.threshold_weekly)])
        else:
            if args.action in ("enable", "disable"):
                cmd.append(args.action)
            else:
                print("error: config api requires action enable|disable")
                return 1
        return run_codex_auth(cmd)
    if args.cmd == "daemon":
        cmd = ["daemon", "--watch" if args.watch else "--once"]
        return run_codex_auth(cmd)
    if args.cmd == "clean":
        return run_codex_auth(["clean"])
    if args.cmd == "auth":
        return cmd_auth_passthrough(args.command)
    if args.cmd == "ui":
        if args.dev or args.build or args.check or args.no_install:
            print("error: legacy Tauri flags are removed. Use: codex-account ui [--host ... --port ... --no-open --interval ...]")
            return 1
        if args.serve:
            token = args.token.strip()
            if not token:
                print("error: missing internal --token")
                return 1
            return cmd_ui_serve(
                host=args.host,
                port=args.port,
                no_open=args.no_open,
                interval_sec=args.interval,
                idle_timeout_sec=args.idle_timeout,
                token=token,
            )
        return cmd_ui(
            host=args.host,
            port=args.port,
            no_open=args.no_open,
            interval_sec=args.interval,
            idle_timeout_sec=args.idle_timeout,
            foreground=args.foreground,
        )
    if args.cmd == "electron":
        return cmd_electron(no_install=args.no_install)
    if args.cmd == "ui-service":
        return cmd_ui_service(
            action=args.action,
            host=args.host,
            port=args.port,
            no_open=args.no_open,
            interval_sec=args.interval,
            idle_timeout_sec=args.idle_timeout,
        )
    if args.cmd == "ui-autostart":
        return cmd_ui_autostart(action=args.action, host=args.host, port=args.port)
    if args.cmd == "autoswitch":
        return cmd_autoswitch(args.action)
    if args.cmd == "notify":
        return cmd_notify(args.action)

    return 1


if __name__ == "__main__":
    sys.exit(main())
