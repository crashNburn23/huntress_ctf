import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config, status  # noqa: E402
from race.watchdog import Watchdog  # noqa: E402


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        self.s = config.Settings()
        self.s.run_dir, self.s.plugin_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.s.steal_after_s = 45
        os.makedirs(self.s.day_dir(1))

    def test_alerts_escalate_and_repeat(self):
        now = time.time()
        brief = os.path.join(self.s.run_dir, "b.json")
        with open(brief, "w") as f:
            json.dump({"deadline": now + 50}, f)
        with open(os.path.join(self.s.day_dir(1), "run.log"), "w") as f:
            f.write("[   1.0s] bin     single: ESCALATE incorrect\n")
        status.report(1, "bin", "single", "escalated", "runner", self.s, brief=brief)
        status.report(1, "meta", "single", "solving", "runner", self.s, brief=brief)
        status.report(1, "web", "single", "claimed", "S1", self.s, session="S1")
        w = Watchdog(1, self.s, quiet=20, fixer_quiet=90)
        first = w.tick(now)
        self.assertIn("DEADLINE_ETA bin/single 50s left, not done", first)
        out = w.tick(now + 50)
        self.assertTrue(any(x.startswith("STALL meta 50s") for x in out))
        self.assertFalse(any(x.startswith("STALL bin") for x in out), "escalated rows are not stalls")
        self.assertTrue(any(x.startswith("UNCLAIMED bin/single") for x in out))
        self.assertEqual([x for x in w.tick(now + 55) if x.startswith("STALL")], [], "no repeat before 2x")
        self.assertTrue(any(x.startswith("FIXER_QUIET web/single") for x in w.tick(now + 100)))

    def test_lane_filter(self):
        status.report(1, "bin", "single", "escalated", "runner", self.s)
        w = Watchdog(1, self.s, lanes=["web"])
        self.assertEqual(w.tick(time.time() + 500), [])


if __name__ == "__main__":
    unittest.main()
