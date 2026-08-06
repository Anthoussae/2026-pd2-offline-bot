# 003 — `npc.accidental` fires once per retry, not once per accident

**Severity: P3**

`pd2bot/town.py` — `_clear_stray_ui`

## What is wrong

The event is emitted inside the retry loop:

```python
for _ in range(1 + self.config.panel_click_retries):
    ...
    if not stray:
        break
    found.append(names)
    self.runlog.event("npc.accidental", panels=names, ...)   # <- per retry
    ...press escape...
```

A single stray panel that takes three ESCs to close produces three
`npc.accidental` events for one accident.

## Why it matters

It does not corrupt anything — the renderer collapses consecutive
identical events, and the retry count is arguably real information. But
it inflates any count of "how many accidental panels happened this run",
which is exactly the question the event exists to answer, and the
inflation is invisible unless you know the loop is there.

Compare `item.dropped`, which was deliberately built to fire on the
TRANSITION into the wanted set for this reason.

## Suggested fix

Either emit once after the loop with the retry count as a field:

```python
if found:
    self.runlog.event(
        "npc.accidental", panels=found[0], attempts=len(found),
        cleared=not stray,
    )
```

or keep the per-retry emit and rename it to something that does not read
as a count of accidents (`npc.accidental_retry`).

The first is preferable: it also records whether the recovery actually
succeeded, which the current version does not.

## Validation

A town test with a stray panel that needs two ESCs emits exactly one
`npc.accidental` carrying `attempts=2`.
