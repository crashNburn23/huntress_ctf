"""race.sessions: which Claude fixer session watches which lanes.

plan(): the split launch.py uses, picked by config session_split:
  "core_target" (default)  S1 takes every core lane (no live targets), S2 takes the target lanes (web).
  "weight"                 split() below, over `sessions` sessions.

split(): longest-job-first by lane weight. The heaviest lanes are placed first, each on the least-loaded session,
so with N sessions the N heaviest lanes always land on different sessions (they are offset from each other), and
the light lanes fill in behind them. Ties go to the earlier session; lanes of equal weight keep config order.

steal_candidates(): the work-stealing rule. A session whose own lanes are quiet may claim another session's row
when that row has sat escalated and unclaimed for steal_after_s, or when its owner already holds two open rows.
Claiming goes through status.claim(), so two sessions can never take the same row.

  python3 -I tools/sessions.py [--sessions N]        print the split for the configured lanes
  python3 -I tools/sessions.py --day N --steal S2     rows session S2 may claim now (uses the saved split)
"""
import json
import os
import time

from . import config, status


def save(day, assignment, s=None):
    s = s or config.load()
    p = os.path.join(s.day_dir(day), "sessions.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump({f"S{i + 1}": ls for i, ls in enumerate(assignment)}, f, indent=1)
    return p


def load(day, s=None):
    s = s or config.load()
    with open(os.path.join(s.day_dir(day), "sessions.json")) as f:
        d = json.load(f)
    return [d[k] for k in sorted(d, key=lambda k: int(k[1:]))]


def split(lanes, n):
    """lanes: {name: weight} (ordered). -> [[lane, ...] per session], len == min(n, len(lanes)) or 1."""
    n = max(1, min(n, len(lanes) or 1))
    order = sorted(lanes, key=lambda k: -lanes[k])          # stable: equal weights keep config order
    out, used = [[] for _ in range(n)], [0] * n
    for lane in order:
        i = min(range(n), key=lambda j: (used[j], j))
        out[i].append(lane)
        used[i] += lanes[lane]
    return out


def split_core_target(lanes, targets):
    """-> [[core lanes], [target lanes]] in config order; an empty group is dropped (so never fewer than 1)."""
    core = [x for x in lanes if x not in targets]
    tgt = [x for x in lanes if x in targets]
    return [g for g in (core, tgt) if g] or [[]]


def plan(s, n=None):
    """The session split for settings s. n overrides s.sessions (weight mode only)."""
    if s.session_split == "weight":
        return split(s.lanes, n or s.sessions)
    return split_core_target(s.lanes, s.target_lanes)


def owner(assignment, lane):
    for i, ls in enumerate(assignment):
        if lane in ls:
            return i
    return None


def steal_candidates(latest, assignment, me, now=None, steal_after_s=45):
    """latest: status.latest() result. -> [(lane, mode)] this session (index `me`) may claim, oldest first."""
    now = now or time.time()
    open_by_owner = {}
    for (lane, mode), r in latest.items():
        if r["state"] in ("escalated", "claimed"):
            open_by_owner.setdefault(owner(assignment, lane), []).append((lane, mode))
    out = []
    for (lane, mode), r in latest.items():
        o = owner(assignment, lane)
        if o == me or r["state"] != "escalated":
            continue
        if now - r["t"] >= steal_after_s or len(open_by_owner.get(o, [])) >= 2:
            out.append((r["t"], lane, mode))
    return [(lane, mode) for _, lane, mode in sorted(out)]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Show how lanes split across fixer sessions.")
    ap.add_argument("--sessions", type=int, default=None)
    ap.add_argument("--day", type=int, default=int(time.strftime("%d")))
    ap.add_argument("--steal", metavar="SESSION", help="e.g. S2: list rows this session may claim now")
    a = ap.parse_args(argv)
    s = config.load()
    if a.steal:
        asg = load(a.day, s)
        rows = steal_candidates(status.latest(a.day, s), asg, int(a.steal.lstrip("Ss")) - 1,
                                steal_after_s=s.steal_after_s)
        for lane, mode in rows:
            print(f"{lane} {mode}    claim: python3 -I tools/status.py --day {a.day} --claim {lane} {mode} "
                  f"--session {a.steal}")
        if not rows:
            print("nothing to steal")
        return 0
    if a.sessions and s.session_split != "weight":
        print(f"note: --sessions is ignored with session_split = {s.session_split!r}")
    for i, ls in enumerate(plan(s, a.sessions), 1):
        print(f"S{i}: {', '.join(ls)}  (weight {sum(s.lanes[x] for x in ls)})")
    return 0
