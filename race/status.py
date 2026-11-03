"""race.status: the shared status board. Python writes it, and the Claude fixer sessions read and claim from it.

One append-only JSONL file per day: <run_dir>/dayNN/status.jsonl. A row is one (lane, mode) group, never one
key, so a fixer gets one item with every wrong/missing key of that mode instead of a flood.

Workflow states, in order:
  open -> solving -> escalated -> claimed -> fixed -> done
    escalated  Python could not finish; the row carries the brief path and the counts (wrong, missing, blank)
    claimed    a fixer session owns it (claim() is atomic, so two sessions never work the same row)
    fixed      a plugin or pin landed; the runner's hot re-run decides whether it becomes done
Info rows (state "note") never change the workflow state. They are shown as the row's last note.

Fixers watch it with:  python3 -I tools/status.py --day N --watch --lanes bin,web
"""
import fcntl
import json
import os
import sys
import time

from . import config

WORKFLOW = ("open", "solving", "escalated", "claimed", "fixed", "done")
INFO = ("note",)


def path(day, s=None):
    s = s or config.load()
    return os.path.join(s.day_dir(day), "status.jsonl")


def _append(p, row):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def rows(day, s=None):
    try:
        with open(path(day, s)) as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def report(day, lane, mode, state, by, s=None, **kw):
    if state not in WORKFLOW + INFO:
        raise ValueError(f"unknown state {state!r}")
    row = {"t": round(time.time(), 2), "day": int(day), "lane": lane, "mode": mode, "state": state, "by": by}
    row.update({k: v for k, v in kw.items() if v is not None})
    _append(path(day, s), row)
    return row


def fold(all_rows):
    """{(lane, mode): latest workflow row, plus 'note' = the latest note text}"""
    out = {}
    for r in all_rows:
        key = (r["lane"], r["mode"])
        if r["state"] in INFO:
            cur = out.setdefault(key, dict(r, state="open"))
            cur["note"] = r.get("detail", "")
            continue
        note = out.get(key, {}).get("note")
        out[key] = dict(r, **({"note": note} if note else {}))
    return out


def latest(day, s=None):
    return fold(rows(day, s))


def claim(day, lane, mode, session, s=None):
    """Atomically take an escalated row. True if this session now owns it (or already did)."""
    p = path(day, s)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".claim", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            cur = latest(day, s).get((lane, mode))
            if not cur:
                return False
            if cur["state"] == "claimed":
                return cur.get("session") == session
            if cur["state"] != "escalated":
                return False
            report(day, lane, mode, "claimed", session, s, session=session, brief=cur.get("brief"))
            return True
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def line(r):
    c = r.get("counts") or {}
    cnt = " ".join(f"{k}={v}" for k, v in c.items() if v)
    extra = " ".join(x for x in (cnt, f"session={r['session']}" if r.get("session") else "",
                                 f"brief={r['brief']}" if r.get("brief") and r["state"] == "escalated" else "",
                                 r.get("detail", "")) if x)
    return f"{time.strftime('%H:%M:%S', time.localtime(r['t']))} {r['state'].upper():9} {r['lane']}/{r['mode']} {extra}".rstrip()


def render(day, s=None):
    s = s or config.load()
    lat = latest(day, s)
    out = [f"# Status day {int(day):02d}  ({time.strftime('%H:%M:%S')})", "",
           "| lane | mode | state | by | counts | note |", "|---|---|---|---|---|---|"]
    for (lane, mode), r in sorted(lat.items()):
        c = " ".join(f"{k}={v}" for k, v in (r.get("counts") or {}).items() if v)
        out.append(f"| {lane} | {mode} | {r['state']} | {r.get('session') or r['by']} | {c} | {r.get('note', '')[:80]} |")
    p = os.path.join(s.day_dir(day), "STATUS.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + f".tmp{os.getpid()}"
    with open(tmp, "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, p)
    return p


def watch(day, lanes=None, s=None, from_start=True, poll=0.5):
    """Print one line per new row for these lanes (forever). For a Claude Monitor."""
    p = path(day, s)
    pos = 0
    while True:
        try:
            with open(p) as f:
                if not from_start and pos == 0:
                    f.seek(0, 2)
                else:
                    f.seek(pos)
                for raw in f:
                    if raw.endswith("\n") and raw.strip():
                        r = json.loads(raw)
                        if not lanes or r["lane"] in lanes:
                            print(line(r), flush=True)
                pos = f.tell()
                from_start = True
        except FileNotFoundError:
            pass
        time.sleep(poll)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Shared status board (read, watch, claim, mark).")
    ap.add_argument("--day", type=int, default=int(time.strftime("%d")))
    ap.add_argument("--watch", action="store_true", help="follow new rows (for a Monitor)")
    ap.add_argument("--lanes", default="", help="comma-separated lane filter")
    ap.add_argument("--new-only", action="store_true", help="with --watch: skip rows already in the file")
    ap.add_argument("--claim", nargs=2, metavar=("LANE", "MODE"))
    ap.add_argument("--mark", nargs=3, metavar=("LANE", "MODE", "STATE"))
    ap.add_argument("--session", default=os.environ.get("RACE_SESSION", "manual"))
    ap.add_argument("--detail", default="")
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args(argv)
    lanes = [x for x in a.lanes.split(",") if x]
    if a.claim:
        ok = claim(a.day, *a.claim, a.session)
        print("claimed" if ok else "not claimable (not escalated, or another session owns it)")
        return 0 if ok else 1
    if a.mark:
        lane, mode, state = a.mark
        report(a.day, lane, mode, state, a.session, session=a.session if state != "note" else None,
               detail=a.detail or None)
        return 0
    if a.render:
        print(render(a.day))
        return 0
    if a.watch:
        try:
            watch(a.day, lanes, from_start=not a.new_only)
        except KeyboardInterrupt:
            return 0
    for r in sorted(latest(a.day).values(), key=lambda r: (r["lane"], r["mode"])):
        if not lanes or r["lane"] in lanes:
            print(line(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
