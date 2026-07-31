# 002 — A refused send ends the whole run loop, and the ladder thinks it acted

Severity: **P2**

`pd2bot/behavior/engine.py` (`tick`), `pd2bot/behavior/reflex.py`
(bookkeeping committed before execution), `pd2bot/cycle.py` (`run_games`
exception taxonomy).

## What is wrong

Two coupled problems on the same path.

**The exception escapes.** `BehaviorEngine.tick` calls
`self._executor.execute(...)` with no handling, and `run_games` catches
`NavigationError`, `ChickenExit`, `DeathHalt` and `CycleError` — not
`InputRefused`. So an ordinary refusal (a panel opened, focus moved to
another window) propagates out of the engine, past the runner, out of
`run_games`, and ends the session with a traceback rather than a failed
cycle.

`InputRefused` is not exotic: the guards raise it by design, and the M4
cycle treats focus loss as a routine, recoverable event with its own
policy (`_with_focus`). The behavior layer has no equivalent.

**The bookkeeping is already spent.** The ladder commits its state at
DECISION time, before the executor is called:

```python
self._last_drink["healing"] = now      # reflex.py, rung 5
self._warp_attempt = (now, position)   # rung 4
self._armor_attempt = now              # rung 8
```

Probed directly: a heal decision, then a send that never lands, and the
ladder refuses to heal again for the full 10 s cooldown — while the
character is below the threshold that asked for it. Same shape for the
escape rung, which is worse: a warp that was never sent blocks re-casts
for `warp_retry_s`.

## Why it matters

The survival ladder's whole promise is that it re-decides from fresh
state every tick. Committing "I acted" before knowing whether the action
left the building breaks that promise precisely when input is being
refused — which correlates with things going wrong.

## Suggested fix

- Catch `InputRefused` at the engine's execute site, log it, and do NOT
  mark activity; let the next tick re-decide. Optionally escalate after
  N consecutive refusals.
- Commit ladder bookkeeping only after a successful `execute`, e.g. have
  `evaluate` return the decision and a `commit()` callable the engine
  invokes on success.

## Validation

A test where the executor raises `InputRefused` on the first heal: the
engine survives the tick, and the ladder offers the heal again on the
next one.
