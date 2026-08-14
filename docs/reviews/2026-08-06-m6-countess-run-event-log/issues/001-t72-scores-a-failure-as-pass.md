# 001 — T72 scores a reproduced failure as PASS

**Severity: P2**

`drills/t72_tower_probe.py:159-166`

## What is wrong

The drill returns PASS when the Tower transition FAILS, as long as the
first transition succeeded:

```python
if traverses < 1:
    raise RuntimeError(f"never reached the Forgotten Tower: {result}")
if traverses < 2:
    result = f"REPRODUCED the tower-stairs failure (log captured) — {result}"
return result          # <- PASS
```

That criterion was correct when written: the log was the deliverable and
a reproduced failure WITH a log was the outcome the probe existed to
produce. It is now wrong. The fix has landed and been verified (run 2:
4.3 s, both transitions, clean `[CVRL]`), so a future run that fails to
cross is a REGRESSION and must not report PASS.

## Why it matters

The drill log is the project's durable record of what worked. A green
row for a failed crossing is exactly the "a test that can pass without
doing the thing it tests" shape this repo has been bitten by before —
`ClearRadiusStep`'s docstring records the same lesson from the
2026-08-01 runs that completed without fighting anything.

The risk is realistic: this drill is the natural regression check for
the critter filter, so it will be re-run precisely when someone
suspects a regression.

## Suggested fix

Require both transitions. Keep the diagnostic framing in the result
string, but fail the drill:

```python
if traverses < 2:
    raise RuntimeError(
        f"the tower-stairs transition FAILED — this was fixed on "
        f"2026-08-06 (T72 run 2: 4.3 s, 2/2) so this is a regression; "
        f"the event log has the detail: {result}"
    )
```

## Validation

Run the drill against a deliberately broken filter (e.g. force
`combat_rated=True`) and confirm it reports FAILED rather than PASS.
