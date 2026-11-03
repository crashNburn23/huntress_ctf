# Lanes, solvers and plugins

A **lane** is one category of the day's challenges. Each lane has up to three modes per day: `single`,
`time_trial` and `mastery`, where mastery bundles several deliveries (`setK.` question ids). Lanes are configured
in `config.toml`:

```toml
[lanes]            # name = weight: how much fixer help the lane usually needs (drives the session split)
warm = 1
meta = 2
web = 3

[lane_match]       # optional: regex over the challenge id (default: the lane name as a word)
meta = "metadata|forensic"

[lane_solver]      # optional: which race/lanes/<module>.py solves the lane (default: same name, else generic)
warm = "example"
```

`target_lanes` lists lanes whose challenges are live systems rather than files. The runner never solves those;
it hands the attempt straight to a fixer.

## Three layers, in the order the runner applies them
1. **Lane solver** (`race/lanes/<name>.py`, a `Lane` subclass with `solve(questions, members)`): the general
   knowledge of the lane. A lane without one uses the generic `Lane`, which fetches and unpacks artifacts and
   answers nothing. That is a fine way to start: the first day's fixes become its plugins.
2. **Plugins** (`plugins/<lane>_<name>.py`): what the solver learned since. They fill blanks (or replace answers
   when `OVERRIDE = True`) and run in sorted filename order; the first answer wins. Start from `plugins/_template.py`.
3. **Pins** (`tools/pin.py`): hand-solved values for one mode. Live tries only fill blanks with them; offline
   re-runs put them over the solver's answers.

Move pins into plugins after the race, and fold plugins that keep proving themselves into the lane solver
between race days. A plugin should be the exception, not the solver.

## Writing a lane solver
```python
from race.lanes import Lane

class MetaLane(Lane):
    def solve(self, questions, members):
        out = {}
        for q in questions:
            files = members.for_qid(q["id"])
            ...                      # answer what you understand; leave the rest out
        return out

LANE_CLASS = MetaLane
```
Override `fetch()` only when artifacts need more than download + safe ZIP extraction (`archive_passwords` and
`max_extract_mb` in config cover the common cases).

## Testing
- `tests/mock_gm.py` is a toy Game Master for rehearsals (`--hard <lane>` adds a key the example solver can't
  answer, to practise the fix loop).
- `tools/replay.py --day DD --all` rebuilds every recorded mode offline and grades it against the accepted
  answers. Run it after changing a solver: every mode that passed before must still pass.
- `--mask stem1,stem2` hides plugins, to check that a solver change covers what those plugins did.

## Lane skills
Code is for what Python can do; a skill is for what a fixer session needs to know. Each lane can have a Claude
skill at `.claude/skills/lane-<lane>/SKILL.md`: format recipes, exact tool commands, known traps and any helper
scripts, kept short enough to read under the clock. `launch.py` tells each session to load the skills for its
lanes, and only names skills that exist.

- New lane: `python3 -I tools/new_skill.py <lane>` (or `--all` for every configured lane without one). It copies
  `docs/SKILL_TEMPLATE.md` and never overwrites.
- After a race: move what `docs/notes/<lane>.md` taught into the skill as a recipe (how to find the value, never
  the value itself). Fold anything mechanical into a plugin or the lane solver instead.
