# P4 — Behavior engine, runs-as-data, the reflex ladder

Part of [plan.md](plan.md) (M5). Size: `sm`. Dependencies: P1–P3
interfaces (consumed, not modified). Sequential per R50. **Sim only:
this phase sends no live input and needs no user presence.**

## Scope

The behavior architecture — the roadmap's third expected ADR
(drafted here, finalized in P6): a ticked engine, run definitions as
declarative TOML, a class-agnostic combat-module interface with the
necro's TOML config, the survival reflex ladder with the R49
thresholds, and the never-idle invariant. Everything unit-tested
against fakes.

Out of scope: the necro combat *implementation* and pickit (P5 — this
phase defines the interfaces they fill), any live run, changes to
`SafetyMonitor`/`cycle.py` internals (the engine is *called by* the
existing `run_games` callback; the monitor stays the untouched last
line beneath everything).

## Context you need

- Roadmap decision 5 (`docs/plans/2026-07-28-bot-from-scratch/plan.md`):
  hierarchical FSM engine; runs as declarative data; per-class combat
  module + per-class config, class-agnostic runs — kolbot's
  three-layer pattern as *design reference* (`kolbot/` is read-only,
  never executed).
- M5 notes.md: the full R47 kit record and the R49-approved ladder —
  the numbers below are the user-approved defaults, all config.
- `pd2bot/safety.py`: the monitor raises `ChickenExit`/`DeathHalt`
  through the tick; the engine must let those propagate untouched.
- `pd2bot/cycle.py` `run_games(run_callback)`: the integration point.
  `NavigationError` → cycle fails, next game; that taxonomy stays.
- Config format: TOML via stdlib `tomllib` (Python 3.12 venv) —
  human-readable with comments (explicit user requirement, R46 Q3).

## Design (agreed in planning; deviations need a stop-and-report)

New package `pd2bot/behavior/`:

- **`engine.py`** — a ticked loop, not threads: each tick = snapshot
  → `SafetyMonitor.tick()` → reflex ladder → current state's step.
  States are small objects/functions with explicit transitions (the
  M3/M4 pattern of injectable clock/sleep for testability). The
  engine knows nothing about necromancers or Cold Plains.
- **`run.py`** — run definitions loaded from `runs/*.toml`: an
  ordered list of steps with params, e.g. for Cold Plains:
  `town_preamble` → `waypoint {dest = 3}` → `clear_radius {center =
  "arrival", radius = 150}` → `pickup` → `done` (leave via the
  cycle). Steps map to registered step-handlers; unknown step names
  fail loudly at load, not mid-run.
- **`combat.py`** — the class-agnostic interface (protocol):
  something like `CombatModule.engage(snapshot, ctx) -> Action`
  plus `upkeep(snapshot, ctx) -> Action | None`; concrete modules
  live per class (P5: `necro.py`) configured from
  `config/<class>.toml` (hotkeys, skill ids, thresholds). Runs never
  reference a class; the config chooses the module.
- **`reflex.py`** — the ladder, evaluated every tick before offense;
  first firing rung wins, everything below is skipped that tick.
  User-approved defaults (R49; every number in the necro TOML):

  | # | Rung | Trigger (out of town) | Action |
  |---|---|---|---|
  | 1 | Death latch | monitor (unchanged) | halt forever |
  | 2 | Chicken | hp ≤ 35% | monitor raises; cycle leaves |
  | 3 | Rejuv | hp < 50% | key 2, no cooldown; empty column + ≥2 hostiles within 10 → escalate to rung 4 |
  | 4 | Blood warp | (≥4 hostiles within 8 AND hp < 60%) OR >25% hp lost within 2 s | verified switch F2, right-click retreat point ~20 subtiles from hostile centroid on known-walkable ground; guards: mana ≥ 10, hp > 2 × max(0.12 × max_hp, 12) |
  | 5 | Heal potion | hp < 100% | key 1 (col 4 backup), 10 s cooldown |
  | 6 | Mana potion | mana < 25% | key 3, **15 s cooldown** (R49 amendment) |
  | 7 | Disengage | bone armor down & on cooldown & hp < 70% | retreat from pack; no attacking until rearmored |
  | 8 | Upkeep | bone armor off cd & absorb < 75% (fallback: after being hit) · revives < 3 | recast bone armor · desecrate → revive (delegated to the combat module; never in town) |

  Rungs 1–2 live in `SafetyMonitor` already — the ladder does **not**
  reimplement them; it sits between the monitor and offense.
  Cooldown/last-cast bookkeeping is the ladder's job (P2's
  primitives are dumb on purpose). Blood warp's own cooldown is
  unknown-length: track "last attempted" and treat a cast that
  didn't move the player as still-on-cooldown (position-verify).
- **Never-idle invariant** (R47.9): if, outside town, no action has
  been *sent* and no progress made for `idle_bail_s` (default 10),
  leave the game via a typed `IdleBail` the cycle treats like a
  chicken (counts toward `max_consecutive_chickens`? No — separate
  counter with its own loud-halt threshold, default 2; an idle loop
  is a bug, not a vitals problem, and must not be masked).
- **`config/necro.toml`** — hotkeys (F1 bone armor, F2 blood warp,
  F3 tp-tome *unused*, F4 bone wall *unused*, F5 desecrate, F6
  revive), skill ids (P1's live-captured constants), every ladder
  number above, belt minimums, drink cooldowns. Comments explain
  each knob — the user reads and tunes this file.

## Work items

1. The package skeleton + engine with injectable timing; state
   machine tests (transitions, monitor exceptions propagate, ladder
   short-circuits offense).
2. Run loader + step registry; `runs/cold-plains.toml` parsed and
   validated (the run *content* is exercised end-to-end in P5's sim).
3. Reflex ladder with full unit-test coverage: every rung's trigger
   and guard, priority order, escalation (rejuv-empty → warp),
   cooldown bookkeeping, warp position-verify, town suppression of
   rungs 3–8 where applicable (drink rules are out-of-town only per
   R47.6; upkeep desecrate/revive never in town per R47.4).
4. Combat-module protocol + a scripted `FakeCombatModule` for engine
   tests; necro TOML loaded and validated (unknown keys fail loudly).
5. `IdleBail` + counter wiring at the `run_games` callback boundary.
6. **ADR draft**: `docs/adr/2026-07-29-behavior-architecture.md`
   (status: proposed until P6 finalizes) — context, options
   (monolithic script vs behavior tree vs ticked FSM + data layers),
   decision, consequences. Follow the house ADR format
   (`docs/adr/2026-07-28-hybrid-map-knowledge.md` is the model).

## Conventions and reminders

- Injectable clock/sleep everywhere; no real sleeps in tests; no
  test touches the game (M3/M4 house rule).
- The monitor and cycle internals are read-only in this phase; if the
  design seems to need a change there, stop and report.
- TOML files carry explanatory comments; loaders reject unknown keys
  (a typo'd threshold silently defaulting is exactly the failure
  mode the user's "robustness" priority forbids).
- Do not commit unless asked. Do not expand scope. Report what
  changed, test coverage summary, deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Engine, run loader, ladder, combat protocol, necro config and
`IdleBail` exist and are thoroughly sim-tested; ADR drafted; nothing
live was run; tests/lint green. Review gate: none (P5 ends with the
go/no-go). ADR expectation: **drafted here**, finalized P6.

## Implementation Result

Status: done (sim-only, as scoped)
Completed: 2026-07-31
Commit: pending

- Changed: new package `pd2bot/behavior/` (engine, run, reflex, combat,
  actions, runner), `config/necro.toml`, `runs/cold-plains.toml`, 88 new
  tests across five `tests/test_behavior_*.py` files, ADR draft
  `docs/adr/2026-07-29-behavior-architecture.md` (status: proposed).
- Validated: `pytest -q` 434 passed; `ruff check .` clean. No live run,
  no input sent — everything against fakes.
- Deviations, reported:
  1. **Belt keys follow R53, not this file's rung table.** The table
     above says heal = key 1 / mana = key 3 (R47.6's original layout);
     R53 declared the permanent layout mana/rejuv/heal/heal, so the
     shipped defaults are heal keys 3+4, mana key 1, rejuv key 2 —
     derived in the loader from `[belt] columns`.
  2. **IdleBail is a `ChickenExit` subclass** so the untouched cycle
     leaves the game; runner counts idles separately and halts loudly
     at 2 consecutive. Wrinkle: the cycle's chicken counter also sees
     idle bails (mixed sequences can halt with the vitals message).
     Clean fix needs one line in cycle.py — deferred to the P5 gate
     (R115).
  3. Added `actions.py` (action vocabulary + executor protocol) and
     `runner.py` (callback boundary) beyond the four planned modules —
     structural seams, no scope added.
  4. Rung 8's armor recast is allowed in town (`armor_in_town = true`):
     castable there (P2 live), and arriving armored is strictly better.
     Desecrate/revive delegation stays out-of-town only per R47.4.
