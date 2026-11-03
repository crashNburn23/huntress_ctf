import io
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import mock_gm  # noqa: E402
from test_runner import PRODUCT_PLUGIN, wait_for  # noqa: E402
from race import config, replay, status  # noqa: E402
from race.runner import Runner  # noqa: E402


class ReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = mock_gm.serve(lanes=["bin"], hard_lanes={"bin"})
        s = cls.s = config.Settings()
        s.gm_url, s.run_dir, s.plugin_dir = cls.srv.url, tempfile.mkdtemp(), tempfile.mkdtemp()
        s.lanes, s.lane_solver, s.park_s = {"bin": 3}, {"bin": "example"}, 30
        r = Runner(1, s)
        with redirect_stdout(io.StringIO()):
            th = threading.Thread(target=r.run, kwargs={"wait": False}, daemon=True)
            th.start()
            wait_for(lambda: status.latest(1, s).get(("bin", "single"), {}).get("state") == "escalated")
            # before the fix: verify a scratch plugin (no ground truth yet)
            cls.scratch = os.path.join(tempfile.mkdtemp(), "bin_product.py")
            with open(cls.scratch, "w") as f:
                f.write(PRODUCT_PLUGIN)
            cls.pre = replay.run(1, "bin", "single", s, extra=cls.scratch, out=lambda m: None)
            shutil.copy(cls.scratch, os.path.join(s.plugin_dir, "bin_product.py"))
            th.join(timeout=60)
        cls.summary = r.summary

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_scratch_plugin_fills_blanks_before_install(self):
        self.assertIsNone(self.pre["wrong"], "no ground truth before the mode is solved")
        self.assertEqual(self.pre["blank"], [])
        self.assertEqual(set(self.pre["provenance"].values()), {"bin_product"})

    def test_replay_passes_and_mask_hides_the_fix(self):
        self.assertTrue(self.summary["bin"]["ok"])
        lines = []
        r = replay.run(1, "bin", "mastery", self.s, out=lines.append)
        self.assertTrue(lines[0].startswith("[grade] bin/mastery: PASS"), lines[0])
        self.assertEqual(r["wrong"], [])
        lines = []
        r = replay.run(1, "bin", "mastery", self.s, mask=["bin_product"], out=lines.append)
        self.assertTrue(lines[0].startswith("[grade] bin/mastery: FAIL wrong 3"), lines[0])
        self.assertNotIn("RACE_PLUGIN_EXCLUDE", os.environ, "mask must not leak past the replay")


if __name__ == "__main__":
    unittest.main()
