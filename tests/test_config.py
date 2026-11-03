import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config  # noqa: E402


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("RACE_"):
                del os.environ[k]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)

    def test_defaults_have_no_gm_url(self):
        s = config.load("/nonexistent.toml")
        self.assertEqual(s.gm_url, "")
        with self.assertRaises(SystemExit):
            s.require_gm()

    def test_env_overrides_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('gm_url = "http://file.invalid/"\nsessions = 3\n')
        os.environ["RACE_SESSIONS"] = "4"
        os.environ["RACE_LANES"] = "a=2,b=1"
        os.environ["RACE_RANKED"] = "yes"
        s = config.load(f.name)
        self.assertEqual(s.gm_url, "http://file.invalid/")
        self.assertEqual(s.sessions, 4)
        self.assertEqual(s.lanes, {"a": 2, "b": 1})
        self.assertTrue(s.ranked)

    def test_unknown_key_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("not_a_setting = 1\n")
        with self.assertRaises(SystemExit):
            config.load(f.name)

    def test_token_env_wins(self):
        os.environ["RACE_GM_TOKEN"] = " abc \n"
        self.assertEqual(config.token(config.load("/nonexistent.toml")), "abc")

    def test_seconds_until_waits_for_the_race_date(self):
        import datetime
        evening = datetime.datetime(2026, 3, 4, 20, 0, 0)
        self.assertEqual(config.seconds_until("08:50:00", 5, now=evening), 12 * 3600 + 50 * 60)
        self.assertEqual(config.seconds_until("08:50:00", 4, now=evening), 0)
        morning = datetime.datetime(2026, 3, 4, 8, 0, 0)
        self.assertEqual(config.seconds_until("08:50:00", None, now=morning), 50 * 60)
        month_end = datetime.datetime(2026, 1, 31, 20, 0, 0)
        self.assertEqual(config.seconds_until("08:50:00", 1, now=month_end), 12 * 3600 + 50 * 60)


if __name__ == "__main__":
    unittest.main()
