---
name: lane-{lane}
description: Fix or hand-solve a {lane}-lane row during the race. Format recipes, tool commands and known traps for the {lane} lane. Use when a {lane} row escalates, when you take over a {lane} key, or before writing a {lane} plugin.
---

# {lane} lane skill

Read this at startup (it is short on purpose) and again when a {lane} row escalates. `docs/FIXER.md` is the
protocol; this file is the lane knowledge. Fill it in after each race day from `docs/notes/{lane}.md`.

**Never put here:** answer values, flags, tokens, hosts or URLs, or anything tied to one player or attempt.
Recipes describe *how* to find a value, not the value.

## First 60 seconds on an escalated row
1. Open the brief; note `counts.missing` vs `counts.wrong` and which questions they belong to.
2. Look at one member in `members_dir` and identify its format (see the table below).
3. Known format: apply the recipe, pin, then write the plugin. Unknown: follow "New format" below.

## Format recipes
| Format / question kind | How to recognise it | How to get the answer | Tool or helper |
|---|---|---|---|
| | | | |

## Tool commands
Exact commands that worked, one line each, with what they print.
```
```

## New format (nothing above matches)
- (what to check first for this lane)

## Known traps
- (answer formatting rules the grader enforces, fields that look alike, slow paths to avoid)

## Helpers
Scripts that belong to this skill live next to this file (for example `helpers/`). List each with one line on what
it does and how to call it.
