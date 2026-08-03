# 002 — Sightings memo keeps no-longer-wanted items pending (P3)

- **Where:** `pd2bot/behavior/steps.py`, `_PickupMixin.pending_sightings`
  / `RunServices.wanted_seen` (T3, R186).
- **What is wrong:** the memo records wanted items by unit id at
  sighting time, and reaps them only when their spot is back in view
  and empty. An item that STOPS being wanted after its sighting — the
  usual case: a mana potion seen early, then `belt_full["mana"]` set —
  stays "pending" and keeps the sweep walking the ring for a bottle
  nobody would pick up on arrival.
- **Why it matters:** costs one avoidable ring walk (~60 s) on runs
  where a belt type fills mid-clearance; T55 run 1's sweep walked for
  exactly this shape. Never wrong, only slow.
- **Suggested fix:** filter `pending_sightings` through the same
  wantedness checks `wanted_items` applies (`belt_full` for the item's
  potion type, `inventory_full` for non-potions) — requires remembering
  each sighting's kind alongside its position.
- **Validation:** a test where a mana potion is sighted, `belt_full`
  gains "mana", and the sweep skips its ring.
