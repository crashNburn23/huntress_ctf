import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import launch  # noqa: E402
import new_skill  # noqa: E402


class SkillTests(unittest.TestCase):
    def test_create_fills_lane_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            p = new_skill.create("demo", root=d)
            with open(p) as f:
                text = f.read()
            self.assertIn("name: lane-demo", text)
            self.assertNotIn("{lane}", text)
            self.assertIsNone(new_skill.create("demo", root=d))
            with self.assertRaises(ValueError):
                new_skill.create("../x", root=d)

    def test_prompt_names_only_existing_skills(self):
        with tempfile.TemporaryDirectory() as d:
            new_skill.create("bin", root=d)
            pr = launch.prompt("S1", 7, ["bin", "meta"], [], root=d)
            self.assertIn("lane-bin", pr)
            self.assertNotIn("lane-meta", pr)
            self.assertNotIn("Skill tool", launch.prompt("S1", 7, ["meta"], [], root=d))


if __name__ == "__main__":
    unittest.main()
