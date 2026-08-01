# 005 — The trace printer reaches into `engine._executor`

Severity: **P3**

`pd2bot/wiring.py` (`main`).

## What is wrong

```python
trace = getattr(engine._executor, "trace", None)
```

Private attribute, reached from another module, guarded by `getattr` so it
fails silently if it is ever renamed — which means the executor trace, the
artifact stage B exists to produce, would quietly stop being printed.

`BehaviorEngine` grew a `step_names` property earlier in the same session
for exactly this reason, so the pattern to follow already exists.

## Why it matters

Low impact, but the failure mode is the bad kind: silence rather than an
error, on the one output the live runs are for.

## Suggested fix

Expose the trace on `BehaviorEngine` as a property, the way `step_names`
is, and have the wiring read that.

## Validation

A test that an engine exposes its executor's trace through a public
accessor.
