#!/usr/bin/env python3
"""Test a scratch plugin offline on a recorded mode before installing it.

  python3 -I tools/verify_plugin.py --day N --lane L --mode M --plugin /path/to/scratch.py

Builds the mode with every installed plugin plus the scratch one (named as it will be installed: use the final
filename, <lane>_<name>.py) and prints the grade line first. If the mode is not solved yet there is no ground
truth: it then shows which keys are still blank and which keys the scratch plugin answered.
Install with mv afterwards; the runner re-runs by itself.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config, replay  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", type=int, required=True)
    ap.add_argument("--lane", required=True)
    ap.add_argument("--mode", required=True, choices=config.MODES)
    ap.add_argument("--plugin", required=True)
    a = ap.parse_args()
    name = os.path.basename(a.plugin)
    if not (name.startswith(a.lane + "_") and name.endswith(".py")):
        ap.error(f"name the scratch file as it will be installed: {a.lane}_<name>.py (got {name})")
    with open(a.plugin, "rb") as f:
        try:
            compile(f.read(), a.plugin, "exec")
        except SyntaxError as e:
            print(f"[grade] {a.lane}/{a.mode}: DOES_NOT_COMPILE line {e.lineno}: {e.msg}")
            return 1
    r = replay.run(a.day, a.lane, a.mode, config.load(), extra=a.plugin)
    if not r:
        return 1
    mine = [k for k, v in r["provenance"].items() if v == name[:-3]]
    print(f"   scratch plugin answered: {len(mine)} key(s) {mine[:10]}")
    return 0 if (r["wrong"] == [] or (r["wrong"] is None and not r["blank"])) else 1


if __name__ == "__main__":
    sys.exit(main())
