# 001 — The cleanse drops everything by default; protection is opt-in

Severity: **P1** — **FIXED** 2026-07-31, same session

`pd2bot/town.py` — `TownLayer.__init__` (`protected_ids` default `None`),
`TownLayer.cleanse_inventory`.

## What is wrong

The two halves of the cleanse have opposite defaults:

```python
protected = self._protected_ids() if self._protected_ids else set()
```

`keep_item=None` disables the cleanse entirely — a safe default. But
`protected_ids=None` means **no item is protected**, so a caller that
supplies a whitelist and forgets the baseline gets the most destructive
configuration available, silently. The dangerous combination is the one
you reach by doing half the wiring.

## Why it matters

This is not hypothetical. T43's audit ran the real whitelist over the
real inventory and would have dropped 4 of 12 items, including a **magic
grand charm** and both tomes — none of which are on the R117 keep list,
all of which the user plainly wants. The baseline guard (R128) is the
only thing standing between that audit and items on the floor, and it
is the part a caller can omit without any error.

P6 has not wired either parameter yet, so the mistake is still ahead of
us rather than behind us — which is exactly when to fix the default.

## Suggested fix

Make protection opt-out, not opt-in. Either:

- have `TownLayer` capture the inventory at construction when
  `protected_ids is None`, so the default protects everything the bot
  did not pick up itself; or
- refuse at construction: `keep_item` without `protected_ids` raises,
  forcing the caller to say `protected_ids=lambda: set()` if it really
  means "protect nothing".

The first is friendlier and matches the feature's intent ("clean up the
bot's own accidents"). The second is louder. Either beats a silent
worst case.

## Validation

A test asserting that a `TownLayer` built with a whitelist and no
explicit `protected_ids` does NOT drop a pre-existing unrecognised item.
Today that test would fail.


## Resolution

Fixed in `TownLayer._protected()`: with no `protected_ids` supplied, a
baseline is captured the first time the cleanse runs, so the default
protects everything rather than nothing. Two existing tests that relied
on the old default now pass `protected_ids=lambda: set()` explicitly,
which also makes them say what they are actually testing.

Two tests added: half-done wiring drops nothing, and the implicit
baseline still cleans accidents that arrive after it was taken (so the
safe default does not quietly disable the feature).

A session-wide baseline passed in by P6 is still the better answer; this
is the floor, not the goal.
