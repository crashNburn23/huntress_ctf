---
name: lane-web
description: Fix or hand-solve a web-lane row during the race. Format recipes, tool commands and known traps for the web lane. Use when a web row escalates, when you take over a web key, or before writing a web plugin.
---

# web lane skill

Read this at startup (it is short on purpose) and again when a web row escalates. `docs/FIXER.md` is the
protocol; this file is the lane knowledge. Fill it in after each race day from `docs/notes/web.md`.

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
