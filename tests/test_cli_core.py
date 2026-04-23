import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from codex_account_manager import cli


class CliCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._orig = {
            "CAM_DIR": cli.CAM_DIR,
            "CAM_CONFIG_FILE": cli.CAM_CONFIG_FILE,
            "CAM_LOG_FILE": cli.CAM_LOG_FILE,
            "PROFILES_DIR": cli.PROFILES_DIR,
            "BACKUPS_DIR": cli.BACKUPS_DIR,
            "PROFILE_HOMES_DIR": cli.PROFILE_HOMES_DIR,
            "EXPORT_SESSIONS": dict(cli.EXPORT_SESSIONS),
            "IMPORT_ANALYSES": dict(cli.IMPORT_ANALYSES),
        }
        cli.CAM_DIR = root / "cam"
        cli.CAM_CONFIG_FILE = cli.CAM_DIR / "config.json"
        cli.CAM_LOG_FILE = cli.CAM_DIR / "ui.log"
        cli.PROFILES_DIR = root / "profiles"
        cli.BACKUPS_DIR = root / "backups"
        cli.PROFILE_HOMES_DIR = root / "homes"
        cli.EXPORT_SESSIONS.clear()
        cli.IMPORT_ANALYSES.clear()

    def tearDown(self):
        cli.CAM_DIR = self._orig["CAM_DIR"]
        cli.CAM_CONFIG_FILE = self._orig["CAM_CONFIG_FILE"]
        cli.CAM_LOG_FILE = self._orig["CAM_LOG_FILE"]
        cli.PROFILES_DIR = self._orig["PROFILES_DIR"]
        cli.BACKUPS_DIR = self._orig["BACKUPS_DIR"]
        cli.PROFILE_HOMES_DIR = self._orig["PROFILE_HOMES_DIR"]
        cli.EXPORT_SESSIONS.clear()
        cli.EXPORT_SESSIONS.update(self._orig["EXPORT_SESSIONS"])
        cli.IMPORT_ANALYSES.clear()
        cli.IMPORT_ANALYSES.update(self._orig["IMPORT_ANALYSES"])
        self.tmp.cleanup()

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

    def test_notification_alarm_preset_defaults_when_missing(self):
        cfg = cli.sanitize_cam_config({"notifications": {"enabled": True}})
        self.assertEqual(cfg["notifications"]["alarm_preset"], cli.DEFAULT_ALARM_PRESET_ID)

    def test_notification_alarm_preset_rejects_unknown_values(self):
        cfg = cli.sanitize_cam_config({"notifications": {"alarm_preset": "nope"}})
        self.assertEqual(cfg["notifications"]["alarm_preset"], cli.DEFAULT_ALARM_PRESET_ID)

    def test_notification_alarm_preset_keeps_known_value(self):
        cfg = cli.sanitize_cam_config({"notifications": {"alarm_preset": "zenith"}})
        self.assertEqual(cfg["notifications"]["alarm_preset"], "zenith")

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
                {"tag": "v0.0.13", "version": "v0.0.13", "title": "v0.0.13", "published_at": "2026-04-22T10:00:00Z", "body": "stable", "highlights": [], "url": "", "is_prerelease": False, "is_draft": False, "is_current": False, "source": "github"},
            ],
        }
        status = cli.build_update_status_payload(payload)
        self.assertTrue(status["update_available"])
        self.assertEqual(status["latest_version"], "v0.0.13")
        self.assertEqual((status["latest_release"] or {}).get("tag"), "v0.0.13")

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
        html = cli.render_ui_html(default_interval=5, token="test-token")
        self.assertIn('id="appUpdateBadge"', html)
        self.assertIn('id="appUpdateBtn"', html)
        self.assertIn('id="appUpdateBackdrop"', html)
        self.assertIn('id="appUpdateProgress"', html)
        self.assertIn('id="appUpdateProgressBar"', html)
        self.assertIn('id="appUpdateProgressNote"', html)
        self.assertIn("/api/app-update-status", html)
        self.assertIn("/api/system/update", html)

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

    def _write_profile(self, name: str, *, email: str, account_id: str) -> None:
        profile_dir = cli.PROFILES_DIR / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        auth = {
            "account_id": account_id,
            "id_token": f"header.{self._jwt_payload({'email': email})}.sig",
        }
        (profile_dir / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
        (profile_dir / "meta.json").write_text(json.dumps({"name": name, "saved_at": "2026-04-23T00:00:00", "account_hint": email}), encoding="utf-8")

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
