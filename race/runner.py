"""race.runner: the Python driver. Every lane runs in its own thread: single -> time_trial -> mastery.

Per mode:
  1. start (reconnects to the current attempt; regular pool unless ranked), record every response
  2. fetch + unpack members, build answers (lane solver, then plugins), fill blanks from pins
  3. blank keys -> escalate at once (an unknown key is a real problem; submitting would only waste a try)
     otherwise submit once; CORRECT -> next mode
  4. not CORRECT -> write the brief, post `escalated`, and PARK: watch the lane's plugins and pins; on any change
     rebuild OFFLINE from the saved members, then make one live submit to the same attempt. A fixer never re-runs
     anything. Writing a plugin or a pin is the whole interface.
Lanes with live targets (config target_lanes) skip 2-4: their attempt and brief go straight to a fixer, and the
runner only watches for the challenge to report solved.

Signals for fixers (in the log and as status notes):
  PLUGIN_FIRST  a pin solved this mode but no plugin changed since unlock: write the plugin before the next mode
  LANE_DONE     every mode of the lane is CORRECT
A lane never waits on another lane.

  python3 -I tools/run.py --day N [--wait] [--lanes a,b] [--dry]
"""
import json
import os
import re
import threading
import time

from . import config, lanes as lanes_mod, pins, plugins, status
from .gm import GM, GMError, solved

BLANK = plugins.BLANK


class Runner:
    def __init__(self, day, s=None, only=None, dry=False):
        self.day, self.s, self.dry = int(day), s or config.load(), dry
        self.dir = self.s.day_dir(day)
        os.makedirs(self.dir, exist_ok=True)
        self.lanes = [l for l in lanes_mod.all_lanes(self.s) if not only or l.name in only]
        self.t0 = time.time()
        self._lock = threading.Lock()
        self.summary = {}
        self.plugin_stamp0 = {}

    # ------------------------------------------------------------------ output
    def log(self, lane, msg):
        line = f"[{time.time() - self.t0:7.1f}s] {lane:7} {msg}"
        with self._lock:
            print(line, flush=True)
            with open(os.path.join(self.dir, "run.log"), "a") as f:
                f.write(line + "\n")

    def note(self, lane, mode, msg):
        self.log(lane, f"{mode}: {msg}")
        status.report(self.day, lane, mode, "note", "runner", self.s, detail=msg)

    def gm(self, lane=None, mode=None, replay=None):
        rec = os.path.join(self.dir, "rec", lane, mode) if lane else os.path.join(self.dir, "rec", "_list")
        return GM(self.s, record_dir=None if replay else rec, replay_dir=replay, prio=True)

    # ------------------------------------------------------------------ unlock
    def is_today(self, ch):
        if "day" in ch:
            try:
                return int(ch["day"]) == self.day
            except (TypeError, ValueError):
                pass
        cid = ch.get("challenge") or ch.get("id") or ""
        return bool(re.search(self.s.day_pattern.format(day=self.day), cid))

    def wait_unlock(self, wait=True, timeout=1800):
        if wait:
            delay = config.seconds_until(self.s.unlock_poll_at, self.day)
            if delay > 0:
                self.log("runner", f"day {self.day:02d}: polling starts at {self.s.unlock_poll_at} ({delay}s)")
                time.sleep(delay)
        gm, t_end = self.gm(), time.time() + timeout
        self.log("runner", f"day {self.day:02d}: polling for the day's challenges")
        while time.time() < t_end:
            try:
                r = gm.list()
            except GMError as e:
                self.log("runner", f"list failed: {e}; retrying")
                time.sleep(1)
                continue
            chs = r.get("challenges", r) if isinstance(r, dict) else r
            today = [c for c in (chs or []) if isinstance(c, dict) and self.is_today(c)]
            found = {}
            for lane in self.lanes:
                hit = [c for c in today if lane.match(c)]
                if hit:
                    found[lane.name] = hit[0]
            if found:
                self.t0 = time.time()
                self.log("runner", f"DAY{self.day:02d}_LIVE lanes={sorted(found)}")
                unmatched = [c.get("challenge") for c in today if not any(l.match(c) for l in self.lanes)]
                if unmatched:
                    self.log("runner", f"NEW/UNKNOWN challenge(s) no lane matches: {unmatched}")
                return found
            time.sleep(1)
        self.log("runner", "POLL_TIMEOUT: the day never listed")
        return {}

    # ------------------------------------------------------------------ one mode
    def brief(self, lane, mode, cidm, st, qs, ans, prov, missing, result, mdir):
        b = {"day": self.day, "lane": lane.name, "mode": mode, "challenge": cidm,
             "attempt_id": st.get("attempt_id"), "deadline": st.get("deadline"), "result": result,
             "missing": missing, "wrong": st.get("_wrong", []),
             "counts": {"total": len(qs), "missing": len(missing), "wrong": len(st.get("_wrong", []))},
             "questions": [dict(q, ours=ans.get(q["id"]), by=prov.get(q["id"], "solver")) for q in qs],
             "members_dir": mdir, "record_dir": os.path.join(self.dir, "rec", lane.name, mode),
             "pins_file": pins.path(self.day, lane.name, self.s), "updated": time.time()}
        p = os.path.join(self.dir, "briefs", f"{lane.name}_{mode}.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + f".tmp{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(b, f, indent=1, default=str)
        os.replace(tmp, p)
        return p, b["counts"]

    def build(self, lane, mode, qs, members, live):
        ans, prov = lane.build(qs, members, log=lambda m: self.log(lane.name, m))
        pm = pins.load(self.day, lane.name, mode, self.s)
        merged = pins.fill_blank(ans, pm) if live else pins.overlay(ans, pm)
        for k in pm:
            if merged.get(k) == pm[k] and ans.get(k) != pm[k]:
                prov[k] = "pin"
        return merged, prov

    def run_mode(self, lane, cid, mode, nxt):
        cidm = self.gm().cid_mode(cid, mode)
        timed = mode != "single"
        gm = self.gm(lane.name, mode)
        status.report(self.day, lane.name, mode, "solving", "runner", self.s)
        st = gm.start(cidm, timed=timed)
        if not isinstance(st, dict) or "questions" not in st:
            self.note(lane.name, mode, f"start gave no questions: {str(st)[:160]}")
            return False
        qs = st["questions"]
        deadline = st.get("deadline")
        mdir = os.path.join(self.dir, "members", lane.name, mode)

        if lane.has_targets:
            self.log(lane.name, f"{mode}: ESCALATE live target, handed to a fixer ({len(qs)} question(s))")
            p, c = self.brief(lane, mode, cidm, st, qs, {}, {}, [q["id"] for q in qs], "handoff", mdir)
            status.report(self.day, lane.name, mode, "escalated", "runner", self.s, brief=p, counts=c,
                          detail="live target: fixer solves and submits")
            return self.watch_target(lane, mode, cidm, gm)

        members = lane.fetch(gm, cidm, st, mdir)
        ans, prov = self.build(lane, mode, qs, members, live=True)
        missing = [q["id"] for q in qs if ans.get(q["id"]) in BLANK]
        result = "not submitted (blank keys)"
        if not missing:
            if self.dry:
                self.log(lane.name, f"{mode}: dry run, would submit {len(ans)} answers")
                return True
            r = gm.submit(cidm, ans, deadline=deadline)
            if solved(r):
                return self.mode_done(lane, mode, prov, nxt)
            result = str(r.get("result") if isinstance(r, dict) else r)
        self.log(lane.name, f"{mode}: ESCALATE {result}; missing {len(missing)} of {len(qs)}")
        p, c = self.brief(lane, mode, cidm, st, qs, ans, prov, missing, result, mdir)
        status.report(self.day, lane.name, mode, "escalated", "runner", self.s, brief=p, counts=c,
                      detail=("blank keys: fix before any submit" if missing else "graded " + result))
        return self.park(lane, mode, cidm, st, qs, members, mdir, ans, nxt)

    def mode_done(self, lane, mode, prov, nxt):
        status.report(self.day, lane.name, mode, "done", "runner", self.s)
        self.log(lane.name, f"{mode}: CORRECT")
        if nxt and "pin" in prov.values() and plugins.stamp(lane.name, self.s) == self.plugin_stamp0.get(lane.name):
            self.note(lane.name, mode, f"PLUGIN_FIRST: a pin solved {mode}; write the plugin before {nxt} starts")
        return True

    def park(self, lane, mode, cidm, st, qs, members, mdir, sent, nxt):
        gm = self.gm(lane.name, mode)
        seen = (plugins.stamp(lane.name, self.s), pins.stamp(self.day, lane.name, self.s))
        t_end = time.time() + self.s.park_s
        while time.time() < t_end:
            time.sleep(0.5)
            now = (plugins.stamp(lane.name, self.s), pins.stamp(self.day, lane.name, self.s))
            if now == seen:
                continue
            seen = now
            bad = plugins.broken(lane.name, self.s)
            if bad:
                self.note(lane.name, mode, f"plugin does not compile, skipped: {bad}")
            ans, prov = self.build(lane, mode, qs, members, live=False)        # offline: saved members only
            missing = [q["id"] for q in qs if ans.get(q["id"]) in BLANK]
            if missing:
                self.note(lane.name, mode, f"hot re-run: still {len(missing)} blank: {missing[:8]}")
                self.brief(lane, mode, cidm, st, qs, ans, prov, missing, "blank after re-run", mdir)
                continue
            if ans == sent:
                self.note(lane.name, mode, "hot re-run: answers unchanged, not resubmitting")
                continue
            if self.dry:
                self.note(lane.name, mode, "hot re-run: dry run, would resubmit")
                return True
            sent = ans
            r = gm.submit(cidm, ans, deadline=st.get("deadline"))
            if solved(r):
                self.log(lane.name, f"{mode}: hot re-run CORRECT")
                return self.mode_done(lane, mode, prov, nxt)
            res = str(r.get("result") if isinstance(r, dict) else r)
            self.note(lane.name, mode, f"hot re-run: {res}")
            self.brief(lane, mode, cidm, st, qs, ans, prov, [], "graded " + res, mdir)
        self.note(lane.name, mode, f"parked {self.s.park_s}s without a fix; lane stops here")
        return False

    def watch_target(self, lane, mode, cidm, gm):
        t_end = time.time() + self.s.park_s
        while time.time() < t_end:
            time.sleep(5)
            try:
                r = gm.status(cidm)
                if solved(r) or (isinstance(r, dict) and r.get("solved")):
                    status.report(self.day, lane.name, mode, "done", "runner", self.s)
                    self.log(lane.name, f"{mode}: CORRECT (fixer)")
                    return True
            except GMError:
                continue
        return False

    # ------------------------------------------------------------------ lane / day
    def run_lane(self, lane, ch):
        cid = ch.get("challenge") or ch.get("id")
        modes = [m for m in config.MODES if m in (ch.get("modes") or config.MODES)]
        self.plugin_stamp0[lane.name] = plugins.stamp(lane.name, self.s)
        ok = True
        for i, mode in enumerate(modes):
            try:
                done = self.run_mode(lane, cid, mode, modes[i + 1] if i + 1 < len(modes) else None)
            except Exception as e:
                self.note(lane.name, mode, f"runner error {e.__class__.__name__}: {str(e)[:200]}")
                done = False
            ok = ok and done
            if not done:
                break
        self.summary[lane.name] = {"ok": ok, "s": round(time.time() - self.t0, 1)}
        self.log(lane.name, "LANE_DONE" if ok else "LANE_STOPPED")

    def run(self, wait=True):
        found = self.wait_unlock(wait)
        ts = [threading.Thread(target=self.run_lane, args=(l, found[l.name]), daemon=True)
              for l in self.lanes if l.name in found]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        with open(os.path.join(self.dir, "summary.json"), "w") as f:
            json.dump(self.summary, f, indent=1)
        status.render(self.day, self.s)
        self.log("runner", f"ALL DONE {sum(v['ok'] for v in self.summary.values())}/{len(self.summary)} lanes")
        return self.summary


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Race runner: Python solves, parks on failure, re-runs on fixes.")
    ap.add_argument("--day", type=int, required=True)
    ap.add_argument("--wait", action="store_true", help="sleep until unlock_poll_at before polling")
    ap.add_argument("--lanes", default="", help="comma-separated subset")
    ap.add_argument("--dry", action="store_true", help="build and report, never submit")
    a = ap.parse_args(argv)
    s = config.load()
    s.require_gm()
    Runner(a.day, s, [x for x in a.lanes.split(",") if x], a.dry).run(wait=a.wait)
    return 0
