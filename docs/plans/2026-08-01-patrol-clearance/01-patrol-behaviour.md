# P1 — The patrol itself

Size: `sm`. Depends on nothing. Read
[plan.md](plan.md) and [notes.md](notes.md) first; this file is otherwise
self-contained.

## Scope

Teach `ClearRadiusStep` to walk its circle instead of standing in the
middle of it. Unit-tested only — the sim and the run files are P2.

**Out of scope:** run files, the sim scenario, the CLI override, any
change to the navigator or to `PickupStep`.

## Why

`units.PERCEPTION_RADIUS` is 80 subtiles and `scan_units` drops
everything beyond it. `ClearRadiusStep` decides the area is clear when no
live monster is within `radius` of the arrival point — which it can do
from a standstill only while `radius <= 80`. `runs/cold-plains.toml` asks
for 150, so it has always been declaring clear a circle it can see barely
half of. And on 2026-08-01 two live runs completed without ever fighting,
because nothing happened to be inside stage B's radius 50.

## Design

Keep it simple (user: *we don't need this to become enormously onerous*).
A fixed ring of sample points, a visited set, one short leg per tick.

### Parameters

On `ClearRadiusStep`, from the run file:

- `patrol: bool = False` — off by default, so every existing run behaves
  exactly as it does today.

On `RunServices`, as commented defaults (not run-file parameters — these
are judgement calls nobody should have to restate per run):

- `patrol_points: int = 8` — sample points evenly spaced around the ring.
- `patrol_ring: float = 0.66` — ring radius as a FRACTION of `radius`.
  A fraction on purpose: the radius is the number the user tunes, and an
  absolute ring would stay put while the circle grew around it.
- `patrol_step: int = 12` — maximum subtiles per leg.
- `patrol_reach: int = 6` — close enough to count a point as visited.
- `patrol_attempts: int = 3` — legs toward one point before giving up on
  it, so a point we can approach but never reach cannot loop forever.

Coverage sanity check at radius 96: the ring sits at ~63, adjacent points
are ~49 apart (within perception of each other), and the furthest edge of
the circle is ~33 from the nearest ring point. Comfortable.

### Per-tick order

1. `recover_panels` (unchanged, stays first).
2. Compute `in_radius` (unchanged).
3. **If hostiles are in the radius:** exactly today's behaviour — engage,
   loot, cleanse, approach, declare a wait. The patrol does not run
   during a fight; clearing is the job and walking is only what we do
   when there is nothing to clear.
4. **If the radius reads empty and the patrol is incomplete:** take one
   leg toward the current point. This is the new branch, and note it
   comes BEFORE the settle timer — see below.
5. **If the radius reads empty and the patrol is complete:** today's
   settle logic, unchanged (loot, cleanse, `_empty_since`, finish after
   `clear_settle_s`).

**The settle timer must not start until the patrol is complete.**
Otherwise the step can finish while unvisited ground remains, which is
the exact bug being fixed, merely with extra steps. Concretely: only set
`_empty_since` in branch 5.

### One leg

```python
def _hop(origin, destination, step):
    """One short leg toward `destination`, capped at `step` subtiles.

    `walk_to` BLOCKS until arrival (navigate.py), so a leg is time the
    reflex ladder is not being consulted. Same discipline and the same
    reason as NecroCombat._dash_target.
    """
    dx, dy = destination[0] - origin[0], destination[1] - origin[1]
    span = max(abs(dx), abs(dy))
    if span <= step:
        return destination
    scale = step / span
    return (round(origin[0] + dx * scale), round(origin[1] + dy * scale))
```

Reaching a point (within `patrol_reach`) marks it visited and advances to
the next. Exceeding `patrol_attempts` legs on one point marks it visited
too, with a log line saying it was given up on — visited means "dealt
with", not "stood on".

### Unreachable ground is not fatal

`MoveTo` executes through `walk_to`, which raises `NavigationError` for
ground the atlas has never read: *"that ground has never been seen —
survey it first (unknown ground is treated as blocked on purpose)"*.
`NavigationError` is NOT in the engine's `SEND_DID_NOT_LAND` pair, so it
propagates out of the step, through the engine, and fails the whole cycle
(`cycle.py`). Several screens out will frequently be ground nobody has
read yet, so this WILL happen.

Catch it around the leg, log it, mark the point visited, continue:

```python
try:
    ctx.executor.execute(MoveTo(leg))
except NavigationError as exc:
    self.services.log(f"patrol: skipping {point} ({exc})")
    self._visited.add(index)
    return StepOutcome(done=False, acted=True, note=f"patrol: skipped {point}")
```

Do NOT catch bare `Exception` here — `InputRefused` and
`SkillSwitchFailed` must keep reaching the engine, which absorbs them and
re-decides. Catching them would silently mark a point visited that we
never even tried to walk to.

### The watchdogs

Both are fed correctly with no special handling: a leg sends input and
moves the character, and the engine counts movement as progress. Say this
in a comment rather than adding anything — a patrol that has to disarm a
watchdog is a patrol that is not moving.

## Files

- `pd2bot/behavior/steps.py` — `RunServices` fields, `ClearRadiusStep`
  state and branches, the `_hop` helper.
- `pd2bot/behavior/run.py` — the `clear_radius` `ParamSpec`s in
  `default_registry` must match `build_registry`'s, or the run linter and
  the drills validate a different vocabulary than the bot runs.

## Tests (`tests/test_behavior_steps.py`)

Cite the motivation in the docstring, as the file's other tests do.

1. A patrolling clearance visits every sample point (drive it with a
   reacting `RecordingExecutor` that moves the player, as
   `test_the_clearance_reaches_a_hostile_that_started_out_of_reach`
   already does).
2. It does not finish while points remain unvisited, even though the
   radius reads clear the whole time — the bug being fixed.
3. A point that raises `NavigationError` is skipped, the run continues,
   and the step still completes.
4. A point that can be walked toward but never reached is abandoned after
   `patrol_attempts` legs.
5. Legs are capped at `patrol_step` subtiles.
6. Without `patrol`, the step behaves exactly as before (assert no
   `MoveTo` at all on an empty radius).
7. A hostile inside the radius suspends the patrol — fighting wins the
   tick.

## Conventions

- Judgement-call numbers go on `RunServices` with a comment explaining
  the number, never inline.
- Comment the evidence, including the live runs referenced above.
- No bare `except Exception` on the send path (see above).

## ADR expectation

None for this phase.

## Review gate

None. Continue to P2 when the tests pass.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope — no run files, no sim, no CLI here.
- Do not suppress warnings or disable tests.
- Stop and report if the design meets something it did not anticipate,
  particularly around `walk_to`'s blocking behaviour.
- Report what changed, what was validated, and any deviations.

## Validation

```
& "$HOME/.venvs/pd2bot/Scripts/python.exe" -m pytest -q
```

```
& "$HOME/.venvs/pd2bot/Scripts/python.exe" -m ruff check .
```

## Definition of done

Patrol behaviour implemented and unit-tested, both registries agree on
the `clear_radius` schema, the full suite passes, ruff is clean, and
non-patrolling runs are provably unchanged.

## Implementation Result

Status: done
Completed: 2026-08-01
Commit: pending

- Changed: `steps.py` (`_hop`, five `RunServices` patrol fields,
  `ClearRadiusStep.patrol` + ring/visited state + `walk_the_circle`, the
  settle gated on `patrol_complete`), `run.py` (`patrol` ParamSpec in
  `default_registry`), 7 new tests.
- Validated: 707 tests pass, ruff clean.
- Deviations: two, both small.
  - `tests/test_behavior_steps.py`'s `make_step` helper was building
    steps from a bare dict, so the factory never saw the validated
    parameters production hands it. It broke the moment `clear_radius`
    gained an optional parameter, which is how it was found; it now
    applies the spec's declared defaults, as `build_states` does.
  - `test_the_shipped_cold_plains_run_validates` asserts `patrol: False`
    for `cold-plains.toml`. P2 switches that file and the assertion.
- Bug caught by the tests rather than by review: `patrol_complete`
  read True before the ring was computed (`len(None or [])` is 0), so
  the patrol was skipped entirely on the first tick and the step behaved
  exactly as before. All four patrol tests failed on it.
