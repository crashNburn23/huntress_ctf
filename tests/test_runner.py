"""End-to-end, offline: mock Game Master + runner + a simulated fixer."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import mock_gm  # noqa: E402
from race import config, status  # noqa: E402
from race.gm import GM  # noqa: E402
from race.runner import Runner  # noqa: E402

PRODUCT_PLUGIN = """def answer(q, ctx):
    if not q['id'].endswith('product_mod_97'):
        return None
    p = 1
    for x in ctx.for_qid(q['id'])['numbers.txt'].split():
        p = p * int(x) % 97
    return str(p)
"""


def load(p):
    with open(p) as f:
        return json.load(f)


def wait_for(fn, timeout=30):
    t = time.time() + timeout
    while time.time() < t:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError("timed out")


class RunnerTest(unittest.TestCase):
    def test_race_with_escalation_fix_and_target_lane(self):
        srv = mock_gm.serve(lanes=["warm", "bin", "web"], hard_lanes={"bin"}, unlock_in=1.0)
        try:
            s = config.Settings()
            s.gm_url, s.run_dir, s.plugin_dir = srv.url, tempfile.mkdtemp(), tempfile.mkdtemp()
            s.lanes = {"warm": 1, "bin": 3, "web": 3}
            s.lane_solver = {"warm": "example", "bin": "example"}
            s.park_s = 60
            r = Runner(1, s)
            th = threading.Thread(target=r.run, kwargs={"wait": False}, daemon=True)
            th.start()

            # bin escalates: the product key is blank, so nothing is submitted
            row = wait_for(lambda: status.latest(1, s).get(("bin", "single"), {}).get("state") == "escalated"
                           and status.latest(1, s)[("bin", "single")])
            self.assertEqual(row["counts"]["missing"], 1)
            self.assertFalse(any(c.startswith("toy-bin-01") for c, _ in srv.world.submits))
            brief = load(row["brief"])
            self.assertEqual(brief["missing"], ["bin-product_mod_97"])

            # a fixer claims it and installs a plugin; the hot re-run fixes single, and TT/mastery go cold
            self.assertTrue(status.claim(1, "bin", "single", "S2", s))
            with open(os.path.join(s.plugin_dir, "bin_product.py"), "w") as f:
                f.write(PRODUCT_PLUGIN)

            # web: a live-target lane goes straight to a fixer, who solves and submits each mode by hand
            def web_fixer():
                fixer, done = GM(s), set()
                while len(done) < 3:
                    for (lane, mode), row in status.latest(1, s).items():
                        if lane == "web" and row["state"] == "escalated" and mode not in done:
                            b = load(row["brief"])
                            a = srv.world.attempts[b["challenge"]]
                            ans = {}
                            for q in b["questions"]:
                                n = a["nums"][int(q["id"][3]) - 1 if q["id"].startswith("set") else 0]
                                f = q["id"].rsplit("-", 1)[1]
                                ans[q["id"]] = str({"sum": sum(n), "count": len(n), "max": max(n)}[f])
                            fixer.submit(b["challenge"], ans)
                            done.add(mode)
                    time.sleep(0.2)
            threading.Thread(target=web_fixer, daemon=True).start()
            th.join(timeout=90)
            self.assertFalse(th.is_alive())
            self.assertTrue(r.summary["warm"]["ok"])
            self.assertTrue(r.summary["bin"]["ok"])
            lat = status.latest(1, s)
            self.assertEqual(lat[("bin", "mastery")]["state"], "done")
            self.assertEqual(lat[("web", "single")]["state"], "done")
            # bin: the hot re-run was the first bin submit; time trial and mastery needed no fixer
            self.assertEqual([c for c, _ in srv.world.submits if c.startswith("toy-bin-01")],
                             ["toy-bin-01", "toy-bin-01/time_trial", "toy-bin-01/mastery"])
        finally:
            srv.shutdown()

    def test_pin_triggers_plugin_first(self):
        srv = mock_gm.serve(lanes=["bin"], hard_lanes={"bin"})
        try:
            s = config.Settings()
            s.gm_url, s.run_dir, s.plugin_dir = srv.url, tempfile.mkdtemp(), tempfile.mkdtemp()
            s.lanes, s.lane_solver, s.park_s = {"bin": 3}, {"bin": "example"}, 3
            r = Runner(1, s)
            th = threading.Thread(target=r.run, kwargs={"wait": False}, daemon=True)
            th.start()
            wait_for(lambda: status.latest(1, s).get(("bin", "single"), {}).get("state") == "escalated")
            nums = srv.world.attempts["toy-bin-01"]["nums"][0]
            p = 1
            for x in nums:
                p = p * x % 97
            from race import pins
            pins.merge(1, "bin", "single", {"bin-product_mod_97": str(p)}, s)
            wait_for(lambda: status.latest(1, s).get(("bin", "single"), {}).get("state") == "done")
            wait_for(lambda: "PLUGIN_FIRST" in (status.latest(1, s)[("bin", "single")].get("note") or "")
                     or any("PLUGIN_FIRST" in (x.get("detail") or "") for x in status.rows(1, s)))
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
