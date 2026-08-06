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
