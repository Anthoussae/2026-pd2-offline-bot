# Review — the R248–R254 tag-mode cycle (combat-logistics)

- **Target:** `01b6967` + `39d3946` (HEAD of `combat-logistics`)
- **Base:** `a8d5b23` (the 2026-08-13 session handoff)
- **Scope:** 34 files, +2921/−19 — the tag-mode battery test kit
  (T90/T91), the run abort channel, the watchdog staleness grace, and
  the label-policy inversion.
- **Validation inspected:** 1299 tests green, ruff clean; six live
  launches during development (drill-log T90 rows 1–6, T91 row 1); the
  full battery data set (15 rounds); a complete cold-plains field
  validation run under the inverted policy (census 1/1 first-click).

## Overall assessment

**Ship it.** The cycle is unusually well-evidenced: every behavior
change is backed by either a measured battery round or a live failure
it directly fixes, the safety-policy change (the grace) was an explicit
operator decision with the analysis on the record, and the test suite
grew 24 tests including a full simulated battery. Three P3 findings,
none blocking; the notable risks are accepted ones, listed below.

| # | severity | finding |
|---|---|---|
| 001 | P3 | the run chat-abort channel shares a one-line buffer with the bot's own unprefixed announcements — a typed abort can be overwritten in a small window, and bot lines are read back as human |
| 002 | P3 | round-boundary telemetry: pending pickups are cleared at test_end, so a click resolving after the boundary scores as "left" and its item.collected never fires |
| 003 | P3 | the consumed-item chat announcement is sent while the inventory panel is open, so Chat refuses it and the operator only sees the console fallback |

## Accepted risks (decided, not findings)

- **Up to 15 s unguarded-backstop window** during a watchdog stall
  (R253, operator-approved; Track A untouched and carries the chicken
  guarantee at 0.100 s).
- **The field validation sample is n=1** (one wanted drop rolled that
  game); the battery's 30/30 is the statistical basis for the
  inversion.
- **The battery's drop-everything rule spends potions to ctrl slips**
  (three across the session, all caught by the floor confirmation) —
  the operator chose the item list.
- **The watchdog stall's root cause is still open**; the grace is
  mitigation plus instrumentation that can now actually fire.

## ADR candidates

None. The grace adjusts a threshold within ADR 2026-08-07's two-track
architecture; the label inversion is a measured constant flip inside
existing mechanics. Both are documented at their decision sites and in
the run-log doc.

## Test gaps

- `run_stop_channel`'s chat path is tested through a fake listener;
  the real `ChatListener` drift/echo behavior is exercised only by its
  own suite.
- The staleness grace has not yet been exercised live (no stall
  occurred after it shipped).
