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
    from .services import DiagnosticsLogger, UiConfigService, UsageService
except Exception:
    # Support direct script execution (python path/to/cli.py ...)
    from contracts import CommandResult  # type: ignore
    from services import DiagnosticsLogger, UiConfigService, UsageService  # type: ignore

CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_CONFIG_FILE = PROJECT_ROOT / "config.json"
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


DEFAULT_CAM_CONFIG = {
    "ui": {
        "theme": "auto",
        "advanced_mode": False,
        "current_auto_refresh_enabled": True,
        "current_refresh_interval_sec": 5,
        "all_auto_refresh_enabled": False,
        "all_refresh_interval_min": 5,
        "debug_mode": False,
    },
    "notifications": {
        "enabled": False,
        "scope": "any",
        "alarm_preset": "beacon",
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

ALARM_PRESETS = [
    {"id": "beacon", "label": "Beacon", "tones": [{"t": 0.00, "f": 880, "d": 0.22, "g": 0.18}, {"t": 0.28, "f": 1046, "d": 0.22, "g": 0.18}, {"t": 0.56, "f": 1318, "d": 0.34, "g": 0.2}]},
    {"id": "pulse", "label": "Pulse", "tones": [{"t": 0.00, "f": 740, "d": 0.18, "g": 0.16}, {"t": 0.22, "f": 740, "d": 0.18, "g": 0.18}, {"t": 0.44, "f": 740, "d": 0.22, "g": 0.2}]},
    {"id": "sentinel", "label": "Sentinel", "tones": [{"t": 0.00, "f": 523, "d": 0.24, "g": 0.16}, {"t": 0.30, "f": 659, "d": 0.24, "g": 0.17}, {"t": 0.60, "f": 784, "d": 0.30, "g": 0.19}]},
    {"id": "radar", "label": "Radar", "tones": [{"t": 0.00, "f": 640, "d": 0.12, "g": 0.14}, {"t": 0.16, "f": 760, "d": 0.12, "g": 0.15}, {"t": 0.32, "f": 920, "d": 0.16, "g": 0.18}, {"t": 0.56, "f": 1120, "d": 0.24, "g": 0.2}]},
    {"id": "lantern", "label": "Lantern", "tones": [{"t": 0.00, "f": 660, "d": 0.20, "g": 0.14}, {"t": 0.24, "f": 990, "d": 0.28, "g": 0.18}]},
    {"id": "signal", "label": "Signal", "tones": [{"t": 0.00, "f": 784, "d": 0.16, "g": 0.16}, {"t": 0.20, "f": 932, "d": 0.16, "g": 0.17}, {"t": 0.40, "f": 1174, "d": 0.16, "g": 0.18}, {"t": 0.66, "f": 1568, "d": 0.26, "g": 0.19}]},
    {"id": "harbor", "label": "Harbor", "tones": [{"t": 0.00, "f": 440, "d": 0.26, "g": 0.16}, {"t": 0.34, "f": 554, "d": 0.26, "g": 0.16}, {"t": 0.68, "f": 659, "d": 0.36, "g": 0.19}]},
    {"id": "nova", "label": "Nova", "tones": [{"t": 0.00, "f": 988, "d": 0.12, "g": 0.15}, {"t": 0.18, "f": 1244, "d": 0.14, "g": 0.16}, {"t": 0.38, "f": 1568, "d": 0.30, "g": 0.21}]},
    {"id": "ripple", "label": "Ripple", "tones": [{"t": 0.00, "f": 698, "d": 0.14, "g": 0.13}, {"t": 0.16, "f": 740, "d": 0.14, "g": 0.13}, {"t": 0.32, "f": 784, "d": 0.14, "g": 0.14}, {"t": 0.48, "f": 831, "d": 0.24, "g": 0.16}]},
    {"id": "flare", "label": "Flare", "tones": [{"t": 0.00, "f": 880, "d": 0.10, "g": 0.14}, {"t": 0.14, "f": 1108, "d": 0.10, "g": 0.16}, {"t": 0.28, "f": 1396, "d": 0.12, "g": 0.18}, {"t": 0.46, "f": 1760, "d": 0.28, "g": 0.2}]},
    {"id": "quartz", "label": "Quartz", "tones": [{"t": 0.00, "f": 587, "d": 0.18, "g": 0.15}, {"t": 0.24, "f": 880, "d": 0.18, "g": 0.17}, {"t": 0.50, "f": 1174, "d": 0.30, "g": 0.19}]},
    {"id": "orbit", "label": "Orbit", "tones": [{"t": 0.00, "f": 523, "d": 0.12, "g": 0.13}, {"t": 0.16, "f": 659, "d": 0.12, "g": 0.14}, {"t": 0.32, "f": 831, "d": 0.12, "g": 0.15}, {"t": 0.52, "f": 1046, "d": 0.22, "g": 0.18}]},
    {"id": "echo", "label": "Echo", "tones": [{"t": 0.00, "f": 660, "d": 0.22, "g": 0.12}, {"t": 0.30, "f": 660, "d": 0.18, "g": 0.10}, {"t": 0.56, "f": 990, "d": 0.26, "g": 0.17}]},
    {"id": "summit", "label": "Summit", "tones": [{"t": 0.00, "f": 784, "d": 0.18, "g": 0.15}, {"t": 0.24, "f": 988, "d": 0.18, "g": 0.16}, {"t": 0.50, "f": 1318, "d": 0.24, "g": 0.18}, {"t": 0.82, "f": 1568, "d": 0.32, "g": 0.2}]},
    {"id": "drift", "label": "Drift", "tones": [{"t": 0.00, "f": 494, "d": 0.24, "g": 0.15}, {"t": 0.28, "f": 622, "d": 0.24, "g": 0.15}, {"t": 0.60, "f": 740, "d": 0.34, "g": 0.18}]},
    {"id": "vector", "label": "Vector", "tones": [{"t": 0.00, "f": 932, "d": 0.12, "g": 0.16}, {"t": 0.16, "f": 1174, "d": 0.12, "g": 0.17}, {"t": 0.32, "f": 1480, "d": 0.12, "g": 0.18}, {"t": 0.52, "f": 1864, "d": 0.26, "g": 0.19}]},
    {"id": "glow", "label": "Glow", "tones": [{"t": 0.00, "f": 698, "d": 0.18, "g": 0.14}, {"t": 0.22, "f": 880, "d": 0.18, "g": 0.16}, {"t": 0.48, "f": 1046, "d": 0.28, "g": 0.18}]},
    {"id": "strobe", "label": "Strobe", "tones": [{"t": 0.00, "f": 1046, "d": 0.09, "g": 0.15}, {"t": 0.12, "f": 1046, "d": 0.09, "g": 0.15}, {"t": 0.24, "f": 1318, "d": 0.09, "g": 0.16}, {"t": 0.36, "f": 1318, "d": 0.09, "g": 0.16}, {"t": 0.52, "f": 1568, "d": 0.24, "g": 0.19}]},
    {"id": "ember", "label": "Ember", "tones": [{"t": 0.00, "f": 554, "d": 0.22, "g": 0.14}, {"t": 0.28, "f": 698, "d": 0.22, "g": 0.15}, {"t": 0.58, "f": 831, "d": 0.30, "g": 0.17}]},
    {"id": "zenith", "label": "Zenith", "tones": [{"t": 0.00, "f": 988, "d": 0.16, "g": 0.16}, {"t": 0.22, "f": 1244, "d": 0.16, "g": 0.17}, {"t": 0.46, "f": 1661, "d": 0.18, "g": 0.18}, {"t": 0.74, "f": 1976, "d": 0.30, "g": 0.2}]},
]
DEFAULT_ALARM_PRESET_ID = ALARM_PRESETS[0]["id"]
ALARM_PRESET_IDS = {item["id"] for item in ALARM_PRESETS}


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
        else:
            s["status"] = "completed"
            s["message"] = f"profile '{name}' added"
        s["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        s["updated_at"] = s["finished_at"]
        _cleanup_add_login_session(s)


def start_add_login_session(name: str, timeout: int, overwrite: bool, keep_temp_home: bool, device_auth: bool) -> dict:
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
    }
    with ADD_LOGIN_LOCK:
        ADD_LOGIN_SESSIONS[session_id] = session
    t = threading.Thread(target=_run_add_login_session, args=(session_id,), daemon=True)
    t.start()
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
    cfg["ui"] = ui

    notif = cfg.get("notifications", {})
    notif["enabled"] = bool(notif.get("enabled", False))
    notif["scope"] = notif.get("scope") if notif.get("scope") in ("any", "5h", "weekly") else "any"
    notif["alarm_preset"] = str(notif.get("alarm_preset") or "").strip()
    if notif["alarm_preset"] not in ALARM_PRESET_IDS:
        notif["alarm_preset"] = DEFAULT_ALARM_PRESET_ID
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
    shutil.copy2(source_auth, target_auth)
    _set_private_permissions(target_auth)
    return profile_home


def _platform_process_candidates() -> dict[str, list[str]]:
    return {
        "Codex": [
            "/Applications/Codex.app/Contents/MacOS/Codex",
            "Codex.exe",
            "codex.exe",
            "codex",
        ],
        "CodexBar": [
            "/Applications/CodexBar.app/Contents/MacOS/CodexBar",
            "CodexBar.exe",
            "codexbar.exe",
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


def detect_running_app_name():
    candidates = _platform_process_candidates()
    for app_name in APP_CANDIDATES:
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
    for app_name in APP_CANDIDATES:
        if sys.platform == "darwin":
            _subprocess_run(["osascript", "-e", f'tell application "{app_name}" to quit'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            touched = True
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
    shutil.copy2(source_auth, target_auth)
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


def sync_profile_auth_snapshot(name: str, source_auth: Path, source_label: str | None = None) -> bool:
    name = (name or "").strip()
    if not name or not source_auth.exists():
        return False
    target_dir = PROFILES_DIR / name
    if not target_dir.exists():
        return False
    target_auth = target_dir / "auth.json"
    try:
        source_canonical = json.dumps(load_json(source_auth), sort_keys=True, separators=(",", ":"))
    except Exception:
        return False
    try:
        target_canonical = json.dumps(load_json(target_auth), sort_keys=True, separators=(",", ":")) if target_auth.exists() else None
    except Exception:
        target_canonical = None
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
            sync_profile_auth_snapshot(p.name, AUTH_FILE, str(AUTH_FILE))
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
    token_json = json.dumps(token)
    interval_json = json.dumps(default_interval)
    version_json = json.dumps(APP_VERSION)
    alarm_presets_json = json.dumps(ALARM_PRESETS, separators=(",", ":"))
    html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <meta name=\"theme-color\" content=\"#0d8a44\" />
  <link rel=\"icon\" type=\"image/svg+xml\" href=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0%25' stop-color='%230f172a'/%3E%3Cstop offset='100%25' stop-color='%23145f3f'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='12' fill='url(%23g)'/%3E%3Crect x='8' y='8' width='48' height='48' rx='10' fill='none' stroke='%233fff8b' stroke-width='4'/%3E%3Cpath d='M21 42V22h9.5c6.4 0 10 3.7 10 10s-3.6 10-10 10z' fill='none' stroke='%233fff8b' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='M43 22v20h-2' fill='none' stroke='%23ffd16c' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E\" />
  <link rel=\"apple-touch-icon\" href=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0%25' stop-color='%230f172a'/%3E%3Cstop offset='100%25' stop-color='%23145f3f'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='12' fill='url(%23g)'/%3E%3Crect x='8' y='8' width='48' height='48' rx='10' fill='none' stroke='%233fff8b' stroke-width='4'/%3E%3Cpath d='M21 42V22h9.5c6.4 0 10 3.7 10 10s-3.6 10-10 10z' fill='none' stroke='%233fff8b' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='M43 22v20h-2' fill='none' stroke='%23ffd16c' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E\" />
  <title>Codex Account Manager</title>
  <style>
    @import url(\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;600;700&display=swap\");
    :root {
      --radius:4px; --gap:16px;
      --surface:#0e0e0e; --surface-low:#131313; --surface-card:#1a1a1a; --surface-high:#20201f; --surface-highest:#262626; --surface-black:#000;
      --text:#ffffff; --text-soft:#adaaaa; --line:rgba(72,72,71,.15);
      --primary:#3fff8b; --primary-container:#13ea79; --on-primary:#005d2c;
      --ok:#3fff8b; --warn:#ffd16c; --danger:#ff716c;
      --ambient:none;
      --bg-grad:none;
      --topbar-bg:rgba(14,14,14,.92);
      --line-soft:rgba(72,72,71,.22);
      --line-strong:rgba(72,72,71,.35);
      --accent-soft:rgba(63,255,139,.24);
      --accent-border:rgba(63,255,139,.4);
      --accent-glow:rgba(63,255,139,.45);
      --accent-glow-strong:rgba(63,255,139,.55);
      --accent-ring:rgba(63,255,139,.35);
      --accent-inset:rgba(63,255,139,.12);
      --accent-bg:rgba(63,255,139,.09);
      --warn-ring:rgba(255,209,108,.40);
      --warn-inset:rgba(255,209,108,.14);
      --warn-strong:#ffd16c;
      --warn-bg:rgba(255,209,108,.11);
      --orange-ring:rgba(255,159,67,.45);
      --orange-inset:rgba(255,159,67,.16);
      --orange-strong:#ff9f43;
      --orange-bg:rgba(255,159,67,.12);
      --danger-ring:rgba(255,113,108,.5);
      --danger-inset:rgba(255,113,108,.2);
      --danger-soft:#ff8a8a;
      --danger-bg:rgba(197,52,60,.08);
      --danger-bg-hover:rgba(197,52,60,.14);
      --danger-banner-bg:rgba(215,56,59,.18);
      --danger-banner-border:rgba(215,56,59,.45);
      --danger-banner-text:#ffd6d6;
      --notice-border:rgba(72,72,71,.45);
      --notice-shadow:0 10px 28px rgba(0,0,0,.35);
      --modal-backdrop:rgba(0,0,0,.55);
      --scroll-track:rgba(72,72,71,.18);
      --scroll-thumb-start:rgba(63,255,139,.42);
      --scroll-thumb-end:rgba(19,234,121,.34);
      --scroll-thumb-start-hover:rgba(63,255,139,.62);
      --scroll-thumb-end-hover:rgba(19,234,121,.5);
      --usage-low:#ff6b6b;
      --usage-midlow:#ff9f43;
      --usage-mid:#ffd16c;
      --toggle-track-off:var(--surface-highest);
      --toggle-track-on:var(--accent-soft);
      --toggle-knob-off:#e5e2e1;
      --toggle-knob-on:var(--primary);
      --log-ts:#7e8b90;
      --log-info:#b7e3ff;
      --log-warn:#ffd16c;
      --log-error:#ff8a8a;
      --log-event:#b5f5d0;
      --log-command:#89fff8;
      --log-detail:#aab7bc;
    }
    [data-theme=\"light\"]{
      --surface:#f3f6fa; --surface-low:#ffffff; --surface-card:#ffffff; --surface-high:#f5f8fc; --surface-highest:#e9eef5; --surface-black:#f8fbff;
      --text:#16202b; --text-soft:#4a5868; --line:rgba(46,58,72,.18);
      --primary:#0d8a44; --primary-container:#2fc56f; --on-primary:#02260f;
      --ok:#0d8a44; --warn:#9a6e00; --danger:#b4232c;
      --ambient:0 12px 34px rgba(20,28,40,.08);
      --bg-grad:radial-gradient(1100px 500px at 85% -20%, rgba(17,153,75,.08), transparent 65%), radial-gradient(900px 420px at 10% 0%, rgba(172,125,0,.05), transparent 70%);
      --topbar-bg:rgba(255,255,255,.94);
      --line-soft:rgba(46,58,72,.22);
      --line-strong:rgba(46,58,72,.3);
      --accent-soft:rgba(13,138,68,.18);
      --accent-border:rgba(13,138,68,.34);
      --accent-glow:rgba(13,138,68,.28);
      --accent-glow-strong:rgba(13,138,68,.36);
      --accent-ring:rgba(13,138,68,.3);
      --accent-inset:rgba(13,138,68,.12);
      --accent-bg:rgba(13,138,68,.09);
      --warn-ring:rgba(154,110,0,.36);
      --warn-inset:rgba(154,110,0,.13);
      --warn-strong:#9a6e00;
      --warn-bg:rgba(154,110,0,.11);
      --orange-ring:rgba(180,102,28,.38);
      --orange-inset:rgba(180,102,28,.14);
      --orange-strong:#9c5312;
      --orange-bg:rgba(180,102,28,.11);
      --danger-ring:rgba(180,35,44,.4);
      --danger-inset:rgba(180,35,44,.15);
      --danger-soft:#a91f29;
      --danger-bg:rgba(180,35,44,.08);
      --danger-bg-hover:rgba(180,35,44,.13);
      --danger-banner-bg:rgba(180,35,44,.12);
      --danger-banner-border:rgba(180,35,44,.38);
      --danger-banner-text:#8b1d27;
      --notice-border:rgba(46,58,72,.28);
      --notice-shadow:0 10px 26px rgba(25,36,50,.13);
      --modal-backdrop:rgba(18,24,32,.34);
      --scroll-track:rgba(46,58,72,.18);
      --scroll-thumb-start:rgba(13,138,68,.34);
      --scroll-thumb-end:rgba(47,197,111,.28);
      --scroll-thumb-start-hover:rgba(13,138,68,.5);
      --scroll-thumb-end-hover:rgba(47,197,111,.42);
      --usage-low:#b4232c;
      --usage-midlow:#b45309;
      --usage-mid:#8a6400;
      --toggle-track-off:#c8d4e0;
      --toggle-track-on:#47b875;
      --toggle-knob-off:#f8fbff;
      --toggle-knob-on:#ffffff;
      --log-ts:#62707d;
      --log-info:#0f5f9f;
      --log-warn:#8a6400;
      --log-error:#b4232c;
      --log-event:#0f7a53;
      --log-command:#0d7c73;
      --log-detail:#4e5c6b;
    }
    *{box-sizing:border-box} html,body{margin:0;padding:0}
    body{font-family:Inter,\"Segoe UI\",-apple-system,sans-serif;background:var(--bg-grad),var(--surface);color:var(--text);min-height:100vh}
    .mono,.k,.rules-title,.group-title,th,.badge,.sub,#lastRefresh,.events-empty,.out,.event-item,.id-cell,.reset-cell,.added-cell,.note-cell{font-family:\"JetBrains Mono\",ui-monospace,monospace}
    .topbar{position:sticky;top:0;z-index:50;height:64px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 22px;background:var(--topbar-bg);backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}
    .brand{font-family:\"Space Grotesk\",Inter,sans-serif;font-weight:700;letter-spacing:-.02em;font-size:30px;line-height:1;color:var(--primary)}
    .topnav{display:flex;align-items:center;gap:26px;color:var(--text-soft);font-size:14px}.topnav span{cursor:pointer;transition:.18s color}.topnav span:hover{color:var(--text)}
    .container{max-width:1540px;margin:0 auto;padding:22px}
    .app-header{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      margin-bottom:12px;
      padding:2px 2px 6px;
    }
    .app-title-wrap{
      display:flex;
      align-items:center;
      gap:10px;
      min-width:0;
    }
    .app-title{
      font-family:Inter,"Segoe UI",-apple-system,sans-serif;
      font-size:18px;
      font-weight:700;
      letter-spacing:-.01em;
      color:var(--text);
    }
    .app-version{
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:11px;
      color:var(--text-soft);
      letter-spacing:.08em;
      text-transform:uppercase;
    }
    .app-update-pill{
      display:none;
      align-items:center;
      gap:6px;
      padding:5px 9px;
      border-radius:999px;
      background:var(--accent-bg);
      border:1px solid var(--accent-border);
      color:var(--primary);
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:10px;
      letter-spacing:.08em;
      text-transform:uppercase;
      white-space:nowrap;
    }
    .app-update-pill.active{display:inline-flex}
    .save-spinner{
      display:none;
      width:15px;
      height:15px;
      border-radius:999px;
      border:2px solid var(--line-strong);
      border-top-color:var(--primary);
      border-right-color:var(--accent-glow-strong);
      animation:spin .8s linear infinite;
      flex:0 0 auto;
    }
    .save-spinner.active{display:inline-block}
    .save-dot{
      width:7px;
      height:7px;
      border-radius:999px;
      background:var(--primary);
      box-shadow:0 0 10px var(--accent-glow);
      animation:savePulse .9s ease-in-out infinite;
    }
    @keyframes savePulse{
      0%,100%{transform:scale(.88);opacity:.7}
      50%{transform:scale(1.1);opacity:1}
    }
    @keyframes spin{
      from{transform:rotate(0deg)}
      to{transform:rotate(360deg)}
    }
    .app-header-right{
      margin-left:auto;
      display:flex;
      align-items:center;
      gap:10px;
    }
    .settings-toggle-btn{
      width:34px;
      height:34px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      border:1px solid var(--line);
      border-radius:var(--radius);
      background:var(--surface-highest);
      color:var(--text-soft);
      font-size:15px;
      cursor:pointer;
      transition:background .15s,color .15s,border-color .15s;
    }
    .settings-toggle-btn:hover{background:var(--surface-high);color:var(--text)}
    .settings-toggle-btn.active{color:var(--primary);border-color:var(--accent-border)}
    .header-icon-btn{
      width:34px;
      height:34px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      border:1px solid var(--line);
      border-radius:var(--radius);
      background:var(--surface-highest);
      color:var(--text-soft);
      font-size:15px;
      cursor:pointer;
      transition:background .15s,color .15s,border-color .15s;
    }
    .header-icon-btn svg,.settings-toggle-btn svg{width:18px;height:18px;display:block;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
    #debugIconBtn svg,#settingsToggleBtn svg{width:32px;height:32px;stroke:none;fill:currentColor;transform:scale(1.2);transform-origin:center}
    .header-icon-btn:hover{background:var(--surface-high);color:var(--text)}
    .header-icon-btn.active{color:var(--primary);border-color:var(--accent-border)}
    .page-head{margin-top:8px;padding:16px 18px;background:var(--surface-low);border-radius:var(--radius);display:flex;align-items:flex-end;justify-content:space-between;gap:14px}
    h1{margin:0;font-size:44px;letter-spacing:-.02em;line-height:1}
    .sub{margin-top:9px;font-size:12px;color:var(--text-soft);text-transform:uppercase;letter-spacing:.12em;display:flex;align-items:center;gap:8px}
    .sub::before{content:\"\";width:8px;height:8px;border-radius:999px;background:var(--primary);box-shadow:0 0 10px var(--accent-glow-strong)}
    #lastRefresh{font-size:11px;color:var(--text-soft)}
    .fatal{display:none;margin-top:10px;background:var(--danger-banner-bg);border:1px solid var(--danger-banner-border);color:var(--danger-banner-text);padding:10px;border-radius:var(--radius);white-space:pre-wrap}
    .inapp-notice-stack{position:fixed;top:84px;right:18px;z-index:120;display:flex;flex-direction:column;gap:10px;max-width:min(420px,calc(100vw - 28px));pointer-events:none}
    .inapp-notice{pointer-events:auto;background:var(--surface-high);border:1px solid var(--notice-border);border-left:4px solid var(--primary);border-radius:12px;box-shadow:var(--notice-shadow);padding:10px 12px;animation:slideNotice .18s ease-out}
    .inapp-notice-title{font-weight:700;font-size:13px;margin-bottom:4px;color:var(--text)}
    .inapp-notice-body{color:var(--text-soft);font-size:12px;line-height:1.45;white-space:pre-wrap}
    @keyframes slideNotice{from{opacity:0;transform:translateY(-8px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
    .section{margin-top:var(--gap)}
    .card,.table-wrap,.toolbar{background:var(--surface-low);border-radius:var(--radius);border:1px solid transparent;box-shadow:var(--ambient)}
    .toolbar{padding:14px}
    .controls-grid{display:grid;grid-template-columns:1.2fr 1fr;gap:12px}
    .control-card,.rules-col{background:var(--surface-card);border:1px solid var(--line);border-radius:var(--radius);padding:12px;display:flex;flex-direction:column;gap:10px}
    .control-card.control-card-full{grid-column:1 / -1}
    .group-title,.rules-title{font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:.12em}
    .settings-card{padding:14px 14px 12px;gap:12px}
    .notify-card{
      display:grid;
      grid-template-rows:auto auto minmax(48px,1fr) auto;
      align-content:stretch;
    }
    .settings-card .group-title{
      font-family:Inter,"Segoe UI",-apple-system,sans-serif;
      font-size:14px;
      font-weight:600;
      color:var(--text);
      text-transform:none;
      letter-spacing:0;
    }
    .setting-row{
      min-height:40px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      padding:0 2px;
    }
    .refresh-setting-row{
      display:grid;
      grid-template-columns:minmax(0,1fr) auto;
      align-items:center;
      column-gap:16px;
    }
    .refresh-setting-controls{
      justify-self:end;
      display:inline-flex;
      align-items:center;
      gap:0;
    }
    .refresh-inline-stepper{
      gap:10px;
      margin-right:24px;
    }
    .refresh-setting-toggle{
      justify-self:end;
    }
    .setting-label{
      font-family:Inter,"Segoe UI",-apple-system,sans-serif;
      font-size:13px;
      color:var(--text-soft);
      letter-spacing:0;
      text-transform:none;
    }
    .setting-field{display:grid;gap:6px}
    .setting-field .setting-label{font-size:13px}
    .setting-row.metric .setting-label{
      font-size:11px;
      font-family:"JetBrains Mono",ui-monospace,monospace;
      text-transform:uppercase;
      letter-spacing:.07em;
    }
    .setting-row.metric .stepper{margin-left:auto}
    .metric-pair-grid{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:10px;
    }
    .metric-pair-grid .setting-row{
      min-width:0;
      margin:0;
    }
    .metric-pair-grid .setting-label{
      white-space:nowrap;
    }
    .metric-pair-grid .stepper{
      flex-shrink:0;
    }
    .notify-card .metric-pair-grid{
      align-self:end;
    }
    .btn-block{width:100%;display:flex;align-items:center;justify-content:center}
    .settings-footer-btn{margin-top:auto}
    .settings-footer-actions{
      margin-top:auto;
      display:grid;
      grid-template-columns:1fr 1fr 1fr;
      gap:8px;
      width:100%;
    }
    .settings-footer-actions .settings-footer-btn{margin-top:0}
    .exec-actions{
      margin-top:auto;
      display:grid;
      grid-template-columns:1fr 1fr 1fr 1fr;
      gap:8px;
      width:100%;
    }
    .exec-actions .settings-footer-btn{
      margin-top:0;
      min-width:0;
    }
    .setting-field select{width:100%}
    .inset-row{
      background:var(--surface-black);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:7px 10px;
      min-height:42px;
    }
    .inset-row .setting-label{font-size:12px;font-family:Inter,"Segoe UI",-apple-system,sans-serif}
    .toolbar-row,.field-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
    .field-block{display:inline-flex;align-items:center;gap:8px}
    .label{font-size:12px;color:var(--text-soft)}
    .rules-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .auto-switch-head{
      margin-bottom:10px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
    }
    .auto-switch-countdown{
      display:none;
      align-items:center;
      justify-content:center;
      min-height:22px;
      padding:2px 9px;
      border:1px solid var(--switch-urgency-border, var(--accent-ring));
      border-radius:999px;
      color:var(--switch-urgency-text, var(--primary));
      background:var(--switch-urgency-bg, var(--accent-bg));
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:11px;
      letter-spacing:.06em;
      white-space:nowrap;
      transition:color .25s ease, background .25s ease, border-color .25s ease;
    }
    .auto-switch-countdown.active{display:inline-flex}
    #autoSwitchRulesSection.auto-switch-armed{
      border-color:var(--switch-urgency-border, var(--accent-ring));
      box-shadow:0 0 0 1px var(--switch-urgency-inset, var(--accent-inset)) inset;
      animation:none;
      background:var(--surface-low);
    }
    #autoSwitchRulesSection.auto-switch-armed.switch-urgency-green{
      --switch-urgency-border:var(--accent-ring);
      --switch-urgency-inset:var(--accent-inset);
      --switch-urgency-text:var(--primary);
      --switch-urgency-bg:var(--accent-bg);
    }
    #autoSwitchRulesSection.auto-switch-armed.switch-urgency-yellow{
      --switch-urgency-border:var(--warn-ring);
      --switch-urgency-inset:var(--warn-inset);
      --switch-urgency-text:var(--warn-strong);
      --switch-urgency-bg:var(--warn-bg);
    }
    #autoSwitchRulesSection.auto-switch-armed.switch-urgency-orange{
      --switch-urgency-border:var(--orange-ring);
      --switch-urgency-inset:var(--orange-inset);
      --switch-urgency-text:var(--orange-strong);
      --switch-urgency-bg:var(--orange-bg);
    }
    #autoSwitchRulesSection.auto-switch-armed.switch-urgency-red{
      --switch-urgency-border:var(--danger-ring);
      --switch-urgency-inset:var(--danger-inset);
      --switch-urgency-text:var(--danger-soft);
      --switch-urgency-bg:var(--danger-bg);
    }
    .status-row{background:var(--surface-low);border-radius:var(--radius);padding:10px 14px;display:flex;align-items:center;justify-content:space-between;gap:14px}
    .status-row .v{font-size:15px;font-family:\"JetBrains Mono\",monospace;color:var(--text)}
    .k{font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:.12em}
    .small{font-size:12px}.muted{color:var(--text-soft)}
    .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap)}
    .grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--gap)}
    @media (max-width:1360px){.controls-grid{grid-template-columns:1fr 1fr}}
    @media (max-width:1040px){.topnav{display:none}.brand{font-size:20px}.container{padding:14px}h1{font-size:28px}}
    @media (max-width:760px){
      .controls-grid,.rules-grid,.grid-2,.grid-3{grid-template-columns:1fr}
      .metric-pair-grid{grid-template-columns:1fr}
      .refresh-setting-row{
        grid-template-columns:1fr;
        row-gap:10px;
      }
      .refresh-setting-controls,.refresh-setting-toggle{
        justify-self:start;
      }
    }
    .btn,button,input,select{font-family:Inter,\"Segoe UI\",-apple-system,sans-serif}
    .btn,button{border:1px solid var(--line);background:var(--surface-highest);color:var(--text);border-radius:var(--radius);padding:8px 11px;cursor:pointer;transition:background .15s,opacity .15s,color .15s}
    .btn:hover,button:hover{background:var(--surface-high)}
    .btn-primary,
    .btn.btn-primary,
    button.btn-primary{
      background:linear-gradient(90deg,var(--primary),var(--primary-container));
      border:0;
      color:var(--on-primary);
      font-weight:700;
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.08);
    }
    .btn-primary:hover,
    .btn.btn-primary:hover,
    button.btn-primary:hover{
      background:linear-gradient(90deg,color-mix(in srgb,var(--primary) 94%, #fff 6%),color-mix(in srgb,var(--primary-container) 94%, #fff 6%));
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.12);
    }
    .btn-primary-danger,
    .btn.btn-primary-danger,
    button.btn-primary-danger{
      background:linear-gradient(90deg,var(--danger),color-mix(in srgb,var(--danger) 80%, #6b0a0a 20%));
      border:0;
      color:#fff;
      font-weight:700;
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.12);
    }
    .btn-primary-danger:hover,
    .btn.btn-primary-danger:hover,
    button.btn-primary-danger:hover{
      background:linear-gradient(90deg,color-mix(in srgb,var(--danger) 92%, #fff 8%),color-mix(in srgb,var(--danger) 82%, #fff 18%));
    }
    .btn-warning,
    .btn.btn-warning,
    button.btn-warning{
      background:linear-gradient(90deg,var(--warn),color-mix(in srgb,var(--warn) 82%, #7a5200 18%));
      border:0;
      color:#1f1600;
      font-weight:700;
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.1);
    }
    .btn-warning:hover,
    .btn.btn-warning:hover,
    button.btn-warning:hover{
      background:linear-gradient(90deg,color-mix(in srgb,var(--warn) 92%, #fff 8%),color-mix(in srgb,var(--warn) 84%, #fff 16%));
    }
    [data-theme=\"light\"] .btn:not(.btn-primary):not(.btn-primary-danger):not(.btn-warning):not(.action-btn),
    [data-theme=\"light\"] button:not(.btn-primary):not(.btn-primary-danger):not(.btn-warning):not(.action-btn){
      background:#edf3f9;
      border-color:rgba(46,58,72,.24);
    }
    [data-theme=\"light\"] .btn:not(.btn-primary):not(.btn-primary-danger):not(.btn-warning):not(.action-btn):hover,
    [data-theme=\"light\"] button:not(.btn-primary):not(.btn-primary-danger):not(.btn-warning):not(.action-btn):hover{
      background:#e4ecf4;
    }
    [data-theme=\"light\"] .btn-primary,
    [data-theme=\"light\"] .btn.btn-primary,
    [data-theme=\"light\"] button.btn-primary{
      background:linear-gradient(90deg,var(--primary),var(--primary-container));
      color:var(--on-primary);
    }
    [data-theme=\"light\"] .btn-primary:hover,
    [data-theme=\"light\"] .btn.btn-primary:hover,
    [data-theme=\"light\"] button.btn-primary:hover{
      background:linear-gradient(90deg,color-mix(in srgb,var(--primary) 94%, #fff 6%),color-mix(in srgb,var(--primary-container) 94%, #fff 6%));
    }
    [data-theme=\"light\"] .btn-primary,
    [data-theme=\"light\"] .btn.btn-primary,
    [data-theme=\"light\"] button.btn-primary{
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.14);
    }
    [data-theme=\"light\"] .btn-primary-danger,
    [data-theme=\"light\"] .btn.btn-primary-danger,
    [data-theme=\"light\"] button.btn-primary-danger{
      background:linear-gradient(90deg,#c72231,#a31221);
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.18);
    }
    [data-theme=\"light\"] .btn-primary-danger:hover,
    [data-theme=\"light\"] .btn.btn-primary-danger:hover,
    [data-theme=\"light\"] button.btn-primary-danger:hover{
      background:linear-gradient(90deg,#d02b3a,#ab1624);
    }
    [data-theme=\"light\"] .btn-warning,
    [data-theme=\"light\"] .btn.btn-warning,
    [data-theme=\"light\"] button.btn-warning{
      background:linear-gradient(90deg,#e0aa1b,#c78900);
      color:#241700;
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.14);
    }
    [data-theme=\"light\"] .btn-warning:hover,
    [data-theme=\"light\"] .btn.btn-warning:hover,
    [data-theme=\"light\"] button.btn-warning:hover{
      background:linear-gradient(90deg,#e8b62f,#d19105);
    }
    [data-theme=\"light\"] .btn-danger{
      color:#a81f2a;
      background:rgba(180,35,44,.08);
      border-color:rgba(180,35,44,.28);
    }
    .btn-danger{color:var(--danger)}
    .btn-disabled,button:disabled{opacity:.45;cursor:not-allowed;pointer-events:none}
    .btn-progress{position:relative}
    .btn-progress{color:transparent !important}
    .btn-progress::after{content:"";position:absolute;left:50%;top:50%;width:12px;height:12px;margin-left:-6px;margin-top:-6px;border-radius:999px;border:2px solid color-mix(in srgb,var(--on-primary) 70%, transparent);border-top-color:var(--on-primary);animation:spin .8s linear infinite}
    .toggle{display:inline-flex;align-items:center;gap:8px}
    .toggle input{appearance:none;width:38px;height:20px;border-radius:999px;background:var(--toggle-track-off);position:relative;border:1px solid var(--line);cursor:pointer}
    .toggle input::after{content:\"\";position:absolute;left:2px;top:2px;width:14px;height:14px;border-radius:999px;background:var(--toggle-knob-off);box-shadow:0 1px 2px rgba(0,0,0,.18);transition:transform .15s ease}
    .toggle input:checked{background:var(--toggle-track-on)}.toggle input:checked::after{transform:translateX(18px);background:var(--toggle-knob-on)}
    input,select{background:var(--surface-highest);border:1px solid var(--line);color:var(--text);border-radius:var(--radius);padding:7px 8px}
    .stepper{display:inline-flex;align-items:center;gap:6px}.stepper input{width:66px;text-align:center;background:var(--surface-black);border:1px solid var(--line);border-radius:var(--radius);padding:6px 4px;appearance:textfield;-moz-appearance:textfield;font-family:\"JetBrains Mono\",monospace}
    .stepper input::-webkit-outer-spin-button,.stepper input::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
    .stepper.compact input{width:60px}.stepper.compact button{padding:6px 8px}
    .accounts-toolbar{position:relative;z-index:40;padding:12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;background:var(--surface-low);border-radius:var(--radius) var(--radius) 0 0;border-bottom:1px solid var(--line)}
    .accounts-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
    .spacer{flex:1}
    .table-wrap{position:relative;z-index:1;overflow-x:auto;overflow-y:visible;border-radius:0 0 var(--radius) var(--radius);background:var(--surface-low)}
    table{width:100%;min-width:100%;border-collapse:separate;border-spacing:0 8px;padding:0 0 10px}
    th,td{padding:9px 8px;text-align:left}
    th{font-size:10px;color:var(--text-soft);cursor:pointer;text-transform:uppercase;letter-spacing:.12em;border:0}
    th.no-sort{cursor:default}
    th.sorted{color:var(--text)}
    .sort-indicator{display:inline-block;margin-left:6px;font-size:10px;opacity:.85;vertical-align:middle}
    tbody tr{background:var(--surface-card);transition:background .18s ease, box-shadow .18s ease, transform .18s ease} tbody tr:nth-child(even){background:var(--surface-high)} tbody tr:hover{background:var(--surface-highest)}
    tbody tr.switch-row-pending{
      animation:rowPendingPulse 1.5s ease-in-out infinite;
      box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--primary) 32%, transparent);
    }
    @keyframes rowPendingPulse{
      0%,100%{
        background:color-mix(in srgb,var(--surface-card) 90%, transparent);
        box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--primary) 18%, transparent);
      }
      50%{
        background:color-mix(in srgb,var(--primary) 12%, var(--surface-high));
        box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--primary) 42%, transparent), 0 0 18px color-mix(in srgb,var(--accent-glow) 32%, transparent);
      }
    }
    tbody tr.switch-row-activated{animation:rowActivatePulse .95s ease-out 1}
    @keyframes rowActivatePulse{
      0%{box-shadow:inset 0 0 0 9999px color-mix(in srgb,var(--primary) 22%, transparent),0 8px 28px color-mix(in srgb,var(--accent-glow) 24%, transparent)}
      100%{box-shadow:inset 0 0 0 9999px transparent,0 0 0 transparent}
    }
    tbody td{font-size:13px}
    .email-cell{max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .reset-cell,.added-cell{white-space:nowrap;font-size:12px}.id-cell{max-width:320px;word-break:break-word;line-height:1.2;font-size:12px}.note-cell{white-space:nowrap}
    .usage-low{color:var(--usage-low);font-weight:700}
    .usage-midlow{color:var(--usage-midlow);font-weight:700}
    .usage-mid{color:var(--usage-mid);font-weight:700}
    .usage-good{color:var(--ok);font-weight:700}
    .usage-cell{display:flex;align-items:center;gap:12px}
    .usage-pct{min-width:46px}
    .usage-meter{flex:1;min-width:92px;height:6px;background:var(--surface-highest);border-radius:999px;overflow:hidden}
    .usage-fill{height:100%;display:block;background:var(--primary)}
    .usage-fill.low{background:var(--usage-low)}
    .usage-fill.midlow{background:var(--usage-midlow)}
    .usage-fill.mid{background:var(--usage-mid)}
    .usage-fill.good{background:var(--ok)}
    .usage-cell-loading .usage-pct{min-width:72px}
    .usage-meter.loading{position:relative;background:color-mix(in srgb,var(--surface-highest) 75%, var(--line))}
    .usage-fill.shimmer{width:45%;background:linear-gradient(90deg,transparent, color-mix(in srgb,var(--primary) 72%, white 10%), transparent);animation:usageShimmer 1.05s linear infinite}
    .loading-text{color:var(--text-soft)}
    @keyframes usageShimmer{from{transform:translateX(-140%)}to{transform:translateX(230%)}}
    @keyframes usagePulse{0%{filter:brightness(1);text-shadow:none}50%{filter:brightness(1.2);text-shadow:0 0 8px color-mix(in srgb,var(--primary) 32%, transparent)}100%{filter:brightness(1);text-shadow:none}}
    @keyframes usageBarBlink{0%,100%{opacity:1;filter:brightness(1)}50%{opacity:.78;filter:brightness(1.12)}}
    .usage-cell.updated .usage-pct{animation:usageBarBlink 1.1s ease-in-out infinite}
    .usage-cell.updated .usage-meter{animation:none}
    .usage-cell.updated .usage-fill.blink{animation:usageBarBlink 1.1s ease-in-out infinite}
    .mobile-stat .updated{animation:usagePulse .72s ease-in-out 2}
    .status-dot{display:inline-block;width:10px;height:10px;border-radius:999px;background:var(--text-soft);box-shadow:0 0 0 1px color-mix(in srgb,var(--surface-low) 75%, transparent),0 0 6px color-mix(in srgb,var(--text-soft) 30%, transparent)}
    .status-dot.active{background:var(--primary);box-shadow:0 0 0 1px color-mix(in srgb,var(--surface-low) 78%, transparent),0 0 10px var(--accent-glow)}.status-dot.warn{background:var(--warn)}.status-dot.danger{background:var(--danger)}
    [data-theme=\"light\"] .status-dot{
      background:#b7c3d1;
      box-shadow:0 0 0 2px rgba(255,255,255,.96), 0 0 0 1px rgba(124,141,160,.16), inset 0 1px 0 rgba(255,255,255,.55);
    }
    [data-theme=\"light\"] .status-dot.active{
      background:#0f9b52;
      box-shadow:0 0 0 2px rgba(255,255,255,.98), 0 0 0 1px rgba(15,155,82,.22), 0 4px 10px rgba(15,155,82,.24);
    }
    [data-theme=\"light\"] .status-dot.warn{
      background:#9a6e00;
      box-shadow:0 0 0 2px rgba(255,255,255,.98), 0 0 0 1px rgba(154,110,0,.2), 0 4px 10px rgba(154,110,0,.18);
    }
    [data-theme=\"light\"] .status-dot.danger{
      background:#b4232c;
      box-shadow:0 0 0 2px rgba(255,255,255,.98), 0 0 0 1px rgba(180,35,44,.2), 0 4px 10px rgba(180,35,44,.18);
    }
    .badge{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 7px;font-size:11px;color:var(--text-soft)}
    th[data-col="actions"],td[data-col="actions"]{text-align:right;white-space:nowrap}
    td[data-col="actions"]{width:1%}
    .actions-cell{display:inline-flex;align-items:center;justify-content:flex-end;gap:12px}
    .actions-menu-btn{padding:6px 10px;min-width:40px;text-align:center}
    .mobile-list{display:none}
    .mobile-row{background:var(--surface-card);border:1px solid var(--line);border-radius:var(--radius);padding:10px;display:grid;gap:8px;cursor:pointer;overflow:visible}
    .mobile-row:nth-child(even){background:var(--surface-high)}
    .mobile-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
    .mobile-left{display:flex;align-items:center;gap:8px;min-width:0}
    .mobile-profile{font-weight:700;font-size:14px}
    .mobile-email{font-size:12px;color:var(--text-soft);word-break:break-word;line-height:1.3}
    .mobile-stats{display:grid;grid-template-columns:1fr 1fr;gap:6px}
    .mobile-stat{display:flex;justify-content:space-between;gap:8px;background:var(--surface-black);border:1px solid var(--line);border-radius:var(--radius);padding:6px 8px;font-size:12px}
    .mobile-stat .label{color:var(--text-soft);font-size:10px;letter-spacing:.08em;text-transform:uppercase}
    .mobile-actions{display:flex;justify-content:flex-end;align-items:center;gap:10px}
    @media (max-width:980px){
      .table-wrap{overflow-x:hidden}
      .table-wrap table{display:none}
      .mobile-list{display:grid;gap:8px;padding:8px}
    }
    .columns-modal{width:min(460px,92vw);max-height:82vh;display:flex;flex-direction:column;background:color-mix(in srgb,var(--surface-highest) 60%, transparent);backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
    .columns-modal h3{margin:0 0 10px 0}
    .columns-list{overflow:auto;display:grid;gap:6px;padding-right:4px}
    .columns-item{display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--surface-high);border:1px solid var(--line);border-radius:var(--radius);padding:8px 10px}
    .columns-item label{display:flex;align-items:center;gap:10px;cursor:pointer;flex:1}
    .columns-item span{font-size:14px}
    .columns-item input[type="checkbox"]{width:16px;height:16px}
    .columns-modal .row{margin-top:12px}
    .actions-modal{width:min(340px,92vw);background:color-mix(in srgb,var(--surface-highest) 62%, transparent);backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:var(--radius);padding:12px}
    .actions-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:8px}
    .actions-head h3{margin:0;font-size:18px;letter-spacing:-.01em}
    .actions-close{width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);background:var(--surface-highest);color:var(--text-soft);border-radius:var(--radius);cursor:pointer;line-height:1}
    .actions-close:hover{background:var(--surface-high);color:var(--text)}
    .actions-sub{margin:2px 0 10px 0;color:var(--text-soft);font-size:12px;font-family:"JetBrains Mono",ui-monospace,monospace}
    .actions-list{display:grid;gap:8px}
    .action-btn{width:100%;display:flex;align-items:center;justify-content:space-between;gap:10px;text-align:left;padding:10px 12px;border:1px solid var(--line-soft);background:var(--surface-high);color:var(--text);border-radius:var(--radius);cursor:pointer}
    .action-btn:hover{background:var(--surface-highest)}
    .action-btn .hint{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-soft)}
    .action-btn.danger{
      background:linear-gradient(90deg,var(--danger),color-mix(in srgb,var(--danger) 80%, #6b0a0a 20%));
      border:0;
      color:#fff;
      font-weight:700;
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.12);
    }
    .action-btn.danger:hover{
      background:linear-gradient(90deg,color-mix(in srgb,var(--danger) 92%, #fff 8%),color-mix(in srgb,var(--danger) 82%, #fff 18%));
    }
    .action-btn.danger .hint{color:rgba(255,255,255,.9)}
    [data-theme=\"light\"] .action-btn.danger{
      background:linear-gradient(90deg,#c72231,#a31221);
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.18);
    }
    [data-theme=\"light\"] .action-btn.danger:hover{
      background:linear-gradient(90deg,#d02b3a,#ab1624);
    }
    .device-modal{width:min(700px,96vw);background:color-mix(in srgb,var(--surface-highest) 62%, transparent);backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
    .device-modal h3{margin:0 0 8px 0}
    .device-intro{margin:0 0 10px 0;color:var(--text-soft);font-size:12px}
    .device-name-row{display:grid;gap:6px;margin:0 0 10px 0}
    .device-name-row span{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--text-soft)}
    .device-name-input{width:100%;font-size:14px;padding:9px 10px}
    .device-note{margin:0 0 10px 0;background:var(--surface-black);border:1px solid var(--line);border-radius:var(--radius);padding:10px}
    .device-note-title{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--text-soft);margin:0 0 6px 0}
    .device-note ul{margin:0;padding-left:18px;display:grid;gap:4px}
    .device-note li{font-size:12px;color:var(--text-soft)}
    .device-note strong{color:var(--text)}
    .device-status{font-size:12px;color:var(--text-soft);margin:0 0 10px 0}
    .device-box{display:grid;gap:8px;background:var(--surface-black);border:1px solid var(--line);border-radius:var(--radius);padding:10px}
    .device-label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--text-soft)}
    .device-value{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12px;word-break:break-all;color:var(--text)}
    .device-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;margin-top:10px}
    .col-hidden{display:none !important}
    .error{color:var(--danger);white-space:pre-wrap}.out{max-height:360px;overflow:auto;white-space:pre-wrap}
    .system-out{
      scrollbar-width:thin;
      scrollbar-color:var(--accent-ring) var(--scroll-track);
    }
    .system-out::-webkit-scrollbar{width:10px;height:10px}
    .system-out::-webkit-scrollbar-track{
      background:var(--scroll-track);
      border-radius:999px;
    }
    .system-out::-webkit-scrollbar-thumb{
      background:linear-gradient(180deg, var(--scroll-thumb-start), var(--scroll-thumb-end));
      border-radius:999px;
      border:2px solid transparent;
      background-clip:padding-box;
    }
    .system-out::-webkit-scrollbar-thumb:hover{
      background:linear-gradient(180deg, var(--scroll-thumb-start-hover), var(--scroll-thumb-end-hover));
      background-clip:padding-box;
    }
    .system-out::-webkit-scrollbar-corner{background:transparent}
    .terminal-card{background:var(--surface-black);border:1px solid var(--line)} .terminal-card .k{color:var(--primary)}
    .terminal-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
    .system-out{min-height:280px;line-height:1.45}
    .log-line{display:block}
    .log-ts{color:var(--log-ts)}
    .log-level{font-weight:700;margin:0 6px 0 0}
    .log-info{color:var(--log-info)}
    .log-warn{color:var(--log-warn)}
    .log-error{color:var(--log-error)}
    .log-event{color:var(--log-event)}
    .log-command{color:var(--log-command)}
    .log-detail{display:block;color:var(--log-detail);padding-left:18px}
    .rules-actions{justify-content:flex-end;margin-top:auto}
    .chain-panel{margin-top:12px;background:var(--surface-card);border:1px solid var(--line);border-radius:var(--radius);padding:10px}
    .chain-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
    .chain-title{font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:.1em}
    .chain-track{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
    .chain-node{display:inline-flex;align-items:center;gap:8px;background:var(--surface-black);border:1px solid var(--line-soft);border-radius:var(--radius);padding:6px 8px}
    .chain-name{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12px;color:var(--text)}
    .chain-metric{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px}
    .chain-arrow{color:var(--text-soft);font-size:12px}
    .chain-edit-modal{width:min(520px,92vw);background:color-mix(in srgb,var(--surface-highest) 64%, transparent);backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
    .chain-edit-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
    .chain-edit-list{display:grid;gap:6px;max-height:min(58vh,420px);overflow:auto;padding-right:2px}
    .chain-edit-item{display:flex;align-items:center;justify-content:space-between;gap:10px;background:var(--surface-black);border:1px solid var(--line-soft);border-radius:var(--radius);padding:9px 10px;cursor:grab}
    .chain-edit-item.dragging{opacity:.55}
    .chain-edit-main{display:grid;gap:2px;min-width:0}
    .chain-edit-item .name{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12px}
    .chain-edit-item .meta{font-size:11px;color:var(--text-soft)}
    .chain-edit-metrics{display:flex;flex-wrap:wrap;gap:10px}
    .chain-edit-metric{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px}
    .chain-edit-item.locked{border-color:var(--accent-ring);background:linear-gradient(90deg,var(--accent-bg),rgba(0,0,0,0))}
    .chain-edit-item.locked .name{color:var(--primary)}
    .chain-edit-handle{font-size:10px;color:var(--text-soft);letter-spacing:.08em;text-transform:uppercase}
    .chain-edit-arrow{display:flex;align-items:center;justify-content:center;font-size:14px;line-height:1;color:var(--text-soft);padding:1px 0}
    .chain-edit-empty{font-size:12px;color:var(--text-soft);padding:8px;border:1px dashed var(--line);border-radius:var(--radius);background:var(--surface-black)}
    details.guide{
      margin-top:var(--gap);
      padding:0;
      overflow:hidden;
    }
    details.guide summary{
      list-style:none;
      cursor:pointer;
      display:flex;
      align-items:center;
      gap:10px;
      padding:12px 14px;
      margin:0;
      user-select:none;
      border-bottom:1px solid transparent;
      transition:background .15s ease, border-color .15s ease;
    }
    details.guide summary::-webkit-details-marker{display:none}
    details.guide summary:hover{background:var(--surface-high)}
    details.guide summary:focus-visible{
      outline:2px solid color-mix(in srgb,var(--primary) 62%, transparent);
      outline-offset:-2px;
    }
    details.guide[open] summary{
      border-bottom-color:var(--line);
      background:color-mix(in srgb,var(--surface-card) 86%, var(--surface-high) 14%);
    }
    .guide-chevron{
      width:16px;
      height:16px;
      color:var(--text-soft);
      flex:0 0 auto;
      transition:transform .18s ease,color .18s ease;
    }
    details.guide[open] .guide-chevron{
      transform:rotate(90deg);
      color:var(--text);
    }
    .guide-title{
      font-size:11px;
      color:var(--text-soft);
      text-transform:uppercase;
      letter-spacing:.12em;
      font-family:"JetBrains Mono",ui-monospace,monospace;
    }
    .guide-body{
      display:grid;
      gap:10px;
      padding:12px 14px 14px;
      background:var(--surface-card);
    }
    .guide-intro{
      margin:0;
      color:var(--text-soft);
      font-size:13px;
      line-height:1.45;
    }
    .guide-grid{
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:10px;
    }
    .guide-block{
      background:var(--surface-black);
      border:1px solid var(--line-soft);
      border-radius:var(--radius);
      padding:9px 10px;
      display:grid;
      gap:6px;
      min-width:0;
    }
    .guide-block h4{
      margin:0;
      font-size:11px;
      letter-spacing:.08em;
      text-transform:uppercase;
      color:var(--text-soft);
      font-family:"JetBrains Mono",ui-monospace,monospace;
    }
    .guide-block ul{
      margin:0;
      padding-left:18px;
      display:grid;
      gap:4px;
      color:var(--text);
      font-size:12px;
      line-height:1.4;
    }
    .guide-block li{margin:0}
    .guide-release-block{display:grid;gap:8px}
    .guide-release-headline{display:flex;align-items:center;justify-content:space-between;gap:10px}
    .guide-release-headline h4{margin:0}
    .guide-release-status{
      font-size:12px;
      color:var(--text-soft);
      border:1px solid var(--line-soft);
      background:var(--surface-high);
      border-radius:var(--radius);
      padding:6px 8px;
    }
    .guide-release-status.synced{color:var(--primary);border-color:var(--accent-border);background:var(--accent-bg)}
    .guide-release-status.fallback{color:var(--warn-strong);border-color:var(--warn-ring);background:var(--warn-bg)}
    .guide-release-status.failed{color:var(--danger-soft);border-color:var(--danger-ring);background:var(--danger-bg)}
    .guide-release-list{display:grid;gap:7px;max-height:320px;overflow:auto;padding-right:2px}
    .guide-release-empty{
      border:1px dashed var(--line-soft);
      border-radius:var(--radius);
      padding:8px;
      color:var(--text-soft);
      font-size:12px;
      background:var(--surface-high);
    }
    .guide-release-item{
      border:1px solid var(--line-soft);
      border-radius:var(--radius);
      background:var(--surface-high);
      padding:8px;
      display:grid;
      gap:6px;
    }
    .guide-release-item.current{
      border-color:var(--accent-border);
      box-shadow:0 0 0 1px var(--accent-inset) inset;
    }
    .guide-release-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
    .guide-release-tag{
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:12px;
      color:var(--text);
      font-weight:600;
    }
    .guide-release-badge{
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:10px;
      letter-spacing:.06em;
      text-transform:uppercase;
      border-radius:999px;
      padding:2px 7px;
      border:1px solid var(--line);
      color:var(--text-soft);
      background:var(--surface-black);
    }
    .guide-release-badge.prerelease{
      color:var(--warn-strong);
      border-color:var(--warn-ring);
      background:var(--warn-bg);
    }
    .guide-release-badge.current{
      color:var(--primary);
      border-color:var(--accent-border);
      background:var(--accent-bg);
    }
    .guide-release-meta{font-size:11px;color:var(--text-soft)}
    .guide-release-highlights{margin:0;padding-left:18px;display:grid;gap:3px;font-size:12px;color:var(--text)}
    .guide-release-link{font-size:12px;color:var(--primary);text-decoration:none;font-weight:600}
    .guide-release-link:hover{text-decoration:underline}
    .panel-footer{
      margin-top:var(--gap);
      padding:12px 14px;
      border:1px solid var(--line);
      border-radius:var(--radius);
      background:var(--surface-low);
      color:var(--text-soft);
      font-size:12px;
      line-height:1.5;
    }
    .panel-footer strong{color:var(--text)}
    .panel-footer a{
      color:var(--primary);
      text-decoration:none;
      font-weight:600;
    }
    .panel-footer a:hover{text-decoration:underline}
    .panel-footer-row{
      display:flex;
      flex-wrap:wrap;
      gap:10px 16px;
      align-items:center;
      margin-top:6px;
    }
    .migration-note{
      margin:0;
      color:var(--text-soft);
      font-size:12px;
      line-height:1.45;
    }
    .migration-actions{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      align-items:center;
    }
    .migration-actions button{
      flex:1 1 180px;
      min-width:0;
    }
    .migration-file{
      font-size:12px;
      color:var(--text-soft);
      min-height:16px;
    }
    .profiles-panel{
      gap:14px;
    }
    .profiles-panel-body{
      display:grid;
      gap:10px;
    }
    .profiles-panel-head{
      display:grid;
      gap:6px;
    }
    .export-modal{
      width:min(860px,96vw);
      max-height:84vh;
      display:flex;
      flex-direction:column;
      gap:12px;
      background:color-mix(in srgb,var(--surface-highest) 64%, transparent);
      backdrop-filter:blur(24px);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:14px;
    }
    .export-modal h3{margin:0}
    .export-modal-intro{
      margin:0;
      color:var(--text-soft);
      font-size:12px;
      line-height:1.45;
    }
    .export-modal-field{
      display:grid;
      gap:6px;
    }
    .export-modal-field label{
      font-size:12px;
      color:var(--text-soft);
    }
    .export-modal-table-wrap{
      border:1px solid var(--line);
      border-radius:var(--radius);
      background:var(--surface-black);
      overflow:auto;
      max-height:44vh;
    }
    .export-modal-table{
      width:100%;
      min-width:100%;
      border-collapse:collapse;
    }
    .export-modal-table thead th{
      position:sticky;
      top:0;
      background:var(--surface-high);
      z-index:1;
      font-size:10px;
      color:var(--text-soft);
      text-transform:uppercase;
      letter-spacing:.12em;
      padding:10px 12px;
      border-bottom:1px solid var(--line);
    }
    .export-modal-table tbody td{
      padding:11px 12px;
      border-bottom:1px solid var(--line-soft);
      font-size:13px;
      vertical-align:middle;
    }
    .export-modal-table tbody tr:last-child td{
      border-bottom:0;
    }
    .export-modal-table tbody tr:hover{
      background:var(--surface-high);
    }
    .export-modal-table th:first-child,
    .export-modal-table td:first-child{
      width:52px;
      text-align:center;
    }
    .export-modal-table input[type="checkbox"]{
      width:16px;
      height:16px;
    }
    .export-modal-name{
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:12px;
      color:var(--text);
    }
    .export-modal-hint{
      color:var(--text-soft);
      word-break:break-word;
    }
    .export-modal-summary{
      font-size:12px;
      color:var(--text-soft);
      background:var(--surface-high);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:9px 10px;
    }
    .export-modal-actions{
      display:flex;
      flex-wrap:wrap;
      align-items:center;
      justify-content:space-between;
      gap:8px;
    }
    .export-modal-bulk-actions{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
    }
    .export-modal-footer{
      display:flex;
      justify-content:flex-end;
      gap:8px;
    }
    .alarm-actions{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:8px;
    }
    .alarm-selected-row{
      display:grid;
      gap:6px;
      padding:9px 10px;
      background:var(--surface-black);
      border:1px solid var(--line);
      border-radius:var(--radius);
    }
    .alarm-selected-head{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
    }
    .alarm-selected-label{
      font-size:11px;
      color:var(--text-soft);
      text-transform:uppercase;
      letter-spacing:.08em;
    }
    .alarm-selected-value{
      font-size:13px;
      color:var(--text);
      font-weight:600;
    }
    .alarm-modal{
      width:min(860px,96vw);
      max-height:84vh;
      display:flex;
      flex-direction:column;
      gap:12px;
      background:color-mix(in srgb,var(--surface-highest) 64%, transparent);
      backdrop-filter:blur(24px);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:14px;
    }
    .alarm-modal h3{margin:0}
    .alarm-modal-intro{
      margin:0;
      color:var(--text-soft);
      font-size:12px;
      line-height:1.45;
    }
    .alarm-preset-list{
      display:grid;
      gap:8px;
      overflow:auto;
      max-height:52vh;
      padding-right:4px;
    }
    .alarm-preset-item{
      display:grid;
      grid-template-columns:minmax(0,1fr) auto;
      gap:10px;
      align-items:center;
      background:var(--surface-black);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:10px;
      transition:border-color .15s ease, background .15s ease, box-shadow .15s ease;
    }
    .alarm-preset-item.selected{
      border-color:var(--accent-border);
      background:color-mix(in srgb,var(--accent-bg) 55%, var(--surface-black));
      box-shadow:0 0 0 1px var(--accent-inset) inset;
    }
    .alarm-preset-main{
      min-width:0;
      display:grid;
      gap:4px;
      cursor:pointer;
    }
    .alarm-preset-name{
      font-size:13px;
      font-weight:600;
      color:var(--text);
    }
    .alarm-preset-meta{
      font-size:12px;
      color:var(--text-soft);
    }
    .alarm-preset-actions{
      display:flex;
      align-items:center;
      gap:8px;
      flex-shrink:0;
    }
    .alarm-modal-footer{
      display:flex;
      justify-content:flex-end;
      gap:8px;
    }
    .update-modal{
      width:min(780px,96vw);
      max-height:84vh;
      display:flex;
      flex-direction:column;
      gap:12px;
      background:color-mix(in srgb,var(--surface-highest) 64%, transparent);
      backdrop-filter:blur(24px);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:14px;
    }
    .update-modal h3{margin:0}
    .update-modal-intro{
      margin:0;
      color:var(--text-soft);
      font-size:12px;
      line-height:1.45;
    }
    .update-modal-release{
      display:grid;
      gap:10px;
      overflow:auto;
      max-height:52vh;
      padding-right:4px;
    }
    .update-modal-card{
      display:grid;
      gap:8px;
      background:var(--surface-black);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:12px;
    }
    .update-modal-meta{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      align-items:center;
    }
    .update-modal-tag{
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:12px;
      color:var(--primary);
      font-weight:700;
    }
    .update-modal-date{
      font-size:11px;
      color:var(--text-soft);
    }
    .update-modal-title{
      font-size:15px;
      font-weight:700;
      color:var(--text);
    }
    .update-modal-highlights{
      margin:0;
      padding-left:18px;
      display:grid;
      gap:4px;
      color:var(--text);
      font-size:12px;
      line-height:1.45;
    }
    .update-modal-body{
      margin:0;
      white-space:pre-wrap;
      color:var(--text-soft);
      font-size:12px;
      line-height:1.5;
    }
    .update-modal-link{
      font-size:12px;
      color:var(--primary);
      text-decoration:none;
      font-weight:600;
    }
    .update-modal-link:hover{text-decoration:underline}
    .update-modal-output{
      margin:0;
      background:var(--surface-black);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:10px;
      color:var(--text-soft);
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:11px;
      line-height:1.45;
      white-space:pre-wrap;
      overflow:auto;
      max-height:160px;
    }
    .update-modal-progress{
      display:none;
      gap:8px;
      padding:10px 12px;
      background:color-mix(in srgb,var(--surface-black) 84%, transparent);
      border:1px solid var(--line);
      border-radius:var(--radius);
    }
    .update-modal-progress.active{
      display:grid;
    }
    .update-modal-progress-head{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      font-size:12px;
    }
    .update-modal-progress-label{
      color:var(--text);
      font-weight:700;
    }
    .update-modal-progress-value{
      color:var(--primary);
      font-family:"JetBrains Mono",ui-monospace,monospace;
      font-size:11px;
    }
    .update-modal-progress-track{
      height:10px;
      border-radius:999px;
      overflow:hidden;
      background:color-mix(in srgb,var(--surface) 78%, transparent);
      border:1px solid color-mix(in srgb,var(--line) 88%, transparent);
    }
    .update-modal-progress-bar{
      height:100%;
      width:0%;
      border-radius:999px;
      background:linear-gradient(90deg, var(--primary), color-mix(in srgb,var(--primary) 50%, white));
      transition:width .22s ease;
    }
    .update-modal-progress-note{
      color:var(--text-soft);
      font-size:12px;
      line-height:1.45;
    }
    .update-modal-footer{
      display:flex;
      justify-content:flex-end;
      gap:8px;
    }
    .review-modal{
      width:min(760px,96vw);
      max-height:84vh;
      display:flex;
      flex-direction:column;
      background:color-mix(in srgb,var(--surface-highest) 64%, transparent);
      backdrop-filter:blur(24px);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:14px;
    }
    .review-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px}
    .review-head h3{margin:0}
    .review-intro{margin:0;color:var(--text-soft);font-size:12px;line-height:1.45}
    .review-list{display:grid;gap:8px;overflow:auto;padding-right:4px}
    .review-item{
      display:grid;
      gap:8px;
      background:var(--surface-black);
      border:1px solid var(--line-soft);
      border-radius:var(--radius);
      padding:10px;
    }
    .review-item-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px}
    .review-name{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12px;color:var(--text)}
    .review-hint{font-size:12px;color:var(--text-soft)}
    .review-status{
      font-size:10px;
      letter-spacing:.08em;
      text-transform:uppercase;
      border-radius:999px;
      padding:3px 8px;
      border:1px solid var(--line);
      background:var(--surface-high);
      color:var(--text-soft);
    }
    .review-status.ready{color:var(--primary);border-color:var(--accent-border);background:var(--accent-bg)}
    .review-status.conflict{color:var(--warn-strong);border-color:var(--warn-ring);background:var(--warn-bg)}
    .review-status.invalid{color:var(--danger-soft);border-color:var(--danger-ring);background:var(--danger-bg)}
    .review-problems{margin:0;padding-left:18px;display:grid;gap:4px;font-size:12px;color:var(--text-soft)}
    .review-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
    .review-actions select,.review-actions input{min-width:170px}
    .review-summary{
      margin-top:10px;
      font-size:12px;
      color:var(--text-soft);
      background:var(--surface-high);
      border:1px solid var(--line);
      border-radius:var(--radius);
      padding:9px 10px;
    }
    @media (max-width:900px){
      .guide-grid{grid-template-columns:1fr}
    }
    .modal-backdrop{position:fixed;inset:0;background:var(--modal-backdrop);display:none;align-items:center;justify-content:center;z-index:40}
    .modal{width:min(520px,92vw);background:color-mix(in srgb,var(--surface-highest) 60%, transparent);backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
    .modal h3{margin:0 0 8px 0}.modal .row{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}.modal .body{white-space:pre-wrap;color:var(--text-soft)}.modal input{width:100%;margin-top:8px}
  </style>
</head>
<body>
  <main class=\"container\">
    <section class=\"app-header\">
      <div class=\"app-title-wrap\">
        <div class=\"app-title\">Codex Account Manager</div>
        <div class=\"app-version\">v__UI_VERSION__</div>
        <div id=\"appUpdateBadge\" class=\"app-update-pill\">Update available</div>
        <span id=\"saveSpinner\" class=\"save-spinner\" aria-label=\"Saving\" title=\"Saving\"></span>
      </div>
      <div class=\"app-header-right\">
        <button id=\"appUpdateBtn\" class=\"btn-primary\" type=\"button\" style=\"display:none\" title=\"Review the latest release notes and update this app.\">Update</button>
        <button id=\"themeIconBtn\" class=\"header-icon-btn\" type=\"button\" title=\"Cycle theme mode between auto, dark, and light.\" aria-label=\"Cycle theme\">◐</button>
        <button id=\"debugIconBtn\" class=\"header-icon-btn\" type=\"button\" title=\"Toggle debug mode to show System.Out logs and advanced diagnostics.\" aria-label=\"Toggle debug mode\">
          <svg viewBox=\"0 0 16 16\" aria-hidden=\"true\" focusable=\"false\">
            <path d=\"M1.8 2.2h12.4c.66 0 1.2.54 1.2 1.2v9.2c0 .66-.54 1.2-1.2 1.2H1.8c-.66 0-1.2-.54-1.2-1.2V3.4c0-.66.54-1.2 1.2-1.2z\"/>
            <path d=\"M4.1 5.1l2.2 2-2.2 2v-4z\" fill=\"var(--surface-highest)\"/>
            <rect x=\"7.4\" y=\"8.4\" width=\"4.4\" height=\"1.3\" rx=\"0.65\" fill=\"var(--surface-highest)\"/>
          </svg>
        </button>
        <button id=\"settingsToggleBtn\" class=\"settings-toggle-btn\" type=\"button\" title=\"Show or hide the settings panels to free up screen space.\" aria-label=\"Toggle settings\" aria-pressed=\"false\">
          <svg viewBox=\"0 0 16 16\" aria-hidden=\"true\" focusable=\"false\">
            <path d=\"M9.405 1.05c-.413-1.4-2.397-1.4-2.81 0l-.1.34a1.46 1.46 0 0 1-2.105.872l-.31-.17c-1.25-.69-2.65.71-1.96 1.96l.17.31a1.46 1.46 0 0 1-.872 2.105l-.34.1c-1.4.413-1.4 2.397 0 2.81l.34.1a1.46 1.46 0 0 1 .872 2.105l-.17.31c-.69 1.25.71 2.65 1.96 1.96l.31-.17a1.46 1.46 0 0 1 2.105.872l.1.34c.413 1.4 2.397 1.4 2.81 0l.1-.34a1.46 1.46 0 0 1 2.105-.872l.31.17c1.25.69 2.65-.71 1.96-1.96l-.17-.31a1.46 1.46 0 0 1 .872-2.105l.34-.1c1.4-.413 1.4-2.397 0-2.81l-.34-.1a1.46 1.46 0 0 1-.872-2.105l.17-.31c.69-1.25-.71-2.65-1.96-1.96l-.31.17a1.46 1.46 0 0 1-2.105-.872l-.1-.34zM8 10.3A2.3 2.3 0 1 1 8 5.7a2.3 2.3 0 0 1 0 4.6z\"/>
          </svg>
        </button>
      </div>
    </section>
    <select id=\"themeSelect\" style=\"display:none\"><option value=\"auto\">Auto</option><option value=\"dark\">Dark</option><option value=\"light\">Light</option></select>
    <input id=\"debugToggle\" type=\"checkbox\" style=\"display:none\" />
    <div id=\"fatalBanner\" class=\"fatal\"></div>
    <div id=\"inAppNoticeStack\" class=\"inapp-notice-stack\" aria-live=\"polite\" aria-atomic=\"false\"></div>

    <section id=\"settingsSection\" data-settings-section=\"1\" class=\"section toolbar\">
      <div class=\"controls-grid\">
        <section class=\"control-card settings-card\">
          <div class=\"group-title\">Panel Controls</div>
          <div class=\"setting-row inset-row refresh-setting-row\">
            <span class=\"setting-label\" title=\"Automatically refresh usage for only the current active account.\">Current Account Auto Refresh</span>
            <div class=\"field-block refresh-setting-controls\">
              <div class=\"stepper compact refresh-inline-stepper\" data-stepper title=\"Set how often the current active account refreshes, in seconds.\"><button id=\"currentIntervalDec\" data-stepper-dec type=\"button\" title=\"Decrease current-account refresh interval by 1 second.\">-</button><input id=\"currentIntervalInput\" type=\"number\" min=\"1\" max=\"3600\" step=\"1\" value=\"__INTERVAL_INT__\" title=\"Current-account auto refresh interval in seconds.\" /><button id=\"currentIntervalInc\" data-stepper-inc type=\"button\" title=\"Increase current-account refresh interval by 1 second.\">+</button><span class=\"label\" title=\"Seconds\">sec</span></div>
              <label class=\"toggle refresh-setting-toggle\" title=\"Enable or disable automatic refresh for the current active account only.\"><input id=\"currentAutoToggle\" type=\"checkbox\" title=\"Enable or disable automatic refresh for the current active account only.\" /></label>
            </div>
          </div>
          <div class=\"setting-row inset-row refresh-setting-row\">
            <span class=\"setting-label\" title=\"Periodically refresh all saved accounts one by one in the background.\">Auto Refresh All</span>
            <div class=\"field-block refresh-setting-controls\">
              <div class=\"stepper compact refresh-inline-stepper\" data-stepper title=\"Set how often all saved accounts are refreshed in the background, in minutes.\"><button id=\"allIntervalDec\" data-stepper-dec type=\"button\" title=\"Decrease all-accounts refresh interval by 1 minute.\">-</button><input id=\"allIntervalInput\" type=\"number\" min=\"1\" max=\"60\" step=\"1\" value=\"5\" title=\"All-accounts background refresh interval in minutes.\" /><button id=\"allIntervalInc\" data-stepper-inc type=\"button\" title=\"Increase all-accounts refresh interval by 1 minute.\">+</button><span class=\"label\" title=\"Minutes\">min</span></div>
              <label class=\"toggle refresh-setting-toggle\" title=\"Enable or disable background refresh for all saved accounts.\"><input id=\"allAutoToggle\" type=\"checkbox\" title=\"Enable or disable background refresh for all saved accounts.\" /></label>
            </div>
          </div>
          <div class=\"settings-footer-actions\">
            <button id=\"refreshBtn\" class=\"btn btn-block settings-footer-btn btn-primary\" title=\"Refresh config, current account state, and usage for all accounts right now.\">Refresh</button>
            <button id=\"restartBtn\" class=\"btn btn-block settings-footer-btn btn-warning\" title=\"Restart the local UI service without opening a new browser tab.\">Restart</button>
            <button id=\"killAllBtn\" class=\"btn btn-block settings-footer-btn btn-primary-danger\" title=\"Stop running background Codex account processes. Use only when you need a hard reset.\">Kill All</button>
          </div>
        </section>

        <section class=\"control-card notify-card settings-card\">
          <div class=\"group-title\">Alarm</div>
          <div class=\"alarm-selected-row\">
            <div class=\"alarm-selected-head\">
              <div class=\"alarm-selected-label\">Selected Alarm</div>
              <label class=\"toggle\" title=\"Turn sound alarms on or off for usage warnings.\"><input id=\"alarmToggle\" type=\"checkbox\" title=\"Turn sound alarms on or off for usage warnings.\" /></label>
            </div>
            <div id=\"alarmPresetValue\" class=\"alarm-selected-value\">Beacon</div>
          </div>
          <div class=\"metric-pair-grid\">
            <div class=\"setting-row metric inset-row\">
              <span class=\"setting-label\" title=\"Trigger an alarm when 5-hour remaining usage falls below this percentage.\">5H alarm %</span>
              <div class=\"stepper compact\" data-stepper title=\"5-hour warning threshold percentage.\"><button data-stepper-dec type=\"button\" title=\"Decrease 5-hour alarm threshold by 1 percent.\">-</button><input id=\"alarm5h\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" title=\"5-hour warning threshold percentage.\" /><button data-stepper-inc type=\"button\" title=\"Increase 5-hour alarm threshold by 1 percent.\">+</button></div>
            </div>
            <div class=\"setting-row metric inset-row\">
              <span class=\"setting-label\" title=\"Trigger an alarm when weekly remaining usage falls below this percentage.\">Weekly alarm %</span>
              <div class=\"stepper compact\" data-stepper title=\"Weekly warning threshold percentage.\"><button data-stepper-dec type=\"button\" title=\"Decrease weekly alarm threshold by 1 percent.\">-</button><input id=\"alarmWeekly\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" title=\"Weekly warning threshold percentage.\" /><button data-stepper-inc type=\"button\" title=\"Increase weekly alarm threshold by 1 percent.\">+</button></div>
            </div>
          </div>
          <div class=\"alarm-actions\">
            <button id=\"chooseAlarmBtn\" class=\"btn\" type=\"button\" title=\"Browse built-in alarm presets and preview alternatives before saving one.\">Choose Alarm</button>
            <button id=\"testAlarmBtn\" class=\"btn-warning\" type=\"button\" title=\"Play the currently selected alarm preset and show the warning preview now.\">Test Alarm</button>
          </div>
        </section>

        <section class=\"control-card settings-card control-card-full profiles-panel\">
          <div class=\"group-title\">Profiles</div>
          <div class=\"profiles-panel-body\">
            <div class=\"profiles-panel-head\">
              <p class=\"migration-note\">Move saved local profiles between systems. Exported files include sensitive auth data, so keep archives private and only import from sources you trust.</p>
              <div class=\"migration-actions\">
                <button id=\"importProfilesBtn\" class=\"btn-primary\" type=\"button\" title=\"Choose a migration archive, analyze its profiles, and review changes before importing.\">Import</button>
                <button id=\"exportProfilesBtn\" class=\"btn-warning\" type=\"button\" title=\"Choose saved profiles to package into a private migration archive.\">Export</button>
              </div>
            </div>
            <div class=\"migration-file\" id=\"importFileLabel\"></div>
          </div>
          <input id=\"importProfilesInput\" type=\"file\" accept=\".camzip,application/zip\" style=\"display:none\" />
        </section>
      </div>
    </section>

    <section id=\"autoSwitchRulesSection\" data-settings-section=\"1\" class=\"section card\" style=\"padding:12px;\">
      <div class=\"auto-switch-head\">
        <div class=\"k\" style=\"margin-bottom:0;\" title=\"Rules that decide when and how the app should switch accounts automatically.\">Auto-Switch Rules</div>
        <div id=\"asPendingCountdown\" class=\"auto-switch-countdown\" title=\"Shows how long until the next scheduled automatic switch attempt.\">Switch in 00:00</div>
      </div>
      <div class=\"rules-grid\">
        <div class=\"rules-col settings-card\">
          <div class=\"rules-title\">Execution</div>
          <div class=\"setting-row\">
            <span class=\"setting-label\" title=\"Allow the app to switch accounts automatically when rules are met.\">Enabled</span>
            <label class=\"toggle\" title=\"Enable or disable automatic account switching.\"><input id=\"asEnabled\" type=\"checkbox\" title=\"Enable or disable automatic account switching.\" /></label>
          </div>
          <div class=\"setting-row metric inset-row\">
            <span class=\"setting-label\" title=\"Wait this many seconds after a rule is triggered before switching accounts.\">Delay (sec)</span>
            <div class=\"stepper compact\" data-stepper title=\"Delay before an automatic switch executes.\"><button data-stepper-dec type=\"button\" title=\"Decrease auto-switch delay by 1 second.\">-</button><input id=\"asDelay\" type=\"number\" min=\"0\" step=\"1\" title=\"Auto-switch delay in seconds.\" /><button data-stepper-inc type=\"button\" title=\"Increase auto-switch delay by 1 second.\">+</button></div>
          </div>
          <div class=\"exec-actions\">
            <button id=\"asRunSwitchBtn\" class=\"btn btn-block settings-footer-btn\" title=\"Run the next switch immediately using the current chain and rules.\">Run Switch</button>
            <button id=\"asRapidTestBtn\" class=\"btn btn-block settings-footer-btn\" title=\"Run a fast diagnostic pass to test switching behavior.\">Rapid Test</button>
            <button id=\"asForceStopBtn\" class=\"btn btn-block settings-footer-btn btn-danger\" title=\"Stop running auto-switch test jobs.\">Stop Tests</button>
            <button id=\"asTestAutoSwitchBtn\" class=\"btn btn-block settings-footer-btn\" title=\"Start a controlled auto-switch test using the current thresholds.\">Test Auto Switch</button>
          </div>
        </div>
        <div class=\"rules-col settings-card\">
          <div class=\"rules-title\">Selection Policy</div>
          <div class=\"setting-field\"><span class=\"setting-label\" title=\"Choose how candidate accounts are ranked before switching.\">Ranking</span><select id=\"asRanking\" title=\"Select the account ranking mode used for automatic switching.\"><option value=\"balanced\">balanced</option><option value=\"max_5h\">max_5h</option><option value=\"max_weekly\">max_weekly</option><option value=\"manual\">manual</option></select></div>
          <div class=\"metric-pair-grid\">
            <div class=\"setting-row metric inset-row\">
              <span class=\"setting-label\" title=\"Consider switching when 5-hour remaining usage falls below this percentage.\">5H switch %</span>
              <div class=\"stepper compact\" data-stepper title=\"5-hour switching threshold percentage.\"><button data-stepper-dec type=\"button\" title=\"Decrease 5-hour switch threshold by 1 percent.\">-</button><input id=\"as5h\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" title=\"5-hour switch threshold percentage.\" /><button data-stepper-inc type=\"button\" title=\"Increase 5-hour switch threshold by 1 percent.\">+</button></div>
            </div>
            <div class=\"setting-row metric inset-row\">
              <span class=\"setting-label\" title=\"Consider switching when weekly remaining usage falls below this percentage.\">Weekly switch %</span>
              <div class=\"stepper compact\" data-stepper title=\"Weekly switching threshold percentage.\"><button data-stepper-dec type=\"button\" title=\"Decrease weekly switch threshold by 1 percent.\">-</button><input id=\"asWeekly\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" title=\"Weekly switch threshold percentage.\" /><button data-stepper-inc type=\"button\" title=\"Increase weekly switch threshold by 1 percent.\">+</button></div>
            </div>
          </div>
          <div id=\"asAutoArrangeRow\" class=\"field-row rules-actions\"><button id=\"asAutoArrangeBtn\" class=\"btn-primary\" title=\"Rebuild the switch chain automatically from current usage and ranking rules.\">Auto Arrange</button></div>
        </div>
      </div>
      <div id=\"asChainPanel\" class=\"chain-panel\">
        <div class=\"chain-head\">
          <div class=\"chain-title\" title=\"Preview of the current account order used for automatic switching.\">Switch Chain Preview</div>
          <button id=\"asChainEditBtn\" class=\"btn\" type=\"button\" title=\"Edit the switch chain order manually.\">Edit</button>
        </div>
        <div id=\"asChainPreview\" class=\"chain-track\" title=\"Current auto-switch chain order.\">-</div>
      </div>
    </section>

    <section class=\"section\">
      <div class=\"accounts-toolbar\">
        <div class=\"k\" style=\"margin:0\">Accounts</div>
        <div class=\"spacer\"></div>
        <div class=\"accounts-actions\">
          <button id=\"addAccountBtn\" class=\"btn-primary\" title=\"Create a new saved profile and start login.\">Add Account</button>
          <button id=\"removeAllBtn\" class=\"btn btn-primary-danger\" title=\"Remove every saved account profile from this app.\">Remove All</button>
          <button id=\"colSettingsBtn\" class=\"btn\" title=\"Choose which table columns are visible.\">Columns</button>
        </div>
      </div>
      <div class=\"table-wrap\">
      <table>
        <thead>
          <tr>
            <th data-col=\"cur\" data-sort=\"current\" title=\"Current account status. Green dot means this profile is active.\">STS</th><th data-col=\"profile\" data-sort=\"name\" title=\"Saved profile name. Click the header to sort.\">Profile</th><th data-col=\"email\" data-sort=\"email\" title=\"Email linked to the saved account.\">Email</th><th data-col=\"h5\" data-sort=\"usage5\" title=\"Remaining 5-hour usage percentage.\">5H Usage</th><th data-col=\"h5remain\" data-sort=\"usage5remain\" title=\"Time remaining until the 5-hour window resets.\">5H Remain</th><th data-col=\"h5reset\" data-sort=\"usage5reset\" title=\"Exact reset time for the 5-hour window.\">5H Reset At</th><th data-col=\"weekly\" data-sort=\"usageW\" title=\"Remaining weekly usage percentage.\">Weekly</th><th data-col=\"weeklyremain\" data-sort=\"usageWremain\" title=\"Time remaining until the weekly window resets.\">W Remain</th><th data-col=\"weeklyreset\" data-sort=\"usageWreset\" title=\"Exact reset time for the weekly window.\">Weekly Reset At</th><th data-col=\"plan\" data-sort=\"planType\" title=\"Detected account plan type.\">Plan</th><th data-col=\"paid\" data-sort=\"isPaid\" title=\"Whether the account appears to be paid.\">Paid</th><th data-col=\"id\" data-sort=\"id\" title=\"Account identifier or principal.\">ID</th><th data-col=\"added\" data-sort=\"savedAt\" title=\"When this profile was added to the app.\">Added</th><th data-col=\"note\" class=\"note-col\" data-sort=\"note\" title=\"Extra account notes, such as same-principal markers.\">Note</th><th data-col=\"auto\" class=\"no-sort\" title=\"Include this profile in automatic switching.\">Auto</th><th data-col=\"actions\" class=\"no-sort\" title=\"Switch, rename, or remove this profile.\">Actions</th>
          </tr>
        </thead>
        <tbody id=\"rows\"></tbody>
      </table>
      <div id=\"mobileRows\" class=\"mobile-list\"></div>
      </div>
    </section>
    <div id=\"error\" class=\"error\"></div>

    <section id=\"debugRuntimeSection\" class=\"section\" style=\"display:none;\">
      <div class=\"card terminal-card\" style=\"padding:12px;\">
        <div class=\"terminal-head\">
          <div class=\"k\">System.Out</div>
          <button id=\"exportLogsBtn\" class=\"btn\" type=\"button\" title=\"Download recent debug logs as JSON for troubleshooting.\">Export Debug Logs</button>
        </div>
        <pre id=\"debugOut\" class=\"out system-out\"></pre>
      </div>
    </section>

    <section id=\"advancedCard\" class=\"section card\" style=\"display:none;padding:12px;\">
        <div class=\"k\">Advanced Actions</div>
        <div class=\"grid-2\"><div><button id=\"advStatusBtn\">Status</button><button id=\"advListBtn\">List</button><label class=\"small\"><input id=\"advListDebug\" type=\"checkbox\"/> debug</label></div><div><label class=\"small\"><input id=\"advLoginDevice\" type=\"checkbox\"/> device-auth</label><button id=\"advLoginBtn\">Login</button></div></div>
        <hr/>
        <div class=\"grid-2\"><div><input id=\"advQuery\" placeholder=\"query\"/><button id=\"advSwitchBtn\">switch-adv</button><button id=\"advRemoveBtn\">remove-adv</button><label class=\"small\"><input id=\"advRemoveAll\" type=\"checkbox\"/> all</label></div><div><select id=\"advScope\"><option value=\"auto\">auto</option><option value=\"api\">api</option></select><select id=\"advAction\"><option value=\"\">(no action)</option><option value=\"enable\">enable</option><option value=\"disable\">disable</option></select><div class=\"stepper compact\" data-stepper><button data-stepper-dec type=\"button\">-</button><input id=\"adv5h\" type=\"number\" placeholder=\"5h\" min=\"0\" step=\"1\"/><button data-stepper-inc type=\"button\">+</button></div><div class=\"stepper compact\" data-stepper><button data-stepper-dec type=\"button\">-</button><input id=\"advWeekly\" type=\"number\" placeholder=\"weekly\" min=\"0\" step=\"1\"/><button data-stepper-inc type=\"button\">+</button></div><button id=\"advConfigBtn\">config</button></div></div>
        <hr/>
        <div class=\"grid-2\"><div><div class=\"small muted\">Advanced import</div><input id=\"advImportPath\" placeholder=\"/path/to/auth.json or dir\"/><input id=\"advImportAlias\" placeholder=\"alias (optional)\"/><label class=\"small\"><input id=\"advImportCpa\" type=\"checkbox\"/> cpa</label><label class=\"small\"><input id=\"advImportPurge\" type=\"checkbox\"/> purge</label><button id=\"advImportBtn\">import</button></div><div><div class=\"small muted\">Maintenance</div><button id=\"advDaemonOnceBtn\">daemon --once</button><button id=\"advDaemonWatchBtn\">daemon --watch</button><button id=\"advCleanBtn\">clean</button></div></div>
        <hr/>
        <div><div class=\"small muted\">Raw auth args</div><input id=\"advAuthArgs\" placeholder=\"list --debug\"/><button id=\"advAuthBtn\">run auth</button></div>
    </section>

    <details id=\"guideDetails\" class=\"guide card\">
      <summary>
        <svg class=\"guide-chevron\" viewBox=\"0 0 24 24\" aria-hidden=\"true\" focusable=\"false\">
          <path d=\"M9 6l6 6-6 6\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"></path>
        </svg>
        <span class=\"guide-title\">Guide & Help</span>
      </summary>
      <div class=\"guide-body\">
        <p class=\"guide-intro\">Use this panel to add accounts, monitor live usage, import or export saved profiles, tune alarms and auto-switch behavior, review release notes, and update the app from one place.</p>
        <div class=\"guide-grid\">
          <section class=\"guide-block\">
            <h4>Quick Start</h4>
            <ul>
              <li>Use <b>Add Account</b> to open the combined login dialog, enter a profile name, then choose <b>Device Login</b> or <b>Normal Login</b>.</li>
              <li>Use <b>Switch</b> on any row to activate a saved profile in Codex; the active account gets the green status dot and stays pinned first.</li>
              <li>Use <b>Refresh</b> for a full immediate sync after switching, login, config changes, or recovering from stale data.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Header & Panel Controls</h4>
            <ul>
              <li>Header shows the current app version, and when a newer release exists it adds a green <b>Update available</b> badge plus an <b>Update</b> button.</li>
              <li>Header controls cycle <b>Theme</b>, toggle <b>Debug mode</b>, and show or hide the settings panels.</li>
              <li><b>Current Account Auto Refresh</b> polls only the active account in seconds and is meant for lightweight continuous monitoring.</li>
              <li><b>Auto Refresh All</b> runs a slower background sweep in minutes and refreshes saved accounts one by one instead of doing one expensive batch on every tick.</li>
              <li><b>Restart</b> restarts the local UI service, and <b>Kill All</b> force-stops managed background account processes.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Profiles Import / Export</h4>
            <ul>
              <li><b>Import</b> opens an archive picker, analyzes the migration file, and lets you review per-profile actions before anything is applied.</li>
              <li><b>Export</b> opens a profile-selection dialog with bulk select actions and an optional custom archive filename.</li>
              <li>Migration archives include sensitive auth data. Keep them private and only import files from sources you trust.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Alarm & Notification</h4>
            <ul>
              <li>Use the toggle in <b>Selected Alarm</b> to turn usage warning alarms on/off.</li>
              <li><b>Choose Alarm</b> opens a built-in preset browser with preview buttons, and <b>Test Alarm</b> plays the currently selected preset immediately.</li>
              <li>Set warning thresholds with <b>5H alarm %</b> and <b>Weekly alarm %</b>.</li>
              <li>Alarm warnings are based on remaining percentage and work with the refreshed table values shown in the Accounts section.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Auto-Switch Rules</h4>
            <ul>
              <li><b>Execution</b>: toggle <b>Enabled</b>, set <b>Delay (sec)</b>, run <b>Run Switch</b>/<b>Rapid Test</b>/<b>Stop Tests</b>/<b>Test Auto Switch</b>.</li>
              <li><b>Selection Policy</b>: choose ranking mode and set switch thresholds.</li>
              <li><b>Switch Chain Preview</b> shows current order; <b>Edit</b> supports manual reorder.</li>
              <li><b>Auto Arrange</b> recalculates chain ordering from current usage and keeps the active account locked at the front when editing the chain manually.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Accounts Area</h4>
            <ul>
              <li>Toolbar actions: <b>Add Account</b>, <b>Remove All</b>, and <b>Columns</b>.</li>
              <li>Table supports sorting by headers and optional column visibility control.</li>
              <li>Per-row actions: <b>Switch</b>, row menu (<b>Rename</b>/<b>Remove</b>), and <b>Auto</b> eligibility toggle.</li>
              <li><b>Plan</b> and <b>Paid</b> fields are available as optional columns (hidden by default).</li>
              <li>Mobile cards open full detail modal and include switch + row-actions shortcuts.</li>
              <li>Tooltips are available across controls, headers, and row actions to explain what each setting or button does.</li>
              <li>Current-account usage is read from the live active auth session, and healthy current sessions automatically sync back into the saved profile snapshot to avoid stale-token drift later.</li>
              <li>If a row shows <b>auth expired</b>, the saved profile auth snapshot no longer works for usage API calls and that account needs a fresh healthy session.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Debug & Advanced</h4>
            <ul>
              <li>In debug mode, <b>System.Out</b> shows UI/API actions, warnings, events, and errors.</li>
              <li><b>Export Debug Logs</b> downloads a JSON snapshot for troubleshooting.</li>
              <li><b>Advanced Actions</b> exposes wrapped `codex-auth` operations for status/login/switch/import/config/daemon/clean/raw auth when deeper inspection is needed.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>About Project</h4>
            <ul>
              <li><b>App Version:</b> v__UI_VERSION__</li>
              <li><b>Repository:</b> <a href=\"https://github.com/alisinaee/Codex-Account-Manager\" target=\"_blank\" rel=\"noopener noreferrer\">Codex-Account-Manager</a></li>
              <li>Local-first Codex profile manager with usage monitoring, safe switching workflows, and auto-switch automation.</li>
              <li>When an update is available, the app can show the latest GitHub release notes first and then run the pipx upgrade flow from the UI.</li>
            </ul>
          </section>
          <section class=\"guide-block guide-release-block\">
            <div class=\"guide-release-headline\">
              <h4>Release Notes</h4>
        <button id=\"guideReleaseRefreshBtn\" class=\"btn\" type=\"button\" title=\"Refresh release notes from GitHub and fall back to local notes if needed.\">Refresh</button>
            </div>
            <div id=\"guideReleaseStatus\" class=\"guide-release-status\">Open this section to load release history.</div>
            <div id=\"guideReleaseList\" class=\"guide-release-list\"></div>
          </section>
        </div>
      </div>
    </details>
    <footer class=\"panel-footer\" aria-label=\"Project footer\">
      <div><strong>MIT License</strong> | Copyright (c) 2026 Codex Account Manager contributors</div>
      <div style=\"margin-top:6px;\"><strong>About:</strong> Manage multiple local Codex profiles, track 5H/weekly usage, and run controlled account switching from one panel.</div>
      <div class=\"panel-footer-row\">
        <span>Project:</span>
        <a href=\"https://github.com/alisinaee/Codex-Account-Manager\" target=\"_blank\" rel=\"noopener noreferrer\">github.com/alisinaee/Codex-Account-Manager</a>
      </div>
      <div style=\"margin-top:6px;\">If you like this product, feel free to star the GitHub repository.</div>
    </footer>
  </main>

  <div id=\"modalBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\">
    <div class=\"modal\">
      <h3 id=\"modalTitle\">Confirm</h3>
      <div id=\"modalBody\" class=\"body\"></div>
      <input id=\"modalInput\" style=\"display:none\" />
      <div class=\"row\">
        <button id=\"modalCancelBtn\" class=\"btn\" title=\"Cancel and close this dialog.\">Cancel</button>
        <button id=\"modalOkBtn\" class=\"btn-primary\" title=\"Confirm and continue.\">OK</button>
      </div>
    </div>
  </div>

  <div id=\"columnsModalBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"columns-modal\">
      <h3>Table Columns</h3>
      <div id=\"columnsModalList\" class=\"columns-list\"></div>
      <div class=\"row\">
        <button id=\"columnsResetBtn\" class=\"btn\" type=\"button\" title=\"Restore the default visible columns.\">Reset Defaults</button>
        <button id=\"columnsDoneBtn\" class=\"btn-primary\" type=\"button\" title=\"Apply column visibility changes and close this dialog.\">Done</button>
      </div>
    </div>
  </div>

  <div id=\"exportProfilesBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"export-modal\">
      <h3>Export Profiles</h3>
      <p class=\"export-modal-intro\">Choose the saved profiles you want to package into a migration archive. You can optionally provide a custom archive name.</p>
      <div class=\"export-modal-field\">
        <label for=\"exportFilenameInput\">Archive Name (Optional)</label>
        <input id=\"exportFilenameInput\" type=\"text\" placeholder=\"codex-account-profiles\" autocomplete=\"off\" />
      </div>
      <div class=\"export-modal-actions\">
        <div class=\"export-modal-bulk-actions\">
          <button id=\"exportSelectAllBtn\" class=\"btn\" type=\"button\" title=\"Select every saved profile in this export list.\">Select All</button>
          <button id=\"exportUnselectAllBtn\" class=\"btn\" type=\"button\" title=\"Clear every selected profile in this export list.\">Unselect All</button>
        </div>
      </div>
      <div class=\"export-modal-table-wrap\">
        <table class=\"export-modal-table\">
          <thead>
            <tr>
              <th scope=\"col\"><input id=\"exportHeaderCheckbox\" type=\"checkbox\" aria-label=\"Toggle all export rows\" /></th>
              <th scope=\"col\">Profile</th>
              <th scope=\"col\">Account Hint</th>
            </tr>
          </thead>
          <tbody id=\"exportProfilesTableBody\"></tbody>
        </table>
      </div>
      <div id=\"exportProfilesSummary\" class=\"export-modal-summary\">No saved profiles are available.</div>
      <div class=\"export-modal-footer\">
        <button id=\"exportProfilesCancelBtn\" class=\"btn\" type=\"button\" title=\"Close this export dialog without creating an archive.\">Cancel</button>
        <button id=\"exportProfilesConfirmBtn\" class=\"btn-warning\" type=\"button\" title=\"Create and download a migration archive for the selected profiles.\">Export Selected</button>
      </div>
    </div>
  </div>

  <div id=\"rowActionsBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"actions-modal\">
      <div class=\"actions-head\">
        <h3>Row Actions</h3>
        <button id=\"rowActionsCloseBtn\" class=\"actions-close\" type=\"button\" aria-label=\"Close row actions\" title=\"Close row actions.\">×</button>
      </div>
      <p class=\"actions-sub\" id=\"rowActionsTarget\">-</p>
      <div class=\"actions-list\">
        <button id=\"rowActionsRenameBtn\" class=\"action-btn\" type=\"button\" title=\"Rename only the saved profile label in this app.\"><span>Rename</span><span class=\"hint\">edit</span></button>
        <button id=\"rowActionsRemoveBtn\" class=\"action-btn danger\" type=\"button\" title=\"Remove this saved profile from the app.\"><span>Remove</span><span class=\"hint\">danger</span></button>
      </div>
    </div>
  </div>

  <div id=\"addDeviceBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"device-modal\">
      <h3>Add Account</h3>
      <p class=\"device-intro\">Create a profile and choose how to log in. Device Login is recommended to avoid browser auto-select issues.</p>
      <label class=\"device-name-row\" for=\"addDeviceNameInput\">
        <span>Profile Name</span>
        <input id=\"addDeviceNameInput\" class=\"device-name-input\" placeholder=\"profile name\" autocomplete=\"off\" title=\"Enter the saved profile name you want to use in this app.\" />
      </label>
      <div class=\"device-note\">
        <p class=\"device-note-title\">Login Methods</p>
        <ul>
          <li><strong>Device Login</strong>: generates a login URL and code. Better when browser cookies auto-select the wrong account.</li>
          <li><strong>Normal Login</strong>: opens regular browser login directly. Faster when you already control account selection.</li>
        </ul>
      </div>
      <p id=\"addDeviceStatus\" class=\"device-status\">Choose a login method to begin.</p>
      <div class=\"device-box\">
        <div class=\"device-label\">Login URL</div>
        <div id=\"addDeviceUrl\" class=\"device-value\">-</div>
        <div class=\"device-label\">Code</div>
        <div id=\"addDeviceCode\" class=\"device-value\">-</div>
      </div>
      <div class=\"device-actions\">
        <button id=\"addDeviceStartBtn\" class=\"btn-primary\" type=\"button\" title=\"Generate a device-login code and URL for this profile.\">Start Device Login</button>
        <button id=\"addDeviceCopyBtn\" class=\"btn\" type=\"button\" title=\"Copy the device-login URL and code.\">Copy</button>
        <button id=\"addDeviceOpenBtn\" class=\"btn\" type=\"button\" title=\"Open the generated device-login URL in your browser.\">Open In Browser</button>
        <button id=\"addDeviceLegacyBtn\" class=\"btn\" type=\"button\" title=\"Use the regular browser login flow instead of device login.\">Use Normal Login</button>
        <button id=\"addDeviceCancelBtn\" class=\"btn\" type=\"button\" title=\"Close this add-account dialog without starting a login flow.\">Close</button>
      </div>
    </div>
  </div>

  <div id=\"chainEditBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"chain-edit-modal\">
      <div class=\"chain-edit-head\">
        <h3 style=\"margin:0;\">Edit Switch Chain</h3>
      </div>
      <div id=\"chainEditHint\" class=\"device-status\">Drag rows to set switch order. Active account is locked at top; edit only the next chain.</div>
      <div id=\"chainEditList\" class=\"chain-edit-list\"></div>
      <div class=\"row\">
        <button id=\"chainEditCancelBtn\" class=\"btn\" type=\"button\" title=\"Close the switch-chain editor without saving changes.\">Cancel</button>
        <button id=\"chainEditSaveBtn\" class=\"btn-primary\" type=\"button\" title=\"Save the current manual switch-chain order.\">Save</button>
      </div>
    </div>
  </div>

  <div id=\"importReviewBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"review-modal\">
      <div class=\"review-head\">
        <div>
          <h3>Import Review</h3>
          <p id=\"importReviewIntro\" class=\"review-intro\">Review each profile before applying this import.</p>
        </div>
        <button id=\"importReviewCloseBtn\" class=\"actions-close\" type=\"button\" aria-label=\"Close import review\">×</button>
      </div>
      <div id=\"importReviewList\" class=\"review-list\"></div>
      <div id=\"importReviewSummary\" class=\"review-summary\"></div>
      <div class=\"row\">
        <button id=\"importReviewCancelBtn\" class=\"btn\" type=\"button\" title=\"Close the import review without applying any profile changes.\">Cancel</button>
        <button id=\"importReviewApplyBtn\" class=\"btn-primary\" type=\"button\" title=\"Apply the reviewed import actions to your saved profiles.\">Apply Import</button>
      </div>
    </div>
  </div>

  <div id=\"alarmPresetBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"alarm-modal\">
      <h3>Choose Alarm</h3>
      <p class=\"alarm-modal-intro\">Browse built-in alarm presets, preview them with the play button, then save the one you want for warning alerts.</p>
      <div id=\"alarmPresetList\" class=\"alarm-preset-list\"></div>
      <div class=\"alarm-modal-footer\">
        <button id=\"alarmPresetCancelBtn\" class=\"btn\" type=\"button\" title=\"Close the alarm picker without changing the current preset.\">Cancel</button>
        <button id=\"alarmPresetUseBtn\" class=\"btn-primary\" type=\"button\" title=\"Save the selected alarm preset for future warning sounds.\">Use Selected</button>
      </div>
    </div>
  </div>

  <div id=\"appUpdateBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"update-modal\">
      <h3>Update App</h3>
      <p id=\"appUpdateIntro\" class=\"update-modal-intro\">Review the latest release notes before upgrading this app.</p>
      <div id=\"appUpdateProgress\" class=\"update-modal-progress\" aria-live=\"polite\">
        <div class=\"update-modal-progress-head\">
          <span id=\"appUpdateProgressLabel\" class=\"update-modal-progress-label\">Preparing update...</span>
          <span id=\"appUpdateProgressValue\" class=\"update-modal-progress-value\">0%</span>
        </div>
        <div class=\"update-modal-progress-track\"><div id=\"appUpdateProgressBar\" class=\"update-modal-progress-bar\"></div></div>
        <div id=\"appUpdateProgressNote\" class=\"update-modal-progress-note\">The update can continue in the background if you close this dialog.</div>
      </div>
      <div id=\"appUpdateRelease\" class=\"update-modal-release\"></div>
      <pre id=\"appUpdateOutput\" class=\"update-modal-output\" style=\"display:none;\"></pre>
      <div class=\"update-modal-footer\">
        <button id=\"appUpdateCancelBtn\" class=\"btn\" type=\"button\" title=\"Close this update review without running the pipx upgrade.\">Cancel</button>
        <button id=\"appUpdateConfirmBtn\" class=\"btn-primary\" type=\"button\" title=\"Run the pipx upgrade now using the reviewed release notes.\">Update Now</button>
      </div>
    </div>
  </div>

  <script>
  const token = __TOKEN_JSON__;
  const UI_VERSION = __UI_VERSION_JSON__;
  const ALARM_PRESETS = __ALARM_PRESETS_JSON__;
  let currentRefreshTimer = null;
  let allRefreshTimer = null;
  let remainTicker = null;
  let eventsTimer = null;
  let sortState = JSON.parse(localStorage.getItem("codex_sort_state") || '{"key":"savedAt","dir":"desc"}');
  let latestData = { status: null, usage: null, list: null, config: null, autoState: null, autoChain: null, events: [] };
  let sessionUsageCache = null;
  let usageFlashUntil = {};
  let usageFetchBlinkActive = false;
  let lastEventId = 0;
  const notifiedEventIds = new Set();
  let alarmAudioCtx = null;
  let notificationSwRegistration = null;
  let baseLogs = [];
  let overlayLogs = [];
  let activeRowActionsName = null;
  let addDeviceSessionId = null;
  let addDevicePollTimer = null;
  let addDeviceSessionState = null;
  let addDeviceProfileName = "";
  let chainEditNames = [];
  let chainEditLockedName = "";
  let autoSwitchTimingSaveTimer = null;
  let autoSwitchPolicySaveTimer = null;
  let configSaveQueue = Promise.resolve();
  let pendingConfigSaves = 0;
  let latestConfigRevision = null;
  let saveUiVisibleSince = 0;
  let saveUiHideTimer = null;
  let pendingAutoSwitchEnabled = null;
  let switchInFlight = false;
  let switchPendingName = "";
  let refreshRunning = false;
  let refreshQueuedOpts = null;
  let currentRefreshRunning = false;
  let allRefreshSweepRunning = false;
  let guideReleaseLoaded = false;
  let guideReleaseLoading = false;
  let guideReleaseLastPayload = null;
  let appUpdateState = null;
  let appUpdateInFlight = false;
  let appUpdateRequestController = null;
  let appUpdateProgressTimer = null;
  let appUpdateProgressValue = 0;
  let appUpdateProgressLabel = "";
  let appUpdateProgressNote = "";
  let appUpdateOutputLines = [];
  let diagnosticsHooksInstalled = false;
  let exportSelectedNames = [];
  let importReviewState = null;
  let alarmPresetDraftId = "";
  const alarmPresetMap = new Map((Array.isArray(ALARM_PRESETS) ? ALARM_PRESETS : []).map((item) => [String(item.id || ""), item]));
  const MAX_OVERLAY_LOGS = 900;
  const LOG_COALESCE_WINDOW_MS = 3500;
  const LOG_STRING_LIMIT = 360;
  const LOG_DETAIL_LIMIT = 1200;
  const POLL_PATHS = new Set([
    "/api/status",
    "/api/ui-config",
    "/api/auto-switch/state",
    "/api/events",
    "/api/debug/logs",
    "/api/list",
    "/api/usage-local",
    "/api/usage-local/current",
    "/api/usage-local/profile",
  ]);
  let activeModalResolver = null;
  const columnLabels = { cur:"STS", profile:"Profile", email:"Email", h5:"5H Usage", h5remain:"5H Remain", h5reset:"5H Reset At", weekly:"Weekly", weeklyremain:"W Remain", weeklyreset:"Weekly Reset At", plan:"Plan", paid:"Paid", id:"ID", added:"Added", note:"Note", auto:"Auto", actions:"Actions" };
  const defaultColumns = { cur:true, profile:true, email:true, h5:true, h5remain:true, h5reset:false, weekly:true, weeklyremain:true, weeklyreset:false, plan:false, paid:false, id:false, added:false, note:false, auto:false, actions:true };
  const requiredColumns = new Set(["h5remain", "weeklyremain"]);
  function normalizeColumnPrefs(pref){
    const next = { ...defaultColumns, ...(pref || {}) };
    requiredColumns.forEach((k) => { next[k] = true; });
    return next;
  }
  function isLegacyAllColumnsEnabled(pref){
    try { return Object.keys(defaultColumns).every((k) => !!pref[k]); } catch(_) { return false; }
  }
  let columnPrefs = (() => {
    try {
      const p = JSON.parse(localStorage.getItem("codex_table_columns") || "{}") || {};
      const migrated = localStorage.getItem("codex_table_columns_default_v2") === "1";
      if(!migrated && p && Object.keys(p).length && isLegacyAllColumnsEnabled(p)){
        localStorage.setItem("codex_table_columns_default_v2", "1");
        const normalized = normalizeColumnPrefs(defaultColumns);
        localStorage.setItem("codex_table_columns", JSON.stringify(normalized));
        return normalized;
      }
      return normalizeColumnPrefs(p);
    } catch(_) { return normalizeColumnPrefs(defaultColumns); }
  })();
  window.__camBootState = { booted: false, lastError: null, version: UI_VERSION, ts: Date.now() };

  function byId(id, required=true){ const el=document.getElementById(id); if(!el && required) throw new Error("Missing element: "+id); return el; }
  function showFatal(e){ const b=byId("fatalBanner", false); if(!b) return; b.style.display="block"; b.textContent="UI boot error: " + (e?.message || String(e)); }
  function setError(msg){ const e=byId("error", false); if(e) e.textContent = msg || ""; }
  function showInAppNotice(title, body, opts){
    const stack = byId("inAppNoticeStack", false);
    if(!stack) return;
    const holdMs = Math.max(1500, Number((opts && opts.duration_ms) || 7000));
    const keep = !!(opts && opts.require_interaction);
    const card = document.createElement("div");
    card.className = "inapp-notice";
    card.innerHTML = `<div class="inapp-notice-title">${escHtml(title || "Notification")}</div><div class="inapp-notice-body">${escHtml(body || "")}</div>`;
    stack.prepend(card);
    while(stack.children.length > 5){
      const last = stack.lastElementChild;
      if(last) last.remove();
      else break;
    }
    if(!keep){
      setTimeout(() => { try { card.remove(); } catch(_) {} }, holdMs);
    }
  }
  function intOrDefault(raw, fallback, min=0, max=1000000){
    const n = parseInt(String(raw ?? "").trim(), 10);
    const base = Number.isFinite(n) ? n : Number(fallback);
    const safe = Number.isFinite(base) ? base : min;
    return Math.max(min, Math.min(max, safe));
  }
  function setControlValueIfPristine(id, value){
    const el = byId(id, false);
    if(!el) return;
    if(el.dataset.dirty === "1") return;
    const next = String(value ?? "");
    if(String(el.value ?? "") !== next) el.value = next;
  }
  function formatCountdownMMSS(secRaw){
    const sec = Math.max(0, Math.floor(Number(secRaw) || 0));
    const mm = Math.floor(sec / 60);
    const ss = sec % 60;
    return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  }
  function updateAutoSwitchArmedUI(){
    const card = byId("autoSwitchRulesSection", false);
    const badge = byId("asPendingCountdown", false);
    const state = latestData?.autoState || {};
    const due = Number(state.pending_switch_due_at || 0);
    const delay = Math.max(1, Number(state.config_delay_sec || 0) || 1);
    const nowSec = Date.now() / 1000;
    const remaining = due - nowSec;
    const armed = Number.isFinite(due) && due > 0 && remaining > 0;
    const urgencyClasses = ["switch-urgency-green", "switch-urgency-yellow", "switch-urgency-orange", "switch-urgency-red"];
    let urgency = "switch-urgency-green";
    if(armed){
      const ratio = Math.max(0, Math.min(1, remaining / delay));
      if(remaining <= 3 || ratio <= 0.15) urgency = "switch-urgency-red";
      else if(remaining <= 8 || ratio <= 0.35) urgency = "switch-urgency-orange";
      else if(remaining <= 16 || ratio <= 0.6) urgency = "switch-urgency-yellow";
    }
    if(card){
      card.classList.toggle("auto-switch-armed", !!armed);
      card.classList.remove(...urgencyClasses);
      if(armed) card.classList.add(urgency);
    }
    if(!badge) return;
    if(armed){
      badge.classList.add("active");
      badge.classList.remove(...urgencyClasses);
      badge.classList.add(urgency);
      badge.textContent = `Switch in ${formatCountdownMMSS(remaining)}`;
    } else {
      badge.classList.remove("active");
      badge.classList.remove(...urgencyClasses);
      badge.textContent = "Switch in 00:00";
    }
  }
  function updateRankingModeUI(modeRaw, enabledRaw){
    const enabled = enabledRaw !== undefined ? !!enabledRaw : !!byId("asEnabled", false)?.checked;
    const mode = String(modeRaw || "balanced");
    const manual = mode === "manual";
    const chainPanel = byId("asChainPanel", false);
    const autoArrangeRow = byId("asAutoArrangeRow", false);
    const chainEditBtn = byId("asChainEditBtn", false);
    if(chainPanel) chainPanel.style.display = enabled ? "" : "none";
    if(autoArrangeRow) autoArrangeRow.style.display = enabled ? "" : "none";
    if(chainEditBtn){
      chainEditBtn.disabled = !enabled;
      chainEditBtn.title = enabled ? (manual ? "Edit manual chain order" : "Edit chain (switches ranking to manual)") : "Enable auto-switch first";
    }
  }
  function setConfigSavingState(active, text){
    if(saveUiHideTimer){
      clearTimeout(saveUiHideTimer);
      saveUiHideTimer = null;
    }
    const spinner = byId("saveSpinner", false);
    if(active){
      saveUiVisibleSince = Date.now();
      if(spinner) spinner.classList.add("active");
    } else {
      const elapsed = Date.now() - saveUiVisibleSince;
      const remain = Math.max(0, 220 - elapsed);
      const hideNow = () => {
        if(spinner) spinner.classList.remove("active");
      };
      if(remain > 0){
        saveUiHideTimer = setTimeout(hideNow, remain);
      } else {
        hideNow();
      }
    }
  }
  async function enqueueConfigPatch(patch){
    pendingConfigSaves += 1;
    setConfigSavingState(true, "Saving...");
    const applyPatch = async () => {
      const keys = Object.keys(patch || {});
      const payload = { ...(patch || {}) };
      if(Number.isFinite(Number(latestConfigRevision))){
        payload.base_revision = Number(latestConfigRevision);
      }
      pushOverlayLog("ui", "config.patch", { keys, base_revision: payload.base_revision || null });
      try{
        const cfg = await postApi("/api/ui-config", payload);
        latestConfigRevision = Number(cfg?._meta?.revision || latestConfigRevision || 1);
        return cfg;
      } catch(e){
        const msg = String(e?.message || "");
        if(msg.includes("Config changed elsewhere")){
          await refreshAll({ usageTimeoutSec: 2 });
          const retryPayload = { ...(patch || {}) };
          if(Number.isFinite(Number(latestConfigRevision))){
            retryPayload.base_revision = Number(latestConfigRevision);
          }
          const cfg2 = await postApi("/api/ui-config", retryPayload);
          latestConfigRevision = Number(cfg2?._meta?.revision || latestConfigRevision || 1);
          return cfg2;
        }
        throw e;
      }
    };
    const run = configSaveQueue.then(applyPatch);
    configSaveQueue = run.catch(() => {});
    try{
      return await run;
    } finally {
      pendingConfigSaves = Math.max(0, pendingConfigSaves - 1);
      if(pendingConfigSaves === 0) setConfigSavingState(false);
    }
  }
  function usageClass(v){ const n=Number(v); if(Number.isNaN(n))return ""; if(n<25)return "usage-low"; if(n<50)return "usage-midlow"; if(n<75)return "usage-mid"; return "usage-good"; }
  function usageErrorLabel(rowError){
    const msg = String(rowError || "").trim();
    if(!msg) return "";
    const lower = msg.toLowerCase();
    if(lower === "http 401") return "auth expired";
    if(lower === "http 403") return "access denied";
    if(lower.startsWith("http ")) return msg;
    if(lower.includes("timed out")) return "timeout";
    if(lower.includes("missing access_token/account_id")) return "missing auth";
    return msg;
  }
  function fmtUsagePct(usage){
    const n = Number(usage?.remaining_percent);
    if(Number.isFinite(n)) return `${Math.max(0, Math.min(100, Math.round(n)))}%`;
    return usage?.text || "-";
  }
  function usagePercentNumber(usage){
    const n = Number(usage?.remaining_percent);
    if(!Number.isFinite(n)) return null;
    return Math.max(0, Math.min(100, Math.round(n)));
  }
  function usageFillClass(n){
    if(!Number.isFinite(n)) return "good";
    if(n < 25) return "low";
    if(n < 50) return "midlow";
    if(n < 75) return "mid";
    return "good";
  }
  function usageMetricSignature(usage){
    const pct = usagePercentNumber(usage);
    const resetTs = Number(usage?.resets_at || 0);
    const text = String(usage?.text || "");
    return `${Number.isFinite(pct) ? pct : "na"}|${Number.isFinite(resetTs) ? resetTs : "na"}|${text}`;
  }
  function markUsageFlashUpdates(prevUsage, nextUsage){
    if(!prevUsage || !nextUsage) return;
    const prevRows = Array.isArray(prevUsage?.profiles) ? prevUsage.profiles : [];
    const nextRows = Array.isArray(nextUsage?.profiles) ? nextUsage.profiles : [];
    if(!prevRows.length || !nextRows.length) return;
    const until = Date.now() + 1400;
    const prevByName = {};
    for(const row of prevRows){
      const name = String(row?.name || "").trim();
      if(name) prevByName[name] = row;
    }
    for(const row of nextRows){
      const name = String(row?.name || "").trim();
      if(!name) continue;
      const prev = prevByName[name];
      if(!prev) continue;
      if(usageMetricSignature(prev.usage_5h) !== usageMetricSignature(row.usage_5h)){
        usageFlashUntil[`${name}|h5`] = until;
      }
      if(usageMetricSignature(prev.usage_weekly) !== usageMetricSignature(row.usage_weekly)){
        usageFlashUntil[`${name}|weekly`] = until;
      }
    }
  }
  function shouldFlashUsage(name, metric){
    const key = `${String(name || "").trim()}|${metric}`;
    const until = Number(usageFlashUntil[key] || 0);
    if(!Number.isFinite(until) || until <= 0) return false;
    if(until < Date.now()){
      delete usageFlashUntil[key];
      return false;
    }
    return true;
  }
  function shouldBlinkUsage(name, metric, loading){
    if(loading) return false;
    return !!usageFetchBlinkActive || shouldFlashUsage(name, metric);
  }
  function isUsageLoadingState(usage, rowError, rowLoading){
    if(!!rowLoading) return true;
    const pct = usagePercentNumber(usage);
    if(!rowError) return false;
    const msg = String(rowError || "").toLowerCase();
    let transient = msg.includes("request failed") || msg.includes("timed out");
    if(!transient && msg.startsWith("http ")){
      const code = parseInt(msg.slice(5).trim(), 10);
      if(Number.isFinite(code)){
        // Treat only retryable HTTP statuses as loading placeholders.
        transient = (code >= 500) || code === 408 || code === 429;
      }
    }
    if(!transient) return false;
    if(!Number.isFinite(pct)) return true;
    const resetTs = Number(usage?.resets_at || 0);
    return !(Number.isFinite(resetTs) && resetTs > 0);
  }
  function renderUsageMeter(usage, loading=false, flash=false){
    if(loading){
      return `<div class="usage-cell usage-cell-loading"><span class="usage-pct loading-text">loading...</span><div class="usage-meter loading"><span class="usage-fill shimmer"></span></div></div>`;
    }
    const pct = usagePercentNumber(usage);
    if(!Number.isFinite(pct)){
      return "<span>-</span>";
    }
    const tone = usageFillClass(pct);
    const txtClass = usageClass(pct);
    return `<div class="usage-cell ${flash ? "updated" : ""}"><span class="usage-pct ${txtClass}">${pct}%</span><div class="usage-meter"><span class="usage-fill ${tone} ${flash ? "blink" : ""}" style="width:${pct}%"></span></div></div>`;
  }
  function renderUsageErrorCell(rowError){
    const label = usageErrorLabel(rowError) || "error";
    return `<div class="usage-cell"><span class="usage-pct usage-low">${escHtml(label)}</span><div class="usage-meter"><span class="usage-fill low" style="width:100%"></span></div></div>`;
  }
  function fmtReset(ts){ if(!ts) return "unknown"; try { const d = new Date(Number(ts)*1000); return Number.isFinite(d.getTime()) ? d.toLocaleString() : "unknown"; } catch(_) { return "unknown"; } }
  function fmtSavedAt(ts){ if(!ts) return "-"; try { const d = new Date(ts); return Number.isFinite(d.getTime()) ? d.toLocaleString() : ts; } catch(_) { return ts; } }
  function formatPctValue(v){
    const n = Number(v);
    return Number.isFinite(n) ? `${Math.max(0, Math.min(100, Math.round(n)))}%` : "-";
  }
  function renderChainPreview(payload){
    const el = byId("asChainPreview", false);
    if(!el) return;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    if(!items.length){
      el.textContent = payload?.chain_text || "-";
      return;
    }
    const parts = [];
    for(let i=0;i<items.length;i++){
      const it = items[i] || {};
      const h5 = Number(it.remaining_5h);
      const w = Number(it.remaining_weekly);
      const h5Class = usageClass(h5);
      const wClass = usageClass(w);
      parts.push(
        `<span class="chain-node"><span class="chain-name">${escHtml(String(it.name || "-"))}</span><span class="chain-metric ${h5Class}">5H ${formatPctValue(h5)}</span><span class="chain-metric ${wClass}">W ${formatPctValue(w)}</span></span>`
      );
      if(i < items.length - 1) parts.push(`<span class="chain-arrow">-></span>`);
    }
    el.innerHTML = parts.join("");
  }
  function getChainEditSourceNames(){
    const payload = latestData.autoChain || {};
    const chain = Array.isArray(payload.chain) ? payload.chain : [];
    const manual = Array.isArray(payload.manual_chain) ? payload.manual_chain : [];
    const names = [];
    const seen = new Set();
    const pushName = (value) => {
      const n = String(value || "").trim();
      if(!n || seen.has(n)) return;
      seen.add(n);
      names.push(n);
    };
    chain.forEach(pushName);
    manual.forEach(pushName);
    return names;
  }
  function getActiveChainName(){
    const chain = Array.isArray(latestData?.autoChain?.chain) ? latestData.autoChain.chain : [];
    const first = String(chain[0] || "").trim();
    if(first) return first;
    const fallback = String(latestData?.usage?.current_profile || "").trim();
    return fallback || "";
  }
  function closeChainEditModal(){
    const b = byId("chainEditBackdrop", false);
    if(b) b.style.display = "none";
    chainEditNames = [];
    chainEditLockedName = "";
  }
  function ensureLockedChainOrder(list){
    const names = Array.isArray(list) ? list.map((x)=>String(x||"").trim()).filter(Boolean) : [];
    if(!chainEditLockedName) return names;
    const rest = names.filter((n)=>n!==chainEditLockedName);
    return [chainEditLockedName, ...rest];
  }
  function getChainMetricsByName(name){
    const n = String(name || "").trim();
    if(!n) return { h5: null, w: null };
    const items = Array.isArray(latestData?.autoChain?.items) ? latestData.autoChain.items : [];
    for(const it of items){
      if(String(it?.name || "").trim() === n){
        const h5 = Number(it?.remaining_5h);
        const w = Number(it?.remaining_weekly);
        return {
          h5: Number.isFinite(h5) ? h5 : null,
          w: Number.isFinite(w) ? w : null,
        };
      }
    }
    const rows = Array.isArray(latestData?.usage?.profiles) ? latestData.usage.profiles : [];
    for(const row of rows){
      if(String(row?.name || "").trim() === n){
        const h5 = Number(row?.usage_5h?.remaining_percent);
        const w = Number(row?.usage_weekly?.remaining_percent);
        return {
          h5: Number.isFinite(h5) ? h5 : null,
          w: Number.isFinite(w) ? w : null,
        };
      }
    }
    return { h5: null, w: null };
  }
  function renderChainEditModal(){
    const list = byId("chainEditList", false);
    if(!list) return;
    list.innerHTML = "";
    if(!chainEditNames.length){
      list.innerHTML = `<div class="chain-edit-empty">No profiles available.</div>`;
      return;
    }
    chainEditNames.forEach((name, index) => {
      const row = document.createElement("div");
      const isLocked = !!chainEditLockedName && name === chainEditLockedName;
      const metrics = getChainMetricsByName(name);
      const h5Class = usageClass(metrics.h5);
      const wClass = usageClass(metrics.w);
      const h5Text = formatPctValue(metrics.h5);
      const wText = formatPctValue(metrics.w);
      row.className = `chain-edit-item ${isLocked ? "locked" : ""}`;
      row.draggable = !isLocked;
      row.dataset.index = String(index);
      row.innerHTML = `<div class="chain-edit-main"><div class="name">${escHtml(name)}</div><div class="meta">${isLocked ? "Active account (fixed)" : `Position ${index + 1}`}</div><div class="chain-edit-metrics"><span class="chain-edit-metric ${h5Class}">5H ${h5Text}</span><span class="chain-edit-metric ${wClass}">W ${wText}</span></div></div><div class="chain-edit-handle">${isLocked ? "Locked" : "Drag"}</div>`;
      row.addEventListener("dragstart", (ev) => {
        if(isLocked){
          ev.preventDefault();
          return;
        }
        if(ev.dataTransfer){
          ev.dataTransfer.setData("text/plain", String(index));
          ev.dataTransfer.effectAllowed = "move";
        }
        row.classList.add("dragging");
      });
      row.addEventListener("dragend", () => row.classList.remove("dragging"));
      row.addEventListener("dragover", (ev) => {
        ev.preventDefault();
        if(ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
      });
      row.addEventListener("drop", (ev) => {
        ev.preventDefault();
        const from = Number(ev.dataTransfer?.getData("text/plain"));
        const to = Number(row.dataset.index);
        if(!Number.isInteger(from) || !Number.isInteger(to) || from === to) return;
        if(from === 0 || to === 0) return;
        const next = [...chainEditNames];
        const [moved] = next.splice(from, 1);
        next.splice(to, 0, moved);
        chainEditNames = ensureLockedChainOrder(next);
        renderChainEditModal();
      });
      list.appendChild(row);
      if(index < chainEditNames.length - 1){
        const arrow = document.createElement("div");
        arrow.className = "chain-edit-arrow";
        arrow.textContent = "↓";
        list.appendChild(arrow);
      }
    });
  }
  function openChainEditModal(){
    chainEditNames = getChainEditSourceNames();
    chainEditLockedName = getActiveChainName();
    chainEditNames = ensureLockedChainOrder(chainEditNames);
    renderChainEditModal();
    const b = byId("chainEditBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function fmtRemain(ts, withSeconds=false, loading=false){
    if(!ts) return loading ? "loading..." : "unknown";
    try {
      let sec = Math.max(0, Math.floor(Number(ts) - (Date.now()/1000)));
      const d = Math.floor(sec / 86400); sec %= 86400;
      const h = Math.floor(sec / 3600); sec %= 3600;
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      if(!withSeconds){
        if (d > 0) return `${d}d ${h}h ${m}m`;
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
      }
      if (d > 0) return `${d}d ${h}h ${m}m ${s}s`;
      if (h > 0) return `${h}h ${m}m ${s}s`;
      return `${m}m ${s}s`;
    } catch(_) { return loading ? "loading..." : "unknown"; }
  }
  function formatRemainCell(ts, withSeconds, loading, rowError){
    if(loading) return fmtRemain(ts, withSeconds, true);
    const label = usageErrorLabel(rowError);
    if(label) return label;
    return fmtRemain(ts, withSeconds, false);
  }
  function refreshRemainCountdowns(){
    document.querySelectorAll("td[data-remain-ts]").forEach((el) => {
      const raw = el.getAttribute("data-remain-ts");
      const ts = Number(raw);
      const withSeconds = el.getAttribute("data-remain-seconds") === "1";
      const loading = el.getAttribute("data-remain-loading") === "1";
      el.textContent = Number.isFinite(ts) && ts > 0 ? fmtRemain(ts, withSeconds, false) : (loading ? "loading..." : "unknown");
      el.classList.toggle("loading-text", loading && !(Number.isFinite(ts) && ts > 0));
    });
    updateAutoSwitchArmedUI();
  }
  function themeFromPref(sel){ if(sel==="dark") return "dark"; if(sel==="light") return "light"; return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
  function applyTheme(pref){ document.documentElement.setAttribute("data-theme", themeFromPref(pref || "auto")); }
  function applySettingsSectionVisibility(hidden){
    document.querySelectorAll("[data-settings-section='1']").forEach((section) => {
      section.style.display = hidden ? "none" : "";
    });
    const btn = byId("settingsToggleBtn", false);
    if(btn){
      btn.setAttribute("aria-pressed", hidden ? "true" : "false");
      btn.classList.toggle("active", !hidden);
      btn.title = hidden ? "Show settings" : "Hide settings";
    }
  }
  function updateHeaderThemeIcon(themeValue){
    const btn = byId("themeIconBtn", false);
    if(!btn) return;
    const mode = themeValue || "auto";
    btn.classList.toggle("active", mode !== "auto");
    btn.title = `Theme: ${mode}`;
  }
  function updateHeaderDebugIcon(enabled){
    const btn = byId("debugIconBtn", false);
    if(!btn) return;
    btn.classList.toggle("active", !!enabled);
    btn.title = enabled ? "Debug mode: ON" : "Debug mode: OFF";
  }
  function shouldTraceRequest(path, method){
    const m = String(method || "GET").toUpperCase();
    if(m !== "GET") return true;
    return !POLL_PATHS.has(String(path || ""));
  }
  function getMergedLogs(limit=1200){
    const merged = [...baseLogs, ...overlayLogs].map((r) => ({
      ts: r.ts || new Date().toISOString(),
      last_ts: r.last_ts || null,
      repeat_count: Number(r.repeat_count || 1),
      level: String(r.level || "info").toLowerCase(),
      message: String(r.message || ""),
      details: r.details || null,
    }));
    if(limit > 0 && merged.length > limit) return merged.slice(-limit);
    return merged;
  }
  function safeJsonStringify(value){
    try { return JSON.stringify(value); } catch(_) { return String(value); }
  }
  function truncateText(s, maxLen=LOG_STRING_LIMIT){
    const str = String(s ?? "");
    if(str.length <= maxLen) return str;
    return `${str.slice(0, maxLen)}… [truncated ${str.length - maxLen} chars]`;
  }
  function sanitizeLogDetails(value, depth=0){
    if(value === null || value === undefined) return value;
    if(typeof value === "string") return truncateText(value);
    if(typeof value === "number" || typeof value === "boolean") return value;
    if(depth > 3) return "[depth-limit]";
    if(Array.isArray(value)){
      return value.slice(0, 20).map((v) => sanitizeLogDetails(v, depth + 1));
    }
    if(typeof value === "object"){
      const out = {};
      let count = 0;
      for(const [k, v] of Object.entries(value)){
        if(count >= 24){ out.__truncated__ = "object keys truncated"; break; }
        out[k] = sanitizeLogDetails(v, depth + 1);
        count += 1;
      }
      return out;
    }
    return truncateText(String(value));
  }
  function compactDetailString(details){
    const raw = safeJsonStringify(details || {});
    return raw.length > LOG_DETAIL_LIMIT ? `${raw.slice(0, LOG_DETAIL_LIMIT)}… [truncated ${raw.length - LOG_DETAIL_LIMIT} chars]` : raw;
  }
  function installDiagnosticsHooks(){
    if(diagnosticsHooksInstalled) return;
    diagnosticsHooksInstalled = true;
    window.addEventListener("error", (ev) => {
      const err = ev?.error;
      pushOverlayLog("error", "window.error", {
        message: err?.message || ev?.message || "unknown error",
        source: ev?.filename || null,
        line: ev?.lineno || null,
        column: ev?.colno || null,
        stack: err?.stack || null,
      });
    });
    window.addEventListener("unhandledrejection", (ev) => {
      const reason = ev?.reason;
      pushOverlayLog("error", "window.unhandledrejection", {
        reason: reason?.message || String(reason || "unknown rejection"),
        stack: reason?.stack || null,
      });
    });
  }

  async function callApi(path, options={}){
    const method = String(options?.method || "GET").toUpperCase();
    const startedAt = Date.now();
    const shouldTrace = shouldTraceRequest(path, method);
    const timeoutMsRaw = Number(options?.timeoutMs || 0);
    const timeoutMs = Number.isFinite(timeoutMsRaw) ? Math.max(0, Math.floor(timeoutMsRaw)) : 0;
    if(shouldTrace) pushOverlayLog("ui", `api.request ${method} ${path}`);
    let res;
    let timeoutHandle = null;
    let timeoutController = null;
    const fetchOptions = { ...options };
    delete fetchOptions.timeoutMs;
    if(timeoutMs > 0){
      timeoutController = new AbortController();
      const callerSignal = options?.signal || null;
      if(callerSignal){
        if(callerSignal.aborted){
          timeoutController.abort();
        } else {
          callerSignal.addEventListener("abort", () => timeoutController && timeoutController.abort(), { once: true });
        }
      }
      fetchOptions.signal = timeoutController.signal;
      timeoutHandle = setTimeout(() => {
        try { timeoutController && timeoutController.abort(); } catch(_) {}
      }, timeoutMs);
    }
    try {
      res = await fetch(path, fetchOptions);
    } catch(e){
      if(timeoutHandle) clearTimeout(timeoutHandle);
      if(e && e.name === "AbortError"){
        if(timeoutMs > 0){
          throw new Error(`timeout after ${Math.round(timeoutMs/1000)}s`);
        }
        throw e;
      }
      pushOverlayLog("error", `api.network ${method} ${path}`, {
        error: e?.message || String(e),
        duration_ms: Date.now() - startedAt,
      });
      throw e;
    }
    if(timeoutHandle) clearTimeout(timeoutHandle);
    const body = await res.json().catch(() => ({ok:false,error:{message:"bad json"}}));
    if(!res.ok || !body.ok){
      const code = body?.error?.code || "";
      const type = body?.error?.type || "";
      const msg = body?.error?.message || "request failed";
      pushOverlayLog("error", `api.error ${method} ${path}`, {
        status: res.status,
        code: code || null,
        type: type || null,
        message: msg,
        duration_ms: Date.now() - startedAt,
      });
      if(code === "STALE_CONFIG"){
        throw new Error("Config changed elsewhere. Refreshing and retrying...");
      }
      if(code === "FORBIDDEN" && /invalid session token/i.test(msg)){
        setError("Session expired after service restart. Reloading panel...");
        setTimeout(() => { try { window.location.href = "/?r="+Date.now(); } catch(_) {} }, 350);
      }
      throw new Error(msg);
    }
    if(shouldTrace){
      pushOverlayLog("ui", `api.response ${method} ${path}`, {
        status: res.status,
        request_id: body?.meta?.request_id || null,
        duration_ms: Date.now() - startedAt,
      });
    }
    return body.data;
  }
  async function postApi(path, payload={}, options={}){
    return callApi(path, {
      ...options,
      method:"POST",
      headers:{"Content-Type":"application/json","X-Codex-Token":token, ...(options?.headers || {})},
      body: JSON.stringify(payload),
    });
  }
  async function safeGet(path, options={}){
    try { return await callApi(path, options); }
    catch(e){
      if(e && e.name === "AbortError") return { __aborted: true, __error: "request aborted" };
      return {__error:e.message};
    }
  }

  function escHtml(s){
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }
  function escAttr(s){
    return escHtml(s).replaceAll('"', "&quot;");
  }
  function normalizeReleaseTag(raw){
    let s = String(raw || "").trim().toLowerCase();
    if(s.startsWith("release ")) s = s.slice("release ".length);
    if(s.startsWith("v")) s = s.slice(1);
    return s.replace(/[^0-9a-z.+_-]/g, "");
  }
  function isCurrentReleaseTag(raw){
    const a = normalizeReleaseTag(raw);
    const b = normalizeReleaseTag(UI_VERSION);
    return !!a && !!b && a === b;
  }
  function formatReleaseAge(iso){
    const t = Date.parse(String(iso || ""));
    if(!Number.isFinite(t)) return "Unknown date";
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if(sec < 60) return `${sec}s ago`;
    if(sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if(sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    if(sec < 86400 * 30) return `${Math.floor(sec / 86400)}d ago`;
    return new Date(t).toLocaleDateString();
  }
  function setGuideReleaseStatus(text, state){
    const el = byId("guideReleaseStatus", false);
    if(!el) return;
    el.textContent = String(text || "");
    el.classList.remove("synced", "fallback", "failed");
    if(state && (state === "synced" || state === "fallback" || state === "failed")){
      el.classList.add(state);
    }
  }
  function renderGuideReleaseNotes(payload){
    const list = byId("guideReleaseList", false);
    if(!list) return;
    const releases = Array.isArray(payload?.releases) ? payload.releases : [];
    if(!releases.length){
      list.innerHTML = `<div class="guide-release-empty">No release entries available.</div>`;
      return;
    }
    const html = releases.map((r) => {
      const tag = String(r?.tag || r?.version || "-");
      const pre = !!r?.is_prerelease;
      const current = !!r?.is_current || isCurrentReleaseTag(tag);
      const highlights = Array.isArray(r?.highlights) ? r.highlights.filter(Boolean).slice(0, 4) : [];
      const link = String(r?.url || "").trim();
      const meta = r?.published_at ? formatReleaseAge(r.published_at) : "Local entry";
      const badges = [
        pre ? `<span class="guide-release-badge prerelease">Pre-release</span>` : "",
        current ? `<span class="guide-release-badge current">Current</span>` : "",
      ].filter(Boolean).join("");
      const highlightHtml = highlights.length
        ? `<ul class="guide-release-highlights">${highlights.map((h) => `<li>${escHtml(h)}</li>`).join("")}</ul>`
        : "";
      const linkHtml = link ? `<a class="guide-release-link" href="${escAttr(link)}" target="_blank" rel="noopener noreferrer">Open on GitHub</a>` : "";
      return `
        <article class="guide-release-item ${current ? "current" : ""}">
          <div class="guide-release-row">
            <span class="guide-release-tag">${escHtml(tag)}</span>
            ${badges}
          </div>
          <div class="guide-release-meta">${escHtml(meta)}</div>
          ${highlightHtml}
          ${linkHtml}
        </article>
      `;
    }).join("");
    list.innerHTML = html;
  }
  async function loadGuideReleaseNotes(force=false){
    if(guideReleaseLoading) return;
    guideReleaseLoading = true;
    setGuideReleaseStatus("Loading release notes...", "");
    try{
      const path = force ? "/api/release-notes?force=true" : "/api/release-notes";
      const payload = await safeGet(path);
      if(payload.__error){
        guideReleaseLastPayload = null;
        setGuideReleaseStatus("Failed to load release notes", "failed");
        const list = byId("guideReleaseList", false);
        if(list){
          list.innerHTML = `<div class="guide-release-empty">${escHtml(payload.__error)}</div>`;
        }
        return;
      }
      guideReleaseLoaded = true;
      guideReleaseLastPayload = payload;
      const statusText = payload?.status_text || "Release notes";
      const status = String(payload?.status || "");
      setGuideReleaseStatus(statusText, status);
      renderGuideReleaseNotes(payload);
    } finally {
      guideReleaseLoading = false;
    }
  }
  function renderUpdateReleaseModal(state){
    const intro = byId("appUpdateIntro", false);
    const releaseEl = byId("appUpdateRelease", false);
    const outputEl = byId("appUpdateOutput", false);
    const confirmBtn = byId("appUpdateConfirmBtn", false);
    const cancelBtn = byId("appUpdateCancelBtn", false);
    const progressEl = byId("appUpdateProgress", false);
    const progressBar = byId("appUpdateProgressBar", false);
    const progressValueEl = byId("appUpdateProgressValue", false);
    const progressLabelEl = byId("appUpdateProgressLabel", false);
    const progressNoteEl = byId("appUpdateProgressNote", false);
    const release = state?.latest_release || null;
    const latestVersion = String(state?.latest_version || "");
    if(outputEl){
      const text = appUpdateOutputLines.join("\\n");
      outputEl.style.display = text ? "block" : "none";
      outputEl.textContent = text;
    }
    if(intro){
      intro.textContent = latestVersion
        ? `Review the ${latestVersion} release notes before upgrading this app with pipx.`
        : "Review the latest release notes before upgrading this app.";
    }
    if(progressEl){
      progressEl.classList.toggle("active", !!appUpdateInFlight || appUpdateProgressValue > 0);
    }
    if(progressBar){
      progressBar.style.width = `${Math.max(0, Math.min(100, Math.round(appUpdateProgressValue || 0)))}%`;
    }
    if(progressValueEl){
      progressValueEl.textContent = `${Math.max(0, Math.min(100, Math.round(appUpdateProgressValue || 0)))}%`;
    }
    if(progressLabelEl){
      progressLabelEl.textContent = appUpdateProgressLabel || (appUpdateInFlight ? "Updating..." : "Ready to update");
    }
    if(progressNoteEl){
      progressNoteEl.textContent = appUpdateProgressNote || "The update can continue in the background if you close this dialog.";
    }
    if(confirmBtn){
      confirmBtn.disabled = !state?.update_available || appUpdateInFlight;
      confirmBtn.textContent = appUpdateInFlight ? "Updating..." : "Update Now";
      confirmBtn.classList.toggle("btn-progress", !!appUpdateInFlight);
    }
    if(cancelBtn){
      cancelBtn.textContent = appUpdateInFlight ? "Close" : "Cancel";
      cancelBtn.title = appUpdateInFlight
        ? "Close this dialog while the update continues in the background."
        : "Close this update review without running the pipx upgrade.";
    }
    if(!releaseEl) return;
    if(!release){
      releaseEl.innerHTML = `<div class="update-modal-card"><div class="update-modal-body">Release notes are unavailable right now. You can still continue with the pipx upgrade if you want.</div></div>`;
      return;
    }
    const highlights = Array.isArray(release?.highlights) ? release.highlights.filter(Boolean) : [];
    const body = String(release?.body || "").trim();
    const link = String(release?.url || "").trim();
    const dateText = release?.published_at ? formatReleaseAge(release.published_at) : "Release date unavailable";
    const highlightHtml = highlights.length
      ? `<ul class="update-modal-highlights">${highlights.map((item) => `<li>${escHtml(item)}</li>`).join("")}</ul>`
      : "";
    const bodyHtml = body ? `<p class="update-modal-body">${escHtml(body)}</p>` : `<p class="update-modal-body">No release notes body was provided for this release.</p>`;
    const linkHtml = link ? `<a class="update-modal-link" href="${escAttr(link)}" target="_blank" rel="noopener noreferrer">Open on GitHub</a>` : "";
    releaseEl.innerHTML = `
      <div class="update-modal-card">
        <div class="update-modal-meta">
          <span class="update-modal-tag">${escHtml(String(release?.tag || release?.version || latestVersion || "Latest release"))}</span>
          <span class="update-modal-date">${escHtml(dateText)}</span>
        </div>
        <div class="update-modal-title">${escHtml(String(release?.title || release?.tag || latestVersion || "Latest release"))}</div>
        ${highlightHtml}
        ${bodyHtml}
        ${linkHtml}
      </div>
    `;
  }
  function openUpdateModal(){
    renderUpdateReleaseModal(appUpdateState || {});
    const b = byId("appUpdateBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function closeUpdateModal(){
    const b = byId("appUpdateBackdrop", false);
    if(b) b.style.display = "none";
    if(appUpdateInFlight){
      showInAppNotice("Update Running", "The update is still running in the background. The panel will restart when it finishes.", { duration_ms: 7000 });
    }
  }
  function setAppUpdateProgress(value, label="", note=""){
    appUpdateProgressValue = Math.max(0, Math.min(100, Number(value) || 0));
    if(label) appUpdateProgressLabel = String(label);
    if(note !== undefined && note !== null && String(note) !== "") appUpdateProgressNote = String(note);
    renderUpdateReleaseModal(appUpdateState || {});
  }
  function resetAppUpdateProgress(){
    if(appUpdateProgressTimer){
      clearInterval(appUpdateProgressTimer);
      appUpdateProgressTimer = null;
    }
    appUpdateProgressValue = 0;
    appUpdateProgressLabel = "";
    appUpdateProgressNote = "";
  }
  function startAppUpdateProgress(){
    resetAppUpdateProgress();
    setAppUpdateProgress(8, "Preparing update request...", "Starting the local updater command.");
    appUpdateProgressTimer = setInterval(() => {
      if(!appUpdateInFlight) return;
      const next = appUpdateProgressValue < 28 ? appUpdateProgressValue + 5
        : appUpdateProgressValue < 58 ? appUpdateProgressValue + 3
        : appUpdateProgressValue < 86 ? appUpdateProgressValue + 1.5
        : appUpdateProgressValue;
      if(next !== appUpdateProgressValue){
        appUpdateProgressValue = Math.min(90, next);
        renderUpdateReleaseModal(appUpdateState || {});
      }
    }, 850);
  }
  function pushAppUpdateOutput(line){
    const text = String(line || "").trim();
    if(!text) return;
    appUpdateOutputLines.push(text);
    if(appUpdateOutputLines.length > 14){
      appUpdateOutputLines = appUpdateOutputLines.slice(-14);
    }
    renderUpdateReleaseModal(appUpdateState || {});
  }
  function summarizeUpdateOutput(raw){
    return String(raw || "")
      .split(/\\r?\\n/)
      .map((line) => String(line || "").trim())
      .filter(Boolean)
      .filter((line) => /Processing |Preparing metadata|Building wheel|Created wheel|Installing collected packages|Attempting uninstall|Successfully uninstalled|Successfully installed|error[: ]/i.test(line))
      .slice(0, 8);
  }
  function applyAppUpdateStatus(state){
    appUpdateState = state && typeof state === "object" ? state : {};
    const badge = byId("appUpdateBadge", false);
    const btn = byId("appUpdateBtn", false);
    const latestVersion = String(appUpdateState?.latest_version || "").trim();
    const updateAvailable = !!appUpdateState?.update_available;
    if(badge){
      badge.textContent = latestVersion ? `Update available: ${latestVersion}` : "Update available";
      badge.classList.toggle("active", updateAvailable);
    }
    if(btn){
      btn.style.display = updateAvailable ? "" : "none";
      btn.disabled = !updateAvailable || appUpdateInFlight;
      btn.textContent = appUpdateInFlight ? "Updating..." : "Update";
      btn.classList.toggle("btn-progress", !!appUpdateInFlight);
    }
  }
  async function loadAppUpdateStatus(force=false){
    const path = force ? "/api/app-update-status?force=true" : "/api/app-update-status";
    const payload = await safeGet(path);
    if(payload.__error){
      pushOverlayLog("warn", "app_update.status_failed", { error: payload.__error });
      applyAppUpdateStatus({
        ...(appUpdateState || {}),
        status: "failed",
        error: payload.__error,
        update_available: false,
      });
      return;
    }
    applyAppUpdateStatus(payload);
  }
  async function runAppUpdateFlow(){
    if(appUpdateInFlight) return;
    appUpdateInFlight = true;
    appUpdateRequestController = new AbortController();
    appUpdateOutputLines = [];
    startAppUpdateProgress();
    pushAppUpdateOutput("[1/4] Opening updater...");
    applyAppUpdateStatus(appUpdateState || {});
    renderUpdateReleaseModal(appUpdateState || {});
    setError("");
    try{
      setAppUpdateProgress(18, "Sending update command...", "Request accepted. Waiting for the upgrader to finish.");
      pushAppUpdateOutput("[2/4] Running pipx upgrade...");
      const data = await postApi("/api/system/update", {}, { signal: appUpdateRequestController.signal, timeoutMs: 180000 });
      setAppUpdateProgress(78, "Applying updated package...", "The updater command finished. Preparing UI restart.");
      pushAppUpdateOutput("[3/4] Upgrade command finished.");
      const output = [String(data?.stdout || "").trim(), String(data?.stderr || "").trim()].filter(Boolean).join("\\n\\n");
      summarizeUpdateOutput(output).forEach((line) => pushAppUpdateOutput(`  ${line}`));
      if(!data?.updated){
        throw new Error(String(data?.stderr || data?.error || "Update failed."));
      }
      setAppUpdateProgress(92, "Restarting web panel...", "Reloading the UI service so the new version is active.");
      pushAppUpdateOutput("[4/4] Restarting UI service...");
      showInAppNotice("Update Complete", "App updated successfully. Restarting the UI service now.", { duration_ms: 9000 });
      closeUpdateModal();
      await restartUiService();
      setAppUpdateProgress(100, "Update complete", "The app finished upgrading successfully.");
    } catch(e){
      if(e && e.name === "AbortError"){
        pushAppUpdateOutput("Update request was cancelled in this dialog.");
        setAppUpdateProgress(appUpdateProgressValue || 20, "Update request cancelled", "If the updater had already started, it may continue in the background.");
        return;
      }
      const msg = e?.message || String(e);
      setError(msg);
      pushAppUpdateOutput(`Update failed: ${msg}`);
      setAppUpdateProgress(appUpdateProgressValue || 20, "Update failed", "The updater returned an error. Review the details below.");
      pushOverlayLog("error", "app_update.failed", { error: msg });
    } finally {
      appUpdateInFlight = false;
      appUpdateRequestController = null;
      if(appUpdateProgressTimer){
        clearInterval(appUpdateProgressTimer);
        appUpdateProgressTimer = null;
      }
      applyAppUpdateStatus(appUpdateState || {});
      renderUpdateReleaseModal(appUpdateState || {});
    }
  }
  async function copyText(text){
    const value = String(text || "");
    if(!value) return false;
    try {
      if(navigator.clipboard && window.isSecureContext){
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch(_) {}
    try {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      ta.style.pointerEvents = "none";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return !!ok;
    } catch(_) {
      return false;
    }
  }
  function pushOverlayLog(level, message, details){
    const nowIso = new Date().toISOString();
    const nowMs = Date.now();
    const normalizedLevel = String(level || "info").toLowerCase();
    const normalizedMessage = String(message || "");
    const normalizedDetails = sanitizeLogDetails(details || null);
    const sig = `${normalizedLevel}|${normalizedMessage}|${safeJsonStringify(normalizedDetails)}`;
    const last = overlayLogs.length ? overlayLogs[overlayLogs.length - 1] : null;
    if(last && last._sig === sig){
      const lastMs = Number(last._last_ts_ms || 0);
      if(nowMs - lastMs <= LOG_COALESCE_WINDOW_MS){
        last.repeat_count = Number(last.repeat_count || 1) + 1;
        last._last_ts_ms = nowMs;
        last.last_ts = nowIso;
        renderSystemOut();
        return;
      }
    }
    overlayLogs.push({
      ts: nowIso,
      last_ts: nowIso,
      _last_ts_ms: nowMs,
      _sig: sig,
      repeat_count: 1,
      level: normalizedLevel,
      message: normalizedMessage,
      details: normalizedDetails,
    });
    if(overlayLogs.length > MAX_OVERLAY_LOGS) overlayLogs = overlayLogs.slice(-MAX_OVERLAY_LOGS);
    renderSystemOut();
  }
  function lineLevelClass(level){
    const lv = String(level || "").toLowerCase();
    if(lv.includes("error")) return "log-error";
    if(lv.includes("ui")) return "log-info";
    if(lv.includes("warn")) return "log-warn";
    if(lv.includes("event")) return "log-event";
    if(lv.includes("command")) return "log-command";
    return "log-info";
  }
  function renderSystemOut(){
    const box = byId("debugOut", false);
    if(!box) return;
    const merged = [...baseLogs, ...overlayLogs];
    if(!merged.length){ box.innerHTML = "<span class='log-line log-info'>No logs yet.</span>"; return; }
    const html = merged.map((r) => {
      const ts = escHtml(r.ts || "-");
      const levelRaw = String(r.level || "info").toUpperCase();
      const level = escHtml(levelRaw);
      const repeat = Number(r.repeat_count || 1);
      const msg = escHtml(r.message || "");
      const cls = lineLevelClass(r.level);
      let detailHtml = "";
      if(r.details && Object.keys(r.details || {}).length){
        detailHtml = `<span class="log-detail">${escHtml(compactDetailString(r.details))}</span>`;
      }
      const repeatBadge = repeat > 1 ? ` <span class="log-level">×${repeat}</span>` : "";
      return `<span class="log-line ${cls}"><span class="log-ts">[${ts}]</span> <span class="log-level">${level}</span>${msg}${repeatBadge}</span>${detailHtml}`;
    }).join("");
    box.innerHTML = html;
    box.scrollTop = box.scrollHeight;
  }
  function setCmdOut(title,data){
    if(!data) return;
    const msg = `action=${title} exit=${data.exit_code ?? "-"}`;
    pushOverlayLog("command", msg, {
      stdout: (data.stdout || "").trim(),
      stderr: (data.stderr || "").trim(),
    });
  }
  async function runAction(title,fn,refreshOpts=null){
    setError("");
    const startedAt = Date.now();
    pushOverlayLog("ui", `action.start ${title}`);
    try{
      const d = await fn();
      setCmdOut(title,d);
      pushOverlayLog("ui", `action.success ${title}`, { duration_ms: Date.now() - startedAt });
      if(!(refreshOpts && refreshOpts.skipRefresh)){
        await refreshAll(refreshOpts || undefined);
      }
      return true;
    } catch(e){
      const msg = e?.message || String(e);
      pushOverlayLog("error", `action.fail ${title}`, { error: msg, duration_ms: Date.now() - startedAt });
      setError(msg);
      return false;
    }
  }
  function exportDebugSnapshot(){
    pushOverlayLog("ui", "ui.click export_snapshot");
    const payload={
      exported_at:new Date().toISOString(),
      version:UI_VERSION,
      status:latestData.status,
      usage:latestData.usage,
      profiles:latestData.list,
      config:latestData.config,
      auto_state:latestData.autoState,
      events:latestData.events.slice(-200),
      logs:getMergedLogs(2000),
      client:{
        user_agent:navigator.userAgent,
        language:navigator.language,
        platform:navigator.platform,
        timezone:(Intl.DateTimeFormat().resolvedOptions().timeZone || null),
        viewport:{ width: window.innerWidth, height: window.innerHeight },
      },
    };
    const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});
    const a=document.createElement("a");
    a.href=URL.createObjectURL(blob);
    a.download="codex-account-snapshot-"+Date.now()+".json";
    document.body.appendChild(a);
    a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href); a.remove();},200);
  }

  function rowKey(row,key){
    switch(key){
      case "current": return row.is_current ? 1 : 0;
      case "name": return (row.name||"").toLowerCase();
      case "email": return (row.email||"").toLowerCase();
      case "planType": return (row.plan_type||"").toLowerCase();
      case "isPaid": {
        if(row.is_paid === true) return 2;
        if(row.is_paid === false) return 1;
        return 0;
      }
      case "id": return (row.account_id||"").toLowerCase();
      case "usage5": return Number(row.usage_5h?.remaining_percent ?? -1);
      case "usage5remain": {
        const ts = Number(row.usage_5h?.resets_at ?? 0);
        return ts ? Math.max(0, ts - (Date.now()/1000)) : 0;
      }
      case "usageW": return Number(row.usage_weekly?.remaining_percent ?? -1);
      case "usageWremain": {
        const ts = Number(row.usage_weekly?.resets_at ?? 0);
        return ts ? Math.max(0, ts - (Date.now()/1000)) : 0;
      }
      case "usage5reset": return Number(row.usage_5h?.resets_at ?? 0);
      case "usageWreset": return Number(row.usage_weekly?.resets_at ?? 0);
      case "savedAt": return row.saved_at_ts || 0;
      case "note": return row.same_principal ? 1 : 0;
      default: return 0;
    }
  }

  function fmtPaid(v){
    if(v === true) return "yes";
    if(v === false) return "no";
    return "-";
  }

  function applySort(rows){
    const key=sortState.key||"savedAt"; const dir=sortState.dir==="asc"?1:-1;
    const withIdx=rows.map((r,i)=>({r,i})); const current=withIdx.filter(x=>x.r.is_current); const others=withIdx.filter(x=>!x.r.is_current);
    others.sort((aObj,bObj)=>{ const a=aObj.r,b=bObj.r; const av=rowKey(a,key), bv=rowKey(b,key);
      if(typeof av==="string" || typeof bv==="string"){ const cmp=String(av).localeCompare(String(bv))*dir; if(cmp!==0) return cmp; return aObj.i-bObj.i; }
      const cmp=((av>bv)-(av<bv))*dir; if(cmp!==0) return cmp; return aObj.i-bObj.i;
    });
    return [...current.map(x=>x.r), ...others.map(x=>x.r)];
  }
  function waitMs(ms){
    return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
  }
  async function animateSwitchRowToTop(name, fromRect=null){
    const tbody = byId("rows", false);
    if(!tbody) return;
    const source = tbody.querySelector(`tr[data-row-name="${CSS.escape(String(name || ""))}"]`);
    if(!source) return;
    if(fromRect && Number.isFinite(fromRect.top) && Number.isFinite(fromRect.left)){
      const dstRect = source.getBoundingClientRect();
      const dx = fromRect.left - dstRect.left;
      const dy = fromRect.top - dstRect.top;
      if(Math.abs(dx) > 2 || Math.abs(dy) > 2){
        source.style.position = "relative";
        source.style.zIndex = "3";
        source.style.transition = "none";
        source.style.transform = `translate(${dx}px, ${dy}px)`;
        source.style.boxShadow = "0 14px 34px color-mix(in srgb,var(--accent-glow) 34%, transparent)";
        void source.offsetWidth;
        source.classList.add("switch-row-activated");
        source.style.transition = "transform .72s cubic-bezier(0.2, 0.9, 0.2, 1), box-shadow .72s ease";
        source.style.transform = "translate(0, 0)";
        source.style.boxShadow = "0 10px 22px color-mix(in srgb,var(--accent-glow) 18%, transparent)";
        await waitMs(760);
        source.classList.remove("switch-row-activated");
        source.style.transition = "";
        source.style.transform = "";
        source.style.boxShadow = "";
        source.style.position = "";
        source.style.zIndex = "";
        return;
      }
    }
    source.classList.add("switch-row-activated");
    await waitMs(240);
    source.classList.remove("switch-row-activated");
  }
  function renderSortIndicators(){
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      const key = th.dataset.sort;
      const active = sortState.key === key;
      th.classList.toggle("sorted", active);
      let indicator = th.querySelector(".sort-indicator");
      if(!indicator){
        indicator = document.createElement("span");
        indicator.className = "sort-indicator";
        th.appendChild(indicator);
      }
      indicator.textContent = active ? (sortState.dir === "asc" ? "↑" : "↓") : "";
    });
  }

  function initSteppers(root){
    const scope = root || document;
    scope.querySelectorAll("[data-stepper]").forEach((wrap) => {
      if (wrap.dataset.bound === "1") return;
      const input = wrap.querySelector("input[type='number']");
      const dec = wrap.querySelector("[data-stepper-dec]");
      const inc = wrap.querySelector("[data-stepper-inc]");
      if (!input || !dec || !inc) return;
      const applyDelta = (sign) => {
        const step = Number(input.step || "1") || 1;
        const min = input.min !== "" ? Number(input.min) : null;
        const max = input.max !== "" ? Number(input.max) : null;
        let next = Number(input.value || "0");
        if (!Number.isFinite(next)) next = 0;
        next = next + (sign * step);
        if (min !== null && Number.isFinite(min)) next = Math.max(min, next);
        if (max !== null && Number.isFinite(max)) next = Math.min(max, next);
        if (Math.abs(step - Math.round(step)) < 1e-9) next = Math.round(next);
        input.value = String(next);
        input.dispatchEvent(new Event("change", { bubbles: true }));
      };
      let holdTimer = null;
      let holdInterval = null;
      let holdTriggered = false;
      let pointerUsed = false;
      const clearHold = () => {
        if(holdTimer){ clearTimeout(holdTimer); holdTimer = null; }
        if(holdInterval){ clearInterval(holdInterval); holdInterval = null; }
      };
      const startHold = (sign) => {
        clearHold();
        holdTriggered = false;
        applyDelta(sign);
        holdTimer = setTimeout(() => {
          holdTriggered = true;
          holdInterval = setInterval(() => applyDelta(sign), 70);
        }, 320);
      };
      const bindStepperButton = (btn, sign) => {
        btn.addEventListener("pointerdown", (ev) => {
          ev.preventDefault();
          pointerUsed = true;
          btn.setPointerCapture?.(ev.pointerId);
          startHold(sign);
        });
        btn.addEventListener("pointerup", clearHold);
        btn.addEventListener("pointercancel", clearHold);
        btn.addEventListener("pointerleave", clearHold);
        // keyboard fallback
        btn.addEventListener("click", () => {
          if(pointerUsed){ pointerUsed = false; return; }
          if(holdTriggered){ holdTriggered = false; return; }
          applyDelta(sign);
        });
      };
      bindStepperButton(dec, -1);
      bindStepperButton(inc, +1);
      wrap.dataset.bound = "1";
    });
  }
  function saveColumnPrefs(){
    try {
      columnPrefs = normalizeColumnPrefs(columnPrefs);
      localStorage.setItem("codex_table_columns", JSON.stringify(columnPrefs));
    } catch(_) {}
  }
  function isAutoSwitchEnabled(){
    try { return !!(latestData.config && latestData.config.auto_switch && latestData.config.auto_switch.enabled); } catch(_) { return false; }
  }
  function applyColumnVisibility(){
    Object.keys(defaultColumns).forEach((k) => {
      let visible = requiredColumns.has(k) ? true : !!columnPrefs[k];
      if(k === "auto" && !isAutoSwitchEnabled()) visible = false;
      document.querySelectorAll(`[data-col="${k}"]`).forEach((el) => {
        if (visible) el.classList.remove("col-hidden");
        else el.classList.add("col-hidden");
      });
    });
  }
  function renderColumnsModal(){
    const panel = byId("columnsModalList", false);
    if(!panel) return;
    panel.innerHTML = "";
    Object.keys(defaultColumns).forEach((k) => {
      if(k === "auto" && !isAutoSwitchEnabled()) return;
      if(requiredColumns.has(k)) return;
      const wrap = document.createElement("div");
      wrap.className = "columns-item";
      const row = document.createElement("label");
      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.checked = !!columnPrefs[k];
      chk.addEventListener("change", () => {
        columnPrefs[k] = !!chk.checked;
        saveColumnPrefs();
        applyColumnVisibility();
      });
      const txt = document.createElement("span");
      txt.textContent = columnLabels[k] || k;
      row.appendChild(chk);
      row.appendChild(txt);
      wrap.appendChild(row);
      panel.appendChild(wrap);
    });
  }
  function openColumnsModal(){
    renderColumnsModal();
    const b = byId("columnsModalBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function closeColumnsModal(){
    const b = byId("columnsModalBackdrop", false);
    if(b) b.style.display = "none";
  }
  function getExportableProfiles(){
    const rows = Array.isArray(latestData?.list?.profiles) ? latestData.list.profiles : [];
    return rows.map((row) => ({ name: String(row?.name || "").trim(), account_hint: String(row?.account_hint || row?.email || "-") })).filter((row) => !!row.name);
  }
  function setImportFileLabel(text=""){
    const label = byId("importFileLabel", false);
    if(!label) return;
    label.textContent = String(text || "").trim();
  }
  function syncExportSelection(rows, selectedNames){
    const selectedSet = new Set((selectedNames || []).map((name) => String(name || "").trim()).filter(Boolean));
    return rows.filter((row) => selectedSet.has(row.name)).map((row) => row.name);
  }
  function updateExportSelectedSummary(){
    const rows = getExportableProfiles();
    exportSelectedNames = syncExportSelection(rows, exportSelectedNames);
    updateExportProfilesSummary(rows);
  }
  function updateExportProfilesSummary(rows){
    const summary = byId("exportProfilesSummary", false);
    const confirmBtn = byId("exportProfilesConfirmBtn", false);
    const headerCheckbox = byId("exportHeaderCheckbox", false);
    if(!summary) return;
    const selectedCount = exportSelectedNames.length;
    if(confirmBtn) confirmBtn.disabled = !rows.length || selectedCount === 0;
    if(headerCheckbox){
      headerCheckbox.checked = !!rows.length && selectedCount === rows.length;
      headerCheckbox.indeterminate = selectedCount > 0 && selectedCount < rows.length;
      headerCheckbox.disabled = rows.length === 0;
    }
    if(!rows.length){
      summary.textContent = "No saved profiles are available.";
      return;
    }
    summary.textContent = `${selectedCount} of ${rows.length} profile(s) selected for export.`;
  }
  function toggleAllExportProfiles(checked){
    const rows = getExportableProfiles();
    exportSelectedNames = checked ? rows.map((row) => row.name) : [];
    renderExportProfilesModal();
  }
  function renderExportProfilesModal(){
    const panel = byId("exportProfilesTableBody", false);
    if(!panel) return;
    panel.innerHTML = "";
    const rows = getExportableProfiles();
    exportSelectedNames = syncExportSelection(rows, exportSelectedNames);
    if(!rows.length){
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 3;
      td.className = "export-modal-hint";
      td.textContent = "No saved profiles are available.";
      tr.appendChild(td);
      panel.appendChild(tr);
      updateExportProfilesSummary(rows);
      return;
    }
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const checkboxCell = document.createElement("td");
      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.checked = exportSelectedNames.includes(row.name);
      chk.addEventListener("change", () => {
        if(chk.checked){
          if(!exportSelectedNames.includes(row.name)) exportSelectedNames.push(row.name);
        } else {
          exportSelectedNames = exportSelectedNames.filter((name) => name !== row.name);
        }
        updateExportProfilesSummary(rows);
      });
      checkboxCell.appendChild(chk);
      const nameCell = document.createElement("td");
      const nameText = document.createElement("div");
      nameText.className = "export-modal-name";
      nameText.textContent = row.name;
      nameCell.appendChild(nameText);
      const hintCell = document.createElement("td");
      hintCell.className = "export-modal-hint";
      hintCell.textContent = row.account_hint || "-";
      tr.appendChild(checkboxCell);
      tr.appendChild(nameCell);
      tr.appendChild(hintCell);
      panel.appendChild(tr);
    });
    updateExportProfilesSummary(rows);
  }
  function openExportProfilesModal(){
    const rows = getExportableProfiles();
    exportSelectedNames = rows.map((row) => row.name);
    const filenameInput = byId("exportFilenameInput", false);
    if(filenameInput) filenameInput.value = "";
    renderExportProfilesModal();
    const b = byId("exportProfilesBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function closeExportProfilesModal(){
    const b = byId("exportProfilesBackdrop", false);
    if(b) b.style.display = "none";
  }
  function renderAlarmPresetModal(){
    const list = byId("alarmPresetList", false);
    const useBtn = byId("alarmPresetUseBtn", false);
    if(!list) return;
    list.innerHTML = "";
    const activeId = String(alarmPresetDraftId || getSelectedAlarmPresetId());
    (Array.isArray(ALARM_PRESETS) ? ALARM_PRESETS : []).forEach((preset) => {
      const row = document.createElement("div");
      row.className = `alarm-preset-item${preset.id === activeId ? " selected" : ""}`;
      const main = document.createElement("div");
      main.className = "alarm-preset-main";
      main.addEventListener("click", () => {
        alarmPresetDraftId = preset.id;
        renderAlarmPresetModal();
      });
      const name = document.createElement("div");
      name.className = "alarm-preset-name";
      name.textContent = preset.label || preset.id;
      const meta = document.createElement("div");
      meta.className = "alarm-preset-meta";
      meta.textContent = preset.id === getSelectedAlarmPresetId() ? "Current selection" : `Preset: ${preset.id}`;
      main.appendChild(name);
      main.appendChild(meta);
      const actions = document.createElement("div");
      actions.className = "alarm-preset-actions";
      const playBtn = document.createElement("button");
      playBtn.className = "btn";
      playBtn.type = "button";
      playBtn.textContent = "Play";
      playBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        alarmPresetDraftId = preset.id;
        renderAlarmPresetModal();
        await previewAlarmPreset(preset.id, { message: `Previewing ${preset.label}. This is how warning alarms will sound.` });
      });
      actions.appendChild(playBtn);
      row.appendChild(main);
      row.appendChild(actions);
      list.appendChild(row);
    });
    if(useBtn) useBtn.disabled = !activeId || activeId === getSelectedAlarmPresetId();
  }
  function openAlarmPresetModal(){
    alarmPresetDraftId = getSelectedAlarmPresetId();
    renderAlarmPresetModal();
    const b = byId("alarmPresetBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function closeAlarmPresetModal(){
    alarmPresetDraftId = "";
    const b = byId("alarmPresetBackdrop", false);
    if(b) b.style.display = "none";
  }
  async function applyAlarmPresetSelection(){
    const nextId = String(alarmPresetDraftId || "").trim();
    if(!nextId || nextId === getSelectedAlarmPresetId()){
      closeAlarmPresetModal();
      return;
    }
    await saveUiConfigPatch({ notifications: { alarm_preset: nextId } });
    latestData.config = latestData.config || {};
    latestData.config.notifications = latestData.config.notifications || {};
    latestData.config.notifications.alarm_preset = nextId;
    updateAlarmPresetSummary();
    closeAlarmPresetModal();
    showInAppNotice("Alarm Updated", `${getSelectedAlarmPresetLabel(nextId)} is now the active warning alarm.`, { duration_ms: 5000 });
  }
  async function fileToBase64(file){
    const buf = await file.arrayBuffer();
    let binary = "";
    const bytes = new Uint8Array(buf);
    const chunk = 0x8000;
    for(let i=0;i<bytes.length;i+=chunk){
      const slice = bytes.subarray(i, i + chunk);
      binary += String.fromCharCode.apply(null, slice);
    }
    return btoa(binary);
  }
  function closeImportReviewModal(){
    importReviewState = null;
    const b = byId("importReviewBackdrop", false);
    if(b) b.style.display = "none";
  }
  function renderImportReviewModal(){
    const list = byId("importReviewList", false);
    const summary = byId("importReviewSummary", false);
    if(!list || !summary || !importReviewState) return;
    list.innerHTML = "";
    const rows = Array.isArray(importReviewState.profiles) ? importReviewState.profiles : [];
    rows.forEach((row) => {
      const card = document.createElement("div");
      card.className = "review-item";
      const head = document.createElement("div");
      head.className = "review-item-head";
      const left = document.createElement("div");
      const name = document.createElement("div");
      name.className = "review-name";
      name.textContent = row.name || "-";
      const hint = document.createElement("div");
      hint.className = "review-hint";
      hint.textContent = row.account_hint || "-";
      left.appendChild(name);
      left.appendChild(hint);
      const badge = document.createElement("div");
      const statusClass = row.status === "ready" ? "ready" : ((row.status || "").includes("conflict") ? "conflict" : "invalid");
      badge.className = `review-status ${statusClass}`;
      badge.textContent = String(row.status || "unknown").replaceAll("_", " ");
      head.appendChild(left);
      head.appendChild(badge);
      card.appendChild(head);
      if(Array.isArray(row.problems) && row.problems.length){
        const ul = document.createElement("ul");
        ul.className = "review-problems";
        row.problems.forEach((msg) => {
          const li = document.createElement("li");
          li.textContent = msg;
          ul.appendChild(li);
        });
        card.appendChild(ul);
      }
      const actions = document.createElement("div");
      actions.className = "review-actions";
      const select = document.createElement("select");
      [
        { value:"import", label:"Import" },
        { value:"skip", label:"Skip" },
        { value:"rename", label:"Rename" },
        { value:"overwrite", label:"Overwrite" },
      ].forEach((opt) => {
        const el = document.createElement("option");
        el.value = opt.value;
        el.textContent = opt.label;
        if(opt.value === "overwrite" && !row.existing_name) el.disabled = true;
        select.appendChild(el);
      });
      select.value = row.action || (row.status === "ready" ? "import" : "skip");
      const rename = document.createElement("input");
      rename.type = "text";
      rename.placeholder = "new profile name";
      rename.value = row.rename_to || "";
      rename.style.display = select.value === "rename" ? "" : "none";
      select.addEventListener("change", () => {
        row.action = select.value;
        rename.style.display = select.value === "rename" ? "" : "none";
      });
      rename.addEventListener("input", () => {
        row.rename_to = rename.value;
      });
      actions.appendChild(select);
      actions.appendChild(rename);
      card.appendChild(actions);
      list.appendChild(card);
    });
    const total = rows.length;
    const importCount = rows.filter((row) => (row.action || "skip") !== "skip").length;
    const overwriteCount = rows.filter((row) => row.action === "overwrite").length;
    summary.textContent = `Profiles in archive: ${total}. Selected for apply: ${importCount}. Overwrite actions: ${overwriteCount}.`;
  }
  function openImportReviewModal(payload){
    importReviewState = JSON.parse(JSON.stringify(payload || {}));
    byId("importReviewIntro").textContent = `Archive: ${importReviewState.filename || "uploaded file"}. Review each profile before applying this import.`;
    renderImportReviewModal();
    const b = byId("importReviewBackdrop", false);
    if(b) b.style.display = "flex";
  }
  async function startProfilesExportFlow(){
    const rows = getExportableProfiles();
    const names = syncExportSelection(rows, exportSelectedNames);
    if(!names.length){
      setError("Select at least one profile to export.");
      return;
    }
    const requestedFilename = String(byId("exportFilenameInput", false)?.value || "").trim();
    const payload = await postApi("/api/local/export/prepare", {
      scope: "selected",
      names,
      filename: requestedFilename,
    });
    const href = `/api/local/export/download?token=${encodeURIComponent(token)}&id=${encodeURIComponent(payload.export_id)}`;
    const res = await fetch(href, { method: "GET", cache: "no-store", credentials: "same-origin" });
    if(!res.ok){
      let detail = `download failed (${res.status})`;
      try{
        const errPayload = await res.json();
        detail = errPayload?.error?.message || detail;
      } catch(_) {}
      throw new Error(detail);
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = payload.filename || "profiles.camzip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => {
      try { URL.revokeObjectURL(objectUrl); } catch(_) {}
    }, 1500);
    closeExportProfilesModal();
    showInAppNotice("Export Ready", `Downloaded ${payload.count || 0} profile(s) as a migration archive.`, { duration_ms: 7000 });
  }
  async function startProfilesImportFlow(file){
    if(!file) return;
    setImportFileLabel(`Selected file: ${file.name}`);
    const warning = await openModal({
      title: "Import Profiles",
      body: "Imported data may grant account access and should only come from a trusted source. Keep exported files private, do not share them with other people, and use this feature at your own risk.\\n\\nContinue and analyze this archive?",
      okText: "Analyze Import",
      okClass: "btn-warning",
    });
    if(!warning || !warning.ok){
      byId("importProfilesInput").value = "";
      return;
    }
    const content_b64 = await fileToBase64(file);
    const payload = await postApi("/api/local/import/analyze", {
      filename: file.name,
      content_b64,
    });
    openImportReviewModal(payload);
  }
  function openRowActionsModal(name){
    activeRowActionsName = name || null;
    const target = byId("rowActionsTarget", false);
    if(target) target.textContent = name ? `Profile: ${name}` : "-";
    const b = byId("rowActionsBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function closeRowActionsModal(){
    activeRowActionsName = null;
    const b = byId("rowActionsBackdrop", false);
    if(b) b.style.display = "none";
  }
  async function renameProfileFlow(oldName){
    const inputRes = await openModal({ title:"Rename Profile", body:"Enter the new profile name:", input:true, inputValue:oldName, inputPlaceholder:"new name" });
    if(!inputRes || !inputRes.ok) return;
    const newName = (inputRes.value || "").trim();
    if(!newName || newName===oldName) return;
    const confirmRes = await openModal({ title:"Confirm Rename", body:"From: "+oldName+"\\nTo: "+newName });
    if(!confirmRes || !confirmRes.ok) return;
    await runAction("local.rename", ()=>postApi("/api/local/rename",{old_name:oldName,new_name:newName}));
  }
  async function removeProfileFlow(name){
    const ok = await openModal({ title:"Confirm Remove", body:"Remove profile '"+name+"'?" });
    if(!ok || !ok.ok) return;
    await runAction("local.remove", ()=>postApi("/api/local/remove",{name}));
  }
  function clearAddDevicePolling(){
    if(addDevicePollTimer){
      clearInterval(addDevicePollTimer);
      addDevicePollTimer = null;
    }
  }
  function openAddDeviceModal(opts={}){
    if(opts.reset){
      clearAddDevicePolling();
      addDeviceSessionId = null;
      addDeviceSessionState = null;
      addDeviceProfileName = String(opts.name || "").trim();
      const nameInput = byId("addDeviceNameInput", false);
      if(nameInput){
        nameInput.value = addDeviceProfileName;
        setTimeout(()=>nameInput.focus(), 0);
      }
      updateAddDeviceModal({ status:"idle", message:"Choose a login method to begin.", url:null, code:null });
    }
    const b = byId("addDeviceBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function closeAddDeviceModal(){
    clearAddDevicePolling();
    addDeviceSessionId = null;
    addDeviceSessionState = null;
    addDeviceProfileName = "";
    const nameInput = byId("addDeviceNameInput", false);
    if(nameInput) nameInput.value = "";
    const b = byId("addDeviceBackdrop", false);
    if(b) b.style.display = "none";
  }
  function getAddDeviceProfileName(){
    const input = byId("addDeviceNameInput", false);
    const name = String((input?.value || addDeviceProfileName || "")).trim();
    if(!name){
      setError("Enter profile name for the new login.");
      if(input) input.focus();
      return "";
    }
    const existing = Array.isArray(latestData.list?.profiles) ? latestData.list.profiles : [];
    const taken = existing.some((p) => String(p?.name || "").toLowerCase() === name.toLowerCase());
    if(taken){
      setError(`Profile name '${name}' already exists. Choose a different name.`);
      if(input) input.focus();
      return "";
    }
    return name;
  }
  function updateAddDeviceModal(session){
    addDeviceSessionState = session || null;
    const st = byId("addDeviceStatus", false);
    const urlEl = byId("addDeviceUrl", false);
    const codeEl = byId("addDeviceCode", false);
    const startBtn = byId("addDeviceStartBtn", false);
    const normalBtn = byId("addDeviceLegacyBtn", false);
    const copyBtn = byId("addDeviceCopyBtn", false);
    const openBtn = byId("addDeviceOpenBtn", false);
    if(st) st.textContent = session?.error || session?.message || `status: ${session?.status || "-"}`;
    if(urlEl) urlEl.textContent = session?.url || "-";
    if(codeEl) codeEl.textContent = session?.code || "-";
    const finished = !!session && ["completed", "failed", "canceled"].includes(String(session.status || ""));
    const running = !!addDeviceSessionId && !finished;
    if(startBtn) startBtn.disabled = running;
    if(normalBtn) normalBtn.disabled = running;
    if(copyBtn) copyBtn.disabled = !String(session?.url || session?.code || "").trim();
    if(openBtn) openBtn.disabled = !String(session?.url || "").trim();
  }
  async function pollAddDeviceSession(){
    if(!addDeviceSessionId) return;
    const payload = await safeGet(`/api/local/add/session?id=${encodeURIComponent(addDeviceSessionId)}`);
    if(payload.__error){
      updateAddDeviceModal({ status:"failed", error: payload.__error, message:`session error: ${payload.__error}` });
      clearAddDevicePolling();
      return;
    }
    updateAddDeviceModal(payload);
    if(["completed", "failed", "canceled"].includes(String(payload.status || ""))){
      clearAddDevicePolling();
      if(payload.status === "completed"){
        await refreshAll();
      }
    }
  }
  async function startAddDeviceFlow(name){
    clearAddDevicePolling();
    addDeviceSessionId = null;
    addDeviceProfileName = String(name || "").trim();
    const nameInput = byId("addDeviceNameInput", false);
    if(nameInput) nameInput.value = addDeviceProfileName;
    updateAddDeviceModal({ status:"running", message:"starting login flow..." });
    const data = await postApi("/api/local/add/start", { name, timeout: 600, device_auth: true });
    addDeviceSessionId = data.id;
    updateAddDeviceModal(data);
    await pollAddDeviceSession();
    addDevicePollTimer = setInterval(pollAddDeviceSession, 1200);
  }
  function closeModal(result){
    const b=byId("modalBackdrop", false);
    if(b) b.style.display="none";
    if(activeModalResolver){ const fn=activeModalResolver; activeModalResolver=null; fn(result); }
  }
  function modalOkAction(){
    const input=byId("modalInput");
    closeModal({ ok:true, value: (input && input.style.display !== "none") ? input.value : "" });
  }
  function modalCancelAction(){
    closeModal({ ok:false });
  }
  function openModal(opts){
    return new Promise((resolve) => {
      activeModalResolver = resolve;
      byId("modalTitle").textContent = opts.title || "Confirm";
      byId("modalBody").textContent = opts.body || "";
      const okBtn = byId("modalOkBtn", false);
      const cancelBtn = byId("modalCancelBtn", false);
      if(okBtn){
        okBtn.textContent = opts.okText || "OK";
        okBtn.className = `btn ${opts.okClass || "btn-primary"}`;
      }
      if(cancelBtn){
        cancelBtn.textContent = opts.cancelText || "Cancel";
        cancelBtn.className = `btn ${opts.cancelClass || ""}`.trim() || "btn";
        cancelBtn.style.display = opts.hideCancel ? "none" : "";
      }
      const input = byId("modalInput");
      if(opts.input){
        input.style.display = "block";
        input.value = opts.inputValue || "";
        input.placeholder = opts.inputPlaceholder || "";
        setTimeout(()=>input.focus(), 0);
      } else {
        input.style.display = "none";
        input.value = "";
      }
      byId("modalBackdrop").style.display = "flex";
    });
  }

  async function saveUiConfigPatch(patch){
    await enqueueConfigPatch(patch);
  }

  async function setEligibility(name, eligible){ await postApi("/api/auto-switch/account-eligibility", { name, eligible }); }
  const IS_MAC_CLIENT = /mac os|macintosh/i.test((navigator && navigator.userAgent) || "");
  function switchRequestBody(name){
    if(IS_MAC_CLIENT) return { name };
    return { name, close_only: true, no_restart: true };
  }
  async function switchProfile(name){
    await postApi("/api/switch", switchRequestBody(name));
  }
  function renderSwitchProgressState(){
    if(latestData.usage && Array.isArray(latestData.usage.profiles)){
      renderTable(latestData.usage);
    }
  }
  async function runSwitchAction(name){
    const target = String(name || "").trim();
    if(!target) return;
    if(switchInFlight){
      return;
    }
    let startRect = null;
    try{
      const row = byId("rows", false)?.querySelector(`tr[data-row-name="${CSS.escape(target)}"]`);
      if(row){
        const rect = row.getBoundingClientRect();
        startRect = { left: rect.left, top: rect.top };
      }
    } catch(_) {}
    switchInFlight = true;
    switchPendingName = target;
    renderSwitchProgressState();
    try{
      await switchProfile(target);
      await refreshAll({ usageTimeoutSec: 8, usageForce: true, showLoading: false });
      switchInFlight = false;
      renderSwitchProgressState();
      await waitMs(70);
      await animateSwitchRowToTop(target, startRect);
    } finally {
      switchInFlight = false;
      switchPendingName = "";
      renderSwitchProgressState();
    }
  }
  function renderEvents(items){ return items; }

  async function loadDebugLogs(){
    const payload = await safeGet("/api/debug/logs?tail=240&token="+encodeURIComponent(token));
    if(payload.__error) return;
    baseLogs = (payload.logs || []).map((r) => ({
      ts: r.ts || "-",
      level: String(r.level || "info").toLowerCase(),
      message: r.message || "",
      details: (r.details && Object.keys(r.details).length) ? r.details : null,
    }));
    renderSystemOut();
  }

  async function ensureNotificationPermission(showError){
    if(!("Notification" in window)){
      if(showError) setError("Notifications are not supported in this browser.");
      return false;
    }
    if(Notification.permission === "default"){
      try { await Notification.requestPermission(); } catch(_) {}
    }
    if(Notification.permission !== "granted"){
      if(showError) setError("Notification permission is blocked. Enable it in browser settings.");
      return false;
    }
    return true;
  }

  async function ensureNotificationServiceWorker(){
    if(!("serviceWorker" in navigator)) return null;
    if(notificationSwRegistration) return notificationSwRegistration;
    try{
      const reg = await navigator.serviceWorker.register("/sw.js?v="+encodeURIComponent(UI_VERSION), { scope: "/" });
      notificationSwRegistration = reg || null;
      return notificationSwRegistration;
    } catch(_) {
      return null;
    }
  }

  async function primeAlarmAudio(){
    const AC = window.AudioContext || window.webkitAudioContext;
    if(!AC) return false;
    if(!alarmAudioCtx){
      try { alarmAudioCtx = new AC(); } catch(_) { return false; }
    }
    if(alarmAudioCtx.state === "suspended"){
      try { await alarmAudioCtx.resume(); } catch(_) {}
    }
    return alarmAudioCtx.state === "running";
  }

  function getAlarmPresetById(presetId){
    const id = String(presetId || "");
    return alarmPresetMap.get(id) || alarmPresetMap.get("beacon") || (Array.isArray(ALARM_PRESETS) ? ALARM_PRESETS[0] : null);
  }

  function getSelectedAlarmPresetId(){
    return String(latestData?.config?.notifications?.alarm_preset || "beacon");
  }

  function getSelectedAlarmPresetLabel(presetId){
    const preset = getAlarmPresetById(presetId || getSelectedAlarmPresetId());
    return String(preset?.label || "Beacon");
  }

  function updateAlarmPresetSummary(){
    const valueEl = byId("alarmPresetValue", false);
    if(valueEl) valueEl.textContent = getSelectedAlarmPresetLabel();
  }

  function playAlarmPreset(presetId, delayMs){
    if(!alarmAudioCtx || alarmAudioCtx.state !== "running") return;
    const preset = getAlarmPresetById(presetId);
    const tones = Array.isArray(preset?.tones) ? preset.tones : [];
    if(!tones.length) return;
    const now = alarmAudioCtx.currentTime + Math.max(0, Number(delayMs || 0)) / 1000;
    tones.forEach((tone) => {
      try {
        const osc = alarmAudioCtx.createOscillator();
        const gain = alarmAudioCtx.createGain();
        osc.type = "triangle";
        const startAt = now + Math.max(0, Number(tone.t || 0));
        const duration = Math.max(0.06, Number(tone.d || 0.18));
        const level = Math.max(0.02, Math.min(0.22, Number(tone.g || 0.16)));
        osc.frequency.setValueAtTime(Number(tone.f || 880), startAt);
        gain.gain.setValueAtTime(0.0001, startAt);
        gain.gain.exponentialRampToValueAtTime(level, startAt + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);
        osc.connect(gain);
        gain.connect(alarmAudioCtx.destination);
        osc.start(startAt);
        osc.stop(startAt + duration + 0.02);
      } catch(_) {}
    });
  }

  async function previewAlarmPreset(presetId, opts){
    const options = opts || {};
    const preset = getAlarmPresetById(presetId);
    if(!preset) return;
    await primeAlarmAudio();
    playAlarmPreset(preset.id, 0);
    const message = options.message || `Previewing ${preset.label}. This is how warning alarms will sound.`;
    await triggerSystemNotification(message, 0, {
      play_alarm: false,
      in_app_always: true,
      require_interaction: false,
      renotify: false,
      suppress_permission_error: true,
      tag: `cam-alarm-preview-${preset.id}`,
    });
  }

  async function triggerSystemNotification(message, delaySec, opts){
    const delayMs = Math.max(0, Number(delaySec || 0) * 1000);
    const playAlarm = !!(opts && opts.play_alarm);
    const tag = String((opts && opts.tag) || ("cam-manual-" + Date.now()));
    const requireInteraction = !!(opts && opts.require_interaction);
    const renotify = !!(opts && opts.renotify);
    const inAppAlways = !!(opts && opts.in_app_always);
    const suppressPermissionError = !!(opts && opts.suppress_permission_error);
    if(playAlarm) playAlarmPreset(getSelectedAlarmPresetId(), delayMs);
    if(!(await ensureNotificationPermission(false))){
      if(inAppAlways){
        setTimeout(() => {
          showInAppNotice("Codex Account Manager", String(message || "Notification"), { require_interaction: requireInteraction });
        }, delayMs);
      }
      if(suppressPermissionError) return;
      if(playAlarm){
        setError("Browser notification permission is blocked. Alarm sound played instead.");
      } else {
        setError("Notification permission is blocked. Enable it in browser settings.");
      }
      return;
    }
    setTimeout(async () => {
      const body = String(message || "Notification");
      const destination = "/?r="+Date.now();
      if(inAppAlways){
        showInAppNotice("Codex Account Manager", body, { require_interaction: requireInteraction });
      }
      const options = {
        body,
        tag,
        renotify,
        requireInteraction,
        data: { url: destination, source: "codex-account-ui" },
      };
      try {
        const reg = await ensureNotificationServiceWorker();
        if(reg && typeof reg.showNotification === "function"){
          await reg.showNotification("Codex Account Manager", options);
          return;
        }
      } catch(_) {}
      try {
        const n = new Notification("Codex Account Manager", options);
        n.onclick = () => { try { window.focus(); window.location.href = destination; } catch(_) {} };
      } catch(e) {
        if(playAlarm){
          setError("Alarm played, but the browser blocked the notification card.");
        } else {
          setError("Failed to display notification card.");
        }
      }
    }, delayMs);
  }

  async function maybeNotify(ev){
    const cfg = latestData.config || {};
    if(!((cfg.notifications||{}).enabled)) return;
    if(!ev || ev.id <= lastEventId || notifiedEventIds.has(ev.id)) return;
    if(ev.type !== "warning") return;
    notifiedEventIds.add(ev.id);
    const details = ev.details || {};
    const alarmCfg = (cfg.notifications || {});
    const ath = alarmCfg.thresholds || {};
    const rem5 = Number(details.remaining_5h);
    const remW = Number(details.remaining_weekly);
    const h5Hit = Number.isFinite(rem5) ? rem5 < Number(ath.h5_warn_pct ?? 20) : !!details.h5_hit;
    const wHit = Number.isFinite(remW) ? remW < Number(ath.weekly_warn_pct ?? 20) : !!details.weekly_hit;
    if(!(h5Hit || wHit)) return;
    await primeAlarmAudio();
    playAlarmPreset(alarmCfg.alarm_preset, 0);
    await triggerSystemNotification(ev.message || "Usage warning", 0, {
      play_alarm: false,
      in_app_always: true,
      require_interaction: false,
      renotify: true,
      suppress_permission_error: true,
      tag: `cam-warning-${ev.id || Date.now()}`,
    });
  }

  function renderTable(usage){
    const tbody = byId("rows"); tbody.innerHTML="";
    const mobileRows = byId("mobileRows", false); if(mobileRows) mobileRows.innerHTML = "";
    const mappedUsage = (usage?.profiles || []).map(p => ({...p, saved_at_ts: p.saved_at ? Date.parse(p.saved_at) || 0 : 0 }));
    const mappedFallback = (latestData?.list?.profiles || []).map(p => ({
      name: p?.name || "",
      email: "",
      account_id: p?.account_id || "",
      usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
      usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
      plan_type: null,
      is_paid: null,
      is_current: false,
      same_principal: !!p?.same_principal,
      error: null,
      saved_at: p?.saved_at || null,
      auto_switch_eligible: !!p?.auto_switch_eligible,
      loading_usage: true,
      saved_at_ts: p?.saved_at ? Date.parse(p.saved_at) || 0 : 0,
    }));
    const rows = applySort(mappedUsage.length ? mappedUsage : mappedFallback);
    const appendMinimalRows = () => {
      const base = (latestData?.list?.profiles || []).map((p) => ({
        name: p?.name || "-",
        account_id: p?.account_id || "-",
        saved_at: p?.saved_at || null,
      }));
      for(const p of base){
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td data-col="cur"><span class="status-dot" title="Account status indicator."></span></td>
          <td data-col="profile" title="${escHtml(p.name)}">${escHtml(p.name)}</td>
          <td data-col="email" class="email-cell">loading...</td>
          <td data-col="h5">${renderUsageMeter(null, true, false)}</td>
          <td data-col="h5remain" class="reset-cell loading-text">loading...</td>
          <td data-col="h5reset" class="reset-cell">-</td>
          <td data-col="weekly">${renderUsageMeter(null, true, false)}</td>
          <td data-col="weeklyremain" class="reset-cell loading-text">loading...</td>
          <td data-col="weeklyreset" class="reset-cell">-</td>
          <td data-col="plan">-</td>
          <td data-col="paid">-</td>
          <td data-col="id" class="id-cell" title="${escHtml(p.account_id)}">${escHtml(p.account_id)}</td>
          <td data-col="added" class="added-cell" title="When this profile was added to the app.">${fmtSavedAt(p.saved_at || "-")}</td>
          <td data-col="note" class="note-cell"></td>
          <td data-col="auto"><input type="checkbox" disabled title="Auto-switch eligibility loads after account usage is available." /></td>
          <td data-col="actions"><div class="actions-cell"><button class="btn btn-disabled" disabled title="Switch becomes available after the account finishes loading.">Switch</button><button class="btn actions-menu-btn btn-disabled" disabled title="Row actions become available after the account finishes loading.">⋯</button></div></td>
        `;
        tbody.appendChild(tr);
      }
    };
    for(const p of rows){
      try{
        const tr=document.createElement("tr");
        tr.dataset.rowName = p.name || "";
        const statusClass = p.is_current ? "active" : "";
        const h5Loading = isUsageLoadingState(p.usage_5h, p.error, p.loading_usage);
        const wLoading = isUsageLoadingState(p.usage_weekly, p.error, p.loading_usage);
        const h5Flash = shouldBlinkUsage(p.name, "h5", h5Loading);
        const wFlash = shouldBlinkUsage(p.name, "weekly", wLoading);
        const rowErrorLabel = usageErrorLabel(p.error);
        const h5CellHtml = (!h5Loading && rowErrorLabel) ? renderUsageErrorCell(p.error) : renderUsageMeter(p.usage_5h, h5Loading, h5Flash);
        const wCellHtml = (!wLoading && rowErrorLabel) ? renderUsageErrorCell(p.error) : renderUsageMeter(p.usage_weekly, wLoading, wFlash);
        const h5RemainText = formatRemainCell(p.usage_5h?.resets_at, true, h5Loading, p.error);
        const wRemainText = formatRemainCell(p.usage_weekly?.resets_at, false, wLoading, p.error);
        const h5RemainTs = Number(p.usage_5h?.resets_at || 0) || "";
        const wRemainTs = Number(p.usage_weekly?.resets_at || 0) || "";
        const switchTarget = switchInFlight && switchPendingName === p.name;
        if(switchTarget) tr.classList.add("switch-row-pending");
        const h5Pct = usagePercentNumber(p.usage_5h);
        const wPct = usagePercentNumber(p.usage_weekly);
        const quotaBlocked = (Number.isFinite(h5Pct) && h5Pct <= 0) || (Number.isFinite(wPct) && wPct <= 0);
        const disableSwitch = p.is_current || switchInFlight;
        tr.innerHTML = `
        <td data-col="cur"><span class="status-dot ${statusClass}" title="${p.is_current ? "Current active account." : "Saved account, not currently active."}"></span></td>
        <td data-col="profile" title="${(p.name || "-").replace(/"/g,'&quot;')}">${p.name}</td>
        <td data-col="email" class="email-cell" title="${(p.email || "-").replace(/"/g,'&quot;')}">${p.email || "-"}</td>
        <td data-col="h5">${h5CellHtml}</td>
        <td data-col="h5remain" class="reset-cell ${(h5Loading || rowErrorLabel) ? "loading-text" : ""}" data-remain-ts="${h5RemainTs}" data-remain-seconds="1" data-remain-loading="${h5Loading ? "1" : "0"}" title="Time remaining until the 5-hour usage window resets.">${h5RemainText}</td>
        <td data-col="h5reset" class="reset-cell" title="Exact reset time for the 5-hour usage window.">${fmtReset(p.usage_5h?.resets_at)}</td>
        <td data-col="weekly">${wCellHtml}</td>
        <td data-col="weeklyremain" class="reset-cell ${(wLoading || rowErrorLabel) ? "loading-text" : ""}" data-remain-ts="${wRemainTs}" data-remain-seconds="0" data-remain-loading="${wLoading ? "1" : "0"}" title="Time remaining until the weekly usage window resets.">${wRemainText}</td>
        <td data-col="weeklyreset" class="reset-cell" title="Exact reset time for the weekly usage window.">${fmtReset(p.usage_weekly?.resets_at)}</td>
        <td data-col="plan" title="Detected account plan type.">${p.plan_type || "-"}</td>
        <td data-col="paid" title="Whether this account appears to be paid.">${fmtPaid(p.is_paid)}</td>
        <td data-col="id" class="id-cell" title="${(p.account_id || "-").replace(/"/g,'&quot;')}">${p.account_id || "-"}</td>
        <td data-col="added" class="added-cell" title="When this profile was added to the app.">${fmtSavedAt(p.saved_at || "-")}</td>
        <td data-col="note" class="note-cell" title="${p.same_principal ? "This profile shares the same principal identity as another saved profile." : "No extra note for this profile."}">${p.same_principal ? '<span class="badge">same-principal</span>' : ''}</td>
        <td data-col="auto"><input type="checkbox" data-auto="${p.name}" ${p.auto_switch_eligible ? "checked" : ""} title="Allow or block this profile from automatic switching." /></td>
        <td data-col="actions"><div class="actions-cell"><button class="${quotaBlocked ? "btn-primary-danger" : "btn-primary"} ${disableSwitch ? "btn-disabled" : ""} ${switchTarget ? "btn-progress" : ""}" data-switch="${p.name}" ${disableSwitch ? "disabled" : ""} title="${p.is_current ? "This profile is already active." : (quotaBlocked ? "Switch to this profile now. Warning: usage is exhausted in one of the tracked windows." : "Switch to this profile now.")}">Switch</button><button class="btn actions-menu-btn" data-row-actions="${p.name}" title="Open rename and remove actions for this profile.">⋯</button></div></td>
      `;
        tbody.appendChild(tr);
        if(mobileRows){
        const h5PctVal = usagePercentNumber(p.usage_5h);
        const wPctVal = usagePercentNumber(p.usage_weekly);
        const h5Class = usageClass(h5PctVal);
        const wClass = usageClass(wPctVal);
        const mrow = document.createElement("div");
        mrow.className = "mobile-row";
        mrow.setAttribute("tabindex", "0");
        mrow.setAttribute("title", "Tap/click to view full details");
        mrow.innerHTML = `
          <div class="mobile-head">
            <div class="mobile-left">
              <span class="status-dot ${statusClass}" title="${p.is_current ? "Current active account." : "Saved account, not currently active."}"></span>
              <span class="mobile-profile">${p.name || "-"}</span>
            </div>
            <div class="mobile-actions">
              <button class="${quotaBlocked ? "btn-primary-danger" : "btn-primary"} ${(p.is_current || switchInFlight) ? "btn-disabled" : ""} ${(switchInFlight && switchPendingName === p.name) ? "btn-progress" : ""}" data-mobile-switch="${p.name}" ${(p.is_current || switchInFlight) ? "disabled" : ""} title="${p.is_current ? "This profile is already active." : (quotaBlocked ? "Switch to this profile now. Warning: usage is exhausted in one of the tracked windows." : "Switch to this profile now.")}">Switch</button>
              <button class="btn actions-menu-btn" data-mobile-row-actions="${p.name}" title="Open rename and remove actions for this profile.">⋯</button>
            </div>
          </div>
          <div class="mobile-email">${p.email || "-"}</div>
          <div class="mobile-stats">
            <div class="mobile-stat"><span class="label">5H</span><span class="${rowErrorLabel ? "usage-low" : h5Class} ${h5Flash ? "updated" : ""}">${rowErrorLabel || fmtUsagePct(p.usage_5h)}</span></div>
            <div class="mobile-stat"><span class="label">Weekly</span><span class="${rowErrorLabel ? "usage-low" : wClass} ${wFlash ? "updated" : ""}">${rowErrorLabel || fmtUsagePct(p.usage_weekly)}</span></div>
            <div class="mobile-stat"><span class="label">5H Remain</span><span class="${(h5Loading || rowErrorLabel) ? "loading-text" : ""}">${formatRemainCell(p.usage_5h?.resets_at, true, h5Loading, p.error)}</span></div>
            <div class="mobile-stat"><span class="label">W Remain</span><span class="${(wLoading || rowErrorLabel) ? "loading-text" : ""}">${formatRemainCell(p.usage_weekly?.resets_at, false, wLoading, p.error)}</span></div>
          </div>
        `;
        const openDetails = async () => {
          const detailsBody = [
            `Profile: ${p.name || "-"}`,
            `Email: ${p.email || "-"}`,
            `Current: ${p.is_current ? "yes" : "no"}`,
            `5H Usage: ${rowErrorLabel || fmtUsagePct(p.usage_5h)}`,
            `5H Remain: ${formatRemainCell(p.usage_5h?.resets_at, true, h5Loading, p.error)}`,
            `5H Reset At: ${fmtReset(p.usage_5h?.resets_at)}`,
            `Weekly Usage: ${rowErrorLabel || fmtUsagePct(p.usage_weekly)}`,
            `Weekly Remain: ${formatRemainCell(p.usage_weekly?.resets_at, false, wLoading, p.error)}`,
            `Weekly Reset At: ${fmtReset(p.usage_weekly?.resets_at)}`,
            `Plan: ${p.plan_type || "-"}`,
            `Paid: ${fmtPaid(p.is_paid)}`,
            `Account ID: ${p.account_id || "-"}`,
            `Added: ${fmtSavedAt(p.saved_at || "-")}`,
            `Note: ${p.same_principal ? "same-principal" : "-"}`,
          ].join("\\n");
          await openModal({ title: `Account Details: ${p.name || "-"}`, body: detailsBody });
        };
        mrow.addEventListener("click", openDetails);
        mrow.addEventListener("keydown", (ev) => {
          if(ev.key === "Enter" || ev.key === " "){
            ev.preventDefault();
            openDetails();
          }
        });
        const mobileSwitchBtn = mrow.querySelector("button[data-mobile-switch]");
        if(mobileSwitchBtn){
          mobileSwitchBtn.addEventListener("click", (ev) => {
            ev.stopPropagation();
            runSwitchAction(mobileSwitchBtn.dataset.mobileSwitch);
          });
        }
        const mobileRowActionsBtn = mrow.querySelector("button[data-mobile-row-actions]");
        if(mobileRowActionsBtn){
          mobileRowActionsBtn.addEventListener("click", (ev) => {
            ev.stopPropagation();
            openRowActionsModal(mobileRowActionsBtn.dataset.mobileRowActions);
          });
        }
          mobileRows.appendChild(mrow);
        }
      } catch(e){
        pushOverlayLog("error", "render.row_failed", { name: p?.name || "", error: e?.message || String(e) });
      }
    }
    if(tbody.children.length === 0){
      appendMinimalRows();
    }
    applyColumnVisibility();
    refreshRemainCountdowns();
    tbody.querySelectorAll("button[data-switch]").forEach(btn => btn.addEventListener("click", () => runSwitchAction(btn.dataset.switch)));
    tbody.querySelectorAll("button[data-row-actions]").forEach(btn => btn.addEventListener("click", (e)=>{
      e.stopPropagation();
      openRowActionsModal(btn.dataset.rowActions);
    }));
    tbody.querySelectorAll("input[data-auto]").forEach(ch => ch.addEventListener("change", async ()=>{ try { await setEligibility(ch.dataset.auto, !!ch.checked); } catch(e){ setError(e.message); ch.checked=!ch.checked; } }));
  }

  function applyConfigToControls(cfg){
    latestConfigRevision = Number(cfg?._meta?.revision || latestConfigRevision || 1);
    const ui = cfg.ui || {};
    byId("themeSelect").value = ui.theme || "auto";
    applyTheme(ui.theme || "auto");
    updateHeaderThemeIcon(ui.theme || "auto");
    byId("advancedCard").style.display = "none";
    byId("currentAutoToggle").checked = !!ui.current_auto_refresh_enabled;
    byId("currentIntervalInput").value = String(ui.current_refresh_interval_sec || 5);
    byId("allAutoToggle").checked = !!ui.all_auto_refresh_enabled;
    byId("allIntervalInput").value = String(ui.all_refresh_interval_min || 5);
    byId("debugToggle").checked = !!ui.debug_mode;
    updateHeaderDebugIcon(!!ui.debug_mode);
    byId("debugRuntimeSection").style.display = ui.debug_mode ? "block" : "none";
    const n = cfg.notifications || {};
    byId("alarmToggle").checked = !!n.enabled;
    byId("alarm5h").value = String(n.thresholds?.h5_warn_pct ?? 20);
    byId("alarmWeekly").value = String(n.thresholds?.weekly_warn_pct ?? 20);
    updateAlarmPresetSummary();
    const a = cfg.auto_switch || {};
    byId("asEnabled").checked = pendingAutoSwitchEnabled === null ? !!a.enabled : !!pendingAutoSwitchEnabled;
    setControlValueIfPristine("asDelay", String(a.delay_sec ?? 60));
    const rankingEl = byId("asRanking", false);
    if(rankingEl && rankingEl.dataset.dirty !== "1") rankingEl.value = a.ranking_mode || "balanced";
    updateRankingModeUI((rankingEl ? rankingEl.value : (a.ranking_mode || "balanced")), !!a.enabled);
    setControlValueIfPristine("as5h", String(a.thresholds?.h5_switch_pct ?? 20));
    setControlValueIfPristine("asWeekly", String(a.thresholds?.weekly_switch_pct ?? 20));
  }

  function extractEmailFromHint(hint){
    const s = String(hint || "");
    const left = s.split("|")[0].trim();
    return left.includes("@") ? left : "";
  }
  function buildUsageLoadingSnapshot(prevUsage, listPayload, currentPayload, errorMsg, loadingMode=false){
    const srcProfiles = [];
    if(prevUsage && Array.isArray(prevUsage.profiles) && prevUsage.profiles.length){
      for(const p of prevUsage.profiles){ srcProfiles.push({ ...p }); }
    } else if(listPayload && Array.isArray(listPayload.profiles)){
      for(const p of listPayload.profiles){
        srcProfiles.push({
          name: p.name,
          email: extractEmailFromHint(p.account_hint),
          account_id: p.account_id || "-",
          usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
          usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
          plan_type: null,
          is_paid: null,
          is_current: false,
          same_principal: !!p.same_principal,
          error: errorMsg || "request failed",
          saved_at: p.saved_at || null,
          auto_switch_eligible: !!p.auto_switch_eligible,
        });
      }
    }
    const currentEmail = (currentPayload && !currentPayload.__error) ? extractEmailFromHint(currentPayload.account_hint) : "";
    const mapped = srcProfiles.map((p) => {
      const keepCurrent = !!p.is_current;
      const byEmail = currentEmail ? (String(p.email || "").toLowerCase() === currentEmail.toLowerCase()) : keepCurrent;
      return {
        ...p,
        usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
        usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
        plan_type: p.plan_type ?? null,
        is_paid: (typeof p.is_paid === "boolean") ? p.is_paid : null,
        is_current: !!byEmail,
        error: errorMsg || p.error || "request failed",
        loading_usage: !!loadingMode,
      };
    });
    const currentProfile = mapped.find((p) => p.is_current)?.name || null;
    return { refreshed_at: new Date().toISOString(), current_profile: currentProfile, profiles: mapped };
  }

  function buildImmediateLoadingSnapshot(reason){
    const snapshot = buildUsageLoadingSnapshot(
      latestData.usage,
      latestData.list,
      null,
      reason || "request pending",
      true,
    );
    if(snapshot && Array.isArray(snapshot.profiles) && snapshot.profiles.length){
      return snapshot;
    }
    return null;
  }

  function saveBootSnapshot(){
    try{
      const payload = {
        saved_at: new Date().toISOString(),
        config: latestData.config || null,
        usage: latestData.usage || null,
      };
      localStorage.setItem("cam_boot_snapshot_v1", JSON.stringify(payload));
    } catch(_) {}
  }

  function loadBootSnapshot(){
    try{
      const raw = localStorage.getItem("cam_boot_snapshot_v1");
      if(!raw) return null;
      const parsed = JSON.parse(raw);
      if(!parsed || typeof parsed !== "object") return null;
      return parsed;
    } catch(_) {
      return null;
    }
  }

  function commitUsagePayload(payload, opts={}){
    if(!payload || payload.__error) return false;
    const prevUsageForFlash = (!opts.showLoading && sessionUsageCache && Array.isArray(sessionUsageCache.profiles) && sessionUsageCache.profiles.length)
      ? sessionUsageCache
      : null;
    if(!opts.showLoading && prevUsageForFlash){
      markUsageFlashUpdates(prevUsageForFlash, payload);
    }
    latestData.usage = payload;
    sessionUsageCache = payload;
    renderTable(payload);
    return true;
  }

  function setProfileLoadingState(name, loading, errorMsg=null){
    const target = String(name || "").trim();
    if(!target) return false;
    const currentUsage = latestData.usage;
    if(!currentUsage || !Array.isArray(currentUsage.profiles) || !currentUsage.profiles.length){
      return false;
    }
    let changed = false;
    const nextProfiles = currentUsage.profiles.map((profile) => {
      if(String(profile?.name || "").trim() !== target){
        return profile;
      }
      changed = true;
      return {
        ...profile,
        loading_usage: !!loading,
        error: loading ? null : (errorMsg || profile.error || null),
      };
    });
    if(!changed) return false;
    latestData.usage = {
      ...currentUsage,
      profiles: nextProfiles,
    };
    renderTable(latestData.usage);
    return true;
  }

  async function refreshCurrentUsage(opts={}){
    if(refreshRunning) return;
    if(currentRefreshRunning) return;
    currentRefreshRunning = true;
    try{
      const timeoutSec = Math.max(1, Number(opts?.timeoutSec || 6));
      const payload = await safeGet(`/api/usage-local/current?timeout=${encodeURIComponent(String(timeoutSec))}`, {
        timeoutMs: Math.max(3500, (timeoutSec + 3) * 1000),
      });
      if(!payload.__error){
        commitUsagePayload(payload, { showLoading: false });
        return;
      }
      setError((byId("error").textContent ? byId("error").textContent + "\\n" : "") + "current usage: " + payload.__error);
    } finally {
      currentRefreshRunning = false;
    }
  }

  async function refreshProfileUsage(name, opts={}){
    const target = String(name || "").trim();
    if(!target) return;
    const timeoutSec = Math.max(1, Number(opts?.timeoutSec || 7));
    setProfileLoadingState(target, true, null);
    const payload = await safeGet(`/api/usage-local/profile?name=${encodeURIComponent(target)}&timeout=${encodeURIComponent(String(timeoutSec))}`, {
      timeoutMs: Math.max(4000, (timeoutSec + 4) * 1000),
    });
    if(!payload.__error){
      commitUsagePayload(payload, { showLoading: false });
      return;
    }
    setProfileLoadingState(target, false, payload.__error || "request failed");
    setError((byId("error").textContent ? byId("error").textContent + "\\n" : "") + `usage(${target}): ` + payload.__error);
  }

  async function runAllAccountsSweep(opts={}){
    if(refreshRunning) return;
    if(allRefreshSweepRunning) return;
    allRefreshSweepRunning = true;
    try{
      const timeoutSec = Math.max(1, Number(opts?.timeoutSec || 7));
      const listProfiles = Array.isArray(latestData.list?.profiles) ? latestData.list.profiles : [];
      const cachedProfiles = Array.isArray(latestData.usage?.profiles) ? latestData.usage.profiles : [];
      const currentName = String(latestData.usage?.current_profile || cachedProfiles.find((p) => p?.is_current)?.name || "").trim();
      const orderedNames = [];
      for(const item of listProfiles){
        const name = String(item?.name || "").trim();
        if(!name || orderedNames.includes(name)) continue;
        orderedNames.push(name);
      }
      if(!orderedNames.length){
        for(const row of cachedProfiles){
          const name = String(row?.name || "").trim();
          if(!name || orderedNames.includes(name)) continue;
          orderedNames.push(name);
        }
      }
      for(const name of orderedNames){
        if(refreshRunning) break;
        if(currentName && name === currentName) continue;
        await refreshProfileUsage(name, { timeoutSec });
      }
    } finally {
      allRefreshSweepRunning = false;
    }
  }

  async function refreshAll(opts){
    if(refreshRunning){
      refreshQueuedOpts = opts || {};
      return;
    }
    refreshRunning = true;
    const runOpts = opts || {};
    const clearUsageCache = !!runOpts?.clearUsageCache;
    const showLoading = !!runOpts?.showLoading;
    if(clearUsageCache){
      sessionUsageCache = null;
      usageFlashUntil = {};
      latestData.usage = null;
    }
    if(pendingConfigSaves > 0){
      try { await configSaveQueue; } catch(_) {}
    }
    const usageTimeoutSec = Math.max(1, Number(runOpts?.usageTimeoutSec || 8));
    const usageForce = !!runOpts?.usageForce;
    const usagePath = `/api/usage-local?timeout=${encodeURIComponent(String(usageTimeoutSec))}${usageForce ? "&force=true" : ""}`;
    setError("");
    if(showLoading){
      const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
      if(!hasLiveUsage){
        const prefetchLoading = buildImmediateLoadingSnapshot("request pending");
        latestData.usage = prefetchLoading;
        renderTable(prefetchLoading);
      }
    }
    try{
      const phase1Started = Date.now();
      const phase1TimeoutMs = Math.max(2000, Number(runOpts?.phase1TimeoutMs || 4500));
      let [config, autoState, current, list] = await Promise.all([
        safeGet("/api/ui-config", { timeoutMs: phase1TimeoutMs }),
        safeGet("/api/auto-switch/state", { timeoutMs: phase1TimeoutMs }),
        safeGet("/api/current", { timeoutMs: phase1TimeoutMs }),
        safeGet("/api/list", { timeoutMs: phase1TimeoutMs }),
      ]);
      if(!config.__error){
        latestData.config = config;
        latestConfigRevision = Number(config?._meta?.revision || latestConfigRevision || 1);
        applyConfigToControls(config);
        renderColumnsModal();
        applyColumnVisibility();
      } else {
        setError("config: " + config.__error);
      }
      if(!autoState.__error){
        latestData.autoState = autoState;
        const rapidBtn = byId("asRapidTestBtn", false);
        if(rapidBtn){
          const activeRapid = !!autoState.rapid_test_active;
          rapidBtn.disabled = activeRapid;
          rapidBtn.textContent = activeRapid ? "Rapid Running..." : "Rapid Test";
        }
        updateAutoSwitchArmedUI();
      }
      if(!list.__error){
        latestData.list = list;
        updateExportSelectedSummary();
        if(showLoading){
          const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
          if(!hasLiveUsage){
            const listLoadingSnapshot = buildUsageLoadingSnapshot(
              latestData.usage,
              latestData.list,
              latestData.current || current,
              "request pending",
              true,
            );
            if(listLoadingSnapshot && Array.isArray(listLoadingSnapshot.profiles) && listLoadingSnapshot.profiles.length){
              latestData.usage = listLoadingSnapshot;
              renderTable(listLoadingSnapshot);
            }
          }
        }
      } else {
        const listRetry = await safeGet("/api/list", { timeoutMs: 12000 });
        if(!listRetry.__error){
          list = listRetry;
          latestData.list = listRetry;
          updateExportSelectedSummary();
          if(showLoading){
            const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
            if(!hasLiveUsage){
              const listRetrySnapshot = buildUsageLoadingSnapshot(
                latestData.usage,
                latestData.list,
                latestData.current || current,
                "request pending",
                true,
              );
              if(listRetrySnapshot && Array.isArray(listRetrySnapshot.profiles) && listRetrySnapshot.profiles.length){
                latestData.usage = listRetrySnapshot;
                renderTable(listRetrySnapshot);
              }
            }
          }
          pushOverlayLog("ui", "refresh.list.retry.success");
        }
      }
      if(!current.__error){
        latestData.current = current;
      } else {
        const currentRetry = await safeGet("/api/current", { timeoutMs: 8000 });
        if(!currentRetry.__error){
          current = currentRetry;
          latestData.current = currentRetry;
          pushOverlayLog("ui", "refresh.current.retry.success");
        }
      }
      pushOverlayLog("ui", "refresh.phase1", { duration_ms: Date.now() - phase1Started });

      const phase2Started = Date.now();
      usageFetchBlinkActive = true;
      if(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length){
        renderTable(latestData.usage);
      }
      if(showLoading){
        const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
        if(!hasLiveUsage){
          const pendingUsage = buildUsageLoadingSnapshot(
            latestData.usage,
            latestData.list,
            latestData.current || current,
            "request pending",
            true,
          );
          latestData.usage = pendingUsage;
          renderTable(pendingUsage);
        }
      }
      const phase2TimeoutMs = Math.max(4000, Number(runOpts?.phase2TimeoutMs || 12000));
      const [usage, autoChain, eventsPayload] = await Promise.all([
        safeGet(usagePath, { timeoutMs: Math.max(phase2TimeoutMs, (usageTimeoutSec + 4) * 1000) }),
        safeGet("/api/auto-switch/chain", { timeoutMs: phase2TimeoutMs }),
        safeGet("/api/events?since_id="+encodeURIComponent(String(lastEventId)), { timeoutMs: phase2TimeoutMs }),
      ]);
      usageFetchBlinkActive = false;
      if(!usage.__error){
        commitUsagePayload(usage, { showLoading });
      } else {
        const hasSessionCache = !!(sessionUsageCache && Array.isArray(sessionUsageCache.profiles) && sessionUsageCache.profiles.length);
        if(!showLoading && hasSessionCache){
          latestData.usage = sessionUsageCache;
          renderTable(sessionUsageCache);
        } else {
          const fallbackUsage = buildUsageLoadingSnapshot(latestData.usage, latestData.list, latestData.current || current, usage.__error);
          latestData.usage = fallbackUsage;
          renderTable(fallbackUsage);
        }
        setError((byId("error").textContent ? byId("error").textContent + "\\n" : "") + "usage: " + usage.__error);
      }
      const renderedRows = byId("rows", false)?.children?.length || 0;
      if(renderedRows === 0 && latestData.list && Array.isArray(latestData.list.profiles) && latestData.list.profiles.length){
        const forcedSnapshot = buildUsageLoadingSnapshot(
          latestData.usage,
          latestData.list,
          latestData.current || current,
          "request pending",
          true,
        );
        if(forcedSnapshot && Array.isArray(forcedSnapshot.profiles) && forcedSnapshot.profiles.length){
          latestData.usage = forcedSnapshot;
          renderTable(forcedSnapshot);
          pushOverlayLog("ui", "refresh.rows.forced_from_list", { count: forcedSnapshot.profiles.length });
        }
      }
      if(!autoChain.__error){
        latestData.autoChain = autoChain;
        renderChainPreview(autoChain);
      }
      if(!eventsPayload.__error){
        const incoming = eventsPayload.events || [];
        if(incoming.length){
          for(const ev of incoming){
            await maybeNotify(ev);
            lastEventId = Math.max(lastEventId, Number(ev.id || 0));
            latestData.events.push(ev);
            pushOverlayLog("event", `${ev.type || "event"}: ${ev.message || ""}`, ev.details || null);
          }
        }
        renderEvents(latestData.events);
      }
      pushOverlayLog("ui", "refresh.phase2", { duration_ms: Date.now() - phase2Started });
      const debugEnabled = !!(latestData.config?.ui?.debug_mode);
      if(debugEnabled){
        await loadDebugLogs();
      }
      saveBootSnapshot();
      const refreshStamp = byId("lastRefresh", false);
      if(refreshStamp) refreshStamp.textContent = "Refreshed: " + new Date().toLocaleTimeString();
    } finally {
      usageFetchBlinkActive = false;
      refreshRunning = false;
      if(refreshQueuedOpts){
        const nextOpts = refreshQueuedOpts;
        refreshQueuedOpts = null;
        setTimeout(() => { refreshAll(nextOpts); }, 0);
      }
    }
  }

  function resetCurrentRefreshTimer(){
    if(currentRefreshTimer) clearInterval(currentRefreshTimer);
    const enabled = !!byId("currentAutoToggle").checked;
    if(!enabled) return;
    const iv = Math.max(1, parseInt(byId("currentIntervalInput").value || "5", 10));
    byId("currentIntervalInput").value = String(iv);
    currentRefreshTimer = setInterval(() => { refreshCurrentUsage({ timeoutSec: Math.max(2, Math.min(12, iv + 2)) }).catch(() => {}); }, iv * 1000);
  }

  function resetAllRefreshTimer(){
    if(allRefreshTimer) clearInterval(allRefreshTimer);
    const enabled = !!byId("allAutoToggle").checked;
    if(!enabled) return;
    const ivMin = Math.max(1, Math.min(60, parseInt(byId("allIntervalInput").value || "5", 10)));
    byId("allIntervalInput").value = String(ivMin);
    allRefreshTimer = setInterval(() => { runAllAccountsSweep({ timeoutSec: 7 }).catch(() => {}); }, ivMin * 60 * 1000);
  }

  function resetTimer(){
    resetCurrentRefreshTimer();
    resetAllRefreshTimer();
  }
  function resetRemainTicker(){
    if(remainTicker) clearInterval(remainTicker);
    remainTicker = setInterval(refreshRemainCountdowns, 1000);
  }

  async function restartUiService(){
    const restartBtn = byId("restartBtn", false);
    const refreshBtn = byId("refreshBtn", false);
    const prevRestart = restartBtn ? (restartBtn.textContent || "Restart") : "Restart";
    if(restartBtn){
      restartBtn.disabled = true;
      restartBtn.textContent = "Restarting...";
    }
    if(refreshBtn) refreshBtn.disabled = true;
    setError("");
    let reloadAfterMs = 1200;
    let previousHealthVersion = "";
    try{
      const initialHealth = await safeGet(`/api/health?r=${Date.now()}`, { timeoutMs: 900 });
      if(!initialHealth.__error){
        previousHealthVersion = String(initialHealth?.version || "").trim();
      }
    } catch(_) {}
    try{
      const data = await postApi("/api/system/restart", {});
      reloadAfterMs = Math.max(400, Number(data?.reload_after_ms || 1200));
    } catch(e){
      const msg = e?.message || String(e);
      if(!/Failed to fetch|network/i.test(msg)){
        throw e;
      }
    }
    setError("Restarting UI service...");
    await waitMs(reloadAfterMs);
    const startedAt = Date.now();
    let sawServiceDrop = false;
    while((Date.now() - startedAt) < 20000){
      const health = await safeGet(`/api/health?r=${Date.now()}`, { timeoutMs: 900 });
      if(health.__error){
        sawServiceDrop = true;
      } else {
        const nextVersion = String(health?.version || "").trim();
        const versionChanged = !!nextVersion && !!previousHealthVersion && nextVersion !== previousHealthVersion;
        if(sawServiceDrop || versionChanged || !previousHealthVersion){
          try {
            window.location.href = "/?r="+Date.now();
            return;
          } catch(_) {}
        }
      }
      await waitMs(700);
    }
    const fallbackStartedAt = Date.now();
    while((Date.now() - fallbackStartedAt) < 4000){
      const health = await safeGet(`/api/health?r=${Date.now()}`, { timeoutMs: 900 });
      if(!health.__error){
        try {
          window.location.href = "/?r="+Date.now();
          return;
        } catch(_) {}
      }
      await waitMs(700);
    }
    if(restartBtn){
      restartBtn.disabled = false;
      restartBtn.textContent = prevRestart;
    }
    if(refreshBtn) refreshBtn.disabled = false;
    throw new Error("UI restart timed out. Reload the page manually.");
  }

  async function init(){
    try {
      installDiagnosticsHooks();
      document.addEventListener("pointerdown", () => { primeAlarmAudio().catch(()=>{}); }, { once: true });
      const settingsBtn = byId("settingsToggleBtn", false);
      if(settingsBtn){
        const hidden = localStorage.getItem("cam_settings_hidden") === "1";
        applySettingsSectionVisibility(hidden);
        settingsBtn.addEventListener("click", () => {
          const firstSection = document.querySelector("[data-settings-section='1']");
          const currentlyHidden = !!firstSection && firstSection.style.display === "none";
          const nextHidden = !currentlyHidden;
          applySettingsSectionVisibility(nextHidden);
          localStorage.setItem("cam_settings_hidden", nextHidden ? "1" : "0");
        });
      }
      const guideDetails = byId("guideDetails", false);
      if(guideDetails){
        guideDetails.addEventListener("toggle", () => {
          if(guideDetails.open && !guideReleaseLoaded){
            loadGuideReleaseNotes(false).catch(() => {});
          }
        });
        if(guideDetails.open && !guideReleaseLoaded){
          loadGuideReleaseNotes(false).catch(() => {});
        }
      }
      const guideReleaseRefreshBtn = byId("guideReleaseRefreshBtn", false);
      if(guideReleaseRefreshBtn){
        guideReleaseRefreshBtn.addEventListener("click", () => {
          loadGuideReleaseNotes(true).catch(() => {});
        });
      }
      byId("refreshBtn").addEventListener("click", async () => {
        const btn = byId("refreshBtn", false);
        const prev = btn ? (btn.textContent || "Refresh") : "Refresh";
        if(btn){
          btn.disabled = true;
          btn.textContent = "Refreshing...";
        }
        try{
          const waitStart = Date.now();
          while(refreshRunning && (Date.now() - waitStart) < 8000){
            await waitMs(60);
          }
          await refreshAll({ showLoading: true, clearUsageCache: true });
        } finally {
          if(btn){
            btn.disabled = false;
            btn.textContent = prev;
          }
        }
      });
      byId("restartBtn").addEventListener("click", async ()=>{
        try{
          await loadAppUpdateStatus(true);
          await restartUiService();
        } catch(e){
          setError(e?.message || String(e));
        }
      });
      byId("killAllBtn").addEventListener("click", async ()=>{
        const ask = await openModal({
          title: "Kill All",
          body: "Stop all Codex Account Manager processes and close this page?\\n\\nThis will force-stop current operations.",
          okText: "Kill All",
          okClass: "btn-primary-danger",
          cancelText: "Cancel",
        });
        if(!ask || !ask.ok) return;
        const btn = byId("killAllBtn", false);
        const prev = btn ? (btn.textContent || "Kill All") : "Kill All";
        if(btn){
          btn.disabled = true;
          btn.textContent = "Killing...";
        }
        setError("");
        try{
          await postApi("/api/system/kill-all", {});
          setTimeout(() => {
            try { window.close(); } catch(_) {}
            try { location.replace("about:blank"); } catch(_) {}
          }, 160);
        } catch(e){
          setError(e?.message || String(e));
          if(btn){
            btn.disabled = false;
            btn.textContent = prev;
          }
        }
      });
      byId("themeSelect").addEventListener("change", async (e) => { applyTheme(e.target.value); await saveUiConfigPatch({ ui: { theme: e.target.value } }); });
      const updateBtn = byId("appUpdateBtn", false);
      if(updateBtn){
        updateBtn.addEventListener("click", ()=>openUpdateModal());
      }
      const themeBtn = byId("themeIconBtn", false);
      if(themeBtn){
        themeBtn.addEventListener("click", () => {
          const select = byId("themeSelect");
          const order = ["auto", "dark", "light"];
          const current = select.value || "auto";
          const idx = order.indexOf(current);
          const next = order[(idx + 1) % order.length];
          select.value = next;
          select.dispatchEvent(new Event("change", { bubbles: true }));
          updateHeaderThemeIcon(next);
        });
      }
      byId("currentAutoToggle").addEventListener("change", async (e)=>{
        await saveUiConfigPatch({ ui: { current_auto_refresh_enabled: !!e.target.checked } });
        resetTimer();
      });
      byId("currentIntervalInput").addEventListener("change", async ()=>{
        const v = Math.max(1, parseInt(byId("currentIntervalInput").value || "5", 10));
        byId("currentIntervalInput").value = String(v);
        await saveUiConfigPatch({ ui: { current_refresh_interval_sec: v } });
        resetTimer();
      });
      byId("allAutoToggle").addEventListener("change", async (e)=>{
        await saveUiConfigPatch({ ui: { all_auto_refresh_enabled: !!e.target.checked } });
        resetTimer();
      });
      byId("allIntervalInput").addEventListener("change", async ()=>{
        const v = Math.max(1, Math.min(60, parseInt(byId("allIntervalInput").value || "5", 10)));
        byId("allIntervalInput").value = String(v);
        await saveUiConfigPatch({ ui: { all_refresh_interval_min: v } });
        resetTimer();
      });
      initSteppers(document);
      setImportFileLabel("Choose a migration archive to review and import.");
      byId("addAccountBtn").addEventListener("click", async ()=>{
        pushOverlayLog("ui", "ui.click add_account");
        setError("");
        openAddDeviceModal({ reset:true });
      });
      byId("exportProfilesBtn").addEventListener("click", ()=>openExportProfilesModal());
      byId("importProfilesBtn").addEventListener("click", async ()=>{
        const warning = await openModal({
          title: "Import Profiles",
          body: "Imported data may grant account access and should only come from a trusted source. Keep exported files private, do not share them with other people, and use this feature at your own risk.\\n\\nContinue and choose an archive file?",
          okText: "Choose Archive",
          okClass: "btn-warning",
        });
        if(!warning || !warning.ok) return;
        byId("importProfilesInput").click();
      });
      byId("importProfilesInput").addEventListener("change", async (e)=>{
        const file = e?.target?.files && e.target.files[0] ? e.target.files[0] : null;
        if(!file) return;
        try{
          await runAction("local.import_profiles.analyze", ()=>startProfilesImportFlow(file), { skipRefresh:true });
        } finally {
          e.target.value = "";
        }
      });
      byId("addDeviceStartBtn").addEventListener("click", async ()=>{
        const name = getAddDeviceProfileName();
        if(!name) return;
        setError("");
        pushOverlayLog("ui", "ui.submit add_account.device", { profile: name });
        try{
          await startAddDeviceFlow(name);
        } catch(e){
          const msg = e?.message || String(e);
          setError(msg);
          pushOverlayLog("error", "device_auth.start_failed", { profile: name, error: msg });
          updateAddDeviceModal({ status:"failed", error: msg, message: msg, url: null, code: null });
        }
      });
      byId("addDeviceCopyBtn").addEventListener("click", async ()=>{
        const text = (addDeviceSessionState?.url || addDeviceSessionState?.code || "").trim();
        if(!text){ setError("No link/code available yet."); return; }
        try{
          const ok = await copyText(text);
          if(!ok){ setError("Failed to copy to clipboard."); return; }
          pushOverlayLog("ui", "device_auth.copy", { kind: addDeviceSessionState?.url ? "url" : "code" });
        } catch(e){
          setError("Failed to copy to clipboard.");
        }
      });
      byId("addDeviceOpenBtn").addEventListener("click", ()=>{
        const url = (addDeviceSessionState?.url || "").trim();
        if(!url){ setError("Login URL is not ready yet."); return; }
        window.open(url, "_blank", "noopener,noreferrer");
        pushOverlayLog("ui", "device_auth.open_browser");
      });
      byId("addDeviceLegacyBtn").addEventListener("click", async ()=>{
        const name = getAddDeviceProfileName();
        if(!name) return;
        if(addDeviceSessionId){
          try { await postApi("/api/local/add/cancel", { id: addDeviceSessionId }); } catch(_) {}
        }
        closeAddDeviceModal();
        pushOverlayLog("ui", "device_auth.fallback_normal_login", { profile: name });
        await runAction("local.add", ()=>postApi("/api/local/add", { name, timeout: 600, device_auth: false }));
      });
      byId("addDeviceCancelBtn").addEventListener("click", async ()=>{
        if(addDeviceSessionId){
          try { await postApi("/api/local/add/cancel", { id: addDeviceSessionId }); } catch(_) {}
        }
        closeAddDeviceModal();
      });
      const addDeviceNameInput = byId("addDeviceNameInput", false);
      if(addDeviceNameInput){
        addDeviceNameInput.addEventListener("input", () => {
          addDeviceProfileName = String(addDeviceNameInput.value || "").trim();
        });
        addDeviceNameInput.addEventListener("keydown", (e) => {
          if(e.key !== "Enter") return;
          e.preventDefault();
          byId("addDeviceStartBtn", false)?.click();
        });
      }
      const exportLogsBtn = byId("exportLogsBtn", false);
      if(exportLogsBtn) exportLogsBtn.addEventListener("click", exportDebugSnapshot);
      byId("removeAllBtn").addEventListener("click", async ()=>{
        const c1 = await openModal({ title:"Remove All Profiles", body:"Remove ALL saved profiles?\\n\\nThis cannot be undone." });
        if(!c1 || !c1.ok) return;
        const c2 = await openModal({ title:"Final Confirmation", body:"Delete all account profiles now?" });
        if(!c2 || !c2.ok) return;
        await runAction("local.remove_all", ()=>postApi("/api/local/remove-all", {}));
      });
      byId("colSettingsBtn").addEventListener("click", (e)=>{ e.stopPropagation(); openColumnsModal(); });
      byId("columnsDoneBtn").addEventListener("click", ()=>closeColumnsModal());
      byId("exportProfilesCancelBtn").addEventListener("click", ()=>closeExportProfilesModal());
      byId("exportProfilesConfirmBtn").addEventListener("click", ()=>runAction("local.export_profiles", ()=>startProfilesExportFlow(), { skipRefresh:true }));
      byId("exportSelectAllBtn").addEventListener("click", ()=>toggleAllExportProfiles(true));
      byId("exportUnselectAllBtn").addEventListener("click", ()=>toggleAllExportProfiles(false));
      byId("exportHeaderCheckbox").addEventListener("change", (e)=>toggleAllExportProfiles(!!e.target.checked));
      byId("columnsResetBtn").addEventListener("click", ()=>{
        columnPrefs = { ...defaultColumns };
        saveColumnPrefs();
        applyColumnVisibility();
        renderColumnsModal();
      });
      byId("alarmPresetCancelBtn").addEventListener("click", ()=>closeAlarmPresetModal());
      byId("alarmPresetUseBtn").addEventListener("click", ()=>applyAlarmPresetSelection().catch((e)=>setError(e?.message || String(e))));
      byId("importReviewCloseBtn").addEventListener("click", ()=>closeImportReviewModal());
      byId("importReviewCancelBtn").addEventListener("click", ()=>closeImportReviewModal());
      byId("importReviewApplyBtn").addEventListener("click", async ()=>{
        if(!importReviewState) return;
        const risky = (importReviewState.profiles || []).some((row) => row.action === "overwrite");
        if(risky){
          const confirmOverwrite = await openModal({
            title: "Confirm Import Apply",
            body: "One or more profiles will overwrite existing saved profiles. Keep exported data private, do not share it with other people, and use this feature at your own risk.\\n\\nApply this import now?",
            okText: "Apply Import",
            okClass: "btn-primary-danger",
          });
          if(!confirmOverwrite || !confirmOverwrite.ok) return;
        }
        await runAction("local.import_profiles.apply", async ()=>{
          const payload = await postApi("/api/local/import/apply", {
            analysis_id: importReviewState.analysis_id,
            profiles: importReviewState.profiles,
          });
          closeImportReviewModal();
          const summary = payload?.summary || {};
          showInAppNotice("Import Complete", `Imported ${summary.imported || 0}, skipped ${summary.skipped || 0}, overwritten ${summary.overwritten || 0}, failed ${summary.failed || 0}.`, { duration_ms: 9000 });
          await refreshAll({ showLoading:false, clearUsageCache:true });
        }, { skipRefresh:true });
      });
      byId("rowActionsCloseBtn").addEventListener("click", ()=>closeRowActionsModal());
      byId("rowActionsRenameBtn").addEventListener("click", async ()=>{
        const name = activeRowActionsName;
        closeRowActionsModal();
        if(!name) return;
        await renameProfileFlow(name);
      });
      byId("rowActionsRemoveBtn").addEventListener("click", async ()=>{
        const name = activeRowActionsName;
        closeRowActionsModal();
        if(!name) return;
        await removeProfileFlow(name);
      });
      byId("debugToggle").addEventListener("change", async ()=>{
        const on=!!byId("debugToggle").checked;
        await saveUiConfigPatch({ ui: { debug_mode: on } });
        updateHeaderDebugIcon(on);
        byId("debugRuntimeSection").style.display = on ? "block" : "none";
        if(on) await loadDebugLogs();
      });
      const debugBtn = byId("debugIconBtn", false);
      if(debugBtn){
        debugBtn.addEventListener("click", () => {
          const debugInput = byId("debugToggle");
          debugInput.checked = !debugInput.checked;
          debugInput.dispatchEvent(new Event("change", { bubbles: true }));
        });
      }
      byId("alarmToggle").addEventListener("change", ()=> saveUiConfigPatch({ notifications: { enabled: !!byId("alarmToggle").checked } }).catch((e)=>setError(e?.message || String(e))));
      byId("alarm5h").addEventListener("change", ()=> saveUiConfigPatch({ notifications: { thresholds: { h5_warn_pct: Math.max(0, Math.min(100, parseInt(byId("alarm5h").value || "20", 10))) } } }).catch((e)=>setError(e?.message || String(e))));
      byId("alarmWeekly").addEventListener("change", ()=> saveUiConfigPatch({ notifications: { thresholds: { weekly_warn_pct: Math.max(0, Math.min(100, parseInt(byId("alarmWeekly").value || "20", 10))) } } }).catch((e)=>setError(e?.message || String(e))));
      byId("chooseAlarmBtn").addEventListener("click", ()=>openAlarmPresetModal());
      byId("testAlarmBtn").addEventListener("click", async ()=>{
        try{
          await previewAlarmPreset(getSelectedAlarmPresetId(), { message: `Testing ${getSelectedAlarmPresetLabel()}. This preview uses the current warning alarm.` });
        } catch(e){
          setError(e?.message || String(e));
        }
      });
      byId("asEnabled").addEventListener("change", async ()=>{
        const next = !!byId("asEnabled").checked;
        const rankingNow = String(byId("asRanking", false)?.value || latestData?.config?.auto_switch?.ranking_mode || "balanced");
        updateRankingModeUI(rankingNow, next);
        pendingAutoSwitchEnabled = next;
        try{
          await runAction("auto_switch.enable", ()=>postApi("/api/auto-switch/enable", { enabled: next }));
        } finally {
          pendingAutoSwitchEnabled = null;
        }
      });
      byId("asRunSwitchBtn").addEventListener("click", ()=> runAction("auto_switch.run_switch", ()=>postApi("/api/auto-switch/run-switch", {})));
      byId("asRapidTestBtn").addEventListener("click", ()=> runAction("auto_switch.rapid_test", ()=>postApi("/api/auto-switch/rapid-test", {})));
      byId("asForceStopBtn").addEventListener("click", ()=> runAction("auto_switch.stop_tests", ()=>postApi("/api/auto-switch/stop-tests", {})));
      byId("asTestAutoSwitchBtn").addEventListener("click", async ()=>{
        const ask = await openModal({
          title: "Test Auto Switch",
          body: "Temporary 5H threshold % for test (optional). Leave empty to use current value.",
          input: true,
          inputPlaceholder: "e.g. 59",
        });
        if(!ask || !ask.ok) return;
        const raw = String(ask.value || "").trim();
        let threshold = null;
        if(raw){
          const n = parseInt(raw, 10);
          if(!Number.isFinite(n)){
            setError("Test threshold must be a number.");
            return;
          }
          threshold = Math.max(0, Math.min(100, n));
        }
        const btn = byId("asTestAutoSwitchBtn", false);
        const prevTxt = btn ? btn.textContent : "";
        if(btn){
          btn.disabled = true;
          btn.textContent = "Testing...";
        }
        setError("");
        try{
          const data = await postApi("/api/auto-switch/test", {
            threshold_5h: threshold,
            timeout_sec: 30,
          });
          const used = data?.used_threshold_5h;
          const switched = !!data?.switched;
          let body = `Used 5H threshold: ${used ?? "(current)"}%\\nTimeout: ${data?.timeout_sec ?? 30}s`;
          if(switched){
            const ev = data?.event || {};
            body += `\\n\\nResult: switched\\nEvent: ${ev.message || "auto-switched"}`;
          } else {
            body += `\\n\\nResult: no switch event within timeout.\\nCheck System.Out for warning/no-candidate details.`;
          }
          await openModal({ title: "Auto Switch Test Result", body });
        } catch(e){
          setError(e?.message || String(e));
        } finally {
          if(btn){
            btn.disabled = false;
            btn.textContent = prevTxt || "Test Auto Switch";
          }
        }
      });
      byId("asChainEditBtn").addEventListener("click", ()=>openChainEditModal());
      byId("chainEditCancelBtn").addEventListener("click", ()=>closeChainEditModal());
      byId("chainEditSaveBtn").addEventListener("click", async ()=>{
        setError("");
        const startedAt = Date.now();
        const payloadChain = ensureLockedChainOrder(chainEditNames);
        const saveBtn = byId("chainEditSaveBtn", false);
        const cancelBtn = byId("chainEditCancelBtn", false);
        const chainBox = byId("asChainPreview", false);
        const prevSaveTxt = saveBtn ? saveBtn.textContent : "";
        if(saveBtn){
          saveBtn.disabled = true;
          saveBtn.textContent = "Saving...";
        }
        if(cancelBtn) cancelBtn.disabled = true;
        if(chainBox) chainBox.style.opacity = "0.55";
        pushOverlayLog("ui", "action.start auto_switch.chain.save");
        try{
          await postApi("/api/auto-switch/chain", { chain: payloadChain });
          const rankingEl = byId("asRanking", false);
          if(rankingEl){
            rankingEl.value = "manual";
            rankingEl.dataset.dirty = "0";
          }
          if(latestData?.config?.auto_switch){
            latestData.config.auto_switch.ranking_mode = "manual";
          }
          updateRankingModeUI("manual", !!byId("asEnabled", false)?.checked);
          const liveChain = await safeGet("/api/auto-switch/chain");
          if(liveChain && !liveChain.__error){
            latestData.autoChain = liveChain;
            renderChainPreview(liveChain);
          } else {
            const fallbackPayload = {
              chain: payloadChain,
              items: payloadChain.map((n)=>({ name:n, remaining_5h:null, remaining_weekly:null })),
              manual_chain: payloadChain,
              chain_text: payloadChain.join(" -> ") || "-",
            };
            latestData.autoChain = fallbackPayload;
            renderChainPreview(fallbackPayload);
          }
          closeChainEditModal();
          pushOverlayLog("ui", "action.success auto_switch.chain.save", { duration_ms: Date.now() - startedAt });
          setTimeout(()=>{ refreshAll().catch(()=>{}); }, 0);
        } catch(e){
          const msg = e?.message || String(e);
          pushOverlayLog("error", "action.fail auto_switch.chain.save", { error: msg, duration_ms: Date.now() - startedAt });
          setError(msg);
        } finally {
          if(chainBox) chainBox.style.opacity = "";
          if(saveBtn){
            saveBtn.disabled = false;
            saveBtn.textContent = prevSaveTxt || "Save";
          }
          if(cancelBtn) cancelBtn.disabled = false;
        }
      });
      const saveAutoSwitchTiming = async () => {
        if(autoSwitchTimingSaveTimer){
          clearTimeout(autoSwitchTimingSaveTimer);
          autoSwitchTimingSaveTimer = null;
        }
        const cfgAuto = latestData?.config?.auto_switch || {};
        const delay = intOrDefault(byId("asDelay").value, cfgAuto.delay_sec ?? 60, 0, 3600);
        byId("asDelay").value = String(delay);
        try{
          await saveUiConfigPatch({ auto_switch: { delay_sec: delay } });
          if(latestData?.config?.auto_switch){
            latestData.config.auto_switch.delay_sec = delay;
          }
          const d1 = byId("asDelay", false);
          if(d1) d1.dataset.dirty = "0";
        } catch(e){
          setError(e?.message || String(e));
        }
      };
      const scheduleAutoSwitchTimingSave = () => {
        if(autoSwitchTimingSaveTimer) clearTimeout(autoSwitchTimingSaveTimer);
        autoSwitchTimingSaveTimer = setTimeout(() => {
          autoSwitchTimingSaveTimer = null;
          saveAutoSwitchTiming();
        }, 320);
      };
      ["asDelay"].forEach((id) => {
        const el = byId(id, false);
        if(!el) return;
        el.addEventListener("input", scheduleAutoSwitchTimingSave);
        el.addEventListener("change", saveAutoSwitchTiming);
      });
      const saveSelectionPolicy = async () => {
        if(autoSwitchPolicySaveTimer){
          clearTimeout(autoSwitchPolicySaveTimer);
          autoSwitchPolicySaveTimer = null;
        }
        const cfgAuto = latestData?.config?.auto_switch || {};
        const cfgThr = cfgAuto.thresholds || {};
        const patch = {
          auto_switch: {
            ranking_mode: byId("asRanking").value || (cfgAuto.ranking_mode || "balanced"),
            thresholds: {
              h5_switch_pct: intOrDefault(byId("as5h").value, cfgThr.h5_switch_pct ?? 20, 0, 100),
              weekly_switch_pct: intOrDefault(byId("asWeekly").value, cfgThr.weekly_switch_pct ?? 20, 0, 100),
            },
          },
        };
        await saveUiConfigPatch(patch);
        if(latestData?.config?.auto_switch){
          latestData.config.auto_switch.ranking_mode = patch.auto_switch.ranking_mode;
          latestData.config.auto_switch.thresholds = {
            ...(latestData.config.auto_switch.thresholds || {}),
            ...patch.auto_switch.thresholds,
          };
        }
        ["as5h","asWeekly","asRanking"].forEach((id) => {
          const el = byId(id, false);
          if(el) el.dataset.dirty = "0";
        });
      };
      const scheduleSelectionPolicySave = () => {
        if(autoSwitchPolicySaveTimer) clearTimeout(autoSwitchPolicySaveTimer);
        autoSwitchPolicySaveTimer = setTimeout(() => {
          autoSwitchPolicySaveTimer = null;
          saveSelectionPolicy().catch((e)=>setError(e?.message || String(e)));
        }, 320);
      };
      ["as5h","asWeekly"].forEach((id) => {
        const el = byId(id, false);
        if(!el) return;
        el.addEventListener("input", scheduleSelectionPolicySave);
        el.addEventListener("change", ()=>saveSelectionPolicy().catch((e)=>setError(e?.message || String(e))));
      });
      const rankingEl = byId("asRanking", false);
      if(rankingEl){
        rankingEl.addEventListener("change", ()=>{
          updateRankingModeUI(rankingEl.value, !!byId("asEnabled", false)?.checked);
          saveSelectionPolicy().catch((e)=>setError(e?.message || String(e)));
        });
      }
      byId("asAutoArrangeBtn").addEventListener("click", async ()=>{
        const rankingEl = byId("asRanking", false);
        if(rankingEl) rankingEl.value = "balanced";
        updateRankingModeUI("balanced", !!byId("asEnabled", false)?.checked);
        const btn = byId("asAutoArrangeBtn", false);
        const prevTxt = btn ? btn.textContent : "";
        setError("");
        if(btn){
          btn.disabled = true;
          btn.textContent = "Arranging...";
        }
        try{
          if(autoSwitchPolicySaveTimer){
            clearTimeout(autoSwitchPolicySaveTimer);
            autoSwitchPolicySaveTimer = null;
          }
          await saveSelectionPolicy();
          const data = await postApi("/api/auto-switch/auto-arrange", {});
          const names = Array.isArray(data?.chain) ? data.chain : [];
          const items = Array.isArray(data?.items) ? data.items : [];
          const payload = {
            chain: names,
            items,
            manual_chain: Array.isArray(data?.manual_chain) ? data.manual_chain : names,
            chain_text: String(data?.chain_text || names.join(" -> ") || "-"),
          };
          latestData.autoChain = payload;
          renderChainPreview(payload);
          setTimeout(()=>{ refreshAll().catch(()=>{}); }, 0);
        } catch(e){
          setError(e?.message || String(e));
        } finally {
          if(btn){
            btn.disabled = false;
            btn.textContent = prevTxt || "Auto Arrange";
          }
        }
      });
      ["asDelay","as5h","asWeekly","asRanking"].forEach((id) => {
        const el = byId(id, false);
        if(!el) return;
        const markDirty = () => { el.dataset.dirty = "1"; };
        el.addEventListener("input", markDirty);
        el.addEventListener("change", markDirty);
      });
      byId("advStatusBtn").addEventListener("click", ()=>runAction("adv.status", ()=>callApi("/api/adv/status")));
      byId("advListBtn").addEventListener("click", ()=>runAction("adv.list", ()=>callApi("/api/adv/list?debug="+(byId("advListDebug").checked?"1":"0"))));
      byId("advLoginBtn").addEventListener("click", ()=>runAction("adv.login", ()=>postApi("/api/adv/login",{device_auth:byId("advLoginDevice").checked})));
      byId("advSwitchBtn").addEventListener("click", ()=>runAction("adv.switch", ()=>postApi("/api/adv/switch",{query:byId("advQuery").value.trim()})));
      byId("advRemoveBtn").addEventListener("click", ()=>runAction("adv.remove", ()=>postApi("/api/adv/remove",{query:byId("advQuery").value.trim(), all:byId("advRemoveAll").checked})));
      byId("advConfigBtn").addEventListener("click", ()=>runAction("adv.config", ()=>postApi("/api/adv/config",{scope:byId("advScope").value, action:byId("advAction").value, threshold_5h:byId("adv5h").value.trim()||null, threshold_weekly:byId("advWeekly").value.trim()||null})));
      byId("advImportBtn").addEventListener("click", ()=>runAction("adv.import", ()=>postApi("/api/adv/import",{path:byId("advImportPath").value.trim(), alias:byId("advImportAlias").value.trim(), cpa:byId("advImportCpa").checked, purge:byId("advImportPurge").checked})));
      byId("advDaemonOnceBtn").addEventListener("click", ()=>runAction("adv.daemon.once", ()=>postApi("/api/adv/daemon",{mode:"once"})));
      byId("advDaemonWatchBtn").addEventListener("click", ()=>runAction("adv.daemon.watch", ()=>postApi("/api/adv/daemon",{mode:"watch"})));
      byId("advCleanBtn").addEventListener("click", ()=>runAction("adv.clean", ()=>postApi("/api/adv/clean",{})));
      byId("advAuthBtn").addEventListener("click", ()=>runAction("adv.auth", ()=>postApi("/api/adv/auth",{args:byId("advAuthArgs").value.trim(), timeout:60})));
      byId("modalCancelBtn").addEventListener("click", ()=>modalCancelAction());
      byId("modalOkBtn").addEventListener("click", ()=>modalOkAction());
      byId("appUpdateCancelBtn").addEventListener("click", ()=>closeUpdateModal());
      byId("appUpdateConfirmBtn").addEventListener("click", ()=>runAppUpdateFlow().catch((e)=>setError(e?.message || String(e))));
      byId("modalBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("modalBackdrop")) closeModal({ ok:false }); });
      byId("appUpdateBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("appUpdateBackdrop")) closeUpdateModal(); });
      byId("addDeviceBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("addDeviceBackdrop")) closeAddDeviceModal(); });
      byId("alarmPresetBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("alarmPresetBackdrop")) closeAlarmPresetModal(); });
      byId("exportProfilesBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("exportProfilesBackdrop")) closeExportProfilesModal(); });
      byId("rowActionsBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("rowActionsBackdrop")) closeRowActionsModal(); });
      byId("chainEditBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("chainEditBackdrop")) closeChainEditModal(); });
      byId("importReviewBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("importReviewBackdrop")) closeImportReviewModal(); });
      document.addEventListener("keydown", (e)=>{
        const chainEditBackdrop = byId("chainEditBackdrop", false);
        if(chainEditBackdrop && chainEditBackdrop.style.display === "flex" && e.key === "Escape"){
          e.preventDefault();
          closeChainEditModal();
          return;
        }
        const importReviewBackdrop = byId("importReviewBackdrop", false);
        if(importReviewBackdrop && importReviewBackdrop.style.display === "flex" && e.key === "Escape"){
          e.preventDefault();
          closeImportReviewModal();
          return;
        }
        const alarmPresetBackdrop = byId("alarmPresetBackdrop", false);
        if(alarmPresetBackdrop && alarmPresetBackdrop.style.display === "flex" && e.key === "Escape"){
          e.preventDefault();
          closeAlarmPresetModal();
          return;
        }
        const exportProfilesBackdrop = byId("exportProfilesBackdrop", false);
        if(exportProfilesBackdrop && exportProfilesBackdrop.style.display === "flex" && e.key === "Escape"){
          e.preventDefault();
          closeExportProfilesModal();
          return;
        }
        const appUpdateBackdrop = byId("appUpdateBackdrop", false);
        if(appUpdateBackdrop && appUpdateBackdrop.style.display === "flex" && e.key === "Escape"){
          e.preventDefault();
          closeUpdateModal();
          return;
        }
        const backdrop = byId("modalBackdrop", false);
        if(!backdrop || backdrop.style.display !== "flex") return;
        if(e.key === "Escape"){
          e.preventDefault();
          modalCancelAction();
          return;
        }
        if(e.key === "Enter"){
          const t = e.target;
          if(t && (t.tagName === "TEXTAREA")) return;
          e.preventDefault();
          modalOkAction();
        }
      });
      byId("columnsModalBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("columnsModalBackdrop")) closeColumnsModal(); });
      applyAppUpdateStatus({ update_available: false, latest_version: "", current_version: `v${UI_VERSION}` });
      renderColumnsModal();
      updateExportSelectedSummary();
      applyColumnVisibility();
      initSteppers(document);
      renderSortIndicators();
      const bootSnapshot = loadBootSnapshot();
      if(bootSnapshot && typeof bootSnapshot === "object"){
        if(bootSnapshot.config && !latestData.config){
          latestData.config = bootSnapshot.config;
          applyConfigToControls(bootSnapshot.config);
          renderColumnsModal();
          applyColumnVisibility();
        }
        if(bootSnapshot.usage && !latestData.usage){
          latestData.usage = bootSnapshot.usage;
          renderTable(bootSnapshot.usage);
        }
      }
      document.querySelectorAll("th[data-sort]").forEach(th => th.addEventListener("click", ()=>{
        const key=th.dataset.sort;
        if(sortState.key===key) sortState.dir=sortState.dir==="asc"?"desc":"asc";
        else sortState={key,dir:"desc"};
        localStorage.setItem("codex_sort_state", JSON.stringify(sortState));
        renderSortIndicators();
        if(latestData.usage) renderTable(latestData.usage);
      }));
      await refreshAll({ showLoading: true, clearUsageCache: true });
      await loadAppUpdateStatus(false);
      resetTimer();
      resetRemainTicker();
      eventsTimer = setInterval(async ()=>{
        const eventsPayload = await safeGet("/api/events?since_id="+encodeURIComponent(String(lastEventId)));
        if(eventsPayload.__error) return;
        const incoming = eventsPayload.events || [];
        if(incoming.length){
          for(const ev of incoming){
            await maybeNotify(ev);
            lastEventId = Math.max(lastEventId, Number(ev.id || 0));
            latestData.events.push(ev);
            pushOverlayLog("event", `${ev.type || "event"}: ${ev.message || ""}`, ev.details || null);
          }
          renderEvents(latestData.events);
        }
      }, 1500);
      window.__camBootState.booted = true;
      window.__camBootState.lastError = null;
      window.__camBootState.ts = Date.now();
    } catch(e) {
      window.__camBootState.booted = false;
      window.__camBootState.lastError = e?.message || String(e);
      window.__camBootState.ts = Date.now();
      showFatal(e);
    }
  }
  init();
  </script>
</body>
</html>"""
    html = html.replace("__TOKEN_JSON__", token_json)
    html = html.replace("__INTERVAL_JSON__", interval_json)
    html = html.replace("__INTERVAL_INT__", str(int(default_interval)))
    html = html.replace("__UI_VERSION__", APP_VERSION)
    html = html.replace("__UI_VERSION_JSON__", version_json)
    html = html.replace("__ALARM_PRESETS_JSON__", alarm_presets_json)
    return html


def render_ui_sw_js() -> str:
    script = """self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
  try { event.notification.close(); } catch(_) {}
  const targetUrl = "/?v=__UI_VERSION__";
  event.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of allClients) {
      try {
        if (client && "focus" in client) {
          await client.focus();
          if ("navigate" in client) await client.navigate(targetUrl);
          return;
        }
      } catch(_) {}
    }
    if (clients.openWindow) {
      await clients.openWindow(targetUrl);
    }
  })());
});"""
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
        now = time.time()
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
            "cooldown_remaining_sec": max(0, int(cooldown_until - now)) if cooldown_until else 0,
            "last_switch_at": runtime.get("last_switch_ts"),
            "last_switch_at_text": epoch_to_text(runtime.get("last_switch_ts")),
            "events_count": len(runtime["events"]),
            "config_enabled": bool(((cfg.get("auto_switch") or {}).get("enabled"))),
            "rapid_test_active": bool(runtime.get("rapid_test_active", False)),
            "rapid_test_started_at": runtime.get("rapid_test_started_at"),
            "rapid_test_started_at_text": epoch_to_text(runtime.get("rapid_test_started_at")),
            "rapid_test_wait_sec": runtime.get("rapid_test_wait_sec"),
            "rapid_test_step": int(runtime.get("rapid_test_step") or 0),
            "test_run_active": bool(runtime.get("test_run_active", False)),
        }

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
                push_event("rapid-test", f"step {step}: switching '{current_name}' -> '{target}' in {wait_sec}s", {"step": step, "current": current_name, "target": target})
                while not runtime["rapid_test_stop"].is_set():
                    due = float(runtime.get("pending_switch_due_at") or 0.0)
                    if due <= 0.0 or time.time() >= due:
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
        except Exception as e:
            push_event("error", f"rapid-test exception: {e}")
        finally:
            runtime["rapid_test_active"] = False
            runtime["rapid_test_started_at"] = None
            runtime["rapid_test_step"] = 0
            runtime["rapid_test_wait_sec"] = None
            runtime["pending_warning"] = None
            runtime["pending_switch_due_at"] = None
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
                    push_event("warning", f"usage threshold reached for '{current_name}'", detail)
                    runtime["last_eval_ok"] = True
                    runtime["stop_event"].wait(1.0)
                    continue
                due = runtime.get("pending_switch_due_at") or now
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
                helper_code = (
                    "import subprocess,time,sys; "
                    "time.sleep(0.45); "
                    "sys.exit(subprocess.call(sys.argv[1:]))"
                )
                cmd = [
                    sys.executable,
                    "-c",
                    helper_code,
                    sys.executable,
                    str(Path(__file__).resolve()),
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
            if parsed.path == "/" or parsed.path == "/index.html":
                html = render_ui_html(interval_sec, token)
                self._reply(200, html, "text/html; charset=utf-8")
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


def _autostart_command(no_open: bool = True) -> list[str]:
    cmd = [sys.executable, str(Path(__file__).resolve()), "ui-service", "start"]
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
