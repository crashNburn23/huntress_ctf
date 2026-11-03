#!/usr/bin/env python3
"""Game Master CLI for fixers (live-target lanes, checks). Uses the shared client, so request pacing and 429
handling are shared with the runner. Responses are recorded under run/dayNN/rec/_manual/. Never prints the token.

  python3 -I tools/gm.py list
  python3 -I tools/gm.py status <challenge>
  python3 -I tools/gm.py start <challenge> [--timed]        reconnects to the current attempt; regular pool
  python3 -I tools/gm.py artifact <challenge>
  python3 -I tools/gm.py download <path> --out FILE          a root-relative artifact link -> file (prints sha256)
  python3 -I tools/gm.py submit <challenge> '<json answers>'
  python3 -I tools/gm.py pair --token-out ~/.config/race/token   create-only; writes the token with mode 600
"""
import argparse
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import config  # noqa: E402
from race.gm import GM  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("op", choices=["list", "status", "start", "artifact", "download", "submit", "pair"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("answers", nargs="?")
    ap.add_argument("--timed", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--token-out")
    ap.add_argument("--day", type=int, default=int(time.strftime("%d")))
    a = ap.parse_args()
    s = config.load()
    gm = GM(s, record_dir=os.path.join(s.day_dir(a.day), "rec", "_manual"))
    if a.op == "pair":
        if not a.token_out:
            ap.error("pair needs --token-out")
        print("paired; token written" if gm.pair(a.token_out) else "pairing returned no token")
        return 0
    if a.op != "list" and not a.arg:
        ap.error(f"{a.op} needs an argument")
    if a.op == "download":
        if not a.out:
            ap.error("download needs --out")
        data = gm.download(a.arg)
        with open(a.out, "wb") as f:
            f.write(data)
        print(f"{a.out}  {len(data)} bytes  sha256 {hashlib.sha256(data).hexdigest()}")
        return 0
    if a.op == "list":
        r = gm.list()
    elif a.op == "status":
        r = gm.status(a.arg)
    elif a.op == "start":
        r = gm.start(a.arg, timed=a.timed)
    elif a.op == "artifact":
        r = gm.artifact(a.arg)
    else:
        if not a.answers:
            ap.error("submit needs a JSON object of answers")
        r = gm.submit(a.arg, json.loads(a.answers))
    print(json.dumps(r, indent=1) if not isinstance(r, bytes) else f"<{len(r)} bytes>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
