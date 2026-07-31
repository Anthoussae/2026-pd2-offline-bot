# P5b — The real pickit and inventory hygiene (R117 amendment)

Part of [plan.md](plan.md) (M5). Inserted at the P5 gate: the user's
check-in answered R116 with the real pickup spec instead of a go/no-go,
which reshapes the pickit before live acceptance makes sense. Scope
recorded as R117, clarifications as R118 (both resolved in the
instruction log). **Sim-side complete; two read-only live drills remain
before the gate re-asks.**

## Scope

1. **The real pickup whitelist** (R117): potion supply with caps,
   flawless+perfect gems/skulls, runes, unique charms, rare+unique
   jewelry, named unique/set/socketed bases, ~30 PD2 quest-and-map
   items. Format stays TOML (R118 Q3).
2. **Potion protocol v2** (R118 Q1/Q2): belt first, then an inventory
   reserve of 2 per type; ALL excess drunk, rejuvs included; **no
   potion is ever stashed**. Supersedes R75's drink-all + rejuvs-to-
   materials.
3. **The inventory cleanse** (R117): ctrl+right-click drops items; a
   whitelist pass drops accidental-pickup junk — in town during the
   preamble, and in the field at the next safe moment after a failed
   pickup.
4. **Discovery drills** (R118 Q4, approved): T38 socket stat, T39 item
   ids by placement.

## What was built (2026-07-31, sim-only)

- `config/item_ids.toml` — the vocabulary: verified ids with
  provenance, ~100 pending names, the groups. `load_item_table` merges
  T39's machine-appended sidecar (`item_ids.learned.toml`) over the
  pending list; contradictions are loud errors.
- `pd2bot/pickit.py` v2 — sockets condition, per-type potion reserve
  (belt room OR inventory < N), strict vs permissive evaluation, and
  `cleanse_keep`: **the cleanse is disabled outright while any
  keep-rule names a pending id** — a whitelist that cannot recognise a
  Worldstone Shard must never throw one away.
- `config/pickit.toml` — the R117 list as rules, in the user's own
  groupings. No gold rule (the R117 list omits gold; note in file).
- `pd2bot/units.py` — `GroundItem.sockets` from the item's stat list;
  `offsets.STAT_NUM_SOCKETS = 194` marked UNVERIFIED until T38.
- `pd2bot/input.py` + `panelinput.py` — `VK_CONTROL`; generalized
  modifier discipline (R113 settle on both sides, release in finally).
- `pd2bot/town.py` — `potion_reserve` config; `_excess_potions`,
  drink-to-reserve (rejuvs included); potions excluded from both stash
  phases; `drop_item` (refuses with the stash open — gesture meaning
  depends on panels, R64) and `cleanse_inventory` (alert-and-continue
  on a stuck drop); wired into `manage_inventory` before the stash
  phases. `keep_item=None` disables cleansing entirely.
- `pd2bot/behavior/steps.py` — shared cleanse queue on `RunServices`;
  a failed pickup queues it; `maybe_cleanse` runs it only with no live
  hostile within `cleanse_safe_radius` (40) and never in town; a
  cleanse that freed space un-writes-off stuck items for one more
  round.
- Drills: `drills/t38_socket_stat.py`, `drills/t39_item_ids.py` —
  both read-only, both append/print evidence, T39 saves progress per
  item and supports skipping unowned items.
- Sim: accidental-pickup event + junk kinds in the scripted world; the
  trace now shows the cleanse running only after the last death.

Validation: 546 tests, ruff clean. `p5-sim-trace.md` regenerated.

## What remains before the gate re-asks (R116)

1. **T38** (socket stat) and **T39** (item ids) over the bridge —
   read-only, user drives. T39 is long (~100 names, skippable); partial
   coverage is fine, unfilled ids just stay pending.
2. Wire-time notes for P6 (unchanged from P5's list) plus:
   `cleanse_keep(pickit)` -> `TownLayer.keep_item` and
   `RunServices.cleanse`; pickit's `belt_capacity` from the class
   config.
3. Live verification items carried forward: gold's kind on the first
   real drop; the ctrl+right-click drop gesture verified by effect the
   first time the cleanse runs live (P6 stage A, in town, zero risk).

## Definition of done

Sim-side: DONE (this file, the tests, the trace). Phase closes when
T38/T39 have run (any coverage), their outcomes are logged, and the
R116 gate question has been re-asked with the real pickit in hand.
