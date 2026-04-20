#!/usr/bin/env python3
import argparse
import base64
import copy
import contextlib
import datetime as dt
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
APP_CANDIDATES = ("Codex", "CodexBar")
UI_BUILD_VERSION = hashlib.sha1(f"{Path(__file__).resolve()}:{Path(__file__).stat().st_mtime_ns}".encode("utf-8")).hexdigest()[:12]
DEFAULT_APP_VERSION = "0.0.6"
AUTO_SWITCH_MIN_INTERNAL_COOLDOWN_SEC = 20


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
                subprocess.run(
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
        res = subprocess.run(
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
        "auto_refresh": True,
        "refresh_interval_sec": 5,
        "debug_mode": False,
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
ADD_LOGIN_SESSIONS: dict[str, dict] = {}
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


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


def cam_log(level: str, message: str, details=None, echo: bool = False) -> None:
    try:
        ensure_dirs()
        payload = {
            "ts": dt.datetime.now().isoformat(),
            "level": str(level).lower(),
            "message": str(message),
            "details": details if details is not None else {},
        }
        with CAM_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if echo:
            print(f"[cam:{payload['level']}] {payload['message']}")
    except Exception:
        pass


def read_log_tail(max_lines: int = 300):
    try:
        if not CAM_LOG_FILE.exists():
            return []
        raw = CAM_LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = raw[-max_lines:]
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
    if isinstance(raw, dict):
        deep_merge(cfg, raw)

    ui = cfg.get("ui", {})
    ui["theme"] = ui.get("theme") if ui.get("theme") in ("dark", "light", "auto") else "auto"
    ui["advanced_mode"] = bool(ui.get("advanced_mode", False))
    ui["auto_refresh"] = bool(ui.get("auto_refresh", True))
    ui["refresh_interval_sec"] = clamp_int(ui.get("refresh_interval_sec"), 5, minimum=1, maximum=3600)
    ui["debug_mode"] = bool(ui.get("debug_mode", False))
    cfg["ui"] = ui

    notif = cfg.get("notifications", {})
    notif["enabled"] = bool(notif.get("enabled", False))
    notif["scope"] = notif.get("scope") if notif.get("scope") in ("any", "5h", "weekly") else "any"
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
        atomic_write_json(CAM_CONFIG_FILE, norm)
        return norm


def update_cam_config(patch: dict) -> dict:
    with CAM_CONFIG_LOCK:
        cfg = load_cam_config()
        if not isinstance(patch, dict):
            return cfg
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
        return None, None, f"bad auth json: {e}"

    tokens = data.get("tokens", {}) if isinstance(data.get("tokens"), dict) else {}
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not access_token or not account_id:
        return None, None, "missing access_token/account_id"

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
        return None, None, f"http {e.code}"
    except Exception as e:
        return None, None, f"request failed: {e}"

    usage_5h, usage_weekly = extract_usage_windows(payload)
    return usage_5h, usage_weekly, None


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


def account_id_from_auth(path: Path):
    try:
        data = load_json(path)
    except Exception:
        return None
    account_id = data.get("account_id")
    if not account_id and isinstance(data.get("tokens"), dict):
        account_id = data["tokens"].get("account_id")
    return str(account_id) if account_id else None


def principal_id_from_auth(path: Path):
    try:
        data = load_json(path)
    except Exception:
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
    account_id = data.get("account_id")
    if not account_id and isinstance(data.get("tokens"), dict):
        account_id = data["tokens"].get("account_id")
    if account_id:
        return f"account_id:{account_id}"
    return None


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
            p = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {image}"],
                capture_output=True,
                text=True,
            )
            if p.returncode != 0:
                return False
            return image in p.stdout.lower()
        if shutil.which("pgrep"):
            p = subprocess.run(
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
            subprocess.run(["osascript", "-e", f'tell application "{app_name}" to quit'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            touched = True
        for proc_pattern in candidates.get(app_name, []):
            if sys.platform.startswith("win"):
                image = Path(proc_pattern).name
                if not image.lower().endswith(".exe"):
                    image = f"{image}.exe"
                subprocess.run(["taskkill", "/F", "/T", "/IM", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                touched = True
            elif shutil.which("pkill"):
                subprocess.run(["pkill", "-f", proc_pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                touched = True
            elif shutil.which("killall"):
                subprocess.run(["killall", "-q", Path(proc_pattern).name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                subprocess.run([ps, "-NoProfile", "-Command", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                touched = True
            except Exception:
                pass
    for _ in range(20):
        if not codex_running():
            break
        time.sleep(0.15)
    return touched


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
        proc = subprocess.run([ps, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=3)
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
        proc = subprocess.run([ps, "-NoProfile", "-Command", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
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
            p = subprocess.run(["open", "-a", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if p.returncode == 0:
                return True
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
        proc = subprocess.run(
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
        proc = subprocess.run(
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
            proc = subprocess.run(
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
        proc = subprocess.run(
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
        subprocess.run(
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
    return subprocess.call(cmd)


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
        if timeout_sec is not None:
            kwargs["timeout"] = timeout_sec
        proc = subprocess.run(cmd, **kwargs)
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
    target_dir = PROFILES_DIR / name
    if target_dir.exists() and not overwrite:
        raise RuntimeError(f"Profile '{name}' already exists. Use --force to overwrite.")

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
        proc = subprocess.run(login_cmd, env=env, timeout=timeout)
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


def collect_usage_local_data(timeout_sec: int, config: dict | None = None):
    ensure_dirs()
    profiles = sorted([p for p in PROFILES_DIR.iterdir() if p.is_dir()])
    if not profiles:
        return {"refreshed_at": dt.datetime.now().isoformat(), "current_profile": None, "profiles": []}
    cfg = config if isinstance(config, dict) else load_cam_config()
    eligibility = ((cfg.get("profiles") or {}).get("eligibility") or {})

    def canonical_auth(path: Path):
        try:
            data = load_json(path)
            return json.dumps(data, sort_keys=True, separators=(",", ":"))
        except Exception:
            return None

    active_canonical = canonical_auth(AUTH_FILE) if AUTH_FILE.exists() else None
    json_rows = []
    current_profile = None
    for p in profiles:
        auth_path = p / "auth.json"
        meta_path = p / "meta.json"
        display_email = "-"
        saved_at = None
        try:
            data = load_json(auth_path)
            tokens = data.get("tokens", {}) if isinstance(data.get("tokens"), dict) else {}
            id_token = tokens.get("id_token") or data.get("id_token")
            if isinstance(id_token, str) and id_token:
                payload = decode_jwt_payload(id_token) or {}
                maybe_email = payload.get("email")
                if maybe_email:
                    display_email = str(maybe_email)
        except Exception:
            pass
        if meta_path.exists():
            try:
                meta = load_json(meta_path)
                saved_at = meta.get("saved_at")
            except Exception:
                saved_at = None
        account_id = account_id_from_auth(auth_path) or "-"
        principal_id = principal_id_from_auth(auth_path)
        usage_5h, usage_weekly, err = fetch_usage_from_auth(auth_path, timeout_sec=timeout_sec)
        cell_5h = format_usage_cell(*(usage_5h or (None, None)))
        cell_weekly = format_usage_cell(*(usage_weekly or (None, None)))
        is_current = active_canonical is not None and canonical_auth(auth_path) == active_canonical
        if is_current:
            current_profile = p.name
        same = len(find_same_principal_profiles(principal_id, exclude_name=p.name)) > 0
        json_rows.append(
            {
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
                "is_current": is_current,
                "same_principal": same,
                "error": err or None,
                "saved_at": saved_at,
                "auto_switch_eligible": bool(eligibility.get(p.name, False)),
            }
        )
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


def restart_codex_app() -> bool:
    running_app = None
    running_exec_path = ""
    try:
        running_app = detect_running_app_name()
    except Exception:
        running_app = None
    if sys.platform.startswith("win"):
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
    _log_runtime_safe("info", "restart final result", {"started": bool(started), "running_app": running_app, "running_exec_path": running_exec_path})
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
    return subprocess.call(cmd, env=env)


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


def _json_error(code: str, message: str, status: int = 400, details=None):
    payload = {"ok": False, "error": {"code": code, "message": message}}
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
    return {
        "command": name,
        "exit_code": rc,
        "stdout": stdout,
        "stderr": stderr,
    }


def render_ui_html(default_interval: float, token: str) -> str:
    token_json = json.dumps(token)
    interval_json = json.dumps(default_interval)
    version_json = json.dumps(APP_VERSION)
    html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
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
      --log-ts:#7e8b90;
      --log-info:#b7e3ff;
      --log-warn:#ffd16c;
      --log-error:#ff8a8a;
      --log-event:#b5f5d0;
      --log-command:#89fff8;
      --log-detail:#aab7bc;
    }
    [data-theme=\"light\"]{
      --surface:#edf1f5; --surface-low:#ffffff; --surface-card:#f6f9fc; --surface-high:#eaf0f5; --surface-highest:#dfe7ef; --surface-black:#f5f8fb;
      --text:#17202a; --text-soft:#4c5968; --line:rgba(46,58,72,.2);
      --primary:#0d8a44; --primary-container:#2fc56f; --on-primary:#02260f;
      --ok:#0d8a44; --warn:#9a6e00; --danger:#b4232c;
      --ambient:0 12px 34px rgba(20,28,40,.08);
      --bg-grad:radial-gradient(1100px 500px at 85% -20%, rgba(17,153,75,.08), transparent 65%), radial-gradient(900px 420px at 10% 0%, rgba(172,125,0,.05), transparent 70%);
      --topbar-bg:rgba(255,255,255,.94);
      --line-soft:rgba(46,58,72,.25);
      --line-strong:rgba(46,58,72,.34);
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
      --danger-bg:rgba(180,35,44,.1);
      --danger-bg-hover:rgba(180,35,44,.15);
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
      font-size:16px;
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
    .header-icon-btn svg{width:16px;height:16px;display:block;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
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
    .group-title,.rules-title{font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:.12em}
    .settings-card{padding:14px 14px 12px;gap:12px}
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
    .btn-block{width:100%;display:flex;align-items:center;justify-content:center}
    .settings-footer-btn{margin-top:auto}
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
    @media (max-width:760px){.controls-grid,.rules-grid,.grid-2,.grid-3{grid-template-columns:1fr}}
    .btn,button,input,select{font-family:Inter,\"Segoe UI\",-apple-system,sans-serif}
    .btn,button{border:1px solid var(--line);background:var(--surface-highest);color:var(--text);border-radius:var(--radius);padding:8px 11px;cursor:pointer;transition:background .15s,opacity .15s,color .15s}
    .btn:hover,button:hover{background:var(--surface-high)}
    .btn-primary{
      background:linear-gradient(90deg,var(--primary),var(--primary-container));
      border:0;
      color:var(--on-primary);
      font-weight:700;
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.08);
    }
    .btn-primary:hover{
      background:linear-gradient(90deg,color-mix(in srgb,var(--primary) 94%, #fff 6%),color-mix(in srgb,var(--primary-container) 94%, #fff 6%));
      box-shadow:inset 0 0 0 1px rgba(0,0,0,.12);
    }
    .btn-danger{color:var(--danger)}
    .btn-disabled,button:disabled{opacity:.45;cursor:not-allowed;pointer-events:none}
    .toggle{display:inline-flex;align-items:center;gap:8px}
    .toggle input{appearance:none;width:38px;height:20px;border-radius:999px;background:var(--surface-highest);position:relative;border:1px solid var(--line);cursor:pointer}
    .toggle input::after{content:\"\";position:absolute;left:2px;top:2px;width:14px;height:14px;border-radius:999px;background:#e5e2e1;transition:transform .15s ease}
    .toggle input:checked{background:var(--accent-soft)}.toggle input:checked::after{transform:translateX(18px);background:var(--primary)}
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
    tbody tr{background:var(--surface-card)} tbody tr:nth-child(even){background:var(--surface-high)} tbody tr:hover{background:var(--surface-highest)}
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
    .status-dot{display:inline-block;width:8px;height:8px;border-radius:999px;background:var(--text-soft);box-shadow:0 0 6px color-mix(in srgb,var(--text-soft) 30%, transparent)}
    .status-dot.active{background:var(--primary);box-shadow:0 0 10px var(--accent-glow)}.status-dot.warn{background:var(--warn)}.status-dot.danger{background:var(--danger)}
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
    .action-btn.danger{color:var(--danger-soft);border-color:var(--danger-banner-border);background:var(--danger-bg)}
    .action-btn.danger:hover{background:var(--danger-bg-hover)}
    .device-modal{width:min(620px,94vw);background:color-mix(in srgb,var(--surface-highest) 62%, transparent);backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
    .device-modal h3{margin:0 0 8px 0}
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
        <span id=\"saveSpinner\" class=\"save-spinner\" aria-label=\"Saving\" title=\"Saving\"></span>
      </div>
      <div class=\"app-header-right\">
        <div class=\"app-version\">v__UI_VERSION__</div>
        <button id=\"themeIconBtn\" class=\"header-icon-btn\" type=\"button\" title=\"Theme: auto\" aria-label=\"Cycle theme\">◐</button>
        <button id=\"debugIconBtn\" class=\"header-icon-btn\" type=\"button\" title=\"Debug mode\" aria-label=\"Toggle debug mode\">
          <svg viewBox=\"0 0 24 24\" aria-hidden=\"true\" focusable=\"false\">
            <path d=\"M9 6l-2-2M15 6l2-2\"/>
            <path d=\"M8.5 10.5h7\"/>
            <path d=\"M12 8c3 0 5 2.2 5 5v2.5a5 5 0 1 1-10 0V13c0-2.8 2-5 5-5Z\"/>
            <path d=\"M5 12H3M21 12h-2M5 16H3M21 16h-2\"/>
          </svg>
        </button>
        <button id=\"settingsToggleBtn\" class=\"settings-toggle-btn\" type=\"button\" title=\"Hide settings\" aria-label=\"Toggle settings\" aria-pressed=\"false\">⚙</button>
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
          <div class=\"setting-row\">
            <span class=\"setting-label\">Auto Refresh</span>
            <label class=\"toggle\"><input id=\"autoToggle\" type=\"checkbox\" /></label>
          </div>
          <div class=\"setting-row inset-row\">
            <span class=\"setting-label\">Refresh Interval (sec)</span>
            <div class=\"stepper\" data-stepper><button id=\"intervalDec\" data-stepper-dec type=\"button\">-</button><input id=\"intervalInput\" type=\"number\" min=\"1\" step=\"1\" value=\"__INTERVAL_INT__\" /><button id=\"intervalInc\" data-stepper-inc type=\"button\">+</button></div>
          </div>
          <button id=\"refreshBtn\" class=\"btn btn-block settings-footer-btn\">Refresh</button>
        </section>

        <section class=\"control-card notify-card settings-card\">
          <div class=\"group-title\">Alarm</div>
          <div class=\"setting-row\">
            <span class=\"setting-label\">Enable Sound Alarm</span>
            <label class=\"toggle\"><input id=\"alarmToggle\" type=\"checkbox\" /></label>
          </div>
          <div class=\"setting-row metric inset-row\">
            <span class=\"setting-label\">5H alarm %</span>
            <div class=\"stepper compact\" data-stepper><button data-stepper-dec type=\"button\">-</button><input id=\"alarm5h\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" /><button data-stepper-inc type=\"button\">+</button></div>
          </div>
          <div class=\"setting-row metric inset-row\">
            <span class=\"setting-label\">Weekly alarm %</span>
            <div class=\"stepper compact\" data-stepper><button data-stepper-dec type=\"button\">-</button><input id=\"alarmWeekly\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" /><button data-stepper-inc type=\"button\">+</button></div>
          </div>
        </section>
      </div>
    </section>

    <section id=\"autoSwitchRulesSection\" data-settings-section=\"1\" class=\"section card\" style=\"padding:12px;\">
      <div class=\"auto-switch-head\">
        <div class=\"k\" style=\"margin-bottom:0;\">Auto-Switch Rules</div>
        <div id=\"asPendingCountdown\" class=\"auto-switch-countdown\">Switch in 00:00</div>
      </div>
      <div class=\"rules-grid\">
        <div class=\"rules-col settings-card\">
          <div class=\"rules-title\">Execution</div>
          <div class=\"setting-row\">
            <span class=\"setting-label\">Enabled</span>
            <label class=\"toggle\"><input id=\"asEnabled\" type=\"checkbox\" /></label>
          </div>
          <div class=\"setting-row metric inset-row\">
            <span class=\"setting-label\">Delay (sec)</span>
            <div class=\"stepper compact\" data-stepper><button data-stepper-dec type=\"button\">-</button><input id=\"asDelay\" type=\"number\" min=\"0\" step=\"1\" /><button data-stepper-inc type=\"button\">+</button></div>
          </div>
          <div class=\"exec-actions\">
            <button id=\"asRunSwitchBtn\" class=\"btn btn-block settings-footer-btn\">Run Switch</button>
            <button id=\"asRapidTestBtn\" class=\"btn btn-block settings-footer-btn\">Rapid Test</button>
            <button id=\"asForceStopBtn\" class=\"btn btn-block settings-footer-btn btn-danger\">Force Stop</button>
            <button id=\"asTestAutoSwitchBtn\" class=\"btn btn-block settings-footer-btn\">Test Auto Switch</button>
          </div>
        </div>
        <div class=\"rules-col settings-card\">
          <div class=\"rules-title\">Selection Policy</div>
          <div class=\"setting-field\"><span class=\"setting-label\">Ranking</span><select id=\"asRanking\"><option value=\"balanced\">balanced</option><option value=\"max_5h\">max_5h</option><option value=\"max_weekly\">max_weekly</option><option value=\"manual\">manual</option></select></div>
          <div class=\"setting-row metric inset-row\">
            <span class=\"setting-label\">5H switch %</span>
            <div class=\"stepper compact\" data-stepper><button data-stepper-dec type=\"button\">-</button><input id=\"as5h\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" /><button data-stepper-inc type=\"button\">+</button></div>
          </div>
          <div class=\"setting-row metric inset-row\">
            <span class=\"setting-label\">Weekly switch %</span>
            <div class=\"stepper compact\" data-stepper><button data-stepper-dec type=\"button\">-</button><input id=\"asWeekly\" type=\"number\" min=\"0\" max=\"100\" step=\"1\" /><button data-stepper-inc type=\"button\">+</button></div>
          </div>
          <div id=\"asAutoArrangeRow\" class=\"field-row rules-actions\"><button id=\"asAutoArrangeBtn\" class=\"btn-primary\">Auto Arrange</button></div>
        </div>
      </div>
      <div id=\"asChainPanel\" class=\"chain-panel\">
        <div class=\"chain-head\">
          <div class=\"chain-title\">Switch Chain Preview</div>
          <button id=\"asChainEditBtn\" class=\"btn\" type=\"button\">Edit</button>
        </div>
        <div id=\"asChainPreview\" class=\"chain-track\">-</div>
      </div>
    </section>

    <section class=\"section\">
      <div class=\"accounts-toolbar\">
        <div class=\"k\" style=\"margin:0\">Accounts</div>
        <div class=\"spacer\"></div>
        <div class=\"accounts-actions\">
          <button id=\"addAccountBtn\" class=\"btn-primary\">Add Account</button>
          <button id=\"removeAllBtn\" class=\"btn btn-danger\">Remove All</button>
          <button id=\"colSettingsBtn\" class=\"btn\" title=\"Table columns\">Columns</button>
        </div>
      </div>
      <div class=\"table-wrap\">
      <table>
        <thead>
          <tr>
            <th data-col=\"cur\" data-sort=\"current\">STS</th><th data-col=\"profile\" data-sort=\"name\">Profile</th><th data-col=\"email\" data-sort=\"email\">Email</th><th data-col=\"h5\" data-sort=\"usage5\">5H Usage</th><th data-col=\"h5remain\" data-sort=\"usage5remain\">5H Remain</th><th data-col=\"h5reset\" data-sort=\"usage5reset\">5H Reset At</th><th data-col=\"weekly\" data-sort=\"usageW\">Weekly</th><th data-col=\"weeklyremain\" data-sort=\"usageWremain\">W Remain</th><th data-col=\"weeklyreset\" data-sort=\"usageWreset\">Weekly Reset At</th><th data-col=\"id\" data-sort=\"id\">ID</th><th data-col=\"added\" data-sort=\"savedAt\">Added</th><th data-col=\"note\" class=\"note-col\" data-sort=\"note\">Note</th><th data-col=\"auto\" class=\"no-sort\">Auto</th><th data-col=\"actions\" class=\"no-sort\">Actions</th>
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
          <button id=\"exportLogsBtn\" class=\"btn\" type=\"button\">Export Debug Logs</button>
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

    <details class=\"guide card\">
      <summary>
        <svg class=\"guide-chevron\" viewBox=\"0 0 24 24\" aria-hidden=\"true\" focusable=\"false\">
          <path d=\"M9 6l6 6-6 6\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"></path>
        </svg>
        <span class=\"guide-title\">Guide & Help</span>
      </summary>
      <div class=\"guide-body\">
        <p class=\"guide-intro\">Use this app to manage local Codex profiles, monitor 5H/weekly usage, and run safe switching workflows from one panel.</p>
        <div class=\"guide-grid\">
          <section class=\"guide-block\">
            <h4>Quick Start</h4>
            <ul>
              <li>Use <b>Add Account</b> to create a new profile via device-login flow.</li>
              <li>Use <b>Switch</b> to activate a profile; active profile is pinned first with green status.</li>
              <li>Use <b>Refresh</b> or enable auto-refresh to keep usage and state updated.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Panel Controls</h4>
            <ul>
              <li><b>Auto Refresh</b> controls periodic data polling.</li>
              <li><b>Refresh Interval</b> changes poll timing (seconds).</li>
              <li>Header icons toggle <b>Theme</b>, <b>Debug mode</b>, and settings panel visibility.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Accounts Table</h4>
            <ul>
              <li>Sort by headers (name, usage, remain, reset, added date, and more).</li>
              <li><b>Columns</b> opens visibility settings for table fields.</li>
              <li>Row menu (<b>...</b>) supports rename/remove; mobile cards open full details on tap.</li>
              <li><b>Auto</b> checkbox marks which profiles are eligible for auto-switch.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Auto-Switch Rules</h4>
            <ul>
              <li>Enable/disable engine, set delay, thresholds, and ranking mode.</li>
              <li><b>Run Switch</b>, <b>Rapid Test</b>, <b>Force Stop</b>, and <b>Test Auto Switch</b> help validate behavior quickly.</li>
              <li><b>Switch Chain Preview</b> shows order; <b>Edit</b> allows manual chain reorder.</li>
              <li><b>Auto Arrange</b> recalculates balanced ordering from current usage.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>Alarm</h4>
            <ul>
              <li>Enable/disable sound alarms for warning events.</li>
              <li>Configure 5H/weekly alarm thresholds in the Alarm panel.</li>
              <li>Main auto-switch is controlled by the single <b>Enabled</b> switch in Execution.</li>
            </ul>
          </section>
          <section class=\"guide-block\">
            <h4>System.Out & Export</h4>
            <ul>
              <li>In debug mode, <b>System.Out</b> shows action logs, events, warnings, and errors.</li>
              <li><b>Export Debug Logs</b> downloads a JSON snapshot for troubleshooting.</li>
            </ul>
          </section>
        </div>
      </div>
    </details>
    <footer class=\"panel-footer\" aria-label=\"Project footer\">
      <div><strong>MIT License</strong> | Copyright (c) 2026 Codex Account Manager contributors</div>
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
        <button id=\"modalCancelBtn\" class=\"btn\">Cancel</button>
        <button id=\"modalOkBtn\" class=\"btn-primary\">OK</button>
      </div>
    </div>
  </div>

  <div id=\"columnsModalBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"columns-modal\">
      <h3>Table Columns</h3>
      <div id=\"columnsModalList\" class=\"columns-list\"></div>
      <div class=\"row\">
        <button id=\"columnsResetBtn\" class=\"btn\" type=\"button\">Reset Defaults</button>
        <button id=\"columnsDoneBtn\" class=\"btn-primary\" type=\"button\">Done</button>
      </div>
    </div>
  </div>

  <div id=\"rowActionsBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"actions-modal\">
      <div class=\"actions-head\">
        <h3>Row Actions</h3>
        <button id=\"rowActionsCloseBtn\" class=\"actions-close\" type=\"button\" aria-label=\"Close row actions\">×</button>
      </div>
      <p class=\"actions-sub\" id=\"rowActionsTarget\">-</p>
      <div class=\"actions-list\">
        <button id=\"rowActionsRenameBtn\" class=\"action-btn\" type=\"button\"><span>Rename</span><span class=\"hint\">edit</span></button>
        <button id=\"rowActionsRemoveBtn\" class=\"action-btn danger\" type=\"button\"><span>Remove</span><span class=\"hint\">danger</span></button>
      </div>
    </div>
  </div>

  <div id=\"addDeviceBackdrop\" class=\"modal-backdrop\" role=\"dialog\" aria-modal=\"true\" style=\"display:none;\">
    <div class=\"device-modal\">
      <h3>Add Account: Device Login</h3>
      <p id=\"addDeviceStatus\" class=\"device-status\">Preparing device auth link…</p>
      <div class=\"device-box\">
        <div class=\"device-label\">Login URL</div>
        <div id=\"addDeviceUrl\" class=\"device-value\">-</div>
        <div class=\"device-label\">Code</div>
        <div id=\"addDeviceCode\" class=\"device-value\">-</div>
      </div>
      <div class=\"device-actions\">
        <button id=\"addDeviceCopyBtn\" class=\"btn\" type=\"button\">Copy</button>
        <button id=\"addDeviceOpenBtn\" class=\"btn\" type=\"button\">Open In Browser</button>
        <button id=\"addDeviceLegacyBtn\" class=\"btn\" type=\"button\">Use Normal Login</button>
        <button id=\"addDeviceCancelBtn\" class=\"btn\" type=\"button\">Cancel</button>
        <button id=\"addDeviceDoneBtn\" class=\"btn-primary\" type=\"button\" style=\"display:none;\">Done</button>
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
        <button id=\"chainEditCancelBtn\" class=\"btn\" type=\"button\">Cancel</button>
        <button id=\"chainEditSaveBtn\" class=\"btn-primary\" type=\"button\">Save</button>
      </div>
    </div>
  </div>

  <script>
  const token = __TOKEN_JSON__;
  const UI_VERSION = __UI_VERSION_JSON__;
  let timer = null;
  let remainTicker = null;
  let eventsTimer = null;
  let sortState = JSON.parse(localStorage.getItem("codex_sort_state") || '{"key":"savedAt","dir":"desc"}');
  let latestData = { status: null, usage: null, list: null, config: null, autoState: null, autoChain: null, events: [] };
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
  let saveUiVisibleSince = 0;
  let saveUiHideTimer = null;
  let pendingAutoSwitchEnabled = null;
  let diagnosticsHooksInstalled = false;
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
  ]);
  let activeModalResolver = null;
  const columnLabels = { cur:"STS", profile:"Profile", email:"Email", h5:"5H Usage", h5remain:"5H Remain", h5reset:"5H Reset At", weekly:"Weekly", weeklyremain:"W Remain", weeklyreset:"Weekly Reset At", id:"ID", added:"Added", note:"Note", auto:"Auto", actions:"Actions" };
  const defaultColumns = { cur:true, profile:true, email:true, h5:true, h5remain:true, h5reset:false, weekly:true, weeklyremain:true, weeklyreset:false, id:false, added:false, note:false, auto:false, actions:true };
  function isLegacyAllColumnsEnabled(pref){
    try { return Object.keys(defaultColumns).every((k) => !!pref[k]); } catch(_) { return false; }
  }
  let columnPrefs = (() => {
    try {
      const p = JSON.parse(localStorage.getItem("codex_table_columns") || "{}") || {};
      const migrated = localStorage.getItem("codex_table_columns_default_v2") === "1";
      if(!migrated && p && Object.keys(p).length && isLegacyAllColumnsEnabled(p)){
        localStorage.setItem("codex_table_columns_default_v2", "1");
        localStorage.setItem("codex_table_columns", JSON.stringify(defaultColumns));
        return { ...defaultColumns };
      }
      return { ...defaultColumns, ...(p||{}) };
    } catch(_) { return { ...defaultColumns }; }
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
      pushOverlayLog("ui", "config.patch", { keys });
      await postApi("/api/ui-config", patch);
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
  function isUsageLoadingState(usage, rowError){
    const pct = usagePercentNumber(usage);
    if(Number.isFinite(pct)) return false;
    if(!rowError) return false;
    const msg = String(rowError || "").toLowerCase();
    return msg.includes("request failed") || msg.includes("timed out") || msg.includes("http ");
  }
  function renderUsageMeter(usage, loading=false){
    const pct = usagePercentNumber(usage);
    if(!Number.isFinite(pct)){
      if(loading){
        return `<div class="usage-cell usage-cell-loading"><span class="usage-pct loading-text">loading...</span><div class="usage-meter loading"><span class="usage-fill shimmer"></span></div></div>`;
      }
      return "<span>-</span>";
    }
    const tone = usageFillClass(pct);
    const txtClass = usageClass(pct);
    return `<div class="usage-cell"><span class="usage-pct ${txtClass}">${pct}%</span><div class="usage-meter"><span class="usage-fill ${tone}" style="width:${pct}%"></span></div></div>`;
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
    if(shouldTrace) pushOverlayLog("ui", `api.request ${method} ${path}`);
    let res;
    try {
      res = await fetch(path, options);
    } catch(e){
      pushOverlayLog("error", `api.network ${method} ${path}`, {
        error: e?.message || String(e),
        duration_ms: Date.now() - startedAt,
      });
      throw e;
    }
    const body = await res.json().catch(() => ({ok:false,error:{message:"bad json"}}));
    if(!res.ok || !body.ok){
      const code = body?.error?.code || "";
      const msg = body?.error?.message || "request failed";
      pushOverlayLog("error", `api.error ${method} ${path}`, {
        status: res.status,
        code: code || null,
        message: msg,
        duration_ms: Date.now() - startedAt,
      });
      if(code === "FORBIDDEN" && /invalid session token/i.test(msg)){
        setError("Session expired after service restart. Reloading panel...");
        setTimeout(() => { try { window.location.href = "/?v="+encodeURIComponent(UI_VERSION)+"&r="+Date.now(); } catch(_) {} }, 350);
      }
      throw new Error(msg);
    }
    if(shouldTrace){
      pushOverlayLog("ui", `api.response ${method} ${path}`, {
        status: res.status,
        duration_ms: Date.now() - startedAt,
      });
    }
    return body.data;
  }
  async function postApi(path, payload={}){ return callApi(path, { method:"POST", headers:{"Content-Type":"application/json","X-Codex-Token":token}, body: JSON.stringify(payload) }); }
  async function safeGet(path){ try { return await callApi(path); } catch(e){ return {__error:e.message}; } }

  function escHtml(s){
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
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
  async function runAction(title,fn){
    setError("");
    const startedAt = Date.now();
    pushOverlayLog("ui", `action.start ${title}`);
    try{
      const d = await fn();
      setCmdOut(title,d);
      pushOverlayLog("ui", `action.success ${title}`, { duration_ms: Date.now() - startedAt });
      await refreshAll();
    } catch(e){
      const msg = e?.message || String(e);
      pushOverlayLog("error", `action.fail ${title}`, { error: msg, duration_ms: Date.now() - startedAt });
      setError(msg);
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

  function applySort(rows){
    const key=sortState.key||"savedAt"; const dir=sortState.dir==="asc"?1:-1;
    const withIdx=rows.map((r,i)=>({r,i})); const current=withIdx.filter(x=>x.r.is_current); const others=withIdx.filter(x=>!x.r.is_current);
    others.sort((aObj,bObj)=>{ const a=aObj.r,b=bObj.r; const av=rowKey(a,key), bv=rowKey(b,key);
      if(typeof av==="string" || typeof bv==="string"){ const cmp=String(av).localeCompare(String(bv))*dir; if(cmp!==0) return cmp; return aObj.i-bObj.i; }
      const cmp=((av>bv)-(av<bv))*dir; if(cmp!==0) return cmp; return aObj.i-bObj.i;
    });
    return [...current.map(x=>x.r), ...others.map(x=>x.r)];
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
  function saveColumnPrefs(){ try { localStorage.setItem("codex_table_columns", JSON.stringify(columnPrefs)); } catch(_) {} }
  function isAutoSwitchEnabled(){
    try { return !!(latestData.config && latestData.config.auto_switch && latestData.config.auto_switch.enabled); } catch(_) { return false; }
  }
  function applyColumnVisibility(){
    Object.keys(defaultColumns).forEach((k) => {
      let visible = !!columnPrefs[k];
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
  function openAddDeviceModal(){
    const b = byId("addDeviceBackdrop", false);
    if(b) b.style.display = "flex";
  }
  function closeAddDeviceModal(){
    clearAddDevicePolling();
    addDeviceSessionId = null;
    addDeviceSessionState = null;
    addDeviceProfileName = "";
    const b = byId("addDeviceBackdrop", false);
    if(b) b.style.display = "none";
  }
  function updateAddDeviceModal(session){
    addDeviceSessionState = session || null;
    const st = byId("addDeviceStatus", false);
    const urlEl = byId("addDeviceUrl", false);
    const codeEl = byId("addDeviceCode", false);
    const doneBtn = byId("addDeviceDoneBtn", false);
    const cancelBtn = byId("addDeviceCancelBtn", false);
    if(st) st.textContent = session?.error || session?.message || `status: ${session?.status || "-"}`;
    if(urlEl) urlEl.textContent = session?.url || "-";
    if(codeEl) codeEl.textContent = session?.code || "-";
    const finished = !!session && ["completed", "failed", "canceled"].includes(String(session.status || ""));
    if(doneBtn) doneBtn.style.display = finished ? "" : "none";
    if(cancelBtn) cancelBtn.style.display = finished ? "none" : "";
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
    updateAddDeviceModal({ status:"running", message:"starting login flow..." });
    openAddDeviceModal();
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
  const IS_WINDOWS_CLIENT = /windows/i.test((navigator && navigator.userAgent) || "");
  function switchRequestBody(name){
    return IS_WINDOWS_CLIENT ? { name, close_only: true } : { name };
  }
  async function switchProfile(name){
    await postApi("/api/switch", switchRequestBody(name));
    await refreshAll();
  }

  function renderEvents(items){ return items; }

  async function loadDebugLogs(){
    const payload = await safeGet("/api/debug/logs?tail=240");
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

  function playAlarmPattern(delayMs){
    if(!alarmAudioCtx || alarmAudioCtx.state !== "running") return;
    const now = alarmAudioCtx.currentTime + Math.max(0, Number(delayMs || 0)) / 1000;
    const seq = [
      { t: 0.00, f: 880, d: 0.22 },
      { t: 0.28, f: 1046, d: 0.22 },
      { t: 0.56, f: 1318, d: 0.34 },
    ];
    seq.forEach((tone) => {
      try {
        const osc = alarmAudioCtx.createOscillator();
        const gain = alarmAudioCtx.createGain();
        osc.type = "triangle";
        osc.frequency.setValueAtTime(tone.f, now + tone.t);
        gain.gain.setValueAtTime(0.0001, now + tone.t);
        gain.gain.exponentialRampToValueAtTime(0.18, now + tone.t + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + tone.t + tone.d);
        osc.connect(gain);
        gain.connect(alarmAudioCtx.destination);
        osc.start(now + tone.t);
        osc.stop(now + tone.t + tone.d + 0.02);
      } catch(_) {}
    });
  }

  async function triggerSystemNotification(message, delaySec, opts){
    const delayMs = Math.max(0, Number(delaySec || 0) * 1000);
    const playAlarm = !!(opts && opts.play_alarm);
    const tag = String((opts && opts.tag) || ("cam-manual-" + Date.now()));
    const requireInteraction = !!(opts && opts.require_interaction);
    const renotify = !!(opts && opts.renotify);
    const inAppAlways = !!(opts && opts.in_app_always);
    if(playAlarm) playAlarmPattern(delayMs);
    if(!(await ensureNotificationPermission(false))){
      if(inAppAlways){
        setTimeout(() => {
          showInAppNotice("Codex Account Manager", String(message || "Notification"), { require_interaction: requireInteraction });
        }, delayMs);
      }
      if(playAlarm){
        setError("Browser notification permission is blocked. Alarm sound played instead.");
      } else {
        setError("Notification permission is blocked. Enable it in browser settings.");
      }
      return;
    }
    setTimeout(async () => {
      const body = String(message || "Notification");
      const destination = "/?v="+encodeURIComponent(UI_VERSION);
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
    playAlarmPattern(0);
    showInAppNotice("Alarm", ev.message || "Usage warning", { duration_ms: 9000 });
  }

  function renderTable(usage){
    const tbody = byId("rows"); tbody.innerHTML="";
    const mobileRows = byId("mobileRows", false); if(mobileRows) mobileRows.innerHTML = "";
    const mapped = (usage?.profiles || []).map(p => ({...p, saved_at_ts: p.saved_at ? Date.parse(p.saved_at) || 0 : 0 }));
    const rows = applySort(mapped);
    for(const p of rows){
      const tr=document.createElement("tr");
      const statusClass = p.is_current ? "active" : "";
      const h5Loading = isUsageLoadingState(p.usage_5h, p.error);
      const wLoading = isUsageLoadingState(p.usage_weekly, p.error);
      const h5RemainTs = Number(p.usage_5h?.resets_at || 0) || "";
      const wRemainTs = Number(p.usage_weekly?.resets_at || 0) || "";
      tr.innerHTML = `
        <td data-col="cur"><span class="status-dot ${statusClass}"></span></td>
        <td data-col="profile">${p.name}</td>
        <td data-col="email" class="email-cell" title="${(p.email || "-").replace(/"/g,'&quot;')}">${p.email || "-"}</td>
        <td data-col="h5">${renderUsageMeter(p.usage_5h, h5Loading)}</td>
        <td data-col="h5remain" class="reset-cell ${h5Loading ? "loading-text" : ""}" data-remain-ts="${h5RemainTs}" data-remain-seconds="1" data-remain-loading="${h5Loading ? "1" : "0"}">${fmtRemain(p.usage_5h?.resets_at, true, h5Loading)}</td>
        <td data-col="h5reset" class="reset-cell">${fmtReset(p.usage_5h?.resets_at)}</td>
        <td data-col="weekly">${renderUsageMeter(p.usage_weekly, wLoading)}</td>
        <td data-col="weeklyremain" class="reset-cell ${wLoading ? "loading-text" : ""}" data-remain-ts="${wRemainTs}" data-remain-seconds="0" data-remain-loading="${wLoading ? "1" : "0"}">${fmtRemain(p.usage_weekly?.resets_at, false, wLoading)}</td>
        <td data-col="weeklyreset" class="reset-cell">${fmtReset(p.usage_weekly?.resets_at)}</td>
        <td data-col="id" class="id-cell" title="${(p.account_id || "-").replace(/"/g,'&quot;')}">${p.account_id || "-"}</td>
        <td data-col="added" class="added-cell">${fmtSavedAt(p.saved_at || "-")}</td>
        <td data-col="note" class="note-cell">${p.same_principal ? '<span class="badge">same-principal</span>' : ''}</td>
        <td data-col="auto"><input type="checkbox" data-auto="${p.name}" ${p.auto_switch_eligible ? "checked" : ""} /></td>
        <td data-col="actions"><div class="actions-cell"><button class="btn-primary ${p.is_current ? "btn-disabled" : ""}" data-switch="${p.name}" ${p.is_current ? "disabled" : ""}>Switch</button><button class="btn actions-menu-btn" data-row-actions="${p.name}">⋯</button></div></td>
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
              <span class="status-dot ${statusClass}"></span>
              <span class="mobile-profile">${p.name || "-"}</span>
            </div>
            <div class="mobile-actions">
              <button class="btn-primary ${p.is_current ? "btn-disabled" : ""}" data-mobile-switch="${p.name}" ${p.is_current ? "disabled" : ""}>Switch</button>
              <button class="btn actions-menu-btn" data-mobile-row-actions="${p.name}">⋯</button>
            </div>
          </div>
          <div class="mobile-email">${p.email || "-"}</div>
          <div class="mobile-stats">
            <div class="mobile-stat"><span class="label">5H</span><span class="${h5Class}">${fmtUsagePct(p.usage_5h)}</span></div>
            <div class="mobile-stat"><span class="label">Weekly</span><span class="${wClass}">${fmtUsagePct(p.usage_weekly)}</span></div>
            <div class="mobile-stat"><span class="label">5H Remain</span><span class="${h5Loading ? "loading-text" : ""}">${fmtRemain(p.usage_5h?.resets_at, true, h5Loading)}</span></div>
            <div class="mobile-stat"><span class="label">W Remain</span><span class="${wLoading ? "loading-text" : ""}">${fmtRemain(p.usage_weekly?.resets_at, false, wLoading)}</span></div>
          </div>
        `;
        const openDetails = async () => {
          const detailsBody = [
            `Profile: ${p.name || "-"}`,
            `Email: ${p.email || "-"}`,
            `Current: ${p.is_current ? "yes" : "no"}`,
            `5H Usage: ${fmtUsagePct(p.usage_5h)}`,
            `5H Remain: ${fmtRemain(p.usage_5h?.resets_at, true, h5Loading)}`,
            `5H Reset At: ${fmtReset(p.usage_5h?.resets_at)}`,
            `Weekly Usage: ${fmtUsagePct(p.usage_weekly)}`,
            `Weekly Remain: ${fmtRemain(p.usage_weekly?.resets_at, false, wLoading)}`,
            `Weekly Reset At: ${fmtReset(p.usage_weekly?.resets_at)}`,
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
            runAction("local.switch", () => switchProfile(mobileSwitchBtn.dataset.mobileSwitch));
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
    }
    applyColumnVisibility();
    refreshRemainCountdowns();
    tbody.querySelectorAll("button[data-switch]").forEach(btn => btn.addEventListener("click", () => runAction("local.switch", () => switchProfile(btn.dataset.switch))));
    tbody.querySelectorAll("button[data-row-actions]").forEach(btn => btn.addEventListener("click", (e)=>{
      e.stopPropagation();
      openRowActionsModal(btn.dataset.rowActions);
    }));
    tbody.querySelectorAll("input[data-auto]").forEach(ch => ch.addEventListener("change", async ()=>{ try { await setEligibility(ch.dataset.auto, !!ch.checked); } catch(e){ setError(e.message); ch.checked=!ch.checked; } }));
  }

  function applyConfigToControls(cfg){
    const ui = cfg.ui || {};
    byId("themeSelect").value = ui.theme || "auto";
    applyTheme(ui.theme || "auto");
    updateHeaderThemeIcon(ui.theme || "auto");
    byId("advancedCard").style.display = "none";
    byId("autoToggle").checked = !!ui.auto_refresh;
    byId("intervalInput").value = String(ui.refresh_interval_sec || 5);
    byId("debugToggle").checked = !!ui.debug_mode;
    updateHeaderDebugIcon(!!ui.debug_mode);
    byId("debugRuntimeSection").style.display = ui.debug_mode ? "block" : "none";
    const n = cfg.notifications || {};
    byId("alarmToggle").checked = !!n.enabled;
    byId("alarm5h").value = String(n.thresholds?.h5_warn_pct ?? 20);
    byId("alarmWeekly").value = String(n.thresholds?.weekly_warn_pct ?? 20);
    const a = cfg.auto_switch || {};
    byId("asEnabled").checked = pendingAutoSwitchEnabled === null ? !!a.enabled : !!pendingAutoSwitchEnabled;
    setControlValueIfPristine("asDelay", String(a.delay_sec ?? 60));
    const rankingEl = byId("asRanking", false);
    if(rankingEl && rankingEl.dataset.dirty !== "1") rankingEl.value = a.ranking_mode || "balanced";
    updateRankingModeUI((rankingEl ? rankingEl.value : (a.ranking_mode || "balanced")), !!a.enabled);
    setControlValueIfPristine("as5h", String(a.thresholds?.h5_switch_pct ?? 20));
    setControlValueIfPristine("asWeekly", String(a.thresholds?.weekly_switch_pct ?? 20));
  }

  async function refreshAll(){
    if(pendingConfigSaves > 0){
      try { await configSaveQueue; } catch(_) {}
    }
    setError("");
    const list = await safeGet("/api/list");
    const usage = await safeGet("/api/usage-local?timeout=3");
    const config = await safeGet("/api/ui-config");
    const autoState = await safeGet("/api/auto-switch/state");
    const autoChain = await safeGet("/api/auto-switch/chain");
    const eventsPayload = await safeGet("/api/events?since_id="+encodeURIComponent(String(lastEventId)));
    if(!config.__error){
      latestData.config=config;
      applyConfigToControls(config);
      const as = config.auto_switch || {};
      const autoEl = byId("auto", false);
      if(autoEl) autoEl.textContent = as.enabled ? "ON" : "OFF";
      const thrEl = byId("thr", false);
      if(thrEl) thrEl.textContent = `${as.thresholds?.h5_switch_pct ?? "-"} / ${as.thresholds?.weekly_switch_pct ?? "-"}`;
      renderColumnsModal();
      applyColumnVisibility();
    } else {
      setError("config: " + config.__error);
    }
    if(!usage.__error){ latestData.usage = usage; renderTable(usage); } else { setError((byId("error").textContent ? byId("error").textContent + "\\n" : "") + "usage: " + usage.__error); }
    if(!list.__error){ latestData.list = list; }
    if(!autoState.__error){
      latestData.autoState = autoState;
      const engineEl = byId("engine", false);
      if(engineEl) engineEl.textContent = autoState.active ? "ACTIVE" : "IDLE";
      const engineMetaEl = byId("engineMeta", false);
      if(engineMetaEl) engineMetaEl.textContent = "pending: " + (autoState.pending_switch_due_at_text || "-") + " | cooldown: " + (autoState.cooldown_until_text || "-");
      const rapidBtn = byId("asRapidTestBtn", false);
      if(rapidBtn){
        const activeRapid = !!autoState.rapid_test_active;
        rapidBtn.disabled = activeRapid;
        rapidBtn.textContent = activeRapid ? "Rapid Running..." : "Rapid Test";
      }
      updateAutoSwitchArmedUI();
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
    await loadDebugLogs();
    const refreshStamp = byId("lastRefresh", false);
    if(refreshStamp) refreshStamp.textContent = "Refreshed: " + new Date().toLocaleTimeString();
  }

  function resetTimer(){
    if(timer) clearInterval(timer);
    const enabled = !!byId("autoToggle").checked;
    if(!enabled) return;
    const iv = Math.max(1, parseInt(byId("intervalInput").value || "5", 10));
    byId("intervalInput").value = String(iv);
    timer = setInterval(refreshAll, iv * 1000);
  }
  function resetRemainTicker(){
    if(remainTicker) clearInterval(remainTicker);
    remainTicker = setInterval(refreshRemainCountdowns, 1000);
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
      byId("refreshBtn").addEventListener("click", refreshAll);
      byId("themeSelect").addEventListener("change", async (e) => { applyTheme(e.target.value); await saveUiConfigPatch({ ui: { theme: e.target.value } }); });
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
      byId("autoToggle").addEventListener("change", async (e)=>{ await saveUiConfigPatch({ ui: { auto_refresh: !!e.target.checked } }); resetTimer(); });
      byId("intervalInput").addEventListener("change", async ()=>{ const v=Math.max(1,parseInt(byId("intervalInput").value||"5",10)); byId("intervalInput").value=String(v); await saveUiConfigPatch({ ui: { refresh_interval_sec: v } }); resetTimer(); });
      initSteppers(document);
      byId("addAccountBtn").addEventListener("click", async ()=>{
        pushOverlayLog("ui", "ui.click add_account");
        const r = await openModal({ title:"Add Account", body:"Enter profile name for the new login:", input:true, inputPlaceholder:"profile name" });
        const name = (r&&r.ok) ? (r.value||"").trim() : "";
        if(!name){
          pushOverlayLog("ui", "ui.cancel add_account");
          return;
        }
        pushOverlayLog("ui", "ui.submit add_account", { profile: name });
        try {
          await startAddDeviceFlow(name);
        } catch(e){
          const msg = e?.message || String(e);
          setError(msg);
          pushOverlayLog("error", "device_auth.start_failed", { profile: name, error: msg });
          updateAddDeviceModal({ status:"failed", error: msg, message: msg, url: null, code: null });
          openAddDeviceModal();
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
        const name = addDeviceProfileName || "";
        if(!name){ setError("Missing profile name for login."); return; }
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
      byId("addDeviceDoneBtn").addEventListener("click", ()=>closeAddDeviceModal());
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
      byId("columnsResetBtn").addEventListener("click", ()=>{
        columnPrefs = { ...defaultColumns };
        saveColumnPrefs();
        applyColumnVisibility();
        renderColumnsModal();
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
      byId("asForceStopBtn").addEventListener("click", ()=> runAction("auto_switch.stop", ()=>postApi("/api/auto-switch/stop", {})));
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
      byId("modalBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("modalBackdrop")) closeModal({ ok:false }); });
      byId("addDeviceBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("addDeviceBackdrop")) closeAddDeviceModal(); });
      byId("rowActionsBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("rowActionsBackdrop")) closeRowActionsModal(); });
      byId("chainEditBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("chainEditBackdrop")) closeChainEditModal(); });
      document.addEventListener("keydown", (e)=>{
        const chainEditBackdrop = byId("chainEditBackdrop", false);
        if(chainEditBackdrop && chainEditBackdrop.style.display === "flex" && e.key === "Escape"){
          e.preventDefault();
          closeChainEditModal();
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
      renderColumnsModal();
      applyColumnVisibility();
      initSteppers(document);
      renderSortIndicators();
      document.querySelectorAll("th[data-sort]").forEach(th => th.addEventListener("click", ()=>{
        const key=th.dataset.sort;
        if(sortState.key===key) sortState.dir=sortState.dir==="asc"?"desc":"asc";
        else sortState={key,dir:"desc"};
        localStorage.setItem("codex_sort_state", JSON.stringify(sortState));
        renderSortIndicators();
        if(latestData.usage) renderTable(latestData.usage);
      }));
      await refreshAll();
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
    tie = (
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
    h5_hit = use_h5 and p5 is not None and p5 < float(thr.get("h5_switch_pct", 20))
    w_hit = use_weekly and pw is not None and pw < float(thr.get("weekly_switch_pct", 20))
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
        if _remaining_pct(r, "usage_5h") is None and _remaining_pct(r, "usage_weekly") is None:
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
    row_by_name: dict[str, dict] = {}
    ranked: list[tuple[float, tuple, dict]] = []
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        name_s = str(name)
        row_by_name[name_s] = r
        if current_name and name_s == current_name:
            continue
        score, tie = _candidate_score(r, cfg)
        ranked.append((score, tie, r))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    fallback = ([str(current_name)] if current_name else []) + [str(x[2].get("name")) for x in ranked if x[2].get("name")]
    manual = _manual_chain_from_cfg(cfg)
    merged: list[str] = []
    seen = set()
    for nm in manual:
        if nm in row_by_name and nm not in seen:
            seen.add(nm)
            merged.append(nm)
    for nm in fallback:
        if nm in row_by_name and nm not in seen:
            seen.add(nm)
            merged.append(nm)
    return merged


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
            if _remaining_pct(r, "usage_5h") is None and _remaining_pct(r, "usage_weekly") is None:
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
    }
    usage_cache_lock = threading.RLock()
    usage_cache: dict[str, object] = {
        "ts": 0.0,
        "payload": None,
        "cfg_hash": None,
        "timeout": None,
    }

    def is_debug_enabled() -> bool:
        try:
            cfg = load_cam_config()
            return bool(((cfg.get("ui") or {}).get("debug_mode")))
        except Exception:
            return False

    def log_runtime(level: str, message: str, details=None):
        cam_log(level, message, details=details, echo=is_debug_enabled())

    def push_event(event_type: str, message: str, details=None):
        ev = {
            "id": runtime["next_event_id"],
            "ts": int(time.time()),
            "type": event_type,
            "message": message,
            "details": details or {},
        }
        runtime["next_event_id"] += 1
        runtime["events"].append(ev)
        if len(runtime["events"]) > 200:
            runtime["events"] = runtime["events"][-200:]
        log_runtime("info", f"event:{event_type}", {"id": ev["id"], "message": message, "details": details or {}})
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
        if not force:
            with usage_cache_lock:
                cached_payload = usage_cache.get("payload")
                cached_ts = float(usage_cache.get("ts") or 0.0)
                cached_key = usage_cache.get("cfg_hash")
                if cached_payload and cached_key == key and (now - cached_ts) <= max(0.05, ttl_sec):
                    return cached_payload
        payload = collect_usage_local_data(timeout_sec=timeout_sec, config=config)
        with usage_cache_lock:
            usage_cache["ts"] = time.time()
            usage_cache["payload"] = payload
            usage_cache["cfg_hash"] = key
            usage_cache["timeout"] = timeout_sec
        return payload

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
                rc, out, err = _capture_fn(lambda: cmd_switch(target, restart_codex=True))
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
                rc, out, err = _capture_fn(lambda: cmd_switch(str(candidate.get("name")), restart_codex=True))
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
                return _json_ok(load_cam_config())
            if self.command == "GET" and path == "/api/auto-switch/state":
                return _json_ok(auto_switch_state_payload(load_cam_config()))
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
                tail = 200
                if "tail" in q:
                    try:
                        tail = max(20, min(2000, int(float(q["tail"][0]))))
                    except Exception:
                        tail = 200
                return _json_ok({"path": str(CAM_LOG_FILE), "logs": read_log_tail(tail)})
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
                return _json_ok(collect_usage_local_data_cached(timeout, config=cfg, ttl_sec=2.0, force=force))
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
                if close_only and sys.platform.startswith("win"):
                    try:
                        stop_codex()
                        _log_runtime_safe("info", "switch close_only stop requested", {"name": name})
                    except Exception as e:
                        _log_runtime_safe("warn", "switch close_only stop failed", {"name": name, "error": str(e)})
                # Apply profile switch first, then restart asynchronously so the HTTP request can complete.
                rc, out, err = _capture_fn(lambda: cmd_switch(name, restart_codex=False))
                payload = _command_result("local.switch", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local switch failed", 400, payload)
                if restart:
                    def _deferred_restart():
                        try:
                            time.sleep(0.8)
                            restart_codex_app()
                        except Exception as e:
                            _log_runtime_safe("warn", "deferred restart failed", {"error": str(e), "name": name})
                    threading.Thread(target=_deferred_restart, daemon=True).start()
                    _log_runtime_safe("info", "switch deferred restart scheduled", {"name": name})
                push_event("switch-manual", f"manually switched to '{name}'")
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/ui-config":
                patch = body if isinstance(body, dict) else {}
                try:
                    cfg = update_cam_config(patch)
                except Exception as e:
                    log_runtime("error", "config update failed", {"error": str(e)})
                    return _json_error("BAD_CONFIG", f"failed to update config: {e}", 400)
                log_runtime("info", "config updated", {"patch": patch})
                return _json_ok(cfg)
            if self.command == "POST" and path == "/api/notifications/test":
                delay_sec = int_value(body.get("delay_sec"), 5, minimum=0)
                ev = push_event("notify-test", f"test notification requested (delay {delay_sec}s)", {"delay_sec": delay_sec})
                return _json_ok({"event": ev})
            if self.command == "POST" and path == "/api/auto-switch/enable":
                enabled = bool_value(body.get("enabled"), False)
                cfg = update_cam_config({"auto_switch": {"enabled": enabled}})
                push_event("auto-switch-toggle", f"auto-switch set to {'enabled' if enabled else 'disabled'}")
                return _json_ok({"enabled": enabled, "config": cfg})
            if self.command == "POST" and path == "/api/auto-switch/stop":
                cfg = update_cam_config({"auto_switch": {"enabled": False}})
                runtime["rapid_test_stop"].set()
                runtime["pending_warning"] = None
                runtime["pending_switch_due_at"] = None
                runtime["last_switch_ts"] = None
                push_event("auto-switch-stop", "auto-switch force-stopped and pending state cleared")
                return _json_ok({"enabled": False, "runtime": auto_switch_state_payload(load_cam_config()), "config": cfg})
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
                rc, out, err = _capture_fn(lambda: cmd_switch(target, restart_codex=True))
                payload = _command_result("auto_switch.run_once", rc, out, err)
                if rc != 0:
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
                rc, out, err = _capture_fn(lambda: cmd_switch(target, restart_codex=True))
                payload = _command_result("auto_switch.run_switch", rc, out, err)
                if rc != 0:
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
            if self.command == "POST" and path == "/api/local/save":
                name = str(body.get("name", "")).strip()
                if not name:
                    return _json_error("MISSING_NAME", "name is required")
                force = bool_value(body.get("force"), False)
                rc, out, err = _capture_fn(lambda: cmd_save(name, overwrite=force))
                payload = _command_result("local.save", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local save failed", 400, payload)
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
                return _json_ok(payload)
            if self.command == "POST" and path == "/api/local/remove-all":
                rc, out, err = _capture_fn(cmd_remove_all_profiles)
                payload = _command_result("local.remove_all", rc, out, err)
                if rc != 0:
                    return _json_error("COMMAND_FAILED", "local remove all failed", 400, payload)
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
            parsed = urlparse(self.path)
            last_seen["ts"] = time.time()
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
                self._reply(status_code, payload)
                return
            self._reply(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "not found"}})

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                status_code, payload = self._api()
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
            proc = subprocess.run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return proc.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


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
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
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
            p = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
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
            p = subprocess.run(["ss", "-lptn", f"sport = :{port}"], capture_output=True, text=True)
            for match in re.findall(r"pid=(\d+)", p.stdout):
                pids.add(int(match))
        except Exception:
            pass
    if pids:
        return pids
    if shutil.which("netstat"):
        try:
            p = subprocess.run(["netstat", "-nlp"], capture_output=True, text=True)
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
        proc = subprocess.run(["systemctl", "--user", "list-unit-files"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            subprocess.run(["launchctl", "unload", str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["launchctl", "load", str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"autostart installed: {plist_path}")
            return 0
        if action == "uninstall":
            subprocess.run(["launchctl", "unload", str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            rc = subprocess.run(["schtasks", "/Create", "/TN", task, "/TR", tr, "/SC", "ONLOGON", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            if rc == 0:
                print("autostart installed")
                return 0
            print("error: failed to install windows autostart")
            return 1
        if action == "uninstall":
            subprocess.run(["schtasks", "/Delete", "/TN", task, "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("autostart uninstalled")
            return 0
        if action == "status":
            rc = subprocess.run(["schtasks", "/Query", "/TN", task], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
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
                subprocess.run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["systemctl", "--user", "enable", "--now", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"autostart installed: {service_path}")
                return 0
            if action == "uninstall":
                subprocess.run(["systemctl", "--user", "disable", "--now", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if service_path.exists():
                    service_path.unlink()
                subprocess.run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("autostart uninstalled")
                return 0
            if action == "status":
                enabled = subprocess.run(["systemctl", "--user", "is-enabled", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                active = subprocess.run(["systemctl", "--user", "is-active", "codex-account-ui.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Codex account profile switcher")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser("save", help="Save current ~/.codex/auth.json as a named profile")
    p_save.add_argument("name")
    p_save.add_argument("--force", action="store_true", help="Overwrite existing profile")

    p_add = sub.add_parser("add", help="Run fresh browser login and save it directly as a profile")
    p_add.add_argument("name")
    p_add.add_argument("--timeout", type=int, default=300, help="Login timeout in seconds (default: 300)")
    p_add.add_argument("--force", action="store_true", help="Overwrite existing profile")
    p_add.add_argument("--keep-temp-home", action="store_true", help="Keep temporary CODEX_HOME for debugging")
    p_add.add_argument("--device-auth", action="store_true", help="Use device auth flow to reduce browser cookie auto-selection")

    p_list = sub.add_parser("list", help="List saved profiles")
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
    p_current = sub.add_parser("current", help="Show current active account hint")
    p_current.add_argument("--json", action="store_true", help="Output structured JSON")

    p_switch = sub.add_parser("switch", help="Switch active ~/.codex/auth.json to a saved profile")
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
