"""race.watchdog: says out loud when time is being lost. Reads local files only (run.log, status, briefs, plugin and
pin stamps) and never calls the Game Master.

Alerts (one line each, repeated at 2x, 4x, ... the threshold until the condition clears):
  STALL <lane> Ns quiet                     a lane Python is still solving has logged nothing for --quiet s
  UNCLAIMED <lane>/<mode> Ns (steal-eligible)  an escalated row nobody claimed for steal_after_s
  FIXER_QUIET <lane>/<mode> Ns              claimed, but no plugin or pin change for --fixer-quiet seconds
  DEADLINE_ETA <lane>/<mode> Ns left        a timed attempt is close to its deadline and not done

  python3 -I tools/watchdog.py --day N [--lanes a,b] [--quiet 20] [--fixer-quiet 90]
"""
import json
import os
import re
import time

from . import config, pins, plugins, status

LINE = re.compile(r"^\[\s*[\d.]+s\] (\S+)\s+(.*)$")


class Watchdog:
    def __init__(self, day, s=None, lanes=None, quiet=20, fixer_quiet=90, eta=(120, 60, 30, 10)):
        self.day, self.s = day, s or config.load()
        self.lanes, self.quiet, self.fixer_quiet, self.eta = lanes, quiet, fixer_quiet, sorted(eta, reverse=True)
        self.log_path = os.path.join(self.s.day_dir(day), "run.log")
        self.pos, self.last_line, self.lane_done = 0, {}, set()
        self.fired = {}                         # alert key -> next threshold
        self.stamps = {}                        # lane -> (plugin stamp, pin stamp, since)

    def _mine(self, lane):
        return not self.lanes or lane in self.lanes

    def _read_log(self, now):
        try:
            with open(self.log_path) as f:
                f.seek(self.pos)
                for raw in f:
                    m = LINE.match(raw.rstrip("\n"))
                    if m:
                        lane, msg = m.groups()
                        self.last_line[lane] = now
                        if "LANE_DONE" in msg or "LANE_STOPPED" in msg:
                            self.lane_done.add(lane)
                self.pos = f.tell()
        except FileNotFoundError:
            pass

    def _fire(self, key, age, base, text):
        nxt = self.fired.get(key, base)
        if age >= nxt:
            while nxt <= age:                   # next repeat at the first doubling past the current age
                nxt *= 2
            self.fired[key] = nxt
            return [text]
        return []

    def tick(self, now=None):
        now = now or time.time()
        self._read_log(now)
        out = []
        lat = status.latest(self.day, self.s)
        # STALL = Python is working on the lane and has gone quiet. Escalated rows are UNCLAIMED / FIXER_QUIET.
        active = {lane for (lane, _), r in lat.items() if r["state"] == "solving"}
        for lane in sorted(active - self.lane_done):
            if not self._mine(lane) or lane == "runner":
                continue
            age = now - self.last_line.setdefault(lane, now)
            if age < self.quiet:
                self.fired.pop(("stall", lane), None)
            else:
                out += self._fire(("stall", lane), age, self.quiet, f"STALL {lane} {age:.0f}s quiet")
        for (lane, mode), r in sorted(lat.items()):
            if not self._mine(lane):
                continue
            age = now - r["t"]
            if r["state"] == "escalated":
                out += self._fire(("unclaimed", lane, mode), age, self.s.steal_after_s,
                                  f"UNCLAIMED {lane}/{mode} {age:.0f}s (steal-eligible)")
            else:
                self.fired.pop(("unclaimed", lane, mode), None)
            if r["state"] == "claimed":
                st = (plugins.stamp(lane, self.s), pins.stamp(self.day, lane, self.s))
                prev = self.stamps.get(lane)
                if not prev or prev[:2] != st:
                    self.stamps[lane] = st + (now,)
                    self.fired.pop(("quiet", lane, mode), None)
                since = now - max(self.stamps[lane][2], r["t"])
                out += self._fire(("quiet", lane, mode), since, self.fixer_quiet,
                                  f"FIXER_QUIET {lane}/{mode} {since:.0f}s, no plugin or pin change")
            if r["state"] in ("escalated", "claimed", "fixed", "solving") and r.get("brief"):
                try:
                    with open(r["brief"]) as f:
                        dl = json.load(f).get("deadline")
                except (OSError, ValueError):
                    dl = None
                if isinstance(dl, (int, float)):
                    left = dl - now
                    for th in self.eta:
                        k = ("eta", lane, mode, th)
                        if left <= th and k not in self.fired:
                            self.fired[k] = 1
                            out.append(f"DEADLINE_ETA {lane}/{mode} {max(0, left):.0f}s left, not done")
                            break
        return out

    def loop(self, poll=1.0):
        while True:
            for line in self.tick():
                print(line, flush=True)
            time.sleep(poll)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Watchdog: stall, unclaimed, quiet-fixer and deadline alerts.")
    ap.add_argument("--day", type=int, default=int(time.strftime("%d")))
    ap.add_argument("--lanes", default="")
    ap.add_argument("--quiet", type=float, default=20)
    ap.add_argument("--fixer-quiet", type=float, default=90)
    a = ap.parse_args(argv)
    try:
        Watchdog(a.day, lanes=[x for x in a.lanes.split(",") if x], quiet=a.quiet,
                 fixer_quiet=a.fixer_quiet).loop()
    except KeyboardInterrupt:
        pass
    return 0
