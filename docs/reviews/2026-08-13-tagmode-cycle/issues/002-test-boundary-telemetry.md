# 002 — round-boundary telemetry: late-resolving clicks score as misses

**Severity:** P3

**Where:** `pd2bot/behavior/steps/tagmode.py::_tick_test` (test_end
path) and `_reset_pickup_bookkeeping`.

## What is wrong

At `test_end` the battery clears `pending_pickup` (via
`_reset_pickup_bookkeeping`) and computes the score from the boundary
tick's ground snapshot. A click sent just before the 30 s cap whose
item leaves the ground one tick LATER is therefore scored as
`wanted_left` (a miss), and because its pending entry is gone,
`confirm_pickups` never emits its `item.collected` — the tabulator's
`to_last` column and the event stream undercount by that item.

## Why it matters

Pure measurement noise at the boundary, worst case one item per
timed-out round, biased consistently AGAINST the tagged modes (they
time out; mode A finishes early with nothing pending). It cannot
change this battery's verdict — the gap is 100% vs 10%/36% — but a
future battery measuring a close contest would care. The census
reconciliation is unaffected (the item lands in the inventory and
counts).

## Suggested fix

At test_end, before resetting: give pending pickups one settle tick
(the `_TOGGLE_SETTLE_S` shape) and re-read the ground, OR carry the
boundary snapshot's pending set into the score as `resolving` so the
tabulator can report it honestly instead of as a miss.

## Validation

A unit test staging a pickup click on the final test tick with the
item leaving ground one tick later — the score should count it (or
report it as `resolving`), not as `wanted_left`.

## Resolution

RESOLVED 2026-08-14 (P6 closeout): test_end now counts wanted items with a pending click as `resolving` (own event field + tabulator flag), not `wanted_left`. Validated by test_timed_out_round_reports_a_click_in_flight_as_resolving.
