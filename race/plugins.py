"""race.plugins: fixes that teach a lane solver something new, loaded from <plugin_dir>/<lane>_<name>.py.

A plugin module may define either or both:
    def answer(q, ctx):            -> value or None      one question ({"id", "question", "answer_format"})
    def build(questions, ctx, base): -> {qid: value}      a whole mode at once (base = answers so far)
    OVERRIDE = False               True: may replace a non-blank solver answer (default: fill blanks only)

ctx is the lane's members object (see race.lanes). Plugins run in sorted filename order and the first non-None
answer wins, so a newer plugin that must win sorts later only if OVERRIDE is set. Name it accordingly.

Rules built in:
  * load_one() is the ONLY import path. Every caller, tools included, goes through it, so the RACE_PLUGIN_EXCLUDE
    mask (used by offline replays to hide fixes written after the recorded morning) cannot be bypassed by a
    helper that imports a plugin file directly.
  * A plugin that does not compile is skipped and reported; a plugin that raises is skipped for that call.
    A broken fix never takes the lane down.
  * stamp() changes whenever a lane's plugin set changes, which is what triggers the runner's hot re-run.
"""
import importlib.util
import os
import sys
import traceback

from . import config

BLANK = (None, "", "none", [], {})
_CACHE = {}


class Masked(ImportError):
    pass


def masked():
    return {x.strip().removesuffix(".py") for x in os.environ.get("RACE_PLUGIN_EXCLUDE", "").split(",") if x.strip()}


def _dir(s=None):
    return (s or config.load()).plugin_dir


def discover(lane, s=None):
    d, m = _dir(s), masked()
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return []
    return [n[:-3] for n in names if n.startswith(lane + "_") and n.endswith(".py") and n[:-3] not in m]


def _check(p):
    with open(p, "rb") as f:
        compile(f.read(), p, "exec")             # syntax check only; nothing is written


def load_one(stem, s=None):
    if stem in masked():
        raise Masked(f"plugin {stem} is masked (RACE_PLUGIN_EXCLUDE)")
    p = os.path.join(_dir(s), stem + ".py")
    mt = os.stat(p).st_mtime_ns
    hit = _CACHE.get(p)
    if hit and hit[0] == mt:
        return hit[1]
    with open(p, "rb") as f:
        code = compile(f.read(), p, "exec")       # from source every time: the .pyc cache keys on whole-second
    spec = importlib.util.spec_from_file_location(f"race_plugin_{stem}", p)   # mtime + size and can go stale
    mod = importlib.util.module_from_spec(spec)
    exec(code, mod.__dict__)
    _CACHE[p] = (mt, mod)
    return mod


def broken(lane, s=None):
    """[(stem, error)] for plugins that do not compile."""
    out = []
    for stem in discover(lane, s):
        try:
            _check(os.path.join(_dir(s), stem + ".py"))
        except SyntaxError as e:
            out.append((stem, f"line {e.lineno}: {e.msg}"))
    return out


def stamp(lane, s=None):
    d = _dir(s)
    return tuple((n, os.stat(os.path.join(d, n + ".py")).st_mtime_ns) for n in discover(lane, s))


def apply(lane, questions, ctx, base, s=None, log=None):
    """-> (answers, provenance {qid: plugin stem}). base is not modified."""
    out, prov = dict(base), {}
    log = log or (lambda m: print(m, file=sys.stderr))
    mods = []
    for stem in discover(lane, s):
        try:
            mods.append((stem, load_one(stem, s)))
        except Masked:
            continue
        except Exception as e:
            log(f"plugin {stem} skipped: {e.__class__.__name__}: {str(e)[:120]}")
    for stem, mod in mods:
        over = getattr(mod, "OVERRIDE", False)
        if hasattr(mod, "build"):
            try:
                got = mod.build(questions, ctx, dict(out)) or {}
            except Exception:
                log(f"plugin {stem}.build raised:\n{traceback.format_exc(limit=3)}")
                got = {}
            for k, v in got.items():
                if v not in BLANK and (over or out.get(k) in BLANK) and k not in prov:
                    out[k], prov[k] = v, stem
        if hasattr(mod, "answer"):
            for q in questions:
                k = q["id"]
                if k in prov or (out.get(k) not in BLANK and not over):
                    continue
                try:
                    v = mod.answer(q, ctx)
                except Exception:
                    log(f"plugin {stem}.answer({k}) raised:\n{traceback.format_exc(limit=3)}")
                    continue
                if v not in BLANK:
                    out[k], prov[k] = v, stem
    return out, prov
