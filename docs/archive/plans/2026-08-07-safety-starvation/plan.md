---
kind: plan
size: md
depth: implementation
status: done
completed: 2026-08-07
repo: 2026-pd2-offline-bot
created: 2026-08-07
adr: expected
---

# The chicken-starvation safety fix

**Why this plan exists.** On 2026-08-07 the T71 acceptance run died in
Tower Cellar 4 because the engine blocked inside a single `walk_to` for
24 seconds and the `SafetyMonitor` only runs at the top of a tick — so a
blocked engine cannot chicken. Root cause and evidence:
`docs/reviews/2026-08-07-chicken-starvation-death/`.

**The invariant this plan restores, and then defends twice:** *nothing
may starve the safety monitor.* From the moment HP crosses the chicken
line, a chicken must begin within a small bounded time — whatever the
engine is doing, including being wedged entirely.

Approved as R228 option (b) and R229 (phase table + Q1–Q5 all yes).

## Size

`md`, depth `implementation`. Five `sm` phases in two tracks. It is not
`sm` because it spans two processes and a live canary; it is not `lg`
because no phase needs its own planning pass.

## Goal and acceptance criteria

1. A `walk_to` that cannot make progress **interrupts itself** on a
   safety condition within ~0.2 s, and **returns to the tick loop**
   within the cap regardless.
2. The operator's abort channel is heard during a walk, not only
   between ticks.
3. A **separate process** presses ESC when vitals cross the line, so a
   wedged bot cannot prevent the pause.
4. The bot **refuses to run unattended** when that process is not alive.
5. Every one of the above is provable from the run event log after the
   fact, and pinned by offline tests — including a regression test that
   reproduces the exact starvation shape and fails without the fix.

## Scope

**In:** `walk_to`'s blocking loops and their cap; the safety-interrupt
type and its conversion; the abort poll during walks; the watchdog
process, its latch/heartbeat protocol, and the bot-side integration
(`GatedInput` latch, dead-man check, honest narration, launcher);
telemetry for all of it; the ADR; docs.

**Out:** *why* traverse got stuck at the Cellar 4 exit with 29 hostiles
(a navigation-quality item — this plan makes the block survivable, not
rarer); the speed pass; corpse retrieval / death recovery; any change to
the death latch's no-input-ever rule.

## Discovery summary

Full notes: [`notes.md`](notes.md). The three findings that shaped it:

1. **`walk_to` has no wall-clock cap on the call.** Per-waypoint (20 s)
   and per-plan-cycle (5) budgets exist and multiply.
2. **A chicken raised from inside a walk would be swallowed.**
   `ChickenExit`/`DeathHalt` are `RuntimeError`s and at least four broad
   `except Exception` handlers sit on the path out — hence
   `SafetyInterrupt(BaseException)` (Q1).
3. **The watchdog's primitives already exist**: `MenuInput.press_escape`
   guards on foreground alone and is documented as "the chicken's first
   move"; `drill.py`'s cancel file is the file-channel pattern to copy
   (including its stickiness lesson).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| Q1 | `SafetyInterrupt(BaseException)`, converted to `ChickenExit`/`DeathHalt` at the engine's tick boundary | Uncatchable by `except Exception`; conversion at the same place the monitor already raises, so every downstream handler is untouched |
| Q2 | 2 s wall-clock cap on one whole `walk_to` call, configurable | Safety latency is covered by the poll; the cap's real job is restoring the **reflex ladder** cadence. Returning short is already normal — every caller re-checks distance |
| Q3 | Watchdog polls 0.2 s at a threshold 5 points **below** the bot's | A backstop that fires first is not a backstop. Same class config, so the numbers cannot drift |
| Q4 | Dead-man heartbeat required for unattended runs; explicit opt-out | A watchdog silently not running is a safety layer that silently does not exist |
| Q5 | Watchdog is its own process + CLI | A thread shares the GIL with the thing it watches |

Also settled in notes: the watchdog presses **ESC and nothing else**
(`cycle.leave_game` keeps its monopoly on the menu dance); it sends
**nothing** when HP reads dead (mirrors the death latch); the
`GatedInput` latch blocks *world* input while leaving the *menu* path
open, so the bot can still complete the leave it should complete.

## Files expected to change

`pd2bot/safety.py` (the interrupt type, the poll helper),
`pd2bot/navigate.py` (poll + cap), `pd2bot/behavior/engine.py`
(conversion, dead-man, narration), `pd2bot/wiring.py` (wiring order and
the poll), `pd2bot/input.py` (latch), `pd2bot/watchdog.py` (**new**),
`tools/live-run.ps1`; tests alongside each.

## Docs expected to change

`docs/architecture/behavior.md` and `docs/architecture/game-cycle.md`
(the safety story is stated in both), `docs/architecture/run-log.md`
(new event kinds), `CLAUDE.md`'s safety-invariant paragraph, the live
protocol in `docs/project-state.md`, and a new ADR.

## ADR

**Expected**, at P5: *safety must not be starvable — an in-process
interrupt plus an out-of-process watchdog*. It chooses among plausible
alternatives (in-process only / watchdog only / both), it changes the
process architecture, and it sets the precedent for how every future
blocking call must behave. Candidate title:
`docs/adr/2026-08-07-unstarvable-safety.md`.

## Validation strategy

Offline, per phase:

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

The load-bearing test is the **starvation regression test** (P1): a
scripted world where the walk cannot progress while HP falls, asserting
the chicken is raised within a bounded number of simulated seconds. It
must fail against the pre-fix navigator — verify that by construction,
not by assumption.

Live validation is P5 only, and uses the zero-risk path `safety.py`
already documents: mana chicken in town with a 99 % threshold exercises
the identical code path as life chicken.

## Phases

| Phase | Size | Summary | Files | Review gate |
|---|---|---|---|---|
| [P1](01-interruptible-walk.md) | sm | `walk_to` polls safety in all three blocking loops; wall-clock cap; the regression test | `navigate.py`, `safety.py`, `test_navigate.py`, `test_safety.py` | None |
| [P2](02-wire-and-prove.md) | sm | Wire the poll through `wiring.py`; convert at the engine boundary; log it so a run can prove it | `wiring.py`, `behavior/engine.py`, `runlog` | **Yes — unblocks live running** |
| [P3](03-watchdog-process.md) | sm | The watchdog: 0.2 s vitals poll, ESC via `MenuInput`, latch + heartbeat, never acts on death | `pd2bot/watchdog.py` (new), tests | None |
| [P4](04-watchdog-integration.md) | sm | `GatedInput` honours the latch; engine dead-man check; honest kill-switch narration; launcher | `input.py`, `engine.py`, `wiring.py`, `tools/live-run.ps1` | None |
| [P5](05-canary-and-closeout.md) | sm | Supervised live canary, docs, ADR, cleanup sweep | `docs/`, drills | **Yes — live canary** |

**Track A is P1–P2** and completes the fix that unblocks the acceptance
battery. **Track B is P3–P5** and must land before any *unattended*
running. P3 can be written in parallel with P2 if useful; P4 depends on
both.
