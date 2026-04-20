import contextlib
import io
import unittest

from codex_account_manager import autoswitch_sim


class AutoSwitchSimTests(unittest.TestCase):
    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = autoswitch_sim.main(argv)
        return rc, buf.getvalue()

    def test_default_scenario_switches_after_drop_below_threshold(self):
        rc, out = self.run_main(["--ticks", "8"])
        self.assertEqual(rc, 0)
        self.assertIn("arm-warning", out)
        self.assertIn("SWITCH ->", out)
        self.assertIn("Simulation complete", out)

    def test_live_detail_contains_threshold_crossing_signal(self):
        rc, out = self.run_main(
            [
                "--ticks",
                "5",
                "--threshold-5h",
                "30",
                "--alpha-5h",
                "33",
                "--alpha-drain-5h",
                "5",
                "--delay-ticks",
                "1",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertIn("h5_hit=yes", out)
        self.assertIn("breached=yes", out)


if __name__ == "__main__":
    unittest.main()
