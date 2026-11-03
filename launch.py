#!/usr/bin/env python3
"""launch.py: one command for race morning. Python drives; N Claude sessions fix what Python can't.

  python3 launch.py                    default: 2 fixer sessions, today's day (after 12:00: tomorrow's)
  python3 launch.py --sessions 3 --day 7
  python3 launch.py --now              start everything immediately (no waiting for arm/unlock times)
  python3 launch.py --dry              print the plan (split, commands, tmux layout) and change nothing
  python3 launch.py --test             real tmux layout, but panes only echo; no runner, no Claude, no GM calls
  python3 launch.py --stop             kill the runner and the tmux session for the day

What it does (safe to run again; it never starts a second copy of anything):
  1. splits the lanes across the sessions and saves it (race/sessions.py; default session_split "core_target":
     S1 = every core lane, S2 = the target lanes such as web; "weight" balances over --sessions instead)
  2. starts the runner detached (tools/run.py --day N --wait), so closing tmux never stops the race
  3. opens tmux session race-dNN:
       window "board"   status board (all lanes) | watchdog (all lanes)
       window "fixers"  one pane per Claude session; each starts at arm_at with its lanes and docs/FIXER.md
Options: --mode (Claude permission mode), --model, --no-attach.
"""
import argparse
import datetime
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from race import config, sessions  # noqa: E402

PY = sys.executable


def default_day():
    now = datetime.datetime.now()
    return (now + datetime.timedelta(days=1)).day if now.hour >= 12 else now.day


def alive(pid, needle):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return needle in f.read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return False


def lane_skills(lanes, root=ROOT):
    """Skill names (lane-<lane>) that exist under .claude/skills for these lanes."""
    return [f"lane-{x}" for x in lanes
            if os.path.exists(os.path.join(root, ".claude", "skills", f"lane-{x}", "SKILL.md"))]


def prompt(name, day, mine, others, root=ROOT):
    other = "; ".join(f"{n}: {', '.join(ls)}" for n, ls in others) or "none"
    sk = lane_skills(mine, root)
    skills = (f"Load your lane skills now with the Skill tool ({', '.join(sk)}) and use them when a row "
              f"escalates. " if sk else "")
    return (f"You are fixer session {name} for race day {day:02d}. Your lanes: {', '.join(mine)}. "
            f"Other sessions: {other}. Read docs/FIXER.md now and follow it exactly: arm the two Monitors for "
            f"your lanes, wait for escalations, claim with --session {name}, and fix by plugin or pin. "
            f"{skills}The status board is run/day{day:02d}/STATUS.md.")


def build_plan(a, s):
    day = a.day or default_day()
    if a.sessions and s.session_split != "weight":
        print(f"launch: note: --sessions is ignored with session_split = {s.session_split!r}")
    asg = sessions.plan(s, a.sessions)
    names = [f"S{i + 1}" for i in range(len(asg))]
    tm = f"race-d{day:02d}"
    arm = 0 if a.now else config.seconds_until(s.arm_at, day)
    passthru = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(os.environ.items())
                        if k.startswith("RACE_") and k != "RACE_GM_TOKEN")
    runner = [PY, "-I", os.path.join(ROOT, "tools/run.py"), "--day", str(day)] + ([] if a.now else ["--wait"])
    board = f"{PY} -I tools/status.py --day {day} --watch"
    dog = f"{PY} -I tools/watchdog.py --day {day}"
    fixers = []
    for i, (n, ls) in enumerate(zip(names, asg)):
        others = [(m, x) for m, x in zip(names, asg) if m != n]
        if a.test:
            cmd = f"echo '[{n}] test pane: lanes {', '.join(ls)}'; exec $SHELL"
        else:
            claude = [s.claude_bin, "--permission-mode", a.mode or s.claude_mode]
            if a.model or s.claude_model:
                claude += ["--model", a.model or s.claude_model]
            claude.append(prompt(n, day, ls, others))
            wait = f"echo '[{n}] starts in {arm}s (arm_at {s.arm_at})'; sleep {arm}; " if arm else ""
            cmd = (f"{wait}env RACE_SESSION={n} {passthru} {' '.join(map(shlex.quote, claude))}; exec $SHELL")
        fixers.append((n, ls, cmd))
    if a.test:
        board, dog = "echo '[board] test pane'; exec $SHELL", "echo '[watchdog] test pane'; exec $SHELL"
    return {"day": day, "assignment": asg, "names": names, "tmux": tm, "runner": runner,
            "board": board, "watchdog": dog, "fixers": fixers, "arm_in": arm}


def tmux(*args, check=True):
    return subprocess.run(["tmux", *args], check=check, capture_output=True, text=True)


def open_tmux(p):
    tm = p["tmux"]
    if tmux("has-session", "-t", tm, check=False).returncode == 0:
        print(f"tmux session {tm} already exists (not touched)")
        return
    tmux("new-session", "-d", "-s", tm, "-n", "board", "-c", ROOT, p["board"])
    tmux("split-window", "-h", "-t", f"{tm}:board", "-c", ROOT, p["watchdog"])
    first = True
    for n, ls, cmd in p["fixers"]:
        if first:
            tmux("new-window", "-t", tm, "-n", "fixers", "-c", ROOT, cmd)
            first = False
        else:
            tmux("split-window", "-t", f"{tm}:fixers", "-c", ROOT, cmd)
            tmux("select-layout", "-t", f"{tm}:fixers", "tiled")
    tmux("set-option", "-t", tm, "pane-border-status", "top", check=False)
    tmux("select-window", "-t", f"{tm}:fixers")


def start_runner(p, s):
    d = s.day_dir(p["day"])
    os.makedirs(d, exist_ok=True)
    pidf = os.path.join(d, "runner.pid")
    try:
        pid = int(open(pidf).read())
        if alive(pid, "tools/run.py"):
            print(f"runner already running (pid {pid})")
            return pid
    except (OSError, ValueError):
        pass
    with open(os.path.join(d, "runner.out"), "ab") as out:
        pr = subprocess.Popen(p["runner"], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, start_new_session=True)
    with open(pidf, "w") as f:
        f.write(str(pr.pid))
    print(f"runner started (pid {pr.pid}), log {os.path.join(d, 'run.log')}")
    return pr.pid


def stop(p, s):
    pidf = os.path.join(s.day_dir(p["day"]), "runner.pid")
    try:
        pid = int(open(pidf).read())
        if alive(pid, "tools/run.py"):
            os.kill(pid, signal.SIGTERM)
            print(f"runner {pid} stopped")
    except (OSError, ValueError):
        print("no runner running")
    if tmux("kill-session", "-t", p["tmux"], check=False).returncode == 0:
        print(f"tmux session {p['tmux']} closed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sessions", type=int, help="number of Claude fixer sessions (session_split = \"weight\" only)")
    ap.add_argument("--day", type=int)
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--mode", help="Claude permission mode")
    ap.add_argument("--model", help="Claude model")
    ap.add_argument("--no-attach", action="store_true")
    a = ap.parse_args()                       # unknown flags exit here, before anything starts
    s = config.load()
    p = build_plan(a, s)
    print(f"day {p['day']:02d}: {len(p['names'])} fixer session(s)")
    for n, ls in zip(p["names"], p["assignment"]):
        print(f"  {n}: {', '.join(ls)}  (weight {sum(s.lanes[x] for x in ls)})")
    if a.dry:
        print("runner:  ", " ".join(map(shlex.quote, p["runner"])))
        print("board:   ", p["board"])
        print("watchdog:", p["watchdog"])
        for n, _, cmd in p["fixers"]:
            print(f"{n}:      ", cmd[:300] + ("..." if len(cmd) > 300 else ""))
        print(f"tmux:     session {p['tmux']}: window board (2 panes), window fixers ({len(p['fixers'])} panes)")
        return 0
    if a.stop:
        stop(p, s)
        return 0
    if not shutil.which("tmux"):
        sys.exit("launch: tmux is not installed")
    if not a.test:
        s.require_gm()
        if not shutil.which(s.claude_bin):
            sys.exit(f"launch: {s.claude_bin!r} not found on PATH")
        if os.environ.get("RACE_GM_TOKEN") and not s.token_file:
            print("launch: note: RACE_GM_TOKEN is not passed to the fixer panes; set token_file in config.toml "
                  "so their tools can authenticate")
    sessions.save(p["day"], p["assignment"], s)
    with open(os.path.join(s.day_dir(p["day"]), "launch.json"), "w") as f:
        json.dump({k: v for k, v in p.items() if k != "fixers"}, f, indent=1)
    if not a.test:
        start_runner(p, s)
    open_tmux(p)
    print(f"attach: tmux attach -t {p['tmux']}")
    if not a.no_attach and sys.stdout.isatty():
        os.execvp("tmux", ["tmux", "attach", "-t", p["tmux"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
