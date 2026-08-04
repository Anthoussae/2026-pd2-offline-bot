# 003 — Seam filter silently skipped when the first patrol tick has no area (P3)

- **Where:** `pd2bot/behavior/steps.py`, `_PatrolMixin.patrol_points`
  (the R189 c bounds filter).
- **What is wrong:** the ring is computed and CACHED on the first
  `walk_the_circle` tick. If `snap.area` happens to be None on that
  tick (a mid-transition read), the filter is skipped and the unfiltered
  ring — seam points included — is cached for the whole step.
- **Why it matters:** re-opens the T55 run 2 border-livelock surface on
  an unlucky first tick. Low likelihood (the step runs after arrival is
  settled), and the collect budget + progress margin now bound the
  damage to a give-up rather than a livelock — hence P3.
- **Suggested fix:** do not cache `_points` until an Area was available
  to filter against (compute-but-don't-store when `area is None`), or
  re-filter on first non-None area.
- **Validation:** a test whose first patrol tick has `area=None` and
  whose second has the narrow area — the seam point must not survive.
