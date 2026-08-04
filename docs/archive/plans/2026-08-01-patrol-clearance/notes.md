# Discovery notes — patrol clearance around the waypoint

## Why this exists

User decision, 2026-08-01, after two clean stage-B runs that **never
fought anything**:

> Currently, our cold plains runs are simply testing. I think we should
> make them slightly more realistic — have the character run about
> considerably more. I'd recommend clearing a wide circle all around the
> waypoint — several screens in each direction. I suggest prepping the
> next trial runs with that expanded scope.

This supersedes the R147 answer, which correctly explained why the bot
does not roam (there is no patrol) and correctly put a patrol out of P6's
scope as a new feature. The evidence has since changed: attempts 11 and
12 both completed `[CVRL]` with an empty radius 50, so the trial run can
pass without exercising combat at all. A run that can be "passed" without
doing the thing it is testing is not a test.

## The constraint that makes this correctness, not realism

`ClearRadiusStep` decides the area is clear when no live monster is within
`radius` of the arrival point, and it can do that **from a standstill**
only because perception reaches further than the radius:

- `units.PERCEPTION_RADIUS = 80` subtiles (units.py:37), and
  `scan_units` drops everything beyond it — the snapshot literally cannot
  see past 80.
- stage B's radius is 50, the full run's is 150.

So the full run's radius 150 is **already wrong**: the step waits for a
150-subtile circle to read clear while seeing only 80 of it, and declares
victory over ground it has never observed. Nobody noticed because the
clearance has always been run where the monsters came to us.

Any radius above 80 needs the character to move for the reading to mean
anything. That makes the patrol a correctness fix for `cold-plains.toml`
as much as a feature.

## What the code does today

**`ClearRadiusStep`** (steps.py) — ticked. Per tick: recover a stray
panel, then if monsters are in radius, ask `combat.engage`, else loot,
else `combat.approach` (the review-001 fix), else declare a wait. When
the radius reads empty it starts `_empty_since` and finishes after
`clear_settle_s` (5 s).

**`walk_to` is BLOCKING** (navigate.py:261). It loops — read grid, path,
click, re-check — until arrival or failure. This is the single most
important fact for the design: a `MoveTo` executed inside a tick does not
return until the walk is over, and the reflex ladder is not consulted for
the whole of it. It is why `NecroCombat._dash_target` caps every approach
at `dash_step` (8 subtiles), and why `steps.py`'s own module docstring
separates "blocking steps" (town, waypoint — safe because town is safe)
from "ticked steps" (everything that happens in Hell).

**A patrol must therefore advance in HOPS**, one short leg per tick, not
one `walk_to` per patrol point. Same discipline as the dash, same reason.

**Unknown ground is impassable by design** (navigate.py:284): walking to
a point the atlas has never read raises `NavigationError` — *"that ground
has never been seen — survey it first (unknown ground is treated as
blocked on purpose)"*. And `NavigationError` fails the whole cycle
(cycle.py:386). A patrol that names a ring point several screens out will
frequently name ground nobody has read yet, so the patrol must either
follow the frontier of known ground or degrade gracefully when a leg is
unreachable. This is the main implementation risk.

The atlas does grow as rooms load (M3: every room grid read is
persisted), so ground becomes known by approaching it — which a patrol
does by construction. The order of operations matters, not the
possibility.

**The engine's two watchdogs** both interact with a long patrol:
`idle_bail_s` (10 s with nothing sent and no progress) and today's new
`wait_bail_s` (30 s of unbroken declared waiting). A patrol leg sends a
click and moves the player, so both are fed — but a patrol that stands
still deciding where to go next is exactly what they are for. Movement
already counts as progress in the engine's tick.

**The run vocabulary is data.** `runs/*.toml` name steps and parameters
only; the registry (`build_registry`) binds them to handlers. A new step
name or new parameters must be registered with `ParamSpec`s, and the
sim's `default_registry` equivalent kept in step.

## Sizing the circle

A screen is ~24 subtiles (R147). "Several screens in each direction":

| Screens | Radius | Notes |
|---|---|---|
| 2 | ~48 | Today's stage B (50). Verifiable from a standstill. |
| 3 | ~72 | Still inside perception (80) — a patrol makes it thorough but is not yet required for correctness. |
| 4 | ~96 | First radius that genuinely needs a patrol. |
| 6 | ~150 | The full run's current number. |

Recommendation: make the patrol serve any radius, then set the run files
deliberately — a supervised stage at ~96, the full run staying 150 and
becoming honest for the first time.

## Files expected to change

- `pd2bot/behavior/steps.py` — the patrol itself, and `RunServices`.
- `pd2bot/behavior/run.py` — `default_registry` parameter schemas.
- `runs/cold-plains.toml`, `runs/cold-plains-stage-b.toml`, probably a
  new staged file for the wider circle.
- `tests/test_behavior_steps.py`, `tests/test_behavior_run.py`,
  `tests/simworld.py` + `tests/test_behavior_sim.py` (the sim scenario
  needs monsters placed outside the standstill radius, or the patrol is
  never exercised end to end).
- `docs/architecture/` — the behaviour architecture doc if the step
  vocabulary grows.

## Answers

**R157 — A: the patrol lives inside `clear_radius`.** The user added the
sizing constraint that matters more than the shape:

> we don't need this to become enormously onerous; ideally, a simple
> detection of how far the character has moved, and if there are any
> living enemies nearby, would cover most of the requirements of the
> final product. I leave the judgement to you.

Taken as: a fixed ring of sample points and a visited set. No frontier
exploration, no coverage map, no path optimisation. "How far the
character has moved" becomes "which sample points have been reached",
which is the same idea made checkable.

**R156** was not answered explicitly; proceeding on the suggested
answers, all reversible config. Q1 (radius 96) and Q3 (switching
`cold-plains.toml`) flagged as worth a second look.

**The radius must be easy to change** (user, on approving the phases):

> please make the radius value easy to alter, so if we want to
> increase/decrease it we can do so easily.

Two consequences, both in P2: one obvious number in the run file, and a
`--radius` override mirroring `--chicken`. And one in P1: everything
derived from the radius is a FRACTION of it, so changing the one number
moves the whole pattern instead of leaving the ring behind.

## Future work / out of scope

- Room-graph or full-area clearance (visit every room of Cold Plains
  rather than a circle). Much larger, and the circle is what was asked
  for.
- Using the patrol for anything but clearance (a shopping route, a boss
  approach).
- Revisiting `pickup`'s radius semantics beyond whatever the patrol
  requires.
