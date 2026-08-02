# Notes — survey system + post-run fixes (M5 P6, R175)

## Initial understanding

Approved in R175 (2026-08-02):

- **Q1 (survey):** an automated survey system. Requirements from the
  user, verbatim intent: design an automated survey; store results so
  they are *permanently reusable*; survey Cold Plains AND the Rogue
  Encampment; ensure future bot runs *use* the stored maps; keep the
  map store logically organized; judgment call — if a bot encounters an
  unmapped area, consider auto-activating survey mode; report the
  design before running (or run it autonomously if the whole process
  can be automated).
- **Q2 (fix package, all approved):**
  1. Field-cleanse drop hygiene: step away from wanted items before
     dropping junk; move off the drop pile afterwards (user diagnosed
     the drop-at-pointer re-pickup loop live in the R173 run).
  2. `maybe_cleanse` must not re-arm a retry that cannot differ (it
     resets `inventory_full` + `stuck` after any drop, even when the
     freed space was created at the bot's own feet).
  3. Damage-while-stationary reposition reflex; thresholds surfaced to
     the user before going live (the R173 run stood in fire to 49%).

Context: the R173 confirmation run ([CV-L] CHICKEN) — the click-fix
itself is confirmed working (491 audited clicks, zero wholesale
accidental exemptions).

## Discovery

### What already exists (user challenged "don't we have a survey tool?" — answer: partly)

- **`pd2bot/mapstore.py`** — the atlas. Permanent, logically organized:
  `maps/<seed:08x>-d<difficulty>/area-<id>.json`, JSON with
  base64-encoded room grids, atomic write-then-rename, seed-keyed so a
  re-rolled layout misses the cache honestly. Terrain only
  (`strip_transient` removes occupancy so corpses never become walls).
  Gitignored: machine-local save-data, regenerable by walking.
- **Passive recording** — `live_navigator`'s position reader calls
  `_record_visible_rooms` ~once/second while walking; *every* bot walk
  grows the atlas already.
- **Manual survey mode** — `python -m pd2bot.navigate --survey`
  records while the HUMAN walks; no input sent (M3, R12/R13/R16).
- **Consumption is already wired** — `live_navigator.grid()` returns
  `OverlayGrid(base=explored_atlas, overlay=live_rooms)`; every walk in
  every run plans on the atlas. Nothing to build there.
- **Unknown ground is treated as BLOCKED on purpose**
  (`navigate.py:412-421` — "survey it first"). So un-surveyed ground is
  never planned into; the cost is targets on unknown ground being
  clamped/skipped (the patrol give-ups the user watched) plus
  stuck/shake-loose cycles at the known/unknown boundary.

### What does NOT exist (the actual new work)

1. **Self-driving coverage**: nothing picks *where to walk next* to
   complete an area. Frontier exploration is needed: find reachable
   known-walkable ground adjacent to unknown ground, walk there (the
   client loads its ~3x3 room neighbourhood — measured 46-67 subtiles,
   T51 — and the recorder stores it), repeat until no reachable
   frontier remains.
2. **Coverage accounting**: "is this area done?" — a report of rooms
   known, frontier remaining, unreachable-frontier written off.
3. **A survey run/step**: a `survey` step usable from a run TOML
   (`runs/survey-cold-plains.toml`, `runs/survey-town.toml`) so the
   full process (create game → waypoint → survey → leave) is
   automated end-to-end through `tools/live-run.ps1`.

### Facts gathered for the design

- `world.read_area` returns `Area(level_no, position, size)` with
  `bounds_subtiles` and `contains()` — the survey can and should
  constrain its targets to the target area's bounding box, otherwise
  frontier edges bleed into adjacent areas (Blood Moor, Stony Field)
  forever.
- Steps send walks as `MoveTo` actions through the executor (same as
  patrol legs); give-up-after-no-progress budgets and the visited-set
  pattern exist in `_PatrolMixin` and are the right shape to reuse.
- Steps have no grid access today; the survey step needs a service
  closure (wiring.py) exposing frontier targets + coverage stats over
  `MapStore` for the current (seed, difficulty, area).
- The reflex ladder (`behavior/reflex.py`) already tracks HP samples in
  a window (`_hp_lost_in_window`, `was_hit`) and has `retreat_point`
  for direction-away-from-hostiles. A reposition rung slots after
  rung 6 (mana) and before rung 7 (armor). Ground fire is NOT visible
  in perception, so the rule must be damage-source-agnostic: direction
  = away from hostiles when any, else rotate through walkable
  directions.
- The cleanse loop mechanics (R173 finding): `maybe_cleanse`
  (steps.py:556-585) runs the cleanse at a safe moment, then clears
  `stuck`/`attempts`/`inventory_full` whenever anything was dropped —
  "give every written-off item one more chance". With the junk dropped
  at the feet and the retried pickup click landing on it, the loop is
  closed. The town cleanse itself (`town.py cleanse_inventory`) is
  fine; the FIELD usage lacks drop hygiene.

## Design decisions (proposed, see plan.md)

- **Survey = frontier walk at ROOM granularity.** Candidate targets are
  midpoints of stored-room edges that no stored room lies beyond,
  clamped to the area's `bounds_subtiles`, nearest-first, with the
  patrol's no-progress give-up and a visited/written-off set.
  Termination: no candidates remain (frontier exhausted) or every
  remainder is written off unreachable. Report coverage counts.
- **Hostile areas**: the survey step yields the tick to combat exactly
  as `clear_radius` does, but with a small engage radius (fight what
  threatens, ignore what doesn't); the reflex ladder and chicken are
  untouched and always on.
- **Auto-survey mid-normal-run: NO** (judgment call, to be confirmed):
  passive recording already frontier-creeps every run; a clearance run
  that detours into a full survey stops being a clearance run. Instead:
  when a step gives up on a target because ground is UNKNOWN (the
  NavigationError already distinguishes this), say so loudly in the
  run summary and recommend the survey run.
- **Rogue Encampment survey**: same step, trivially safe (no hostiles
  in town); run file starts from town spawn, no waypoint travel.

## Questions

- Q1 (confirm): engage radius while surveying — fight only within ~30
  subtiles, else keep walking? Suggested: yes.
- Q2 (confirm): auto-survey mid-run = no, loud report instead?
  Suggested: yes (see judgment above).
- Q3 (confirm): reposition reflex thresholds — fire when ≥2% max HP
  lost within 2.5 s AND moved <3 subtiles in that window; step 10
  subtiles away (from hostiles if any, else any walkable direction);
  2 s cooldown; sits below the potion/warp rungs. User sees these
  before any live run (this IS the surfacing).
- Q4 (confirm): survey runs live as run TOMLs driven by the normal
  engine (not a bare CLI), so chicken/death-latch/reflexes all apply.
  Suggested: yes.

## User answers / scope changes

- **R176 (2026-08-02): all four confirmations approved as suggested.**
  Q2 refinement: dedicated survey runs are the model, and a manual
  survey (user walking, `--survey` recording) remains a valid path —
  the automated runs do not replace it, they add to it.
- User challenged whether a survey tool already exists → clarified:
  manual `--survey` + passive recording + the store exist; the
  self-driving coverage walk does not. Scope narrowed to exactly that
  gap (no changes to mapstore format needed).

## Implementation status (2026-08-02)

- P1 committed `a00a650`; P2 committed `a00a650`; P3+P4 committed with
  this note. 775 tests, ruff clean throughout.
- P4's exit gate (live acceptance: survey-town, then survey-cold-plains,
  then a fresh patrol run for the cleanse fix) is OPEN — the plan stays
  `active` and `_DONE.md` unwritten until those runs pass.

## Future work (out of scope)

- Difficulty still not readable from memory (M4 leftover); callers
  state it (CLI default Hell). Unchanged here.
- Cross-area room bleed: `_record_visible_rooms` records all loaded
  rooms into the CURRENT area's file; near borders some rooms may be
  filed under the neighbour. Harmless for planning (grids merge), noted
  for cleanliness.
- A visual atlas viewer (render area-NNN.json to an image) would make
  coverage verifiable at a glance.
