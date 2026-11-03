import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config  # noqa: E402
from race.sessions import plan, split, split_core_target, steal_candidates  # noqa: E402

LANES = config.Settings().lanes          # warm 1, meta 2, script 1, mobile 1, bin 3, web 3
HEAVY = {"bin", "web"}


class SessionTest(unittest.TestCase):
    def test_every_lane_once(self):
        for n in (1, 2, 3, 4, 6, 9):
            got = split(LANES, n)
            self.assertEqual(sorted(sum(got, [])), sorted(LANES), n)
            self.assertEqual(len(got), min(n, len(LANES)))

    def test_heavy_lanes_offset(self):
        for n in (2, 3, 6):
            for ls in split(LANES, n):
                self.assertLessEqual(len(HEAVY & set(ls)), 1, (n, ls))

    def test_default_two_is_balanced(self):
        a, b = split(LANES, 2)
        wa, wb = sum(LANES[x] for x in a), sum(LANES[x] for x in b)
        self.assertLessEqual(abs(wa - wb), 1)
        self.assertEqual(split(LANES, 1), [list(sorted(LANES, key=lambda k: -LANES[k]))])

    def test_core_target_default(self):
        s = config.Settings()
        self.assertEqual(s.session_split, "core_target")
        self.assertEqual(plan(s), [["warm", "meta", "script", "mobile", "bin"], ["web"]])
        self.assertEqual(plan(s, 5), plan(s))              # session count ignored in this mode
        self.assertEqual(split_core_target({"web": 3}, ["web"]), [["web"]])
        self.assertEqual(split_core_target({"bin": 3}, ["web"]), [["bin"]])

    def test_weight_mode(self):
        s = config.Settings(session_split="weight")
        self.assertEqual(plan(s, 3), split(LANES, 3))

    def test_steal_rule(self):
        asg = [["bin", "meta"], ["web", "warm"]]
        lat = {("web", "single"): {"state": "escalated", "t": 100},
               ("warm", "single"): {"state": "escalated", "t": 140},
               ("bin", "single"): {"state": "escalated", "t": 100}}
        # session 0 may take web (60 s unclaimed) and warm (its owner holds two open rows)
        self.assertEqual(steal_candidates(lat, asg, 0, now=160, steal_after_s=45),
                         [("web", "single"), ("warm", "single")])
        lat2 = {("web", "single"): {"state": "escalated", "t": 150}}
        self.assertEqual(steal_candidates(lat2, asg, 0, now=160, steal_after_s=45), [])


if __name__ == "__main__":
    unittest.main()
