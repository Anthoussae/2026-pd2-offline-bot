# 001 — Stop checks preempted the death latch (P1) — FIXED IN REVIEW

- **Where:** `pd2bot/behavior/engine.py`, `BehaviorEngine.tick` (the
  R184/R189 stop checks vs `monitor.tick()` ordering).
- **What was wrong:** `should_stop` and the operator ESC/Enter check
  both ran BEFORE `self._monitor.tick()`. A `StopRequested` rides
  `ChickenExit` into the cycle's leave-game path, which SENDS INPUT —
  so on the one tick where a death and a stop coincide, the death latch
  would never set and the leave would type at a dead character.
- **Why it matters:** the death latch is the project's absolute safety
  invariant ("after a detected death the bot sends no input of any
  kind, permanently"). Any ordering that can skip its detection, however
  narrow the window, is a P1 by definition.
- **Fix applied:** the monitor ticks first; both stop checks follow in
  the same tick, so an abort still lands within one tick everywhere —
  it just can no longer outrun `DeathHalt`/`ChickenExit`.
- **Validation:** `test_the_death_latch_outranks_every_stop` stages a
  death and an abort on the same tick and requires `DeathHalt`;
  `test_an_outside_stop_wins_the_tick_over_everything` now asserts the
  monitor WAS consulted on the stopping tick. Suite 857 green.
