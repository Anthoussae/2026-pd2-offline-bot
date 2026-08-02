# 004 — `_hp_lost_in_window` re-reads the clock (P3, cosmetic)

**Where:** `pd2bot/behavior/reflex.py`, `_hp_lost_in_window`.

**What:** `evaluate` computes `now` once, but this helper calls
`self._clock()` again, so the warp window's horizon can differ from the
tick's `now` by microseconds under the real monotonic clock.

**Why it matters (barely):** no observable behavior change at real
tick rates; fake clocks in tests are stable. Pure tidiness — one tick,
one timestamp.

**Suggested fix:** pass `now` as a parameter. Fold into any future
reflex-touching phase (the potion plan's P2 is adjacent).

**Validation:** existing reflex suite.
