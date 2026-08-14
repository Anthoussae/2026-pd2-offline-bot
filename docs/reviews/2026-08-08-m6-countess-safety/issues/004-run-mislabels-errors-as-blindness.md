# 004 — `run()` labels every unexpected error a read failure

**Severity: P3** — diagnostics only, but this diff has already cost four
live runs to defects that left no usable trace, so labelling matters more
than usual here.

**Where:** `pd2bot/watchdog.py`, `Watchdog.run`.

## What is wrong

```python
try:
    self.tick()
except Exception as exc:
    self._blind(exc)
```

`_blind` means one specific thing: "a memory read failed, so we cannot
say anything about the character, and we are deliberately not
heartbeating." It increments `_read_failures` and says "not heartbeating
while blind".

But `tick()` already catches its own read failures. Anything reaching
this handler is something else — a bug in the fire path, a filesystem
error, an unexpected `None`. Those get reported as blindness, counted as
read failures, and rate-limited on the same counter, which both misleads
the reader and can suppress the message entirely (the counter only speaks
on 1, 5, 25, then every 100).

## Why it matters

The heartbeat is correctly withheld either way, so the bot still stands
down — the safety behaviour is right. What is wrong is the story: an
operator reading "cannot read the game" will go looking at pymem and
offsets for a fault that is neither.

## Suggested fix

Give the generic handler its own message and counter — "tick failed
(<type>: <detail>)" — while keeping the same no-heartbeat consequence.
Keep `_blind` for genuine read failures only.

## Validation

- Unit: make `tick` raise something that is not a read failure; assert
  the message names the failure rather than blindness, and that no
  heartbeat is written.
