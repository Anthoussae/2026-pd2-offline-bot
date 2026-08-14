# P5 — the mandatory pickup order

Size: md (largest phase; sub-structured below, no separate plan
needed). Dependencies: P2 (line/atlas thread-back), P4 (potions no
longer compete for pickup attention). Review gate: **end of phase —
pickup census review of the pilot run.**

## The design (user's R241 item 7, adjusted by assessment)

A whitelisted drop creates a **PickupOrder** (unit id, kind, position,
created_at): persistent, priority BELOW combat, ABOVE traversal.
Orders queue (the user's "chain"). The "thread" back is not a bespoke
breadcrumb — position + the atlas + A* already answer "how do I get
back"; the order stores the position and the run's route context.

Order lifecycle:

- **OPEN** — created on first sight (the wanted-item detection already
  fires for the census; it now also enqueues).
- **ACTIVE** — no hostiles in the engagement bubble and no reflex rung
  firing: walk back (leash-aware), run the unstack loop: attempt the
  8-offset schedule on the TARGET; if a wrong item is collected, that
  is PROGRESS (the pile shrank) — continue. Inventory full →
  WALK-AWAY CLEANSE: move `cleanse_offset_subtiles` (default 12,
  config) in a random cardinal direction AWAY from the order position
  (must exceed the return scan radius so dropped junk does not rejoin
  the pile), run the existing cleanse, return, resume.
- **INTERRUPTED** — combat/reflex preempts at any point; order stays
  queued; cleanse-in-progress completes its current item drop first
  (atomic per item, not per cleanse).
- **CLOSED (collected)** — the unit id is in the inventory (verified,
  not inferred from a click).
- **CLOSED (gone)** — the unit id is no longer on the floor AND not in
  the inventory (T51 expiry or picked into a pile-grab earlier):
  closed immediately with `pickup.order_gone` — this is the
  anti-livelock rule; never chase a ghost.
- **CLOSED (budget)** — `order_budget_s` (default 75, config; the
  user's 60–90 band) of ACTIVE time spent: write off loudly
  (`pickup.order_abandoned` with the full attempt trail).

Safety: every loop leg is bounded and polls safety (the unstarvable
rule); the never-idle watchdog is naturally satisfied (the loop acts
constantly); the budget caps total dwell.

## Sub-structure

1. `behavior/steps/orders.py` (new): PickupOrder, the queue, lifecycle
   transitions, budget accounting — pure logic, heavily unit-tested.
2. Priority wiring in the step mixins: `_PickupMixin` consults the
   queue when combat is quiet, before traversal resumes; TraverseStep
   and ClearRadiusStep both honor it (the engage-first precedent from
   R223 documented — orders sit BELOW engage by construction).
3. The unstack loop + walk-away cleanse (reuses maybe_cleanse; the
   random cardinal walk goes through the navigator, leash-aware).
4. Instrumentation: event kinds `pickup.order_open/active/interrupted/
   collected/gone/abandoned`, all with order id + position + elapsed;
   census extended to report per-order outcomes.
5. Pilot flag: `[pickup] mandatory = true` accepted in run TOMLs only
   (per-run, default false). Cold Plains pilot before any wider use.

## Live acceptance (standing mandate + census gate)

One pilot cold-plains run with `mandatory = true`: census shows every
whitelisted drop either collected or closed-gone/budget with its trail;
no watchdog events; run duration inflation reported honestly. The
OPERATOR reviews the census before the flag is allowed in other runs.

## Validation

Unit tests: lifecycle (all six transitions), gone-detection against a
sim floor that expires items, budget clock, walk-away direction/
distance property, interrupt/resume, queue ordering. Sim run
end-to-end. pytest + ruff; commit.

## Reminders

Do not touch the 8-offset schedule itself (measured, T76). Do not let
orders preempt combat or reflexes — the ladder's precedence is
inviolable. If run duration balloons in the sim beyond ~2× baseline,
stop and report before going live.
