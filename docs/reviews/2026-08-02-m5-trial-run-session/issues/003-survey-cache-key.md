# 003 — Survey target cache misses same-count terrain updates (P3)

**Where:** `pd2bot/wiring.py`, the survey service closure
(`survey_cache` keyed by `(seed, area_id, room_count)`).

**What:** a room RE-recorded with changed terrain but an unchanged
total room count does not invalidate the cached frontier list.

**Why it matters (barely):** same-count terrain rewrites are the churn
class R12-R14 eliminated (transient bits stripped; byte-identical
re-records don't save), so the stale window is near-theoretical, and
one new room anywhere flushes it.

**Suggested fix:** have `record()` bump a monotonic revision counter on
ExploredArea and key the cache on that. Fold into P5.

**Validation:** unit test — record a changed grid for an existing room,
assert the closure recomputes.
