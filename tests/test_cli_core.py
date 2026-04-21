import tempfile
import unittest
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
        }
        cli.CAM_DIR = root / "cam"
        cli.CAM_CONFIG_FILE = cli.CAM_DIR / "config.json"
        cli.CAM_LOG_FILE = cli.CAM_DIR / "ui.log"
        cli.PROFILES_DIR = root / "profiles"
        cli.BACKUPS_DIR = root / "backups"
        cli.PROFILE_HOMES_DIR = root / "homes"

    def tearDown(self):
        cli.CAM_DIR = self._orig["CAM_DIR"]
        cli.CAM_CONFIG_FILE = self._orig["CAM_CONFIG_FILE"]
        cli.CAM_LOG_FILE = self._orig["CAM_LOG_FILE"]
        cli.PROFILES_DIR = self._orig["PROFILES_DIR"]
        cli.BACKUPS_DIR = self._orig["BACKUPS_DIR"]
        cli.PROFILE_HOMES_DIR = self._orig["PROFILE_HOMES_DIR"]
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


if __name__ == "__main__":
    unittest.main()
