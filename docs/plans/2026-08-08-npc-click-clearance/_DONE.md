# Done — screen-space click clearance around town NPCs

Completed 2026-08-08. Not committed (the operator had not asked).

## Outcome

A travel click no longer lands on a town NPC's sprite. The spawn -> Akara
leg, which failed on `npc_menu` twice in a row before this, now completes:
**3 runs, 3 arrivals, no dialog opened.**

## Completed work

- `pd2bot/navigate.py`
  - `SPRITE_HALF_WIDTH_PX` 80, `SPRITE_ABOVE_FEET_PX` 150,
    `SPRITE_BELOW_FEET_PX` 40, `SPRITE_MARGIN_PX` 20, each carrying the
    T83 measurement that set it.
  - `_screen_offset`, `_inside_sprite`, `_sprite_escapes` — the box and
    its exits, built on `screen.py`'s calibrated 20/10 px per subtile
    rather than a second copy of those numbers.
  - `_nudged_click_point` tests the sprite box FIRST (only the
    screen-space escape can resolve it), keeps the world-space push for
    everything else, and ranks its boxed-in fallback with sprites
    weighed above floor clearance.
  - `sprite_provider`, optional and defaulting to None, wired in
    `live_navigator` from the same snapshot the other hazards come from,
    town only, cleared when perception is unreadable.
- `tests/test_navigate.py` — nine tests, fixtured on the three measured
  clicks.
- `drills/town_click_clearance.py` — the measuring drill (written during
  the investigation), plus a summary that reports how many clicks were
  actually nudged.
- Docs: a new "Where a travel click may land" section in
  `docs/architecture/navigation.md`; the `project-state.md` item closed.

## Validation

```
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q      # 1169 passed
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .   # All checks passed
```

Live, through the bridge, three runs of `drills/town_click_clearance.py`:

| run | legs | clicks | nudged | outcome |
|---|---|---|---|---|
| 1 | 3 | 10 | 0 | arrived, dist 1 |
| 2 | 3 | 10 | 3 | arrived, dist 3 |
| 3 | 5 | 15 | 4 | arrived, dist 4 |

Run 1 proves less than it looks: nothing was standing in the way, so the
escape never fired — which is why the drill now says so out loud rather
than letting a clean route read as a passing test.

**Run 2 is the proof.** Three clicks were nudged, and the report shows
where to: **160 px sideways / 0 px vertical** from the NPC, level with
her feet and well clear of an 80 px-wide, 150 px-tall box. The failing
run before the fix put its nudged click at **0 px sideways / 120 px above
her feet** — inside the sprite — and opened `npc_menu`. Same route, same
NPC, opposite geometry.

Before: two consecutive failures, both `npc_menu`, one stalling at
(5877, 5734) and one exhausting `_walk_guarded`'s three recoveries.

## Deviations from the plan

Two, both found by tests rather than by review:

1. **`_world_delta` was dropped.** Inverting the projection and rounding
   to whole subtiles lands ON the box wall as often as outside it (half a
   subtile is 10 px, and the wall is inclusive). Escapes are now built
   from whole-subtile axis moves instead — (k, −k) is purely sideways on
   screen, (k, k) purely toward the camera — which is exact by
   construction.
2. **An escape must clear `AVOID_RADIUS` as well.** A sprite hazard is
   also a world hazard, so the first escapes were rejected by the very
   next check and the nudge would have spun until it ran out of tries.
   The step count is now `max(screen requirement, AVOID_RADIUS)`.

Both are recorded in the code at the point they matter.

## Documentation

`docs/architecture/navigation.md` gained the click rule, which was
previously undocumented anywhere — the radius, the box, why there are two
shapes, and the standing instruction to re-run the drill after any
resolution or renderer change.

## ADR

None, as planned. This corrects a rule to match a measurement; it does
not choose between plausible architectures.

## Follow-up outside this scope

- **Objects (waypoint, stash) still use the world radius.** Same
  tall-sprite problem, no measurement yet. This is the next thing the
  drill should measure, and it is recorded in `project-state.md`.
- The earlier classification fix (town NPCs filed as scenery) shipped
  with this work but belongs to the investigation that preceded the plan;
  its evidence lives in `units.py`'s comment and drill-log T82.
