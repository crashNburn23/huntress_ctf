import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import mock_gm  # noqa: E402
from race import config  # noqa: E402
from race.gm import GM, DeadlineError, solved  # noqa: E402


def settings(url, **kw):
    s = config.Settings()
    s.gm_url = url
    s.run_dir = tempfile.mkdtemp()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class GMTest(unittest.TestCase):
    def test_start_download_submit_record_replay(self):
        srv = mock_gm.serve(lanes=["warm"], token="tok")
        try:
            os.environ["RACE_GM_TOKEN"] = "tok"
            rec = tempfile.mkdtemp()
            gm = GM(settings(srv.url), record_dir=rec)
            cid = gm.list()["challenges"][0]["challenge"]
            st = gm.start(cid)
            self.assertEqual(st["attempt_id"], gm.start(cid)["attempt_id"], "start must reconnect")
            data = gm.download(st["artifacts"][0]["download"], cid=cid)
            self.assertTrue(data.startswith(b"PK"))
            r = gm.submit(cid, {q["id"]: "0" for q in st["questions"]})
            self.assertFalse(solved(r))
            # replay: same answers offline, no server
            off = GM(settings(""), replay_dir=rec)
            self.assertEqual(off.start(cid)["attempt_id"], st["attempt_id"])
            self.assertEqual(off.download("x", cid=cid), data)
        finally:
            os.environ.pop("RACE_GM_TOKEN", None)
            srv.shutdown()

    def test_regular_pool_unless_ranked(self):
        srv = mock_gm.serve(lanes=["bin"])
        try:
            cid = "toy-bin-01/time_trial"
            self.assertIsNone(GM(settings(srv.url)).start(cid, timed=True)["deadline"])
            cid2 = "toy-bin-01/mastery"
            self.assertIsNotNone(GM(settings(srv.url, ranked=True)).start(cid2, timed=True)["deadline"])
        finally:
            srv.shutdown()

    def test_429_shared_lockout_then_success(self):
        srv = mock_gm.serve(lanes=["warm"], rate_limit=2)
        try:
            gm = GM(settings(srv.url, pace_rate=0))
            t = time.time()
            for _ in range(3):
                gm.list()
            self.assertGreaterEqual(time.time() - t, 0.9, "the 429 lockout must be waited out")
        finally:
            srv.shutdown()

    def test_deadline_error(self):
        srv = mock_gm.serve(lanes=["warm"], rate_limit=1)
        try:
            gm = GM(settings(srv.url, pace_rate=0))
            t = time.time()
            with self.assertRaises(DeadlineError):     # every call 429s (lockout 1 s): must raise, not wait
                gm.status("x", deadline=time.time() + 0.1)
            self.assertLess(time.time() - t, 0.9)
        finally:
            srv.shutdown()

    def test_recordings_never_overwrite_across_clients(self):
        srv = mock_gm.serve(lanes=["warm"])
        try:
            rec = tempfile.mkdtemp()
            for _ in range(3):                         # a new client per call, like tools/gm.py and the runner's park
                GM(settings(srv.url), record_dir=rec).status("toy-warm-01")
            names = sorted(n for n in os.listdir(rec) if n.endswith(".json") and n != "index.json")
            self.assertEqual(len(names), 3, names)
        finally:
            srv.shutdown()

    def test_pair_never_recorded(self):
        srv = mock_gm.serve(lanes=["warm"])
        try:
            rec, out = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "tok")
            self.assertTrue(GM(settings(srv.url), record_dir=rec).pair(out))
            self.assertEqual(oct(os.stat(out).st_mode & 0o777), "0o600")
            for n in os.listdir(rec):
                self.assertNotIn("paired-test-token", open(os.path.join(rec, n), errors="replace").read())
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
