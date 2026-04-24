from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


APP_TITLE = "Codex Account Manager"
ICON_ASSET = Path(__file__).resolve().parent / "assets" / "codex_account_manager.svg"


def build_native_notification_payload(usage_payload: dict, message_prefix: str | None = None) -> dict:
    current_name = str((usage_payload or {}).get("current_profile") or "").strip()
    rows = (usage_payload or {}).get("profiles") or []
    current_row = None

    if current_name:
        for row in rows:
            if str(row.get("name") or "").strip() == current_name:
                current_row = row
                break

    if current_row is None:
        for row in rows:
            if bool(row.get("is_current")):
                current_row = row
                current_name = str(row.get("name") or "").strip()
                break

    if current_row is None or not current_name:
        raise RuntimeError("Native notification test requires a current profile.")

    rem_5h = current_row.get("usage_5h") or {}
    rem_weekly = current_row.get("usage_weekly") or {}
    try:
        pct_5h = int(round(float(rem_5h.get("remaining_percent"))))
        pct_weekly = int(round(float(rem_weekly.get("remaining_percent"))))
    except Exception as exc:
        raise RuntimeError("Native notification test requires current-profile usage data.") from exc

    message = f"5H {pct_5h}% left • Weekly {pct_weekly}% left"
    prefix = str(message_prefix or "").strip()
    if prefix:
        message = f"{prefix} • {message}"

    return {
        "profile_name": current_name,
        "title": APP_TITLE,
        "subtitle": f"Profile {current_name}",
        "message": message,
    }


def _prepare_macos_notification_icon() -> str | None:
    if not ICON_ASSET.exists():
        return None

    out_dir = Path(tempfile.gettempdir()) / "codex-account-manager-native-icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "qlmanage",
            "-t",
            "-s",
            "256",
            "-o",
            str(out_dir),
            str(ICON_ASSET),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    png_path = out_dir / f"{ICON_ASSET.name}.png"
    if not png_path.exists():
        return None
    return png_path.resolve().as_uri()


def _send_macos_native_notification(payload: dict, base_url: str) -> dict:
    notifier = shutil.which("terminal-notifier")
    if not notifier:
        raise RuntimeError("terminal-notifier is required on macOS for native notification tests.")

    cmd = [
        notifier,
        "-title",
        str(payload["title"]),
        "-subtitle",
        str(payload["subtitle"]),
        "-message",
        str(payload["message"]),
        "-open",
        str(base_url),
        "-sound",
        "default",
        "-group",
        "cam-native-test",
    ]
    icon_uri = _prepare_macos_notification_icon()
    if icon_uri:
        cmd.extend(["-appIcon", icon_uri])

    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "macOS native notification failed").strip())

    return {"ok": True, "backend": "terminal-notifier", "profile_name": payload["profile_name"]}


def _send_usage_native_notification(
    usage_payload: dict,
    base_url: str,
    platform_name: str | None = None,
    message_prefix: str | None = None,
) -> dict:
    payload = build_native_notification_payload(usage_payload, message_prefix=message_prefix)
    active_platform = str(platform_name or sys.platform)

    if active_platform == "darwin":
        return _send_macos_native_notification(payload, base_url)
    if active_platform.startswith("linux"):
        raise RuntimeError("Native notifications are not implemented yet on this OS.")
    if active_platform.startswith("win"):
        raise RuntimeError("Native notifications are not implemented yet on this OS.")
    raise RuntimeError(f"Native notifications are not supported on platform: {active_platform}")


def send_native_usage_notification(
    usage_payload: dict,
    base_url: str,
    message_prefix: str | None = None,
    platform_name: str | None = None,
) -> dict:
    return _send_usage_native_notification(
        usage_payload,
        base_url,
        platform_name=platform_name,
        message_prefix=message_prefix,
    )


def send_native_test_notification(usage_payload: dict, base_url: str, platform_name: str | None = None) -> dict:
    return send_native_usage_notification(usage_payload, base_url, platform_name=platform_name)


def send_native_switch_notification(
    usage_payload: dict,
    base_url: str,
    seconds_until_switch: int = 30,
    platform_name: str | None = None,
) -> dict:
    lead_sec = max(0, int(seconds_until_switch))
    prefix = f"Auto switch starts in {lead_sec} seconds"
    return send_native_usage_notification(
        usage_payload,
        base_url,
        platform_name=platform_name,
        message_prefix=prefix,
    )
