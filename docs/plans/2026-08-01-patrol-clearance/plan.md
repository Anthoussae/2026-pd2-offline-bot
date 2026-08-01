---
kind: plan
size: md
depth: implementation
status: done
repo: 2026-pd2-offline-bot
created: 2026-08-01
completed: 2026-08-01
commit: none
adr: possible
---

> **Implemented, and NOT archived on purpose.** P2's review gate is open:
> a supervised live run is what decides whether the wider radius is
> trusted, and nothing here has executed against the game. See `_DONE.md`.

# Patrol clearance: make the circle real

## Goal

`clear_radius` should clear a wide circle around the waypoint by walking
it, rather than standing on the arrival point and declaring victory over
ground it cannot see.

## Why now

Two things arrived together on 2026-08-01.

**The user's decision.** The Cold Plains runs are testing scaffolding and
should behave more like the real thing — the character should move about
considerably more, clearing a wide circle several screens in each
direction. Both live runs that day completed `[CVRL]` **without ever
fighting**, because nothing happened to be inside radius 50. A trial run
that can pass without exercising the thing it exists to test is not
testing it.

**A latent correctness bug.** `units.PERCEPTION_RADIUS` is 80 subtiles
and `scan_units` drops everything beyond it, so a snapshot cannot see
past 80. `runs/cold-plains.toml` clears radius **150** from a standstill.
It has been declaring 150 subtiles clear on the strength of an 80-subtile
look for as long as it has existed. Nobody noticed because the monsters
have always come to us.

So the patrol is what makes any radius above ~80 mean anything, and the
feature and the fix are the same work.

## Acceptance criteria

1. A clearance with patrol enabled visits sample points spread across its
   radius, so every part of the circle passes within perception range of
   the character at least once.
2. It is still a TICKED step: one short leg per tick, the reflex ladder
   consulted between legs. No leg is a long blocking `walk_to`.
3. A patrol point on unknown or unreachable ground is skipped with a log
   line, never fatal — `NavigationError` currently fails the whole cycle.
4. Neither watchdog fires during a legitimately long patrol: legs send
   input and move the character, which is progress by both definitions.
5. `clear_radius` without patrol parameters behaves exactly as today.
6. The sim exercises a patrol end to end, with a monster placed where
   only a patrol will find it.
7. **The radius is trivially easy to change** (user request). One number
   in the run file, and a `--radius` command-line override so a different
   circle can be tried without editing a file at all — the same shape as
   the existing `--chicken` override, and for the same reason: the
   staged-acceptance numbers are the ones that get tuned most. Everything
   derived from the radius (the patrol ring especially) is expressed as a
   FRACTION of it, so changing the one number moves the whole pattern
   rather than leaving the ring where it was.

## Scope

**In:** patrol behaviour inside `ClearRadiusStep`; its parameters in both
step registries; the run files; sim coverage; tests; the architecture doc
if the vocabulary changes.

**Out:** room-graph or whole-area clearance (the ask was a circle);
patrol as a reusable step for other purposes; changing `pickup`'s radius
semantics beyond what the patrol requires; any change to the navigator.

## Decisions

**R157 — the patrol lives inside `clear_radius` (option A).** A separate
`patrol` step would recreate exactly the shape of review 001, which cost
this milestone a P1: two components measuring the same question from two
different points with no shared notion of "done". Clearing and patrolling
also interleave by nature — walk until something appears, kill it, resume
— so two steps would hand control back and forth every few ticks.

**Kept deliberately simple** (user: *we don't need this to become
enormously onerous; ideally, a simple detection of how far the character
has moved, and if there are any living enemies nearby, would cover most
of the requirements*). The design is a fixed ring of sample points and a
visited set — no frontier exploration, no coverage map, no path
optimisation. "How far the character has moved" becomes "which sample
points have been reached", which is the same idea made checkable.

**R156 defaults assumed** (the confirmation table was not answered
explicitly; every one is reversible config): new stage radius 96, a new
run file rather than editing stage B, `cold-plains.toml` switched to
patrol, 12-subtile legs, unreachable points skipped, sim scenario
extended. Q1 and Q3 are the two worth a second look before implementing.

## Files expected to change

- `pd2bot/behavior/steps.py` — `ClearRadiusStep`, `RunServices`.
- `pd2bot/behavior/run.py` — `default_registry` param schemas (the
  validate-without-a-game path used by drills and the run linter).
- `runs/cold-plains.toml`, plus a new `runs/cold-plains-patrol.toml`.
- `tests/test_behavior_steps.py`, `tests/test_behavior_run.py`,
  `tests/simworld.py`, `tests/test_behavior_sim.py`.
- `docs/architecture/` — behaviour architecture, if the step vocabulary
  grows a documented parameter.

## Conventions to carry in

- Numbers that are judgement calls live in config or `RunServices`
  defaults with a comment, never as literals in logic.
- Every non-obvious decision is commented with the evidence that forced
  it, live-run references included.
- Tests cite the run or review that motivated them, and assert the
  ABSENCE of the old behaviour where that is the point.
- Run files name steps and parameters only — never classes.
- Validation: `python -m pytest -q` and `python -m ruff check .` with
  `~/.venvs/pd2bot/Scripts/python.exe`.

## ADR expectation

`possible`. If the patrol ends up defining how any future run covers an
area, that is a precedent worth recording. If it stays a parameter on one
step, the code comments carry it.

## Phases

| Phase | Size | Summary | Files | Review gate | Notes |
|---|---|---|---|---|---|
| P1 | sm | The patrol itself: sample points, one leg per tick, skip-on-unreachable, done only when the circle has been walked AND reads clear | `steps.py`, `run.py`, tests | None | The whole behaviour, unit-tested |
| P2 | sm | Sim coverage + run files: a monster only a patrol can find, `cold-plains-patrol.toml`, `cold-plains.toml` switched over | `simworld.py`, `test_behavior_sim.py`, `runs/*.toml`, docs | **End of phase**: supervised live run before the wider radius is trusted | Depends on P1 |

Parallelisation: none worth having; P2 needs P1's parameters.

## Validation strategy

- Unit: the patrol visits every point, skips an unreachable one, refuses
  to finish early, and is inert when not configured.
- Sim: a monster outside the standstill radius is found and killed, and
  the run still completes.
- Live: one supervised run on the new file, judged on whether it FIGHTS —
  which is the whole point of the change.
