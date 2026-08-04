---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-01
commit: none
adrs: []
---

# Implementation log — patrol clearance

## Outcome

Both phases implemented and validated against fakes. **The review gate at
the end of P2 is open**: no part of this has executed against the game,
and the question it exists to answer — does the bot now fight? — cannot
be answered by a test.

## Completed work

**P1, the patrol.** `ClearRadiusStep` takes an optional `patrol` flag.
When set it plans a ring of `patrol_points` (8) sample points at
`patrol_ring` (0.66) of the radius, walks one capped leg per tick
(`patrol_step`, 12 subtiles), and marks a point visited on arrival within
`patrol_reach` (6). The settle timer cannot start until every point is
dealt with, which is the actual fix: the radius reading clear is a claim
about what perception can see, and perception is 80 subtiles.

Fighting always wins the tick; the patrol is only what happens when there
is nothing to clear. A point on ground the atlas has never read raises
`NavigationError` — which would otherwise fail the whole cycle — and is
skipped with a log line. The catch is narrow on purpose: `InputRefused`
and `SkillSwitchFailed` must keep reaching the engine.

**P2, coverage and tuning.** A new `runs/cold-plains-patrol.toml` at
radius 96, `runs/cold-plains.toml` switched to patrol (its 150 has been
unsound since it was written), a `--radius` override mirroring
`--chicken`, the effective radius printed pre-flight, and a sim scenario
whose pack sits ~70 subtiles out where only a patrol will meet it.

## Validation

- `python -m pytest -q` — **713 passed**.
- `python -m ruff check .` — clean.
- Live, through the elevated bridge:
  `python -m pd2bot.wiring --dry-run --chicken 50 --radius 120 --run
  runs/cold-plains-patrol.toml` prints
  `clearance  radius 120 (--radius override)` and assembles every
  collaborator without sending anything.
- The override's failure path: a run with no clearance refuses with
  *"--radius 120 has nothing to apply to: run 'no-clearance' has no
  clear_radius step"* rather than silently running unmodified.

## Deviations from the plan

Three, all recorded in the phase files:

1. `tests/test_behavior_steps.py`'s `make_step` helper built steps from a
   bare dict, so factories never saw the validated parameters production
   hands them. It broke the moment `clear_radius` gained an optional
   parameter; it now applies the spec's declared defaults.
2. `test_a_stalled_run_idle_bails` moved onto the stage-B run file. With
   a patrol the bot always has somewhere to be, so the old stall stopped
   stalling — the patrol working, not the watchdog failing.
3. Two bugs the plan did not anticipate, both found by running rather
   than by reading:
   - `patrol_complete` read True before the ring was computed
     (`len(None or [])` is 0), so the patrol was skipped entirely on the
     first tick. Caught by the new unit tests.
   - **`patrol_attempts` counted legs rather than lack of progress.**
     Consecutive ring points are ~48 subtiles apart, so three 12-subtile
     legs always fell one short and the sim abandoned seven of its eight
     points — *while passing every assertion*. Only reading the trace
     showed it. It now counts legs that got no closer, which is what the
     budget was always for and is independent of the ring geometry.

## Documentation

No architecture doc changes needed: `docs/architecture/` covers
perception, navigation and the game cycle, and the behaviour
architecture lives in `docs/adr/2026-07-29-behavior-architecture.md`,
which mentions `clear_radius` only as an example of the shared
blackboard — there is no step-parameter list anywhere to fall stale. The
run files carry their own explanation, which is where an operator looks.

## ADRs

None warranted. The patrol is one optional parameter on one step, with
its reasoning in the code and the run files. If it later becomes how
every run covers ground — a Countess route, a full-area clear — that
generalisation is the ADR-worthy moment, and `plan.md` recorded the
expectation as `possible` for exactly that reason.

## The review gate: PASSED (2026-08-01)

`[CVRL]` — a clean, complete run of `cold-plains-patrol.toml` at radius
96. 128 ticks, 73 walk legs, two kills, two healing potions drunk under
pressure, clean leave. No `SkillSwitchFailed`, no waypoint lock, no
misclick, no `NavigationError`, no `IdleBail`.

The gate's four questions:

1. **Points reached: 5 of 8.** The three misses are all on the EAST side
   (x≈5313-5331) — consistent geometry rather than bad luck, so there is
   something genuinely unreachable over there. Worth a look, but the
   ring is not landing on unread ground in general.
2. **It fought**, and resumed the patrol after each fight.
3. **No navigation skips at all** this run.
4. **No idle bail.**

Two of those three misses were the patrol's own fault and are now fixed:
points abandoned from **20 subtiles**, which is walking distance. The
no-progress budget was measuring across a COMBAT INTERRUPTION — the
character walks toward the monster, i.e. away from the patrol point, so
every leg after a fight looked like no progress against a `_closest`
recorded before it. A fight now ends the attempt rather than counting
against it.

It took five supervised runs to get here, and the failures on the way
were town-layer and navigation problems rather than patrol ones — the
waypoint lock-out, a misclick on Warriv that ate three identical
retries, and a wall the navigator re-planned into five times. All three
turned out to be the same principle stated three ways: **a retry that
cannot differ from the attempt it retries is not a retry.**

## Follow-up
2. Radius 96 and switching `cold-plains.toml` were assumed rather than
   confirmed (R156). Both are one-line changes and `--radius` makes the
   first one adjustable without an edit at all.
3. The sim cannot prove the coverage argument — it does not model
   perception's 80-subtile cutoff, so its snapshot lists every monster in
   the world. It proves the patrol walks, finds and finishes. The
   coverage argument is geometry and lives in the step's comments.
