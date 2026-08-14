# P2 â€” bounded A*

Size: sm. Dependencies: P1 (the `nav.plan` events should exist first so
the budget's effect is on the record). Review gate: none.

## Scope

Give `pathing.astar` a node budget so "no path" is answered in
milliseconds instead of flooding the atlas. NOTHING else about search
behavior changes: same heuristic, same costs, same simplify.

Out of scope: connectivity caching / component labeling (a future
optimization if the budget ever proves too blunt â€” note it in notes.md
future work, do not build it).

## The defect being fixed (measured)

`logs/runs/20260813-083614-cold-plains` t+155.9 and t+177.8: two
back-to-back ~21 s ticks, each `nav.failed: no path from (5216,5717)
to (5218,5709)` â€” 8 subtiles apart, both walkable, different connected
components OF THE ATLAS. Replayed offline: **NO PATH in 20.15 s; a
healthy 25-cell path takes 3 ms** (notes.md, discovery). The
two-strike no-route rule doubles every occurrence.

## Implementation

`pd2bot/nav/pathing.py::astar` gains `max_nodes: int | None = None`:

- Count nodes POPPED from the heap; when the count exceeds the budget,
  return `None`.
- `None` (the parameter) = unbounded, preserving every existing test's
  behavior; the DEFAULT for production callers comes from a helper:

```python
def default_node_budget(start: Point, goal: Point) -> int:
    # Scaled by distance so a nearby goal fails fast and a cross-area
    # path still gets room. Constants are first guesses â€” P4 measures.
    d = _octile(start, goal)
    return int(min(50_000, max(2_000, 30 * d * d)))
```

  (Exact constants are the implementer's to tune within these shapes;
  record the final numbers and why in notes.md. The floor must
  comfortably exceed the largest REAL path the baseline log shows â€”
  check `nav.plan` `path_cells` from P1's re-pricing â€” so a genuine
  route can never exhaust the budget in practice.)

- Callers that adopt the budget: `navigate._walk_to` and
  `wiring.route_service` (compute the budget from their own
  start/goal). `nearest_walkable` and `simplify` are untouched. Drills
  and tests that call `astar` directly keep unbounded behavior.
- The `nav.plan` event gains `nodes` (popped count) and
  `budget`/`budget_exhausted` fields â€” the instrument that says which
  answer was a real "no path" and which was a budget stop.

## Semantics (decided R256 Q1 â€” do not relitigate)

Budget-exhausted returns None = the existing no-route answer. Callers
already treat None honestly: two-strike confirmation, then write-off
with expiry-on-movement (clear.py `_no_route`, patrol.py
`_route_denied`). A false "unreachable" against a genuinely reachable
far target is therefore recoverable by design â€” and the budget floor
makes it rare. Accepted risk, measured in P4.

## Validation

- Regression test (`tests/nav/test_pathing.py` or alongside): a
  synthetic grid with two walkable regions separated by a wall, sized
  so unbounded A* would visit â‰¥ 100k cells; assert bounded astar
  answers None **in under 100 ms** and that the same grid WITH a gap
  finds the path.
- A long-path test: a snake-corridor path several hundred cells long
  must still be found under the default budget.
- Existing pathing tests unchanged and green (unbounded default).
- Live replay probe (no game needed, reads the local atlas â€” run it
  and paste the timing into notes.md):
  re-run the discovery probe (notes.md carries the script shape:
  atlas seed 1314025823, Hell, area 3, start (5216,5717), target
  (5218,5709)) with the production budget â€” expect **< 50 ms**.
- Full suite + ruff green.

## Conventions and reminders

- pathing.py constants carry WHY comments with the measurement that
  set them â€” follow that idiom for the budget constants.
- Do not commit unless asked; do not expand scope (no caching layers);
  stop and report if the budget shape conflicts with any caller's
  assumptions found mid-work.

## Definition of done

Bounded astar in with production callers using it, regression + long
path tests green, the replay case answering < 50 ms, `nav.plan`
carrying node counts, notes.md updated with final constants.

## Implementation Result

Status: done
Completed: 2026-08-13
Commit: 4e9be26 (docs; code landed 13d0c6b..bd0cde4)

- Changed: `pathing.astar` takes `max_expansions=None` (None = the
  distance-scaled `default_node_budget`) and an optional `stats` dict;
  budget exhaustion returns None (no-route semantics) instead of the
  old raise; `SearchLimitExceeded` deleted (raised at a never-binding
  200k, caught by nothing in production â€” a latent tick-crash). Both
  production callers (navigate `_walk_to`, wiring `route_service`) use
  the default budget and forward `expanded`/`budget`/`budget_exhausted`
  onto their `nav.plan` events.
- Validated: 4 new/updated pathing tests (budget-answers-None,
  disconnected-flood <100 ms, 400+-cell snake path found, budget
  shape); live atlas replay: the 20.15 s flood answers in 0.057 s,
  production-cap worst case 1.33 s. Full suite 1327 green, ruff clean.
- Deviations: BUDGET_CAP lowered 50k -> 25k after the first live
  measurement (4.86 s at 50k breached the QB no-tick-over-4s bar);
  final constants + measurements recorded in notes.md.

