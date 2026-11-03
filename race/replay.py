"""race.replay: rebuild a recorded mode offline and grade it. No Game Master calls.

Inputs come from the run dir the runner wrote: the recorded start (questions), the unpacked members, and, when
the mode was solved, the answers that the grader accepted (ground truth). The build is the same code the runner
uses (lane solver, then plugins, then pins if asked), so a PASS here means the live re-run will pass too.

  mask:   plugin stems to hide (e.g. fixes written after the recording) via RACE_PLUGIN_EXCLUDE. It is set in the
          environment, so helper processes started by a solver or plugin see the same mask.
  extra:  a scratch plugin file to test before installing it (verify_plugin uses this).

The first output line is always the grade line, `[grade] <lane>/<mode>: PASS|FAIL|NO_TRUTH wrong A -> B`, so
scripts can parse it no matter how long the detail below gets.
"""
import json
import os
import shutil
import tempfile

from . import config, lanes, pins, plugins

BLANK = plugins.BLANK


def recorded(rec_dir):
    """-> (questions, accepted answers or None)."""
    with open(os.path.join(rec_dir, "index.json")) as f:
        idx = json.load(f)
    qs, truth = None, None
    for key, name in idx.items():
        op = key.split(":", 1)[0]
        if op in ("start", "retry") and qs is None:
            with open(os.path.join(rec_dir, name)) as f:
                qs = json.load(f).get("questions")
    for name in sorted(os.listdir(rec_dir)):          # every submit we made, oldest first
        if "_answers_" in name and name.endswith(".json"):
            with open(os.path.join(rec_dir, name)) as f:
                d = json.load(f)
            r = d.get("response") or {}
            if isinstance(r, dict) and str(r.get("result", "")).upper() == "CORRECT":
                truth = d.get("answers")
    return qs or [], truth


def _plugin_view(s, extra):
    """A temporary plugin dir: the real plugins (symlinked) plus the scratch plugin."""
    d = tempfile.mkdtemp(prefix="race_plugins_")
    if os.path.isdir(s.plugin_dir):
        for n in os.listdir(s.plugin_dir):
            if n.endswith(".py"):
                os.symlink(os.path.join(s.plugin_dir, n), os.path.join(d, n))
    base = os.path.basename(extra)
    if os.path.lexists(os.path.join(d, base)):
        os.remove(os.path.join(d, base))
    shutil.copy(extra, os.path.join(d, base))
    return d


def run(day, lane, mode, s=None, mask=(), extra=None, use_pins=False, out=print):
    s = s or config.load()
    dd = s.day_dir(day)
    rec = os.path.join(dd, "rec", lane, mode)
    mdir = os.path.join(dd, "members", lane, mode)
    if not os.path.isdir(rec) or not os.path.isdir(mdir):
        out(f"[grade] {lane}/{mode}: NO_RECORDING (looked in {rec})")
        return None
    old_mask = os.environ.get("RACE_PLUGIN_EXCLUDE")
    if mask:
        os.environ["RACE_PLUGIN_EXCLUDE"] = ",".join(sorted(set(mask) | plugins.masked()))
    view, old_dir = None, s.plugin_dir
    try:
        if extra:
            view = _plugin_view(s, extra)
            s.plugin_dir = view
        qs, truth = recorded(rec)
        members = lanes.Members.from_dir(mdir)
        logs = []
        ans, prov = lanes.get(lane, s).build(qs, members, log=logs.append)
        if use_pins:
            ans = pins.overlay(ans, pins.load(day, lane, mode, s))
        blank = [q["id"] for q in qs if ans.get(q["id"]) in BLANK]
        if truth is None:
            out(f"[grade] {lane}/{mode}: NO_TRUTH blank {len(blank)} of {len(qs)} (mode not solved yet)")
            wrong = None
        else:
            wrong = [k for k, v in truth.items() if str(ans.get(k, "")).strip() != str(v).strip()]
            verdict = "PASS" if not wrong else "FAIL"
            out(f"[grade] {lane}/{mode}: {verdict} wrong {len(wrong)} of {len(truth)}")
            for k in wrong[:20]:
                out(f"   wrong: {k} = {str(ans.get(k))[:80]!r} (accepted {str(truth[k])[:80]!r})")
            if len(wrong) > 20:
                out(f"   ... {len(wrong) - 20} more")
        for k in blank[:20]:
            out(f"   blank: {k}")
        by = {}
        for k, v in prov.items():
            by.setdefault(v, []).append(k)
        for stem, ks in sorted(by.items()):
            out(f"   {stem}: answered {len(ks)} key(s)")
        for line in logs[:10]:
            out(f"   log: {line}")
        return {"wrong": wrong, "blank": blank, "provenance": prov}
    finally:
        s.plugin_dir = old_dir
        if view:
            shutil.rmtree(view, ignore_errors=True)
        if mask:
            if old_mask is None:
                os.environ.pop("RACE_PLUGIN_EXCLUDE", None)
            else:
                os.environ["RACE_PLUGIN_EXCLUDE"] = old_mask
