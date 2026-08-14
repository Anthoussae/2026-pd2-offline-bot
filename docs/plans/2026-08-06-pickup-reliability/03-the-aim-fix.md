# P3 — The aim fix

Part of [plan.md](plan.md). Size: `sm`. **Depends on P2** and is
deliberately under-specified until P2 answers. Review gate: none (P2's
gate already chose the direction).

## Scope

Implement the fix P2's measurement selects. Three directions are
pre-sketched so the implementer knows the shape; **P2 picks one**, and
picking without P2 is the failure mode this plan exists to avoid.

### Direction A — aim at readable label geometry

*If P2's probe finds label rectangles or per-item screen positions in
memory.* The strongest outcome: the aim stops being a guess schedule
and becomes a read. Shape: a `units.item_label_rect(session, unit_id)`
style read, the executor aiming at its centre, the offset schedule
retained only as the fallback when the read is unavailable.

**ADR expected** if this lands — it extends the out-of-process
perception approach into UI-layer geometry, which is new territory and
was previously ruled out as pixel-scraping-adjacent. The distinction to
record: reading a structure the game maintains is not scraping pixels.

### Direction B — derive the offset from the neighbourhood

*If P2 shows the winning offset shifts predictably with neighbour
count/arrangement.* Replace the fixed tuple with a function of the
local census: label band position as a function of how many items
share the tile neighbourhood. Keep the current schedule as the
zero-neighbour case, which is measured and works.

### Direction C — unstack the pile behaviourally

*If P2 shows the offset is unpredictable but the occluder is.* Options,
cheapest first: collect in **draw order** (screen depth, i.e. by
`wx + wy` descending) so the top sprite goes first and uncovers the
next — today the sort is world distance to the player, which is
unrelated to draw order; or step the character 1–2 subtiles to change
the projection and retry; or pick up, then re-approach the remainder.

## Non-negotiables whichever direction wins

- The belt-full / inventory-full reasoning keeps its current semantics.
- The aim change must not silently increase the click budget: if more
  attempts are needed, that is a measured decision with a number, and
  the write-off must still fire.
- `pickup_click_attempts` and the schedule length are coupled by design
  (a write-off means every measured aim point was tried). If the
  schedule stops being a fixed list, that invariant needs restating in
  the code and in `behavior.md`, not quietly dropping.

## Files

`pd2bot/behavior/execute.py` (aim selection), possibly
`pd2bot/units.py` (Direction A), `pd2bot/behavior/steps.py` (Direction
C ordering), `docs/architecture/behavior.md`, tests.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: the P2 drill re-run after the fix is the natural regression check
— same staged arrangements, and the misses should be gone.

## Agent reminders

Do not commit unless asked. Do not implement more than one direction
"to be safe" — that doubles the surface and hides which one worked.
Stop and report if P2's data does not clearly select a direction.

## Definition of done

The selected direction implemented, tested, ruff-clean; `behavior.md`
updated to describe how an aim point is now chosen; the P2 drill
re-run clean (that re-run needs game time — coordinate with the
operator).

## Implementation result (2026-08-06)

P2's calibration selected **Direction C** by elimination:

- **Direction A (read label geometry)** — the T79 probe found no
  screen-like coordinate pairs in an item's unit block. Provisionally
  dead (only the unit block was scanned, not BH.dll's data sections), so
  not pursued.
- **Direction B (derive the offset)** — dead. T76/T79 measured **no
  predictable winning offset**: a dense pile's pick rate swings 1/8–8/8
  on noise and the winner scatters across four offsets. There is no
  stable shift to derive.
- **Direction C (unstack the pile)** — SHIPPED. `_PickupMixin._draw_order`
  collects front-sprite-first (`wx + wy` descending, the codebase's
  projection convention), so the occluding neighbour is lifted before it
  can eat the click aimed at the item behind it. Applied at all four
  collect-selection sites (the two nearest-first sorts replaced, the two
  unsorted `items[0]` picks ordered). Tested; the direction is pinned.

**Not done, and why** (the aim schedule was NOT reordered, per the
"don't do more than one direction" rule and the data): the offset
schedule is noise-dominated, so reordering it is unsupported. The
`step-and-reproject` and `pick-then-re-approach` sub-options of C were
left out — draw-order is the cheapest and the others add walking without
measured benefit. The retry-pacing speedup that T78 hinted at
(`pickup_retry_s` 1.5 s vs 0.12 s live confirms) is a **speed** change,
not an aim fix, and wants a live confirm-window measurement before
tuning — noted for the P6 remeasure, not changed blind here.

The honest frame: the click path stays erratic. Draw-order removes the
occlusion class of miss; the rest is accepted, because the deterministic
answer (command-by-GID) was ruled out. 1048 tests, ruff clean.
`behavior.md` updated. **P6's remeasure run is the live regression
check.**
