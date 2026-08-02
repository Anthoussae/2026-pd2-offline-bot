# P5 — Route-aware legs: steps walk the map's answer, not the compass bearing

Size: sm-md. Dependencies: none hard; last feature phase (added by
R181 after T53 run 2).

## The gap (watched live, twice)

The atlas is fully used by the NAVIGATOR (every hop gets pathfinding)
and ignored by the STEPS: patrol legs, survey legs, and combat
approaches are `_hop(origin, target, step)` — a straight-line bearing.
Against a far-corner or cross-fence target, each hop plans locally,
clamps at the wall, gains nothing, and the no-progress budget burns per
target while the bot visibly shuffles at dead edges. Hops can also lead
straight through a zone exit (T53 run 2 wandered into Stony Field and
back). The map could answer "is there a route, and which way?" — no
step asks.

## Changes

1. **A route service** (wiring closure on RunServices, same treatment
   as the survey service): `route_to(target) -> list[Point] | None` —
   plan A* over the navigator's grid (atlas + live overlay), return the
   simplified waypoint list, or None when no path exists. Read-only:
   no clicks, no walking. Cache per (origin-rounded, target) briefly —
   re-planning every tick is the tick-rate waste this repo keeps
   refusing.
2. **Steps follow the route**: where `_hop` picks a leg (patrol ring
   walk, SurveyStep, `ClearRadiusStep`'s closing approach), take the
   route's next waypoint (capped at `patrol_step`) instead of the
   straight-line bearing. `route_to(...) is None` = INSTANT write-off
   of the target ("no route exists" — the honest fast-fail the R174
   closure wrongly claimed already happened for clamped hops).
3. **Zone containment for free**: a route planned on the area's grid
   never leads through an exit the target is not behind; the Stony
   Field wander class dies with the bearing hops.
4. **Combat**: `NecroCombat.approach`/dash keeps its short-hop shape
   (ladder responsiveness) but takes the route's direction rather than
   the bearing when they differ. The module stays grid-ignorant: the
   step hands it the next route waypoint as the approach target.

## Tests

- A fake grid with a U-shaped wall: the old bearing leg walks into the
  pocket; the route leg walks around — assert the leg sequence follows
  the plan, not the bearing.
- No-path target: written off on the FIRST tick, no budget burn.
- Route cache: unchanged grid + same target = one plan, many legs.
- Sim regression: patrol and survey suites unchanged in outcome.

## Reminders

Do not commit unless asked · keep hops short (the ladder must get its
look between legs — the whole reason hops exist) · stop if blocked ·
report.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: the U-wall test passes, no-path targets fail fast, suite
green, ruff clean.

## Implementation Result

Status: done
Completed: 2026-08-02
Commit: 26857c1

- Changed: `behavior/steps.py` (`RunServices.route_to` service slot;
  `_route_leg` + `_next_route_waypoint` helpers; patrol, survey, and the
  clearance closing approach all follow the route`s next waypoint capped
  at patrol_step; `route_to(...) is None` = instant write-off with its
  own log/narrate lines), `behavior/necro.py` (`approach(..., via=)` —
  gates stay keyed to the monster, the hop takes the route`s direction;
  module stays grid-ignorant), `behavior/combat.py` (fake module
  signature), `wiring.py` (`route_service(navigator)`: read-only A* over
  the navigator`s grid, cached per (8-subtile origin bucket, target),
  grid assembled only on cache miss; wired into RunServices).
- Tests: U-pocket route-vs-bearing (unit + patrol integration);
  routeless point/frontier/monster written off on the FIRST tick with
  zero legs spent; approach receives (monster, via) pair; route cache =
  one plan per bucket; no-path -> None; unreadable position -> straight
  hop (never a write-off); fallback-to-bearing when no service wired.
  Sim/patrol/survey suites unchanged in outcome.
- Validated: full suite 823 passed, ruff clean.
- Deviations: `engage`-internal dashes (mid-fight, within engage_radius)
  keep the bearing — the plan`s change 4 scopes routing to the
  step-mediated approach, and the fight-patience guard already bounds
  the pathological case. The cache test caught the grid being assembled
  on cache HITS; fixed (grid read moved behind the cache check).
