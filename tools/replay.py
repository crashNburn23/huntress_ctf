#!/usr/bin/env python3
"""Rebuild a recorded mode offline and grade it against the answers the grader accepted.

  python3 -I tools/replay.py --day N --lane L --mode M [--mask stem1,stem2] [--pins]
  python3 -I tools/replay.py --day N --all                 every recorded lane/mode of the day (regression check)

Exit code 0 when every graded mode passes.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config, replay  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", type=int, required=True)
    ap.add_argument("--lane")
    ap.add_argument("--mode", choices=config.MODES)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--mask", default="", help="plugin stems to hide")
    ap.add_argument("--pins", action="store_true", help="overlay the day's pins")
    a = ap.parse_args()
    s = config.load()
    mask = [x for x in a.mask.split(",") if x]
    jobs = []
    if a.all:
        rec = os.path.join(s.day_dir(a.day), "rec")
        for lane in sorted(os.listdir(rec)) if os.path.isdir(rec) else []:
            for mode in config.MODES:
                if not os.path.isdir(os.path.join(rec, lane, mode)):
                    continue
                if not os.path.isdir(os.path.join(s.day_dir(a.day), "members", lane, mode)):
                    print(f"[grade] {lane}/{mode}: SKIP (live-target lane, nothing to rebuild)")
                    continue
                jobs.append((lane, mode))
    elif a.lane and a.mode:
        jobs.append((a.lane, a.mode))
    else:
        ap.error("give --lane and --mode, or --all")
    ok = True
    for lane, mode in jobs:
        r = replay.run(a.day, lane, mode, s, mask=mask, use_pins=a.pins)
        ok = ok and bool(r) and (r["wrong"] is None or not r["wrong"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
