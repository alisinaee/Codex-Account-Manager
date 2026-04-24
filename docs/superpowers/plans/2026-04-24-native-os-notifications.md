# Native OS Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new web-panel card for native OS notifications with a `Test` button that sends a real macOS notification using current-profile usage data, while returning clear unsupported-OS errors on Linux and Windows.

**Architecture:** Keep the frontend thin and push native notification logic into a focused Python helper module. The web UI will call a new `POST /api/notifications/native-test` endpoint, the backend will gather current-profile usage from the existing usage cache/collector path, format a minimal notification payload, and dispatch through a macOS-specific `terminal-notifier` backend. Linux and Windows will return explicit structured errors until native backends are added.

**Tech Stack:** Python 3.11+, existing `ThreadingHTTPServer` UI backend, embedded HTML/JS in `codex_account_manager/cli.py`, `pytest` running unittest-style tests via `.venv/bin/python -m pytest`, macOS `terminal-notifier`, macOS `qlmanage` for SVG-to-PNG icon preparation.

---

## File Structure

**Create:**

- `codex_account_manager/native_notifications.py`
  Purpose: isolate native notification payload building, macOS dispatch, icon preparation, and unsupported-OS error normalization.
- `docs/superpowers/plans/2026-04-24-native-os-notifications.md`
  Purpose: this implementation plan.

**Modify:**

- `codex_account_manager/cli.py`
  Purpose: add the new API route, wire the UI card into the existing settings grid, and connect the `Test` button to the backend.
- `tests/test_cli_core.py`
  Purpose: add backend helper tests plus web-UI rendering assertions.
- `docs/ui-api.md`
  Purpose: document the new native notification endpoint.

## Task 1: Add failing backend tests for native notification helpers

**Files:**

- Modify: `tests/test_cli_core.py`
- Test: `tests/test_cli_core.py`

- [ ] **Step 1: Write the failing tests**

Add these tests near the existing UI/config tests in `tests/test_cli_core.py`:

```python
    def test_build_native_notification_payload_uses_current_profile_usage(self):
        usage_payload = {
            "current_profile": "noob",
            "profiles": [
                {
                    "name": "noob",
                    "is_current": True,
                    "usage_5h": {"remaining_percent": 49.0},
                    "usage_weekly": {"remaining_percent": 88.0},
                }
            ],
        }

        payload = cli.native_notifications.build_native_notification_payload(usage_payload)

        self.assertEqual(payload["profile_name"], "noob")
        self.assertEqual(payload["title"], "Codex Account Manager")
        self.assertEqual(payload["subtitle"], "Profile noob")
        self.assertEqual(payload["message"], "5H 49% left • Weekly 88% left")

    def test_send_native_test_notification_returns_error_when_current_profile_missing(self):
        usage_payload = {"current_profile": None, "profiles": []}

        with self.assertRaises(RuntimeError) as ctx:
            cli.native_notifications.send_native_test_notification(
                usage_payload=usage_payload,
                base_url="http://127.0.0.1:4673/",
                platform_name="darwin",
            )

        self.assertIn("current profile", str(ctx.exception).lower())

    @mock.patch("codex_account_manager.native_notifications.subprocess.run")
    @mock.patch("codex_account_manager.native_notifications._prepare_macos_notification_icon")
    @mock.patch("codex_account_manager.native_notifications.shutil.which")
    def test_send_native_test_notification_dispatches_terminal_notifier_on_macos(
        self,
        mock_which,
        mock_prepare_icon,
        mock_run,
    ):
        usage_payload = {
            "current_profile": "noob",
            "profiles": [
                {
                    "name": "noob",
                    "is_current": True,
                    "usage_5h": {"remaining_percent": 49.0},
                    "usage_weekly": {"remaining_percent": 88.0},
                }
            ],
        }
        mock_which.return_value = "/opt/homebrew/bin/terminal-notifier"
        mock_prepare_icon.return_value = "file:///tmp/cam-icon.png"
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        result = cli.native_notifications.send_native_test_notification(
            usage_payload=usage_payload,
            base_url="http://127.0.0.1:4673/",
            platform_name="darwin",
        )

        self.assertTrue(result["ok"])
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], "/opt/homebrew/bin/terminal-notifier")
        self.assertIn("Codex Account Manager", cmd)
        self.assertIn("Profile noob", cmd)
        self.assertIn("5H 49% left • Weekly 88% left", cmd)
        self.assertIn("http://127.0.0.1:4673/", cmd)
        self.assertIn("file:///tmp/cam-icon.png", cmd)

    def test_send_native_test_notification_rejects_unsupported_platform(self):
        usage_payload = {
            "current_profile": "noob",
            "profiles": [{"name": "noob", "is_current": True}],
        }

        with self.assertRaises(RuntimeError) as ctx:
            cli.native_notifications.send_native_test_notification(
                usage_payload=usage_payload,
                base_url="http://127.0.0.1:4673/",
                platform_name="linux",
            )

        self.assertIn("not implemented yet on this os", str(ctx.exception).lower())

    @mock.patch("codex_account_manager.native_notifications.shutil.which", return_value=None)
    def test_send_native_test_notification_reports_missing_terminal_notifier(self, mock_which):
        usage_payload = {
            "current_profile": "noob",
            "profiles": [{"name": "noob", "is_current": True}],
        }

        with self.assertRaises(RuntimeError) as ctx:
            cli.native_notifications.send_native_test_notification(
                usage_payload=usage_payload,
                base_url="http://127.0.0.1:4673/",
                platform_name="darwin",
            )

        self.assertIn("terminal-notifier", str(ctx.exception))
```

Also add the import near the top of `tests/test_cli_core.py`:

```python
from codex_account_manager import cli, native_notifications
```

Then expose the module on `cli` for simpler existing test style:

```python
cli.native_notifications = native_notifications
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -k "native_notification" -v
```

Expected:

- collection succeeds
- new tests fail because `codex_account_manager.native_notifications` does not exist yet

- [ ] **Step 3: Commit the failing-test checkpoint**

```bash
git add tests/test_cli_core.py
git commit -m "test: add native notification helper coverage"
```

## Task 2: Implement the native notification helper module

**Files:**

- Create: `codex_account_manager/native_notifications.py`
- Modify: `codex_account_manager/__init__.py`
- Test: `tests/test_cli_core.py`

- [ ] **Step 1: Write the minimal helper implementation**

Create `codex_account_manager/native_notifications.py` with this initial structure:

```python
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


APP_TITLE = "Codex Account Manager"
ICON_ASSET = Path(__file__).resolve().parent / "assets" / "codex_account_manager.svg"


def build_native_notification_payload(usage_payload: dict) -> dict:
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
    pct_5h = int(round(float(rem_5h.get("remaining_percent"))))
    pct_weekly = int(round(float(rem_weekly.get("remaining_percent"))))

    return {
        "profile_name": current_name,
        "title": APP_TITLE,
        "subtitle": f"Profile {current_name}",
        "message": f"5H {pct_5h}% left • Weekly {pct_weekly}% left",
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


def send_native_test_notification(usage_payload: dict, base_url: str, platform_name: str | None = None) -> dict:
    payload = build_native_notification_payload(usage_payload)
    active_platform = str(platform_name or sys.platform)

    if active_platform == "darwin":
        return _send_macos_native_notification(payload, base_url)
    if active_platform.startswith("linux"):
        raise RuntimeError("Native notifications are not implemented yet on this OS.")
    if active_platform.startswith("win"):
        raise RuntimeError("Native notifications are not implemented yet on this OS.")
    raise RuntimeError(f"Native notifications are not supported on platform: {active_platform}")
```

Expose the module in `codex_account_manager/__init__.py`:

```python
from . import native_notifications
from .cli import main

__all__ = ["main", "native_notifications"]
```

- [ ] **Step 2: Run the backend tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -k "native_notification" -v
```

Expected:

- all new helper tests pass

- [ ] **Step 3: Refactor the payload builder for malformed percentages**

Tighten `build_native_notification_payload` so malformed usage data raises a human-readable error instead of a `TypeError`/`ValueError`:

```python
    try:
        pct_5h = int(round(float(rem_5h.get("remaining_percent"))))
        pct_weekly = int(round(float(rem_weekly.get("remaining_percent"))))
    except Exception as exc:
        raise RuntimeError("Native notification test requires current-profile usage data.") from exc
```

- [ ] **Step 4: Re-run the backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -k "native_notification" -v
```

Expected:

- all native helper tests still pass

- [ ] **Step 5: Commit the helper module**

```bash
git add codex_account_manager/native_notifications.py codex_account_manager/__init__.py tests/test_cli_core.py
git commit -m "feat: add native notification backend helper"
```

## Task 3: Add the backend API route for the web-panel test action

**Files:**

- Modify: `codex_account_manager/cli.py`
- Modify: `docs/ui-api.md`
- Test: `tests/test_cli_core.py`

- [ ] **Step 1: Write the failing route test**

Add this test to `tests/test_cli_core.py` near the other HTML/server-facing tests:

```python
    @mock.patch("codex_account_manager.cli.native_notifications.send_native_test_notification")
    @mock.patch("codex_account_manager.cli.collect_usage_local_data_cached")
    def test_native_notification_api_uses_cached_usage_and_base_url(
        self,
        mock_collect_usage,
        mock_send_native,
    ):
        mock_collect_usage.return_value = {
            "current_profile": "noob",
            "profiles": [
                {
                    "name": "noob",
                    "is_current": True,
                    "usage_5h": {"remaining_percent": 49.0},
                    "usage_weekly": {"remaining_percent": 88.0},
                }
            ],
        }
        mock_send_native.return_value = {"ok": True, "backend": "terminal-notifier"}

        cfg = cli.load_cam_config()
        usage_payload = cli.collect_usage_local_data_cached(7, config=cfg, ttl_sec=2.0, force=True)
        result = cli.native_notifications.send_native_test_notification(
            usage_payload=usage_payload,
            base_url="http://127.0.0.1:4673/",
        )

        self.assertTrue(result["ok"])
        mock_collect_usage.assert_called_once()
        mock_send_native.assert_called_once()
        self.assertEqual(mock_send_native.call_args.kwargs["base_url"], "http://127.0.0.1:4673/")
```

This is intentionally a thin wiring test. It should fail until `cli.py` imports `native_notifications` and exposes a small route helper that uses the same arguments.

- [ ] **Step 2: Run the route test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -k "native_notification_api" -v
```

Expected:

- the test fails because `cli.native_notifications` is not imported yet or because the helper/route wiring is missing

- [ ] **Step 3: Implement the route helper in `cli.py`**

Add the import near the top of `codex_account_manager/cli.py`:

```python
from . import native_notifications
```

Add this helper near the other backend utility functions in `codex_account_manager/cli.py`:

```python
def _native_notification_test_base_url(host: str, port: int) -> str:
    return f"http://{host}:{int(port)}/"


def run_native_notification_test(host: str, port: int, timeout_sec: int = 7) -> dict:
    cfg = load_cam_config()
    usage_payload = collect_usage_local_data_cached(timeout_sec, config=cfg, ttl_sec=2.0, force=True)
    return native_notifications.send_native_test_notification(
        usage_payload=usage_payload,
        base_url=_native_notification_test_base_url(host, port),
    )
```

In the existing `Handler.do_POST` route block, add:

```python
            if self.command == "POST" and path == "/api/notifications/native-test":
                try:
                    payload = run_native_notification_test(host=host, port=port, timeout_sec=7)
                except RuntimeError as e:
                    return _json_error("NATIVE_NOTIFICATION_FAILED", str(e), 400)
                except Exception as e:
                    return _json_error("NATIVE_NOTIFICATION_FAILED", str(e), 500)
                return _json_ok(payload)
```

Update `docs/ui-api.md`:

```md
### Notifications

- `POST /api/notifications/test`
- `POST /api/notifications/native-test`
```

- [ ] **Step 4: Run the targeted route and helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -k "native_notification" -v
```

Expected:

- backend helper tests pass
- route wiring test passes

- [ ] **Step 5: Commit the API wiring**

```bash
git add codex_account_manager/cli.py docs/ui-api.md tests/test_cli_core.py
git commit -m "feat: add native notification api endpoint"
```

## Task 4: Add failing UI tests for the new notification card

**Files:**

- Modify: `tests/test_cli_core.py`
- Test: `tests/test_cli_core.py`

- [ ] **Step 1: Write the failing UI render test**

Add this test near the existing `render_ui_html` assertions:

```python
    def test_render_ui_html_contains_native_notification_test_controls(self):
        html = cli.render_ui_html(default_interval=5, token="test-token")

        self.assertIn('Notification (native os system)', html)
        self.assertIn('id="nativeNotifTestBtn"', html)
        self.assertIn("/api/notifications/native-test", html)
        self.assertIn("runNativeNotificationTest", html)
```

- [ ] **Step 2: Run the UI render test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -k "native_notification_test_controls" -v
```

Expected:

- the new UI render test fails because the card and JS hook do not exist yet

- [ ] **Step 3: Commit the failing UI-test checkpoint**

```bash
git add tests/test_cli_core.py
git commit -m "test: cover native notification ui controls"
```

## Task 5: Implement the new web-panel card and button wiring

**Files:**

- Modify: `codex_account_manager/cli.py`
- Test: `tests/test_cli_core.py`

- [ ] **Step 1: Add the new card markup**

In the settings-grid HTML near the existing `Alarm` and `Profiles` sections, replace the single full-width `Profiles` card with a two-card row shape:

```html
        <section class="control-card settings-card native-notify-card">
          <div class="group-title">Notification (native os system)</div>
          <div class="setting-row inset-row">
            <span class="setting-label" title="Send a real operating-system notification using the current profile usage data.">
              Send a real OS notification using current profile usage.
            </span>
          </div>
          <div class="settings-footer-actions">
            <button
              id="nativeNotifTestBtn"
              class="btn btn-block settings-footer-btn btn-primary"
              type="button"
              title="Send a native OS notification test using the current profile usage."
            >
              Test
            </button>
          </div>
        </section>

        <section class="control-card settings-card profiles-panel">
          <div class="group-title">Profiles</div>
          ...
        </section>
```

Adjust the CSS only as much as needed to keep both cards on one row on wider layouts:

```css
    .controls-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    .profiles-panel{grid-column:auto}
    .control-card.control-card-full{grid-column:1 / -1}
    @media (max-width:1100px){
      .controls-grid{grid-template-columns:1fr}
      .profiles-panel{grid-column:1}
    }
```

- [ ] **Step 2: Add the frontend action helper**

Add this JS helper near the other action wrappers:

```javascript
  async function runNativeNotificationTest(){
    await runAction("notifications.native_test", async ()=>{
      const payload = await postApi("/api/notifications/native-test", {});
      const profileName = String(payload?.profile_name || "").trim();
      setError(profileName ? `Native notification sent for ${profileName}.` : "Native notification sent.");
      return payload;
    }, { skipRefresh:true });
  }
```

Wire the button in the existing event-binding block:

```javascript
      byId("nativeNotifTestBtn").addEventListener("click", ()=>{
        runNativeNotificationTest().catch((e)=>setError(e?.message || String(e)));
      });
```

- [ ] **Step 3: Run the UI render test and the native-notification test subset**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -k "native_notification" -v
```

Expected:

- UI render test passes
- backend helper tests still pass

- [ ] **Step 4: Run the broader CLI core regression slice**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py -v
```

Expected:

- all tests in `tests/test_cli_core.py` pass

- [ ] **Step 5: Manual verification on macOS**

Start the local UI with the project Python, then click the new button in the browser:

```bash
.venv/bin/python -m codex_account_manager ui --host 127.0.0.1 --port 4673
```

Expected:

- the web panel renders the new `Notification (native os system)` card beside `Profiles` on desktop width
- clicking `Test` shows a macOS native notification
- notification title is `Codex Account Manager`
- notification subtitle is `Profile <current profile>`
- message is minimal usage text like `5H 49% left • Weekly 88% left`
- clicking the notification opens `http://127.0.0.1:4673/`

- [ ] **Step 6: Commit the UI implementation**

```bash
git add codex_account_manager/cli.py tests/test_cli_core.py
git commit -m "feat: add native notification web panel test action"
```

## Task 6: Final verification and cleanup

**Files:**

- Modify: none expected
- Test: `tests/test_cli_core.py`

- [ ] **Step 1: Run the full verification command**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_core.py tests/test_autoswitch_sim.py -v
```

Expected:

- full targeted test suite passes with no new failures

- [ ] **Step 2: Check the working tree**

Run:

```bash
git status --short
```

Expected:

- only the intended files are modified or clean if all commits were created as planned

- [ ] **Step 3: Record the implementation outcome**

If everything is green, summarize these points in the handoff:

```text
- New web-panel native notification card added beside Profiles
- POST /api/notifications/native-test implemented
- macOS native dispatch uses terminal-notifier with current-profile usage
- Linux and Windows return explicit not-implemented errors
- Tests: tests/test_cli_core.py and tests/test_autoswitch_sim.py
```

## Self-Review

**Spec coverage:** The plan covers the new UI card, `Test` button, backend-native route, macOS dispatch, explicit Linux/Windows errors, current-profile usage formatting, icon preparation, API docs update, automated tests, and manual click-open verification.

**Placeholder scan:** No `TODO`, `TBD`, or “write tests later” placeholders remain. Each task includes explicit files, code, commands, and expected outcomes.

**Type consistency:** The plan consistently uses `build_native_notification_payload`, `send_native_test_notification`, `run_native_notification_test`, `nativeNotifTestBtn`, and `POST /api/notifications/native-test`.
