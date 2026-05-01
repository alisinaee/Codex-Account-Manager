import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from codex_account_manager import cli, native_notifications


class CliCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._orig = {
            "CAM_DIR": cli.CAM_DIR,
            "CAM_CONFIG_FILE": cli.CAM_CONFIG_FILE,
            "CAM_LOG_FILE": cli.CAM_LOG_FILE,
            "AUTH_FILE": cli.AUTH_FILE,
            "PROFILES_DIR": cli.PROFILES_DIR,
            "BACKUPS_DIR": cli.BACKUPS_DIR,
            "PROFILE_HOMES_DIR": cli.PROFILE_HOMES_DIR,
            "EXPORT_SESSIONS": dict(cli.EXPORT_SESSIONS),
            "IMPORT_ANALYSES": dict(cli.IMPORT_ANALYSES),
            "ADD_LOGIN_SESSIONS": dict(cli.ADD_LOGIN_SESSIONS),
        }
        cli.CAM_DIR = root / "cam"
        cli.CAM_CONFIG_FILE = cli.CAM_DIR / "config.json"
        cli.CAM_LOG_FILE = cli.CAM_DIR / "ui.log"
        cli.AUTH_FILE = root / "auth.json"
        cli.PROFILES_DIR = root / "profiles"
        cli.BACKUPS_DIR = root / "backups"
        cli.PROFILE_HOMES_DIR = root / "homes"
        cli.EXPORT_SESSIONS.clear()
        cli.IMPORT_ANALYSES.clear()
        cli.ADD_LOGIN_SESSIONS.clear()

    def tearDown(self):
        cli.CAM_DIR = self._orig["CAM_DIR"]
        cli.CAM_CONFIG_FILE = self._orig["CAM_CONFIG_FILE"]
        cli.CAM_LOG_FILE = self._orig["CAM_LOG_FILE"]
        cli.AUTH_FILE = self._orig["AUTH_FILE"]
        cli.PROFILES_DIR = self._orig["PROFILES_DIR"]
        cli.BACKUPS_DIR = self._orig["BACKUPS_DIR"]
        cli.PROFILE_HOMES_DIR = self._orig["PROFILE_HOMES_DIR"]
        cli.EXPORT_SESSIONS.clear()
        cli.EXPORT_SESSIONS.update(self._orig["EXPORT_SESSIONS"])
        cli.IMPORT_ANALYSES.clear()
        cli.IMPORT_ANALYSES.update(self._orig["IMPORT_ANALYSES"])
        cli.ADD_LOGIN_SESSIONS.clear()
        cli.ADD_LOGIN_SESSIONS.update(self._orig["ADD_LOGIN_SESSIONS"])
        self.tmp.cleanup()

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

        payload = native_notifications.build_native_notification_payload(usage_payload)

        self.assertEqual(payload["profile_name"], "noob")
        self.assertEqual(payload["title"], "Codex Account Manager")
        self.assertEqual(payload["subtitle"], "Profile noob")
        self.assertEqual(payload["message"], "5H 49% left • Weekly 88% left")

    def test_electron_app_dir_resolves_repo_electron_folder(self):
        self.assertEqual(cli.electron_app_dir().name, "electron")
        self.assertTrue((cli.electron_app_dir() / "package.json").exists())

    def test_platform_process_candidates_on_macos_are_strict(self):
        with mock.patch("sys.platform", "darwin"):
            candidates = cli._platform_process_candidates()
        self.assertEqual(
            candidates["Codex"],
            ["/Applications/Codex.app/Contents/MacOS/Codex"],
        )
        self.assertEqual(
            candidates["CodexBar"],
            ["/Applications/CodexBar.app/Contents/MacOS/CodexBar"],
        )

    def test_platform_process_candidates_on_linux_use_cli_names(self):
        with mock.patch("sys.platform", "linux"):
            candidates = cli._platform_process_candidates()
        self.assertEqual(candidates["Codex"], ["codex"])
        self.assertEqual(candidates["CodexBar"], ["codexbar"])

    @mock.patch("codex_account_manager.cli._proc_running")
    def test_detect_running_app_name_on_macos_uses_strict_process_paths(self, mock_proc_running):
        mock_proc_running.side_effect = [False, True]

        with mock.patch("sys.platform", "darwin"):
            app_name = cli.detect_running_app_name()

        self.assertEqual(app_name, "CodexBar")

    @mock.patch("codex_account_manager.cli._subprocess_run")
    def test_start_codex_on_macos_uses_exact_app_bundle_path(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("sys.platform", "darwin"):
            started = cli.start_codex(preferred_app_name="Codex")

        self.assertTrue(started)
        self.assertEqual(
            mock_run.call_args.args[0],
            ["open", "/Applications/Codex.app"],
        )

    @mock.patch("codex_account_manager.cli.time.sleep")
    @mock.patch("codex_account_manager.cli.codex_running", return_value=False)
    @mock.patch("codex_account_manager.cli._subprocess_run")
    def test_stop_codex_on_macos_quits_exact_app_bundle_paths(self, mock_run, _mock_running, _mock_sleep):
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("sys.platform", "darwin"):
            stopped = cli.stop_codex()

        self.assertTrue(stopped)
        self.assertEqual(
            mock_run.call_args_list[0].args[0],
            ["osascript", "-e", 'tell application (POSIX file "/Applications/Codex.app" as alias) to quit'],
        )
        self.assertEqual(
            mock_run.call_args_list[1].args[0],
            ["osascript", "-e", 'tell application (POSIX file "/Applications/CodexBar.app" as alias) to quit'],
        )

    @mock.patch("codex_account_manager.cli._ui_service_command_base")
    def test_build_ui_service_restart_command_reuses_runtime_base(self, mock_base):
        mock_base.return_value = ["py", "-3", "C:\\repo\\codex_account_manager\\cli.py"]

        command = cli._build_ui_service_restart_command("127.0.0.1", 4673, 5.0, 0.0)

        self.assertEqual(
            command,
            [
                "py",
                "-3",
                "C:\\repo\\codex_account_manager\\cli.py",
                "ui-service",
                "restart",
                "--host",
                "127.0.0.1",
                "--port",
                "4673",
                "--interval",
                "5.0",
                "--idle-timeout",
                "0.0",
                "--no-open",
            ],
        )

    @mock.patch("codex_account_manager.cli._ui_service_command_base")
    def test_build_ui_restart_helper_command_keeps_interpreter_and_script(self, mock_base):
        mock_base.return_value = ["py", "-3", "C:\\repo\\codex_account_manager\\cli.py"]

        command = cli._build_ui_restart_helper_command("127.0.0.1", 4673, 5.0, 0.0)

        self.assertEqual(command[:3], ["py", "-c", mock.ANY])
        self.assertEqual(
            command[3:],
            [
                "py",
                "-3",
                "C:\\repo\\codex_account_manager\\cli.py",
                "ui-service",
                "restart",
                "--host",
                "127.0.0.1",
                "--port",
                "4673",
                "--interval",
                "5.0",
                "--idle-timeout",
                "0.0",
                "--no-open",
            ],
        )

    @mock.patch("codex_account_manager.cli.is_ui_healthy", return_value=True)
    @mock.patch("codex_account_manager.cli.read_ui_pid_info", return_value={"host": "127.0.0.1", "port": 4673, "pid": 4242, "token": "session-token"})
    @mock.patch("codex_account_manager.cli.detect_core_runtime")
    @mock.patch("codex_account_manager.cli.detect_python_runtime")
    def test_build_doctor_report_includes_python_core_and_ui_service_contract(
        self,
        mock_python,
        mock_core,
        _mock_pid,
        _mock_healthy,
    ):
        mock_python.return_value = {
            "available": True,
            "supported": True,
            "version": "3.11.9",
            "path": "/usr/bin/python3",
            "command": "python3",
        }
        mock_core.return_value = {
            "installed": True,
            "version": "0.0.20",
            "command_path": "/Users/test/.local/bin/codex-account",
            "min_supported_version": "0.0.20",
            "meets_minimum_version": True,
        }

        report = cli.build_doctor_report()

        self.assertEqual(report["python"]["version"], "3.11.9")
        self.assertEqual(report["core"]["command_path"], "/Users/test/.local/bin/codex-account")
        self.assertTrue(report["ui_service"]["running"])
        self.assertTrue(report["ui_service"]["healthy"])
        self.assertEqual(report["ui_service"]["token"], "session-token")
        self.assertEqual(report["errors"], [])

    @mock.patch("codex_account_manager.cli.build_doctor_report")
    def test_cmd_doctor_prints_json_payload(self, mock_report):
        mock_report.return_value = {
            "python": {"available": True, "supported": True, "version": "3.11.9", "path": "/usr/bin/python3"},
            "core": {"installed": True, "version": "0.0.20", "command_path": "/Users/test/.local/bin/codex-account"},
            "ui_service": {"running": False, "healthy": False, "host": "127.0.0.1", "port": 4673, "base_url": "http://127.0.0.1:4673/", "token": ""},
            "errors": [],
        }

        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            rc = cli.cmd_doctor(as_json=True)

        self.assertEqual(rc, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["python"]["version"], "3.11.9")
        self.assertEqual(payload["core"]["version"], "0.0.20")

    @mock.patch("codex_account_manager.cli._subprocess_run")
    def test_cmd_electron_runs_npm_install_then_dev_when_deps_missing(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0)
        electron_dir = self.tmp.name and Path(self.tmp.name) / "electron"
        electron_dir.mkdir()
        (electron_dir / "package.json").write_text("{}", encoding="utf-8")

        rc = cli.cmd_electron(electron_dir=electron_dir)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_run.call_args_list[0].args[0], ["npm", "install", "--foreground-scripts", "--progress=true", "--loglevel=info"])
        self.assertEqual(mock_run.call_args_list[0].kwargs["cwd"], str(electron_dir))
        self.assertEqual(mock_run.call_args_list[1].args[0], ["npm", "run", "dev"])
        self.assertEqual(mock_run.call_args_list[1].kwargs["cwd"], str(electron_dir))

    @mock.patch("codex_account_manager.cli._subprocess_run")
    def test_cmd_electron_no_install_reports_missing_runtime_deps(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0)
        electron_dir = Path(self.tmp.name) / "electron"
        electron_dir.mkdir()
        (electron_dir / "package.json").write_text("{}", encoding="utf-8")

        rc = cli.cmd_electron(electron_dir=electron_dir, no_install=True)

        self.assertEqual(rc, 1)
        self.assertEqual(mock_run.call_args_list, [])

    @mock.patch("codex_account_manager.cli._subprocess_run")
    def test_cmd_electron_installs_when_renderer_deps_are_missing(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0)
        electron_dir = Path(self.tmp.name) / "electron"
        electron_dir.mkdir()
        (electron_dir / "package.json").write_text("{}", encoding="utf-8")
        (electron_dir / "node_modules" / "electron").mkdir(parents=True)

        rc = cli.cmd_electron(electron_dir=electron_dir)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_run.call_args_list[0].args[0], ["npm", "install", "--foreground-scripts", "--progress=true", "--loglevel=info"])
        self.assertEqual(mock_run.call_args_list[1].args[0], ["npm", "run", "dev"])

    @mock.patch("codex_account_manager.cli._subprocess_run")
    def test_cmd_electron_skips_install_when_runtime_deps_exist(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0)
        electron_dir = Path(self.tmp.name) / "electron"
        electron_dir.mkdir()
        (electron_dir / "package.json").write_text("{}", encoding="utf-8")
        for dep in ("electron", "vite", "react", "react-dom"):
            (electron_dir / "node_modules" / dep).mkdir(parents=True)

        rc = cli.cmd_electron(electron_dir=electron_dir)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_run.call_args_list[0].args[0], ["npm", "run", "dev"])
        self.assertEqual(len(mock_run.call_args_list), 1)

    @mock.patch("codex_account_manager.cli._subprocess_run")
    def test_cmd_electron_offline_existing_runtime_still_starts(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0)
        electron_dir = Path(self.tmp.name) / "electron"
        electron_dir.mkdir()
        (electron_dir / "package.json").write_text("{}", encoding="utf-8")
        for dep in ("electron", "vite", "react", "react-dom"):
            (electron_dir / "node_modules" / dep).mkdir(parents=True)

        with mock.patch("codex_account_manager.cli._internet_available_for_npm", return_value=False):
            rc = cli.cmd_electron(electron_dir=electron_dir)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_run.call_args_list[0].args[0], ["npm", "run", "dev"])
        self.assertEqual(len(mock_run.call_args_list), 1)

    def test_send_native_test_notification_returns_error_when_current_profile_missing(self):
        usage_payload = {"current_profile": None, "profiles": []}

        with self.assertRaises(RuntimeError) as ctx:
            native_notifications.send_native_test_notification(
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

        result = native_notifications.send_native_test_notification(
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
        self.assertIn("-open", cmd)
        self.assertNotIn("-execute", cmd)
        self.assertIn("http://127.0.0.1:4673/", cmd)
        self.assertIn("file:///tmp/cam-icon.png", cmd)

    @mock.patch("codex_account_manager.native_notifications.subprocess.run")
    @mock.patch("codex_account_manager.native_notifications._prepare_macos_notification_icon")
    @mock.patch("codex_account_manager.native_notifications.shutil.which")
    def test_send_native_switch_notification_uses_lead_message(
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

        result = native_notifications.send_native_switch_notification(
            usage_payload=usage_payload,
            base_url="http://127.0.0.1:4673/",
            seconds_until_switch=30,
            platform_name="darwin",
        )

        self.assertTrue(result["ok"])
        cmd = mock_run.call_args.args[0]
        self.assertIn("Auto switch starts in 30 seconds • 5H 49% left • Weekly 88% left", cmd)

    def test_send_native_test_notification_rejects_unsupported_platform(self):
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

        with self.assertRaises(RuntimeError) as ctx:
            native_notifications.send_native_test_notification(
                usage_payload=usage_payload,
                base_url="http://127.0.0.1:4673/",
                platform_name="linux",
            )

        self.assertIn("not implemented yet on this os", str(ctx.exception).lower())

    @mock.patch("codex_account_manager.native_notifications.shutil.which", return_value=None)
    def test_send_native_test_notification_reports_missing_terminal_notifier(self, mock_which):
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

        with self.assertRaises(RuntimeError) as ctx:
            native_notifications.send_native_test_notification(
                usage_payload=usage_payload,
                base_url="http://127.0.0.1:4673/",
                platform_name="darwin",
            )

        self.assertIn("terminal-notifier", str(ctx.exception))

    def test_log_redaction_applies_to_message_and_details(self):
        cli.cam_log(
            "info",
            "auth bearer abcdefghijklmnopqrstuvwxyz",
            details={"access_token": "secret-value", "nested": {"authorization": "Bearer very-secret-token"}},
            echo=False,
        )
        rows = cli.read_log_tail(5)
        self.assertTrue(rows)
        last = rows[-1]
        self.assertIn("[REDACTED]", str(last.get("message")))
        details = last.get("details") or {}
        self.assertEqual(details.get("access_token"), "[REDACTED]")
        self.assertEqual((details.get("nested") or {}).get("authorization"), "[REDACTED]")

    def test_config_revision_stale_write_rejected(self):
        cfg1 = cli.load_cam_config()
        rev1 = int(((cfg1.get("_meta") or {}).get("revision")) or 0)
        self.assertGreaterEqual(rev1, 1)
        cfg2 = cli.update_cam_config({"ui": {"theme": "dark"}}, base_revision=rev1)
        rev2 = int(((cfg2.get("_meta") or {}).get("revision")) or 0)
        self.assertGreater(rev2, rev1)
        with self.assertRaises(RuntimeError):
            cli.update_cam_config({"ui": {"theme": "light"}}, base_revision=rev1)

    def test_error_taxonomy(self):
        self.assertEqual(cli._error_type_for_code("FORBIDDEN", 403), "permission")
        self.assertEqual(cli._error_type_for_code("BAD_JSON", 400), "validation")
        self.assertEqual(cli._error_type_for_code("COMMAND_FAILED", 400), "transient")
        self.assertEqual(cli._error_type_for_code("INTERNAL", 500), "internal")

    def test_notification_thresholds_are_sanitized(self):
        cfg = cli.sanitize_cam_config({"notifications": {"thresholds": {"h5_warn_pct": 120, "weekly_warn_pct": -10}}})
        self.assertEqual(cfg["notifications"]["thresholds"]["h5_warn_pct"], 100)
        self.assertEqual(cfg["notifications"]["thresholds"]["weekly_warn_pct"], 0)

    def test_local_release_notes_parser_handles_unreleased_and_versions(self):
        fallback = Path(self.tmp.name) / "release-notes.md"
        fallback.write_text(
            "# Release Notes\n\n"
            "## Unreleased\n\n"
            "- Added local fallback support.\n\n"
            "## v1.2.3-beta\n\n"
            "- Added feature A.\n"
            "- Fixed bug B.\n",
            encoding="utf-8",
        )
        rows = cli._parse_local_release_notes(fallback)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["tag"], "Unreleased")
        self.assertTrue(rows[0]["highlights"])
        self.assertEqual(rows[1]["tag"], "v1.2.3-beta")
        self.assertTrue(rows[1]["is_prerelease"])

    def test_github_release_normalization_excludes_drafts(self):
        rows = cli._normalize_github_release_rows(
            [
                {"tag_name": "v0.0.2", "name": "v0.0.2", "draft": False, "prerelease": False, "body": "- stable", "published_at": "2026-04-20T10:00:00Z", "html_url": "https://example/release/2"},
                {"tag_name": "v0.0.3-rc1", "name": "v0.0.3-rc1", "draft": False, "prerelease": True, "body": "- rc", "published_at": "2026-04-21T10:00:00Z", "html_url": "https://example/release/3"},
                {"tag_name": "v0.0.4", "name": "v0.0.4", "draft": True, "prerelease": False, "body": "- draft", "published_at": "2026-04-22T10:00:00Z", "html_url": "https://example/release/4"},
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["tag"], "v0.0.3-rc1")
        self.assertTrue(rows[0]["is_prerelease"])
        self.assertEqual(rows[1]["tag"], "v0.0.2")

    def test_release_notes_payload_falls_back_when_fetch_fails(self):
        fallback = Path(self.tmp.name) / "release-notes.md"
        fallback.write_text(
            "# Release Notes\n\n"
            "## Unreleased\n\n"
            "- Local notes entry.\n",
            encoding="utf-8",
        )
        cache = {}

        def _broken_fetch():
            raise RuntimeError("network unavailable")

        payload = cli.load_release_notes_payload(
            force_refresh=True,
            cache=cache,
            fetcher=_broken_fetch,
            fallback_path=fallback,
        )
        self.assertEqual(payload["status"], "fallback")
        self.assertEqual(payload["source"], "local")
        self.assertTrue(payload["releases"])
        self.assertIn("network unavailable", str(payload.get("error")))

    def test_release_notes_payload_uses_cache_when_fresh(self):
        cache = {}
        mock_rows = [{"tag": "v9.9.9", "version": "v9.9.9", "title": "v9.9.9", "published_at": None, "body": "", "highlights": [], "url": "", "is_prerelease": False, "is_draft": False, "is_current": False, "source": "github"}]
        fetcher = mock.Mock(return_value=mock_rows)

        first = cli.load_release_notes_payload(force_refresh=True, cache=cache, fetcher=fetcher)
        second = cli.load_release_notes_payload(force_refresh=False, cache=cache, fetcher=fetcher)
        self.assertEqual(first["status"], "synced")
        self.assertTrue(second["cached"])
        self.assertEqual(fetcher.call_count, 1)

    def test_update_status_ignores_prerelease_when_newer_stable_exists(self):
        payload = {
            "status": "synced",
            "status_text": "Synced from GitHub",
            "source": "github",
            "repo_url": cli.PROJECT_RELEASES_URL,
            "releases": [
                {"tag": "v9.9.9-rc1", "version": "v9.9.9-rc1", "title": "v9.9.9-rc1", "published_at": "2026-04-23T10:00:00Z", "body": "rc", "highlights": [], "url": "", "is_prerelease": True, "is_draft": False, "is_current": False, "source": "github"},
                {"tag": "v0.0.21", "version": "v0.0.21", "title": "v0.0.21", "published_at": "2026-04-22T10:00:00Z", "body": "stable", "highlights": [], "url": "", "is_prerelease": False, "is_draft": False, "is_current": False, "source": "github"},
            ],
        }
        status = cli.build_update_status_payload(payload)
        self.assertTrue(status["update_available"])
        self.assertEqual(status["latest_version"], "v0.0.21")
        self.assertEqual((status["latest_release"] or {}).get("tag"), "v0.0.21")

    def test_update_status_returns_no_update_when_versions_match(self):
        payload = {
            "status": "synced",
            "status_text": "Synced from GitHub",
            "source": "github",
            "repo_url": cli.PROJECT_RELEASES_URL,
            "releases": [
                {"tag": f"v{cli.APP_VERSION}", "version": f"v{cli.APP_VERSION}", "title": f"v{cli.APP_VERSION}", "published_at": "2026-04-23T10:00:00Z", "body": "", "highlights": [], "url": "", "is_prerelease": False, "is_draft": False, "is_current": True, "source": "github"},
            ],
        }
        status = cli.build_update_status_payload(payload)
        self.assertFalse(status["update_available"])
        self.assertEqual(status["latest_version"], f"v{cli.APP_VERSION}")

    def test_render_ui_html_contains_update_controls(self):
        html = cli.render_ui_html(default_interval=5, token="test-token") + cli.render_ui_js(token="test-token") + cli.render_ui_css()
        self.assertIn('id="appUpdateBadge"', html)
        self.assertIn('id="appUpdateBtn"', html)
        self.assertIn('id="appUpdateBackdrop"', html)
        self.assertIn('/app-icon.svg', html)
        self.assertIn('class="app-brand-icon"', html)
        self.assertIn('id="appUpdateProgress"', html)
        self.assertIn('id="appUpdateProgressBar"', html)
        self.assertIn('id="appUpdateProgressNote"', html)
        self.assertIn("/api/app-update-status", html)
        self.assertIn("/api/system/update", html)

    def test_render_ui_html_contains_native_notification_test_controls(self):
        html = cli.render_ui_html(default_interval=5, token="test-token") + cli.render_ui_js(token="test-token") + cli.render_ui_css()

        self.assertIn(">Notification<", html)
        self.assertIn('id="testAlarmBtn"', html)
        self.assertIn("/api/notifications/native-test", html)
        self.assertIn("runNativeNotificationTest", html)
        self.assertNotIn('id="nativeNotifTestBtn"', html)
        self.assertNotIn("Choose Alarm", html)
        self.assertNotIn("Selected Alarm", html)

    def test_render_ui_html_uses_equal_width_settings_cards(self):
        html = cli.render_ui_html(default_interval=5, token="test-token") + cli.render_ui_js(token="test-token") + cli.render_ui_css()

        self.assertIn(".controls-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}", html)
        self.assertNotIn("grid-template-columns:1.2fr 1fr", html)

    def test_render_ui_html_offsets_alarm_two_seconds_before_notification(self):
        html = cli.render_ui_html(default_interval=5, token="test-token") + cli.render_ui_js(token="test-token") + cli.render_ui_css()

        self.assertIn("Math.max(0, delayMs - 2000)", html)
        self.assertIn('showInAppNotice("Codex Account Manager", ev.message || "Usage warning"', html)

    def test_render_ui_html_marks_run_switch_primary_and_auto_action_progress_hooks(self):
        html = cli.render_ui_html(default_interval=5, token="test-token") + cli.render_ui_js(token="test-token") + cli.render_ui_css()
        self.assertIn('id="asRunSwitchBtn" class="btn btn-block settings-footer-btn btn-primary"', html)
        self.assertIn("function renderAutoSwitchActionButtons(autoStateOverride=null)", html)
        self.assertIn("async function refreshAutoSwitchState()", html)
        self.assertIn('safeGet("/api/auto-switch/state", { timeoutMs: 2500 })', html)
        self.assertIn("resetAutoSwitchStateTimer();", html)
        self.assertIn("animation:autoSwitchArmedPulse 1.35s ease-in-out infinite", html)
        self.assertIn('runBtn.classList.toggle("btn-progress", activeRun);', html)
        self.assertIn('rapidBtn.classList.toggle("btn-progress", activeRapid);', html)
        self.assertIn("const switchFromRect = (!suppressCurrentProfileAutoAnimation", html)
        self.assertIn("getRowRectByName(nextCurrentProfile)", html)
        self.assertIn("animateSwitchRowToTop(nextCurrentProfile, switchFromRect).catch(() => {});", html)

    def test_render_ui_html_reserves_fixed_width_for_loading_table_columns(self):
        html = cli.render_ui_html(default_interval=5, token="test-token") + cli.render_ui_js(token="test-token") + cli.render_ui_css()
        self.assertIn('table{width:100%;min-width:100%;border-collapse:separate;border-spacing:0 8px;padding:0 0 10px}', html)
        self.assertIn('.usage-pct{display:inline-block;min-width:72px}', html)
        self.assertIn('.usage-cell-loading .usage-pct{min-width:72px}', html)

    def test_render_ui_html_guide_mentions_cross_layer_contract_and_supported_clients(self):
        html = cli.render_ui_html(default_interval=5, token="test-token") + cli.render_ui_js(token="test-token") + cli.render_ui_css()
        self.assertIn("source of truth for profile state, switching, usage, and local `/api/*` behavior used by both web and Electron", html)
        self.assertIn("<h4>Layer Responsibilities</h4>", html)
        self.assertIn("<b>Python CLI Core:</b> owns profiles, switching, usage collection, notifications, auto-switch logic, and local API endpoints.", html)
        self.assertIn("<b>Electron Shell:</b> optional desktop GUI with tray/menu integration, runtime bootstrap, and Windows taskbar/mini-meter extras.", html)
        self.assertIn("Current client support targets the <b>Codex CLI</b> and the <b>Codex VS Code extension</b>.", html)
        self.assertIn("manual reload or restart after switching", html)

    def test_build_auto_switch_state_payload_exposes_switch_runtime(self):
        runtime = {
            "events": [{"id": 1}],
            "active": True,
            "last_eval_ts": 120.0,
            "pending_warning": {"reason": "threshold"},
            "pending_switch_due_at": 160.0,
            "last_switch_ts": 100.0,
            "rapid_test_active": True,
            "rapid_test_started_at": 110.0,
            "rapid_test_wait_sec": 7,
            "rapid_test_step": 2,
            "test_run_active": False,
            "switch_in_flight": True,
            "switch_target": "work",
            "switch_started_at": 150.0,
        }
        cfg = {"auto_switch": {"enabled": True, "cooldown_sec": 60, "delay_sec": 45}}
        payload = cli.build_auto_switch_state_payload(runtime, cfg, now=155.0)
        self.assertTrue(payload["switch_in_flight"])
        self.assertEqual(payload["switch_target"], "work")
        self.assertEqual(payload["switch_started_at"], 150.0)
        self.assertEqual(payload["events_count"], 1)
        self.assertEqual(payload["cooldown_remaining_sec"], 5)
        self.assertEqual(payload["config_delay_sec"], 45)

    def test_trigger_breached_hits_when_remaining_equals_threshold(self):
        cfg = {
            "auto_switch": {
                "trigger_mode": "any",
                "thresholds": {
                    "h5_switch_pct": 30,
                    "weekly_switch_pct": 20,
                },
            }
        }
        current_row = {
            "usage_5h": {"remaining_percent": 30.0},
            "usage_weekly": {"remaining_percent": 75.0},
        }
        breached, detail = cli._trigger_breached(current_row, cfg)
        self.assertTrue(breached)
        self.assertTrue(detail["h5_hit"])

    def test_trigger_breached_hits_when_remaining_drops_below_threshold(self):
        cfg = {
            "auto_switch": {
                "trigger_mode": "any",
                "thresholds": {
                    "h5_switch_pct": 30,
                    "weekly_switch_pct": 20,
                },
            }
        }
        current_row = {
            "usage_5h": {"remaining_percent": 28.0},
            "usage_weekly": {"remaining_percent": 70.0},
        }
        breached, detail = cli._trigger_breached(current_row, cfg)
        self.assertTrue(breached)
        self.assertTrue(detail["h5_hit"])

    def test_choose_auto_switch_candidate_skips_exhausted_quota_accounts(self):
        cfg = {"auto_switch": {"ranking_mode": "balanced"}}
        payload = {
            "current_profile": "acc1",
            "profiles": [
                {"name": "acc1", "auto_switch_eligible": True, "usage_5h": {"remaining_percent": 12}, "usage_weekly": {"remaining_percent": 70}},
                {"name": "acc2", "auto_switch_eligible": True, "usage_5h": {"remaining_percent": 0}, "usage_weekly": {"remaining_percent": 95}},
                {"name": "acc3", "auto_switch_eligible": True, "usage_5h": {"remaining_percent": 90}, "usage_weekly": {"remaining_percent": 80}},
            ],
        }
        cand = cli._choose_auto_switch_candidate(payload, cfg)
        self.assertIsNotNone(cand)
        self.assertEqual(cand.get("name"), "acc3")

    def test_merge_cached_usage_payload_preserves_previous_row_when_refresh_returns_only_transient_errors(self):
        base_payload = {
            "refreshed_at": "2026-04-30T07:20:00",
            "current_profile": "acc7",
            "profiles": [
                {
                    "name": "acc7",
                    "email": "acc7@example.test",
                    "usage_5h": {"remaining_percent": 100, "resets_at": 1000, "text": "100%"},
                    "usage_weekly": {"remaining_percent": 88, "resets_at": 2000, "text": "88%"},
                    "plan_type": "team",
                    "is_paid": True,
                    "is_current": True,
                    "error": None,
                },
                {
                    "name": "acc8",
                    "email": "acc8@example.test",
                    "usage_5h": {"remaining_percent": 64, "resets_at": 3000, "text": "64%"},
                    "usage_weekly": {"remaining_percent": 72, "resets_at": 4000, "text": "72%"},
                    "plan_type": "free",
                    "is_paid": False,
                    "is_current": False,
                    "error": None,
                },
            ],
        }
        updated_payload = {
            "refreshed_at": "2026-04-30T07:24:03",
            "current_profile": "acc7",
            "profiles": [
                {
                    "name": "acc7",
                    "email": "acc7@example.test",
                    "usage_5h": {"remaining_percent": None, "resets_at": None, "text": "-"},
                    "usage_weekly": {"remaining_percent": None, "resets_at": None, "text": "-"},
                    "plan_type": None,
                    "is_paid": None,
                    "is_current": True,
                    "error": "request failed: transient reset",
                },
                {
                    "name": "acc8",
                    "email": "acc8@example.test",
                    "usage_5h": {"remaining_percent": None, "resets_at": None, "text": "-"},
                    "usage_weekly": {"remaining_percent": None, "resets_at": None, "text": "-"},
                    "plan_type": None,
                    "is_paid": None,
                    "is_current": False,
                    "error": "request failed: transient reset",
                },
            ],
        }
        list_rows = [{"name": "acc7"}, {"name": "acc8"}]

        merged = cli._merge_cached_usage_payload(base_payload, updated_payload, list_rows)

        self.assertEqual(merged["current_profile"], "acc7")
        self.assertEqual(merged["profiles"][0]["usage_5h"]["remaining_percent"], 100)
        self.assertEqual(merged["profiles"][0]["usage_weekly"]["remaining_percent"], 88)
        self.assertEqual(merged["profiles"][0]["plan_type"], "team")
        self.assertIsNone(merged["profiles"][0]["error"])
        self.assertEqual(merged["profiles"][1]["usage_5h"]["remaining_percent"], 64)
        self.assertEqual(merged["profiles"][1]["usage_weekly"]["remaining_percent"], 72)
        self.assertEqual(merged["profiles"][1]["plan_type"], "free")
        self.assertFalse(merged["profiles"][1]["is_paid"])
        self.assertIsNone(merged["profiles"][1]["error"])

    def test_merge_cached_usage_payload_filters_out_profiles_not_in_current_list(self):
        base_payload = {
            "refreshed_at": "2026-04-30T07:20:00",
            "current_profile": "acc7",
            "profiles": [
                {"name": "acc7", "usage_5h": {"remaining_percent": 100}, "usage_weekly": {"remaining_percent": 88}, "error": None},
                {"name": "old-removed", "usage_5h": {"remaining_percent": 55}, "usage_weekly": {"remaining_percent": 65}, "error": None},
            ],
        }
        updated_payload = {
            "refreshed_at": "2026-04-30T07:25:00",
            "current_profile": "acc7",
            "profiles": [
                {"name": "acc7", "usage_5h": {"remaining_percent": 96}, "usage_weekly": {"remaining_percent": 84}, "error": None},
            ],
        }

        merged = cli._merge_cached_usage_payload(base_payload, updated_payload, [{"name": "acc7"}])

        self.assertEqual([row["name"] for row in merged["profiles"]], ["acc7"])
        self.assertEqual(merged["profiles"][0]["usage_5h"]["remaining_percent"], 96)

    def test_ordered_chain_balanced_mode_ignores_manual_chain_override(self):
        cfg = {"auto_switch": {"ranking_mode": "balanced", "manual_chain": ["acc1", "acc2", "acc3"]}}
        payload = {
            "current_profile": "acc1",
            "profiles": [
                {"name": "acc1", "usage_5h": {"remaining_percent": 10}, "usage_weekly": {"remaining_percent": 50}},
                {"name": "acc2", "usage_5h": {"remaining_percent": 20}, "usage_weekly": {"remaining_percent": 20}},
                {"name": "acc3", "usage_5h": {"remaining_percent": 95}, "usage_weekly": {"remaining_percent": 95}},
            ],
        }
        chain = cli._ordered_chain_names(payload, cfg)
        self.assertEqual(chain, ["acc1", "acc3", "acc2"])

    def test_add_login_session_completes_when_temp_auth_is_written_before_process_exit(self):
        temp_home = Path(self.tmp.name) / "login-temp"
        temp_home.mkdir(parents=True)
        temp_auth = temp_home / "auth.json"
        temp_auth.write_text(json.dumps({
            "tokens": {
                "access_token": "fresh-access",
                "refresh_token": "fresh-refresh",
                "account_id": "acc-fresh",
                "id_token": f"header.{self._jwt_payload({'email': 'fresh@example.com'})}.sig",
            }
        }), encoding="utf-8")

        class Proc:
            terminated = False
            def terminate(self):
                self.terminated = True

        proc = Proc()
        cli.ADD_LOGIN_SESSIONS["sid"] = {
            "id": "sid",
            "name": "work",
            "status": "running",
            "temp_home": str(temp_home),
            "temp_auth": str(temp_auth),
            "overwrite": True,
            "keep_temp_home": True,
            "proc": proc,
        }

        self.assertTrue(cli._complete_add_login_session_from_auth("sid"))
        payload = cli.get_add_login_session("sid")
        self.assertEqual(payload["status"], "completed")
        saved = json.loads((cli.PROFILES_DIR / "work" / "auth.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["tokens"]["access_token"], "fresh-access")
        self.assertTrue(proc.terminated)

    def _write_profile(self, name: str, *, email: str, account_id: str) -> None:
        profile_dir = cli.PROFILES_DIR / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        auth = {
            "account_id": account_id,
            "id_token": f"header.{self._jwt_payload({'email': email})}.sig",
        }
        (profile_dir / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
        (profile_dir / "meta.json").write_text(json.dumps({"name": name, "saved_at": "2026-04-23T00:00:00", "account_hint": email}), encoding="utf-8")

    def _write_profile_auth(self, name: str, auth: dict, *, account_hint: str = "unknown") -> None:
        profile_dir = cli.PROFILES_DIR / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
        (profile_dir / "meta.json").write_text(
            json.dumps({"name": name, "saved_at": "2026-04-23T00:00:00", "account_hint": account_hint}),
            encoding="utf-8",
        )

    def _jwt_payload(self, payload: dict) -> str:
        import base64
        raw = json.dumps(payload).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    def test_export_profiles_archive_contains_manifest_and_profiles(self):
        self._write_profile("work", email="work@example.com", account_id="acc-work")
        self._write_profile("personal", email="personal@example.com", account_id="acc-personal")
        out = Path(self.tmp.name) / "profiles.camzip"
        payload = cli.create_profiles_archive(out)
        self.assertEqual(payload["count"], 2)
        self.assertTrue(out.exists())
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["version"], cli.PROFILE_ARCHIVE_VERSION)
            self.assertEqual(sorted(item["name"] for item in manifest["profiles"]), ["personal", "work"])
            self.assertIn("profiles/work/auth.json", zf.namelist())
            self.assertIn("profiles/personal/meta.json", zf.namelist())

    def test_export_profiles_archive_can_limit_to_selected_profiles(self):
        self._write_profile("work", email="work@example.com", account_id="acc-work")
        self._write_profile("personal", email="personal@example.com", account_id="acc-personal")
        out = Path(self.tmp.name) / "selected.camzip"
        payload = cli.create_profiles_archive(out, ["personal"])
        self.assertEqual(payload["count"], 1)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            self.assertIn("profiles/personal/auth.json", names)
            self.assertNotIn("profiles/work/auth.json", names)

    def test_export_profiles_fails_when_requested_profile_missing(self):
        out = Path(self.tmp.name) / "missing.camzip"
        with self.assertRaises(RuntimeError):
            cli.create_profiles_archive(out, ["nope"])

    def test_prepare_profiles_export_uses_custom_filename_and_extension(self):
        self._write_profile("work", email="work@example.com", account_id="acc-work")
        payload = cli.prepare_profiles_export(["work"], filename="team-migration")
        self.assertEqual(payload["filename"], "team-migration.camzip")
        session = cli.get_export_session(payload["export_id"])
        self.assertIsNotNone(session)
        self.assertEqual(session["filename"], "team-migration.camzip")
        self.assertTrue(Path(session["path"]).exists())

    def test_prepare_profiles_export_sanitizes_custom_filename(self):
        self._write_profile("work", email="work@example.com", account_id="acc-work")
        payload = cli.prepare_profiles_export(["work"], filename="../  weird export 2026!!.camzip")
        self.assertEqual(payload["filename"], "weird-export-2026.camzip")

    def test_import_analysis_rejects_bad_archive(self):
        bad = Path(self.tmp.name) / "bad.camzip"
        bad.write_text("not-a-zip", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            cli.analyze_profiles_archive(bad)

    def test_import_analysis_reports_name_and_account_conflicts(self):
        self._write_profile("work", email="work@example.com", account_id="acc-work")
        export_root = Path(self.tmp.name) / "export-src"
        export_profiles = export_root / "profiles"
        export_profiles.mkdir(parents=True, exist_ok=True)
        old_profiles = cli.PROFILES_DIR
        try:
            cli.PROFILES_DIR = export_profiles
            self._write_profile("work", email="new@example.com", account_id="other-acc")
            self._write_profile("moved", email="work@example.com", account_id="third-acc")
            archive = Path(self.tmp.name) / "conflicts.camzip"
            cli.create_profiles_archive(archive)
        finally:
            cli.PROFILES_DIR = old_profiles
        analysis = cli.analyze_profiles_archive(archive)
        by_name = {row["name"]: row for row in analysis["profiles"]}
        self.assertEqual(by_name["work"]["status"], "name_conflict")
        self.assertEqual(by_name["moved"]["status"], "account_conflict")

    def test_import_analysis_reports_duplicate_emails_inside_archive(self):
        archive = Path(self.tmp.name) / "duplicate-email.camzip"
        export_root = Path(self.tmp.name) / "export-duplicate-email"
        export_profiles = export_root / "profiles"
        export_profiles.mkdir(parents=True, exist_ok=True)
        old_profiles = cli.PROFILES_DIR
        try:
            cli.PROFILES_DIR = export_profiles
            self._write_profile("acc4", email="same@example.com", account_id="acc-4")
            self._write_profile("acc5", email="same@example.com", account_id="acc-5")
            cli.create_profiles_archive(archive)
        finally:
            cli.PROFILES_DIR = old_profiles
        analysis = cli.analyze_profiles_archive(archive)
        by_name = {row["name"]: row for row in analysis["profiles"]}
        self.assertEqual(by_name["acc4"]["status"], "account_conflict")
        self.assertEqual(by_name["acc5"]["status"], "account_conflict")
        self.assertTrue(any("also appears in archive profile" in msg for msg in by_name["acc4"]["problems"]))
        self.assertTrue(any("also appears in archive profile" in msg for msg in by_name["acc5"]["problems"]))

    def test_import_apply_skip_leaves_existing_profile_untouched(self):
        self._write_profile("work", email="work@example.com", account_id="acc-old")
        archive = Path(self.tmp.name) / "skip.camzip"
        export_root = Path(self.tmp.name) / "export-skip"
        export_profiles = export_root / "profiles"
        export_profiles.mkdir(parents=True, exist_ok=True)
        old_profiles = cli.PROFILES_DIR
        try:
            cli.PROFILES_DIR = export_profiles
            self._write_profile("work", email="new@example.com", account_id="acc-new")
            cli.create_profiles_archive(archive)
        finally:
            cli.PROFILES_DIR = old_profiles
        result = cli.apply_profiles_import(archive, [{"name": "work", "action": "skip"}])
        self.assertEqual(result["summary"]["skipped"], 1)
        auth = json.loads((cli.PROFILES_DIR / "work" / "auth.json").read_text(encoding="utf-8"))
        self.assertEqual(auth["account_id"], "acc-old")

    def test_import_apply_rename_creates_new_profile(self):
        archive = Path(self.tmp.name) / "rename.camzip"
        export_root = Path(self.tmp.name) / "export-rename"
        export_profiles = export_root / "profiles"
        export_profiles.mkdir(parents=True, exist_ok=True)
        old_profiles = cli.PROFILES_DIR
        try:
            cli.PROFILES_DIR = export_profiles
            self._write_profile("work", email="work@example.com", account_id="acc-work")
            cli.create_profiles_archive(archive)
        finally:
            cli.PROFILES_DIR = old_profiles
        result = cli.apply_profiles_import(archive, [{"name": "work", "action": "rename", "rename_to": "work-copy"}])
        self.assertEqual(result["summary"]["imported"], 1)
        self.assertTrue((cli.PROFILES_DIR / "work-copy" / "auth.json").exists())

    def test_import_apply_overwrite_replaces_existing_profile(self):
        self._write_profile("work", email="old@example.com", account_id="acc-old")
        archive = Path(self.tmp.name) / "overwrite.camzip"
        export_root = Path(self.tmp.name) / "export-overwrite"
        export_profiles = export_root / "profiles"
        export_profiles.mkdir(parents=True, exist_ok=True)
        old_profiles = cli.PROFILES_DIR
        try:
            cli.PROFILES_DIR = export_profiles
            self._write_profile("work", email="new@example.com", account_id="acc-new")
            cli.create_profiles_archive(archive)
        finally:
            cli.PROFILES_DIR = old_profiles
        result = cli.apply_profiles_import(archive, [{"name": "work", "action": "overwrite"}])
        self.assertEqual(result["summary"]["overwritten"], 1)
        auth = json.loads((cli.PROFILES_DIR / "work" / "auth.json").read_text(encoding="utf-8"))
        self.assertEqual(auth["account_id"], "acc-new")

    def test_usage_row_does_not_sync_live_auth_when_current_profile_is_email_only_match(self):
        self._write_profile_auth(
            "acc4",
            {
                "tokens": {
                    "access_token": "saved-access",
                    "id_token": f"header.{self._jwt_payload({'email': 'same@example.com'})}.sig",
                }
            },
            account_hint="same@example.com",
        )
        cli.AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        cli.AUTH_FILE.write_text(
            json.dumps(
                {
                    "tokens": {
                        "access_token": "live-access",
                        "id_token": f"header.{self._jwt_payload({'email': 'same@example.com'})}.sig",
                    }
                }
            ),
            encoding="utf-8",
        )

        with mock.patch(
            "codex_account_manager.cli.fetch_usage_from_auth",
            return_value=((90, None), (80, None), "plus", True, None),
        ):
            payload = cli.collect_usage_local_data(timeout_sec=1)

        self.assertEqual(payload["current_profile"], "acc4")
        saved = json.loads((cli.PROFILES_DIR / "acc4" / "auth.json").read_text(encoding="utf-8"))
        meta = json.loads((cli.PROFILES_DIR / "acc4" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["tokens"]["access_token"], "saved-access")
        self.assertNotIn("last_synced_at", meta)

    def test_usage_row_syncs_live_auth_when_current_profile_matches_same_principal(self):
        self._write_profile_auth(
            "acc4",
            {
                "tokens": {
                    "access_token": "saved-access",
                    "account_id": "acc-4",
                    "id_token": f"header.{self._jwt_payload({'email': 'same@example.com', 'sub': 'sub-4'})}.sig",
                }
            },
            account_hint="same@example.com",
        )
        cli.AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        cli.AUTH_FILE.write_text(
            json.dumps(
                {
                    "tokens": {
                        "access_token": "live-access",
                        "account_id": "acc-4",
                        "id_token": f"header.{self._jwt_payload({'email': 'same@example.com', 'sub': 'sub-4'})}.sig",
                    }
                }
            ),
            encoding="utf-8",
        )

        with mock.patch(
            "codex_account_manager.cli.fetch_usage_from_auth",
            return_value=((90, None), (80, None), "plus", True, None),
        ):
            payload = cli.collect_usage_local_data(timeout_sec=1)

        self.assertEqual(payload["current_profile"], "acc4")
        saved = json.loads((cli.PROFILES_DIR / "acc4" / "auth.json").read_text(encoding="utf-8"))
        meta = json.loads((cli.PROFILES_DIR / "acc4" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["tokens"]["access_token"], "live-access")
        self.assertIn("last_synced_at", meta)

    def test_import_analysis_rejects_unsupported_manifest_version(self):
        self._write_profile("work", email="work@example.com", account_id="acc-work")
        archive = Path(self.tmp.name) / "version.camzip"
        cli.create_profiles_archive(archive, ["work"])
        rewritten = Path(self.tmp.name) / "version-rewritten.camzip"
        with zipfile.ZipFile(archive, "r") as src, zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "manifest.json":
                    manifest = json.loads(data.decode("utf-8"))
                    manifest["version"] = cli.PROFILE_ARCHIVE_VERSION + 1
                    data = json.dumps(manifest).encode("utf-8")
                dst.writestr(info.filename, data)
        with self.assertRaises(RuntimeError):
            cli.analyze_profiles_archive(rewritten)


if __name__ == "__main__":
    unittest.main()
