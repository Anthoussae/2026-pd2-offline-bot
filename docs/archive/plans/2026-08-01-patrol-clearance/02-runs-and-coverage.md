# P2 — Sim coverage, the run files, and an easily-tuned radius

Size: `sm`. Depends on **P1**. Read [plan.md](plan.md) and
[01-patrol-behaviour.md](01-patrol-behaviour.md) first.

## Scope

Prove the patrol end to end in the sim, expose it in the run files, and
make the radius trivial to change. Then a supervised live run.

**Out of scope:** any change to the patrol behaviour itself (that is P1's
and should not need revisiting); room-graph clearance; `pickup` radius
semantics.

## 1. The radius must be easy to change

Direct user request: *please make the radius value easy to alter, so if
we want to increase/decrease it we can do so easily.*

Two mechanisms, both needed:

**The run file keeps one obvious number.** `radius = 96` on its own line
with a comment saying what it means in screens (~24 subtiles each). No
second number derived from it anywhere in the file — P1 made the patrol
ring a fraction precisely so this stays true.

**A `--radius` command-line override**, mirroring `--chicken` in
`pd2bot/wiring.py`. Same justification: the staged-acceptance numbers are
the ones that get tuned most, and editing a data file to try 120 instead
of 96 is friction the operator should not pay while standing at the
machine.

Implementation sketch — apply it to the loaded run, and only where the
step actually takes a radius:

```python
parser.add_argument(
    "--radius", type=int, default=None,
    help="override the run's clear_radius radius (P6 staged acceptance)",
)
```

The override belongs next to the run load in `main`. It must be
**loud when it does nothing**: if the run has no `clear_radius` step, say
so on stderr and return non-zero rather than silently running the
unmodified file — a flag that appears to work and does not is exactly the
class of bug this project keeps paying for. Print the effective radius in
`describe()` output too, next to the run's step list, so the pre-flight
check the operator reads shows the number that will actually be used.

## 2. Sim coverage

`tests/simworld.py`'s `cold_plains_scenario` puts every monster within a
few subtiles of `ARRIVAL`, so a patrol is never exercised and the
standstill clearance passes exactly as before.

Add a scenario — a separate function, leaving `cold_plains_scenario`
untouched so the existing gate artifact keeps its meaning — with:

- a monster placed beyond the standstill radius but inside the patrol
  circle, i.e. somewhere only a patrol will ever perceive;
- the run loaded from the new patrol run file (or built with `patrol`
  enabled, whichever `build_sim` makes cleaner).

Assert: the monster dies, the clearance completes, and the run finishes.
Assert also that the bot actually MOVED — a scenario that passes without
walking is the same blind spot in a new costume.

Note the sim does not model perception's 80-subtile cutoff (its snapshot
lists every monster in the world), so the sim cannot prove the coverage
argument — only that the patrol walks, finds and finishes. Say so in the
test docstring rather than letting a green test imply more than it shows.
The coverage argument is geometry, and it belongs in P1's comments.

## 3. Run files

**New `runs/cold-plains-patrol.toml`** — copy stage B's header style,
which explains what the stage is FOR rather than just what it does:

```toml
[[step]]
name = "clear_radius"
center = "arrival"
radius = 96    # ~4 screens (a screen is ~24 subtiles)
patrol = true
```

**Switch `runs/cold-plains.toml`** to `patrol = true`, keeping radius
150. This is the file that has been unsound: 150 declared clear on an
80-subtile look. Add a comment saying that the patrol is what makes the
number honest, so nobody later "simplifies" it back.

**Leave `runs/cold-plains-stage-b.toml` alone.** Its radius 50 and its
header document a rung of the staged ladder that is still worth being
able to fall back to.

## 4. Docs

- `docs/architecture/` — the behaviour architecture doc, if it lists the
  step vocabulary or `clear_radius`'s parameters.
- The plan's `_DONE.md` is `yona-implement`'s to write, not this phase's.

## Files

- `tests/simworld.py`, `tests/test_behavior_sim.py`
- `runs/cold-plains-patrol.toml` (new), `runs/cold-plains.toml`
- `pd2bot/wiring.py` (`main`, `describe`)
- `tests/test_wiring.py` for the override, including the loud-failure case

## Conventions

- Run files name steps and parameters only — never classes, never pixels.
- A run file's header explains the stage's PURPOSE (see stage B's).
- Tests cite the run or review that motivated them.

## ADR expectation

`possible`. Write one only if the patrol turns out to define how future
runs cover an area in general; if it stays one parameter on one step, the
code comments are enough.

## Review gate — END OF PHASE, STOP HERE

Do not treat the wider radius as trusted on green tests. Stop and ask for
a supervised live run, and report these specifically:

1. Did the bot actually walk the circle — how many patrol points did it
   reach, and how many were skipped as unreachable?
2. **Did it fight?** This is the point of the whole change: both
   2026-08-01 runs completed without a single `AttackUnit`.
3. Did `NavigationError` skips happen, and how often? Frequent skips mean
   the ring is landing on unread ground and the geometry needs revisiting
   rather than the radius.
4. Any `IdleBail`, and if so what its context block said.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope.
- Do not suppress warnings or disable tests.
- Do not weaken P1's tests to make a scenario pass.
- Report what changed, what was validated, and any deviations.

## Validation

```
& "$HOME/.venvs/pd2bot/Scripts/python.exe" -m pytest -q
```

```
& "$HOME/.venvs/pd2bot/Scripts/python.exe" -m ruff check .
```

```
& "$HOME/.venvs/pd2bot/Scripts/python.exe" -m pd2bot.wiring --dry-run --radius 96 --run runs/cold-plains-patrol.toml
```

(The dry run needs the elevated bridge; it assembles and prints without
sending anything.)

## Definition of done

The sim proves a patrol finds and kills a monster the standstill
clearance would have missed; the new run file exists and the full run is
honest about its radius; `--radius` works and fails loudly when it cannot
apply; the pre-flight print shows the effective radius; suite green, ruff
clean; and the supervised live run has been requested with the four
questions above.

## Implementation Result

Status: done, awaiting the review gate
Completed: 2026-08-01
Commit: pending

- Changed: `runs/cold-plains-patrol.toml` (new, radius 96),
  `runs/cold-plains.toml` (patrol on, with a comment saying why the 150
  needs it), `run.py` (`RunDefinition.with_radius` / `.radius`),
  `wiring.py` (`--radius`, `radius_override`, effective radius in
  `describe`, loud refusal in `main`), `simworld.py` (`run_file`
  parameter, `patrol_scenario`), 6 new tests.
- Validated: 713 tests pass, ruff clean. Live dry run through the bridge
  shows `clearance  radius 120 (--radius override)`, and the no-op case
  refuses: *"--radius 120 has nothing to apply to: run 'no-clearance'
  has no clear_radius step"*.
- Deviations: `test_a_stalled_run_idle_bails` now builds on the stage-B
  run file. With a patrol the bot always has somewhere to be and keeps
  making progress, so the old contrivance stopped stalling — the patrol
  working, not the watchdog failing. The test is about the watchdog, so
  it needs a run that genuinely runs out of things to do.

**The finding this phase exists to have caught.** The sim passed every
assertion while the patrol abandoned SEVEN OF ITS EIGHT points, each
9-23 subtiles short. `patrol_attempts` counted legs, and consecutive
ring points are ~48 subtiles apart, so three 12-subtile legs always fell
one leg short of arriving. Only reading the trace showed it. It now
counts legs that got no closer — progress rather than effort — which is
what the budget was always meant to detect and is independent of the
ring geometry. A test asserting the outcome (no point abandoned, all
eight reached) was added, since the green suite is exactly what failed
to notice.
