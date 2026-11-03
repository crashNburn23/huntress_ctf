"""TEMPLATE: copy to plugins/<lane>_<short_name>.py (files starting with "_" are never loaded).

A plugin teaches a lane something its solver does not know yet. Keep it narrow: answer exactly the questions you
understand and return None for everything else, so that other plugins and the solver keep working.

ctx (race.lanes.Members):
    ctx.for_qid(q["id"])  {member name: bytes} of the delivery this question belongs to (mastery: setK.)
    ctx.sets              one {name: bytes} per delivery;  ctx.files: all members;  ctx.dir: unpacked copy
Questions look like {"id": ..., "question": "...", "answer_format": {...}}. Answer as a string; JSON answers as
compact JSON text. Return the literal "none" only when the format says that is the answer for an absent field.

Test before installing:
    python3 -I tools/verify_plugin.py --day DD --lane <lane> --mode <mode> --plugin /path/to/<lane>_<name>.py
Install with mv; the runner re-runs by itself.
"""
import re

# OVERRIDE = True     # uncomment only if this plugin must replace a non-blank solver answer

WANT = re.compile(r"replace with a pattern that matches the questions this plugin answers")


def answer(q, ctx):
    if not WANT.search(q.get("question", "")):
        return None
    files = ctx.for_qid(q["id"])
    # ... compute from the bytes in `files` (read only; never execute a member) ...
    return None


# For questions that need the whole mode at once (cross-member sets, ordering), use build() instead:
# def build(questions, ctx, base):
#     return {q["id"]: value for q in questions if ...}
