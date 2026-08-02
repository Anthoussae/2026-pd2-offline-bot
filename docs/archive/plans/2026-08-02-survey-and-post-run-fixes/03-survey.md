# P3 — The automated survey: frontier module, step, wiring, run files

Size: md (one agent, several files; no further planning needed).
Dependencies: none hard; P1/P2 first is the natural order.

## What exists (do not rebuild)

- `pd2bot/mapstore.py` — the permanent seed-keyed store. UNCHANGED.
- Passive recording (`navigate.live_navigator` position reader).
- `--survey` manual mode. UNCHANGED — stays valid for user-driven walks.
- `OverlayGrid` consumption in every run. UNCHANGED.

## New: `pd2bot/survey.py`

Frontier extraction at room granularity over one `ExploredArea`:

- `frontier_targets(area: ExploredArea, bounds: tuple[int,int,int,int])
  -> list[tuple[int,int]]` — for each stored room, check the four
  edge-adjacent strips; where no stored room covers the strip, the
  room's edge midpoint (clamped inside `bounds`, the target area's
  `Area.bounds_subtiles`) is a candidate. Only offer candidates whose
  own cell is known-walkable or adjacent to known-walkable ground —
  walking *to the known side of the edge* is what loads the rooms
  beyond (the client loads a ~3x3 room neighbourhood; measured 46-67
  subtiles, T51). Sort nearest-first from the player.
- `coverage(area) -> str` — one-line report: room count, bounds, and
  frontier-candidate count, for logs and the pre-flight `describe`.

Pure functions over ExploredArea; no session access — unit-testable
with hand-built rooms.

## New: `SurveyStep` (behavior/steps.py, registry name `"survey"`)

Per tick, in order:
1. Panels/cleanse plumbing as other field steps (`recover_panels`,
   `maybe_cleanse`).
2. Combat, gated at `survey_engage_radius` (RunServices, default 30 —
   R176 Q1): hostiles within it → let `services.combat.engage` take
   the tick (same absorb-failed-walk handling as `clear_radius`).
3. Ask the survey service for frontier targets; walk the nearest with
   `_PatrolMixin`-style no-progress give-up (reuse/extract the leg
   logic; a given-up target goes in a written-off set keyed by rounded
   position so re-derived neighbours don't resurrect it).
4. No targets left → done, note = the coverage report plus how many
   edges were written off unreachable.

Budget: `survey_max_legs` (RunServices, default 200) as a hard cap —
a bug must end the game, not extend it (the idle-bail and chicken still
stand above this).

## Wiring (wiring.py)

- A survey service closure handed to RunServices: exposes
  `frontier_targets()` (reads seed/area/difficulty live, opens the
  store, clamps to `Area.bounds_subtiles`) and `coverage()`. The step
  never learns what a MapStore is.
- `describe()` gains an atlas line for the run's target area when a
  survey step is present: seed, area, rooms known.
- **Unknown-ground give-ups get loud** (R176 Q2): where steps absorb a
  `NavigationError`, detect the "never been seen" variant (message
  already distinguishes it) and log
  `"target on UNSURVEYED ground — runs/survey-<area>.toml would fix
  this permanently"`; count them and put the count in the run summary.

## Run files

- `runs/survey-cold-plains.toml`: town_preamble → waypoint (Cold
  Plains) → survey → done. Comment: what it does, that it is re-runnable
  (idempotent — a complete area yields zero frontier and finishes
  immediately), chicken stays 50.
- `runs/survey-town.toml`: survey only (starts in town; no waypoint,
  no combat expected; engage radius irrelevant in town).

## Tests

- survey.py: hand-built ExploredAreas — a full rectangle has no
  frontier; a half-explored one lists the boundary midpoints; bounds
  clamp excludes out-of-area edges.
- SurveyStep in the sim: a fake grid/service that "loads" adjacent fake
  rooms when the player nears an edge → the step reaches frontier
  exhaustion and reports; an unreachable edge (walks never progress) is
  written off after the budget; hostiles inside 30 divert the tick to
  combat; `survey_max_legs` caps a scripted pathological service.
- Run files parse (existing run-file validation tests as the pattern).

## Reminders

Do not commit unless asked · mapstore format is frozen · no scope creep
(no visualizer, no auto-survey mid-run) · stop if blocked · report.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: sim survey terminates with a coverage report, all tests
green, ruff clean. Live runs are P4's exit gate, not P3's.
