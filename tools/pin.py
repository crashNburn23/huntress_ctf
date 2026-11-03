#!/usr/bin/env python3
"""Pin hand-solved answers for the runner (it re-runs within about a second).

  python3 -I tools/pin.py <lane> <mode> 'qid=value' ['qid2=value2' ...] [--day N]
  python3 -I tools/pin.py <lane> <mode> --from answers.json [--day N]     # {qid: value}; best for long/JSON values
  python3 -I tools/pin.py <lane> --show [--day N]
  python3 -I tools/pin.py <lane> --clear [--day N]                         # after the real plugin landed

Modes: single, time_trial, mastery. Use the qids exactly as the brief lists them.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config, pins  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lane")
    ap.add_argument("mode", nargs="?", choices=config.MODES)
    ap.add_argument("pairs", nargs="*", help="qid=value")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--day", type=int, default=int(time.strftime("%d")))
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()
    if a.show:
        print(json.dumps(pins.load(a.day, a.lane), indent=1))
        return 0
    if a.clear:
        pins.clear(a.day, a.lane)
        print("cleared")
        return 0
    if not a.mode:
        ap.error("mode is required to pin")
    vals = {}
    if a.src:
        with open(a.src) as f:
            vals.update(json.load(f))
    for p in a.pairs:
        if "=" not in p:
            ap.error(f"expected qid=value, got {p!r}")
        k, v = p.split("=", 1)
        vals[k.strip()] = v
    if not vals:
        ap.error("nothing to pin")
    path = pins.merge(a.day, a.lane, a.mode, vals)
    print(f"pinned {len(vals)} key(s) for {a.lane}/{a.mode} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
