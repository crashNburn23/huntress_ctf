"""race.pins: hand-solved answers a fixer hands to the runner. A pin fixes one mode; a plugin fixes all of them.

File: <run_dir>/dayNN/pins/<lane>.json  ->  {"single": {qid: value}, "time_trial": {...}, "mastery": {...}}

Rules built in:
  * merge() takes a lock and swaps the file atomically in the same directory, so two fixers pinning at once
    never ship each other's answers and the runner never reads half a file.
  * Each mode has its own key. A single-solve pin is never copied to another mode: each mode is a different variant.
  * overlay(): offline re-builds put pins over the solver's answers (the fixer checked them).
    fill_blank(): live tries only fill keys the solver left blank, never replace a solver answer.
"""
import fcntl
import json
import os

from . import config
from .plugins import BLANK


def path(day, lane, s=None):
    s = s or config.load()
    return os.path.join(s.day_dir(day), "pins", f"{lane}.json")


def load(day, lane, mode=None, s=None):
    try:
        with open(path(day, lane, s)) as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError):
        d = {}
    return d.get(mode, {}) if mode else d


def merge(day, lane, mode, values, s=None):
    if mode not in config.MODES:
        raise ValueError(f"mode must be one of {config.MODES}")
    p = path(day, lane, s)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            cur = load(day, lane, s=s)
            cur.setdefault(mode, {}).update({k: v for k, v in values.items()})
            tmp = p + f".tmp{os.getpid()}"
            with open(tmp, "w") as f:
                json.dump(cur, f, indent=1)
            os.replace(tmp, p)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)
    return p


def clear(day, lane, s=None):
    try:
        os.remove(path(day, lane, s))
    except FileNotFoundError:
        pass


def stamp(day, lane, s=None):
    try:
        return os.stat(path(day, lane, s)).st_mtime_ns
    except FileNotFoundError:
        return 0


def overlay(answers, pins, qids=None):
    out = dict(answers)
    for k, v in pins.items():
        if qids is None or k in qids:
            out[k] = v
    return out


def fill_blank(answers, pins, qids=None):
    out = dict(answers)
    for k, v in pins.items():
        if (qids is None or k in qids) and out.get(k) in BLANK:
            out[k] = v
    return out
