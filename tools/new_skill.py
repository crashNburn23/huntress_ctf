#!/usr/bin/env python3
"""Create the empty Claude skill for a lane from docs/SKILL_TEMPLATE.md.

  python3 -I tools/new_skill.py <lane> [<lane> ...]      one or more lanes
  python3 -I tools/new_skill.py --all                    every lane in the config that has no skill yet

Writes .claude/skills/lane-<lane>/SKILL.md. Never overwrites an existing skill.
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from race import config  # noqa: E402

TEMPLATE = os.path.join(ROOT, "docs", "SKILL_TEMPLATE.md")


def skill_path(lane, root=ROOT):
    return os.path.join(root, ".claude", "skills", f"lane-{lane}", "SKILL.md")


def create(lane, root=ROOT):
    """-> path written, or None when the skill already exists."""
    if not re.fullmatch(r"[a-z0-9_-]+", lane):
        raise ValueError(f"bad lane name {lane!r}")
    p = skill_path(lane, root)
    if os.path.exists(p):
        return None
    with open(TEMPLATE) as f:
        text = f.read().replace("{lane}", lane)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "x") as f:
        f.write(text)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lanes", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    lanes = list(config.load().lanes) if a.all else a.lanes
    if not lanes:
        ap.error("name a lane or use --all")
    for lane in lanes:
        p = create(lane)
        print(f"{lane}: {'created ' + os.path.relpath(p, ROOT) if p else 'skill already exists'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
