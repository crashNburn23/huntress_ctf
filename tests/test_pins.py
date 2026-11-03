import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config, pins  # noqa: E402


class PinTest(unittest.TestCase):
    def setUp(self):
        self.s = config.Settings()
        self.s.run_dir = tempfile.mkdtemp()

    def test_concurrent_merges_keep_everything(self):
        ts = [threading.Thread(target=pins.merge, args=(1, "bin", "mastery", {f"k{i}": str(i)}, self.s))
              for i in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(pins.load(1, "bin", "mastery", self.s)), 20)
        self.assertEqual(pins.load(1, "bin", "single", self.s), {}, "modes never share pins")

    def test_overlay_vs_fill_blank(self):
        ans, p = {"a": "solver", "b": ""}, {"a": "pin", "b": "pin"}
        self.assertEqual(pins.overlay(ans, p), {"a": "pin", "b": "pin"})
        self.assertEqual(pins.fill_blank(ans, p), {"a": "solver", "b": "pin"})

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            pins.merge(1, "bin", "practice", {}, self.s)


if __name__ == "__main__":
    unittest.main()
