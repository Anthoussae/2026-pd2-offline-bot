# 004 — The runner's catch-all cannot tell a bug from a bad moment

Severity: **P3**

`pd2bot/behavior/runner.py` (`BehaviorRunner.__call__`, `RunFailed`).

## What is wrong

The final clause is `except Exception`, which is deliberate and correct in
motivation — four exception types escaped one at a time and each fix named
only the one in front of it. But it now also swallows genuine programming
errors. A `TypeError` or `AttributeError` in a rarely-taken branch reads
as "the run failed, leave and retry", costs a game, and then halts with a
message naming the exception type rather than pointing at a bug.

`InputRefusedHalt` is a related loose end: it is a `BehaviorError`
(a plain `RuntimeError`), so the engine's own escalation for a long
refusal streak is itself caught by this clause and downgraded from a halt
to a retry.

## Why it matters

Not urgent — two consecutive failures still halt loudly, so nothing hides
forever, and for unattended running "survive and retry" is the right
default. The cost is diagnostic: the loudest signal a bug can send is a
traceback, and this converts it into a run outcome.

## Suggested fix

Let the obviously-programmer-error types through, or tag them in the
alert so a human reading the halt knows to look at code rather than at the
game. Give `InputRefusedHalt` a type the catch-all respects, so its halt
semantics survive.

## Validation

A test that a `TypeError` from the engine reaches the caller (or produces
an alert that names it as a probable bug), while an `InputRefused` still
becomes a counted `RunFailed`.
