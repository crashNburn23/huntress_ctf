import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config, status  # noqa: E402


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.s = config.Settings()
        self.s.run_dir = tempfile.mkdtemp()

    def test_fold_and_notes_never_override(self):
        status.report(1, "bin", "single", "solving", "runner", self.s)
        status.report(1, "bin", "single", "escalated", "runner", self.s, counts={"wrong": 2}, brief="b.json")
        status.report(1, "bin", "single", "note", "runner", self.s, detail="hint")
        r = status.latest(1, self.s)[("bin", "single")]
        self.assertEqual(r["state"], "escalated")
        self.assertEqual(r["note"], "hint")
        self.assertIn("ESCALATED bin/single wrong=2", status.line(r))

    def test_claim_is_exclusive(self):
        status.report(1, "web", "single", "escalated", "runner", self.s)
        wins = []

        def go(name):
            if status.claim(1, "web", "single", name, self.s):
                wins.append(name)
        ts = [threading.Thread(target=go, args=(f"s{i}",)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(wins), 1)
        self.assertTrue(status.claim(1, "web", "single", wins[0], self.s), "owner may re-claim")
        self.assertFalse(status.claim(1, "meta", "single", "s1", self.s), "nothing to claim")

    def test_render(self):
        status.report(2, "warm", "mastery", "done", "runner", self.s)
        p = status.render(2, self.s)
        with open(p) as f:
            self.assertIn("| warm | mastery | done |", f.read())


if __name__ == "__main__":
    unittest.main()
