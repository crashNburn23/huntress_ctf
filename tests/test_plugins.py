import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config, plugins  # noqa: E402


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.s = config.Settings()
        self.s.plugin_dir = tempfile.mkdtemp()
        os.environ.pop("RACE_PLUGIN_EXCLUDE", None)

    def put(self, name, code):
        with open(os.path.join(self.s.plugin_dir, name + ".py"), "w") as f:
            f.write(code)

    def test_fill_blank_order_override(self):
        self.put("bin_a", "def answer(q, ctx):\n    return 'A'\n")
        self.put("bin_b", "OVERRIDE = True\ndef answer(q, ctx):\n    return 'B' if q['id'] == 'k2' else None\n")
        self.put("meta_x", "def answer(q, ctx):\n    return 'X'\n")
        qs = [{"id": "k1"}, {"id": "k2"}, {"id": "k3"}]
        out, prov = plugins.apply("bin", qs, None, {"k1": "solver", "k2": "solver", "k3": ""}, self.s)
        self.assertEqual(out, {"k1": "solver", "k2": "B", "k3": "A"})
        self.assertEqual(prov, {"k2": "bin_b", "k3": "bin_a"})

    def test_mask_applies_to_every_path(self):
        self.put("bin_new", "def answer(q, ctx):\n    return 'leak'\n")
        os.environ["RACE_PLUGIN_EXCLUDE"] = "bin_new"
        try:
            self.assertEqual(plugins.discover("bin", self.s), [])
            with self.assertRaises(plugins.Masked):
                plugins.load_one("bin_new", self.s)
            out, _ = plugins.apply("bin", [{"id": "k"}], None, {"k": ""}, self.s)
            self.assertEqual(out["k"], "")
        finally:
            os.environ.pop("RACE_PLUGIN_EXCLUDE")

    def test_broken_and_raising_plugins_are_skipped(self):
        self.put("bin_bad", "def answer(q, ctx)\n")
        self.put("bin_boom", "def answer(q, ctx):\n    raise ValueError('x')\n")
        self.put("bin_ok", "def answer(q, ctx):\n    return 'ok'\n")
        self.assertEqual([b[0] for b in plugins.broken("bin", self.s)], ["bin_bad"])
        out, _ = plugins.apply("bin", [{"id": "k"}], None, {}, self.s, log=lambda m: None)
        self.assertEqual(out["k"], "ok")

    def test_stamp_changes_and_reload(self):
        self.put("bin_a", "def answer(q, ctx):\n    return '1'\n")
        st = plugins.stamp("bin", self.s)
        self.assertEqual(plugins.load_one("bin_a", self.s).answer({}, None), "1")
        time.sleep(0.01)
        self.put("bin_a", "def answer(q, ctx):\n    return '2'\n")
        self.assertNotEqual(st, plugins.stamp("bin", self.s))
        self.assertEqual(plugins.load_one("bin_a", self.s).answer({}, None), "2")


if __name__ == "__main__":
    unittest.main()
