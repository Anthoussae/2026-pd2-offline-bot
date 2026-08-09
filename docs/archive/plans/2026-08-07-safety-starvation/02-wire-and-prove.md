# P2 — wire the poll live-shaped, and make a run able to prove it

**Size:** `sm`. **Depends on:** P1. **Review gate: YES — this is the
gate that unblocks live running.** **ADR:** none (P5 writes it).

## Scope

Connect P1's machinery to the real bot and make its operation visible in
the run event log. After this phase the M6 P5 acceptance battery is
unblocked: the in-process half of the invariant holds.

**Out of scope:** the watchdog process and everything about it (P3/P4).

## Implementation

### 1. Wiring order (`pd2bot/wiring.py`)

`build_bot` currently builds the navigator at line ~641 and the
`SafetyMonitor` at ~679, so the navigator cannot see the monitor. Build
the **monitor first**, then pass `monitor.poll` into `live_navigator`.

`live_navigator(session, store, difficulty)` (`navigate.py:561`) gains an
optional `safety_poll` parameter forwarded to the `Navigator`. Keep it
optional and defaulted to `None`: the M3 CLI, the survey tool and the
drills build navigators with no monitor at all, and none of them should
break.

Prefer the plain re-order to a mutable holder. The `narrate_ref` holder
pattern exists in this file for a genuine cycle (the town layer outlives
any one run); safety has no such cycle and should not borrow the
indirection.

### 2. Conversion at the engine boundary (`pd2bot/behavior/engine.py`)

`Engine.tick()` (`engine.py:518`) is the wrapper that already guarantees
every tick is logged via its `finally`. Catch `SafetyInterrupt` there —
or in `_tick` around the step/executor calls — and re-raise the real
exception:

- a death verdict → `DeathHalt`, with the latch already set by the
  monitor;
- a vitals verdict → `ChickenExit`, message built from the interrupt's
  carried vitals so it reads like the monitor's own.

Convert at exactly one place and say in a comment why it is that place:
downstream, `cycle.run_games` (`cycle.py:394`, `424`) and `runner.py`
handle these types and are live-verified — the conversion exists so none
of that has to change.

**The ordering rule from review 2026-08-02 issue 001 still holds:** the
death latch outranks every stop. A converted `DeathHalt` must not be
overtaken by `StopRequested` handling.

### 3. The abort channel, heard during walks

The same block starved `_should_stop` (`engine.py:284`, `655`). Give the
engine's stop check a path into the walk: the cleanest shape is for the
poll callable that `wiring` hands the navigator to check **both** the
monitor and the stop order, raising `SafetyInterrupt` for vitals and the
existing `StopRequested` for an abort. Keep the death-first ordering
inside that callable — the same reason as above.

### 4. Telemetry (`pd2bot/runlog.py` + `docs/architecture/run-log.md`)

Two new event kinds, so the next run can *prove* the fix rather than be
assumed to have worked:

- `safety.interrupt` — a poll fired inside a blocking call: reason,
  vitals, where (`walk`), and how long the call had been running.
- `nav.capped` — a `walk_to` returned on its budget: seconds spent,
  distance short, target, and the replan/click counters from the
  `WalkResult`.

Follow the existing rules for this log — never raises, never blocks,
never interprets, honest absence — and document both kinds in
`run-log.md` alongside the existing families. A `nav.failed` event
already exists from the pickup-reliability P1 work; keep the naming
consistent with it.

Also surface `capped` in whatever prose the engine already writes about
walks, so a reader of `narrative.log` sees it without opening the JSONL.

## Tests

- `tests/test_wiring.py` — the built bot's navigator has a safety poll
  wired, and it is the same monitor the engine uses. This is the test
  that would have caught "the fix exists but nothing calls it".
- `tests/test_behavior_engine.py` — a `SafetyInterrupt` raised from a
  fake step/executor comes out of `tick()` as `ChickenExit`
  (vitals) and as `DeathHalt` (death); the tick is still logged (the
  `finally`); a death interrupt is not overtaken by a pending stop.
- `tests/test_runlog*.py` — both new events serialize with the fields
  documented, and the log survives being handed junk.
- A navigator built without a monitor (the CLI/drill path) still walks.

## Conventions

- The run log's contract is in `docs/architecture/run-log.md` — read it
  before adding kinds; the schema is enforced.
- No new `except Exception` on the safety path.
- `ruff` clean.

## Agent reminders

- Do not commit unless asked.
- Do not start the watchdog work in this phase.
- If the conversion cannot be placed at a single site without a broad
  catch, stop and report — that is a design finding, not a detail.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Review gate — what to review before any live run

Present to the operator, and stop:

1. **The wiring is real**, not just present: which object's `poll` the
   navigator holds, and the test that pins it.
2. **The latency claim, stated as a number**: worst-case seconds from
   HP crossing the line to `ChickenExit` being raised, derived from the
   poll interval and the cap — not estimated.
3. **What the log will show** on the next run so the fix is provable
   from evidence rather than from confidence.
4. **The residual**: the bot still leaves the game through the same ESC
   → Save-and-Exit path, which takes its own time and is unchanged by
   this phase. That is the window the watchdog (P3/P4) closes.

## Definition of done

The live bot's navigator polls the live monitor; a mid-walk safety
condition arrives at the cycle as the exception it has always handled;
the abort channel is heard during a walk; and the run event log records
both interrupts and capped walks. Track A complete.

---

## Implementation Result (2026-08-07) — DONE, review gate open

`wiring.build_bot` now builds the `SafetyMonitor` **before** the
navigator (a plain re-order, not a holder) and hands
`safety_poll_for(monitor, should_stop)` to `live_navigator`, which
forwards it to the `Navigator`. `safety_poll_for` is a module-level
factory so it is directly testable: it asks the monitor first (death
outranks a stop — review 2026-08-02 issue 001) and raises an abort as a
`SafetyInterrupt` rather than a bare `StopRequested`, which as a
`RuntimeError` the broad handlers would have eaten.

`BehaviorEngine.tick()` converts at one boundary, `_converted()`:
death → `DeathHalt`, `stop` → `StopRequested`, otherwise `ChickenExit`.
Downstream is untouched — that is what the conversion is for.

Telemetry: `safety.interrupt` (from the engine, on conversion) and
`nav.capped` (from the executor's `MoveTo` branch, the only place a
`WalkResult` exists). Both documented in
`docs/architecture/run-log.md`.

### The bug the tests caught, worth keeping on the record

The interrupt event was first written with a field named `kind`. The
run log's writer does `record.update(fields)` over an envelope that
already owns `"kind"` — so the field would have **overwritten the event
kind**, renaming `safety.interrupt` to `life` and erasing the event from
the log it exists to appear in. The positional-only `kind` parameter
(added when `npc.interact` hit the same wall) stops the collision being
silent at the *call*; it does not stop this. Field renamed to `verdict`,
and a test asserts `"kind" not in` the event.

### Measured, not derived — the number this gate reports

Real `SafetyMonitor`, real rate limiter, real walk loop, 40 phase
offsets of the crossing:

| | |
|---|---|
| worst-case latency, crossing → `ChickenExit` raised | **0.100 s** |
| mean | 0.055 s |
| same scenario, pre-fix | **21.8 s** (the real death: 24 s) |

Conservatively **≤0.2 s** in production, since real HP can cross between
polls: one monitor rate-limit interval (0.2 s) bounds it, and the walk
polls every 0.1 s inside that.

### Validation

1080 tests pass, `ruff` clean.
