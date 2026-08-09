# DONE — the chicken-starvation safety fix

Completed 2026-08-07. All five phases. Not committed at time of writing
(the operator commits).

## Outcome

**The invariant holds and is proven: nothing may starve the safety
monitor.** From the moment vitals cross the line, a chicken begins
within a bounded, small time — whatever the engine is doing, including
being wedged entirely.

The death this plan exists to answer: on 2026-08-07 the M6 P5 acceptance
run died in Tower Cellar 4 because a blocking `walk_to` held the engine
for **24 seconds** while a 26–29 hostile pack killed the character. The
monitor only ran between ticks, so it never looked; the last logged HP
was 100%, taken before the block. The death latch worked. The *chicken*
was starved.

| | before | after |
|---|---|---|
| worst case, vitals crossing → `ChickenExit` raised | 21.8 s (measured in the same harness; the real death was 24 s) | **0.100 s** |
| a wedged or dead bot process | nothing happens | a separate process presses ESC |

## Completed work

**Track A — in-process (P1, P2).**
`SafetyInterrupt(BaseException)` and a shared `_evaluate()` behind both
`SafetyMonitor.tick()` and a new rate-limited `poll()`, so the two
raisers cannot drift. `Navigator` takes `safety_poll` and
`walk_budget_s` (`WALK_BUDGET_SECONDS = 2.0`) and polls from all four
places it waits — the waypoint loop, the UI wait in `_click`,
`_shake_loose`'s settle (its flat 1.5 s sleep became `_wait`, sliced
into poll-sized pieces), and the budget check. `wiring.build_bot` builds
the monitor *before* the navigator and passes `safety_poll_for(monitor,
should_stop)`, so the operator's abort rides the same uncatchable
channel. The engine converts back to `ChickenExit`/`DeathHalt`/
`StopRequested` at exactly one boundary.

**Track B — out-of-process (P3, P4).**
`pd2bot/watchdog.py`: a separate elevated process polling vitals at
0.2 s that presses ESC and only ESC, verifies the pause via
`UI_ESCMENU_MAIN` rather than assuming it, and sends **nothing** when
the character reads dead. Latch and heartbeat files carry wall-clock
stamps with staleness rules. `GatedInput` refuses world input while the
latch is fresh; `MenuInput` deliberately does not, so the bot can finish
its own clean Save-and-Exit. `EngineConfig.require_watchdog` (default
False) plus a launcher pre-flight that refuses before a game is created.
The kill switch now names the watchdog instead of blaming the operator.

**Telemetry.** `safety.interrupt`, `nav.capped`, `watchdog.fired`, all
documented in `docs/architecture/run-log.md`.

## Validation

- **1128 offline tests pass; `ruff` clean.** Up from 1048 at plan start.
- The load-bearing test pair: one asserts a blocked walk with no poll
  spends **>10 s** unwatched (measured 21.8 s), the one next to it
  asserts the same walk is interrupted in **<1.5 s** with the poll. Red
  is demonstrated permanently, not by a comment.
- **Live, unattended** (`drills/safety_canary.py`, via the elevated
  bridge): T80 runs 1–3, T81 runs 1–2. Run 1 FAILED and found three
  defects. Runs 2 and 3 PASSED 5/5; run 3 is the trustworthy one, in a
  different town (area 40 vs 109) and at 57% mana rather than full.
  Client left at `main_menu`, no latch, no stray process.

## Deviations from the plan

1. **The give-up ladder had to be carried across calls.** The cap
   returns before the no-progress ladder can finish, so a hopeless
   target would be retried for ever. Callers with their own per-target
   budgets would cope; traverse relies on `NavigationError`, and
   traverse is what died. Same ladder, counted across calls.
2. **The budget also had to bound `_click`** — waiting out a blocking
   panel is capped at 10 s, five times the walk budget, and an operator
   pressing ESC creates exactly such a panel.
3. **The dead-man check could not be the whole guarantee.** Raising
   mid-run leaves the game cleanly, but the cycle would create the next
   game and fail again, spinning create/leave. The real guarantee is the
   launcher's pre-flight; the per-tick check is the mid-run backstop.
   Residual, accepted: a watchdog dying mid-battery may cost one wasted
   create/leave.
4. **The canary became one script, not two drills**, and ran unattended
   at the operator's request rather than with them at the machine.

## Bugs found, and how

**A production bug that blocked every unattended run.**
`bring_to_foreground` could not take the window at all from a
bridge-launched process: `SetForegroundWindow` only obeys a process that
already owns the foreground or the most recent input. Fixed with
`force_foreground()` in `pd2bot/window.py`. **Found by running, not by
review** — it had been latent since M3.

**A latch/heartbeat kill targeting the wrong process.** `Popen.pid` is a
launcher shim here, not the watchdog: measured 5192 vs the child's own
18768. `terminate()` could orphan a live watchdog — one that can press
ESC into a later, unrelated game. Both the canary and
`tools/live-run.ps1` now kill the tree and verify the heartbeat went
stale.

**Two vacuous assertions, in a cycle whose own phase files warn about
them.** A 99% mana threshold against a character at 100% mana (`pct <=
99` is false at exactly 100), and a `menu_ok = True` in both branches of
a try/except. The first was caught by run 1 failing; **the second was
caught only because the operator asked "are you sure?" about a run that
had already reported PASS.** Both are written up in the explainer as the
cycle's most transferable lesson.

## Documentation updated

`docs/adr/2026-08-07-unstarvable-safety.md` (**accepted**),
`docs/architecture/game-cycle.md` (a new "Nothing may starve the
monitor" section), `docs/architecture/behavior.md` (the capped-legs
contract, now enforced rather than aspirational),
`docs/architecture/run-log.md` (three event kinds), `CLAUDE.md` (the
second safety invariant), `docs/project-state.md` (HALT lifted),
`docs/learning/2026-08-07-starvation-and-defence-in-depth.md` plus 9
glossary terms.

## Follow-ups outside this plan's scope

- **Never tested: killing a bot mid-walk to watch the watchdog fire
  anyway.** Round 3 runs the watchdog with no bot at all, which is a
  different claim. Worth doing before a long unattended battery.
- **Everything live was town, full health, no monsters.** The death
  happened in a Cellar under load; nothing has exercised the interrupt
  there. The M6 P5 battery is the first real test.
- **Round 2's "0.00 s" is not a latency measurement** — a 100% threshold
  is true whenever asked. The real number is the offline 0.100 s.
- **Why traverse got stuck at the Cellar 4 exit with 29 hostiles** is
  untouched. This plan made the block survivable, not rarer; the
  navigator-quality item belongs with the oscillation already priced in
  `performance-notes.md`.
