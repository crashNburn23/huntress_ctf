import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import mock_gm  # noqa: E402
from race import config, lanes  # noqa: E402
from race.gm import GM, solved  # noqa: E402


class LaneTest(unittest.TestCase):
    def setUp(self):
        self.s = config.Settings()
        self.s.run_dir = tempfile.mkdtemp()
        self.s.plugin_dir = tempfile.mkdtemp()
        self.s.lane_solver = {"bin": "example", "meta": "example"}

    def test_safe_extract_blocks_traversal(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("../evil.txt", "x")
            z.writestr("/abs.txt", "x")
            z.writestr("ok/fine.txt", "hello")
        d = tempfile.mkdtemp()
        lanes.safe_extract(b.getvalue(), d)
        self.assertEqual(os.listdir(d), ["ok"])
        with self.assertRaises(ValueError):
            lanes.safe_extract(b.getvalue(), tempfile.mkdtemp(), budget=2)

    def test_sets_sort_numerically(self):
        d = tempfile.mkdtemp()
        for k in range(1, 13):
            os.makedirs(os.path.join(d, f"delivery-{k}"))
            with open(os.path.join(d, f"delivery-{k}", "n.txt"), "w") as f:
                f.write(str(k))
        m = lanes.Members.from_dir(d)
        self.assertEqual([s["n.txt"] for s in m.sets], [str(k).encode() for k in range(1, 13)])
        self.assertEqual(m.for_qid("set10.x")["n.txt"], b"10")

    @unittest.skipUnless(shutil.which("zip"), "needs the zip CLI to make a ZipCrypto archive")
    def test_wrong_passwords_never_abort_extraction(self):
        # with many wrong passwords, some pass ZipCrypto's 1-byte check and then fail on CRC/inflate
        src, d = tempfile.mkdtemp(), tempfile.mkdtemp()
        with open(os.path.join(src, "secret.txt"), "w") as f:
            f.write("payload " * 200)
        out = os.path.join(tempfile.mkdtemp(), "a.zip")
        subprocess.run(["zip", "-q", "-j", "-P", "right", out, os.path.join(src, "secret.txt")], check=True)
        with open(out, "rb") as f:
            data = f.read()
        lanes.safe_extract(data, d, passwords=[f"wrong{i}" for i in range(2000)] + ["right"])
        with open(os.path.join(d, "secret.txt")) as f:
            self.assertEqual(f.read(), "payload " * 200)

    def test_generic_lane_and_match(self):
        g = lanes.get("warm", self.s)
        self.assertIs(type(g), lanes.Lane)
        self.assertTrue(g.match({"challenge": "toy-warm-01"}))
        self.assertFalse(g.match({"challenge": "toy-warmish-01"}))
        self.assertTrue(lanes.get("web", self.s).has_targets)

    def test_example_lane_end_to_end_with_plugin(self):
        srv = mock_gm.serve(lanes=["bin"], hard_lanes={"bin"})
        try:
            self.s.gm_url = srv.url
            gm = GM(self.s)
            lane = lanes.get("bin", self.s)
            cid = "toy-bin-01/mastery"
            st = gm.start(cid)
            m = lane.fetch(gm, cid, st, tempfile.mkdtemp())
            self.assertEqual(len(m.sets), 3)
            ans, prov = lane.build(st["questions"], m)
            blank = [k for k, v in ans.items() if not v]
            self.assertEqual(len(blank), 3, "product keys stay blank for a fixer")
            with open(os.path.join(self.s.plugin_dir, "bin_product.py"), "w") as f:
                f.write("def answer(q, ctx):\n"
                        "    if not q['id'].endswith('product_mod_97'): return None\n"
                        "    p = 1\n"
                        "    for x in ctx.for_qid(q['id'])['numbers.txt'].split(): p = p * int(x) % 97\n"
                        "    return str(p)\n")
            ans, prov = lane.build(st["questions"], m)
            self.assertTrue(solved(gm.submit(cid, ans)))
            self.assertEqual(set(prov.values()), {"bin_product"})
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
