# P1 — Cleanse drop hygiene, and no retry that cannot differ

Size: sm. Dependencies: none. Parallel-safe with P2.

## The bug being fixed (R173, user-diagnosed live)

Full inventory + wanted rune: pickup fails → cleanse queued →
`maybe_cleanse` drops junk **at the character's feet** → the retried
pickup click lands on the just-dropped junk (overlapping sprites at the
pointer) and scoops it back → inventory full again → cleanse re-queued —
an infinite loop that pinned the character in fire until chicken (49%).
Two code facts close the loop (`pd2bot/behavior/steps.py`,
`maybe_cleanse`, ~L556-585): the cleanse runs wherever the bot stands,
and afterwards it unconditionally clears `stuck`/`attempts`/
`inventory_full` — "one more chance" — re-arming a retry that cannot
differ from the attempt it retries.

## Changes (all in `pd2bot/behavior/steps.py` + tests)

1. **Stand-off before dropping.** In `maybe_cleanse`, before calling
   `services.cleanse()`: if any *wanted* ground item (use
   `wanted_items`) is within `cleanse_standoff` (new RunServices field,
   default 8 subtiles) of the player, do not cleanse yet — emit a
   `MoveTo` directly away from the nearest wanted item to a point
   `cleanse_standoff + 4` away, return True (the tick acted). The
   cleanse then happens on a later tick, clear of anything we intend to
   click.
2. **Step off the pile after dropping.** When the cleanse dropped ≥1
   item, set a `_step_off` marker (position where the drop happened).
   Next tick, `maybe_cleanse` (or the caller) emits one `MoveTo` ~10
   subtiles away from that spot before anything else; clear the marker
   once the player is ≥8 subtiles from it. Junk on the ground behind us
   is already a travel-click hazard (ground items are avoided), so
   distance is the whole cure.
3. **No doomed re-arm.** Track `cleanse_retried: set[int]` in
   RunServices. When `maybe_cleanse` clears `stuck`/`inventory_full`
   after a productive cleanse, record every unit id it un-stuck. If the
   SAME unit id fails its pickup again (lands back in `_mark_stuck` /
   `_mark_inventory_full`), do NOT queue another cleanse for it — the
   retry already differed (space was freed, we stepped off) and still
   failed, so the item is genuinely stuck for this game. The
   INVENTORY-FULL latch then holds for the rest of the game as its
   docstring already promises.

## Style / conventions

- Numbers live on `RunServices` with a why-comment, not inline.
- Every log line states what happened AND why it matters (match the
  file's voice).
- The step must keep working when `cleanse` is None (unavailable).

## Tests (tests/test_behavior_steps.py)

- The R173 loop shape in the sim: full inventory, wanted item, cleanse
  available, junk "re-appears" if dropped within pickup reach of the
  standing spot → assert the run terminates: cleanse happens ≥
  standoff away from the wanted item, a step-off MoveTo follows, and
  the second failure of the same unit id ends the retries for the game.
- A cleanse with no wanted item nearby proceeds immediately (no
  needless walking).
- `cleanse_retried` does not block a *different* item's cleanse.

## Reminders

Do not commit unless asked · no scope creep · don't suppress warnings
or disable tests · stop if blocked · report changes + validation.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: tests above pass, full suite green, ruff clean.
