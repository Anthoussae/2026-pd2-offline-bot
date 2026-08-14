# P2 — The calibration: does the label move?

Part of [plan.md](plan.md). Size: `sm`. **Needs the game and the
operator.** Depends on P1 (the drill reports through the same events).
**Review gate: end of phase — its answer picks P3's fix.**

Per the operator's 2026-08-06 constraint, the drill is **written and
unit-tested now, and launched later**.

## The question

`_PICKUP_OFFSETS` is 8 fixed screen offsets from an item's projected
ground tile. The hypothesis from T71 run 4:

> PD2 displaces item labels vertically when items are close together,
> so the clickable point for a given item **depends on its
> neighbours** — and a fixed schedule cannot find it.

It predicts: bimodal failure, density-correlated failure, "clicked A
got B", and worst-case behaviour for label-only classes (runes, gems —
T65 run 4 measured their ground sprites surviving 58–147 direct probes
while both hits landed in the label band at y=−48).

**Falsifiable**: if the winning offset for a given item is the same
alone as it is in a pile, the hypothesis is dead and the cause is
elsewhere (draw-order occlusion, stand-off geometry, item class).

## Design — T76, `drills/t76_pickup_calibration.py`

Bot-controlled, sends input. The operator stages items by dropping
them; the drill does the rest and announces each round in chat.

### Rounds

For each **arrangement**:

1. **solo** — one item, clear ground
2. **pair** — two items 1–2 subtiles apart
3. **pile** — four or more items within 2 subtiles

...and for each **class** available: potion, rune, gem, charm, and one
larger item (armour/weapon) as the sprite-clickable control.

### Per round, per target

- Record the target's world position, its projected screen point, the
  live ground-item census within 5 subtiles, and label state
  (`units.label_display_on`).
- Walk the **full offset schedule** — do not stop at the first hit —
  clicking one offset at a time, and after each click read back:
  - did any item leave the ground, and **which one** (the "clicked A
    got B" measurement — this is the whole point);
  - the carried-items delta.
- Report, per target: **which offsets hit, which item each hit
  produced**, and how that set differs between solo / pair / pile.

The drill must re-drop or re-stage between rounds, or ask the operator
to; a round that cannot be staged is skipped and **said out loud**,
never silently.

### The read-only probe, same session

Before the click rounds, dump what memory knows about labels: whether
any BH.dll structure exposes label rectangles or per-item screen
positions. If label geometry is *readable*, P3 becomes "aim at the
label we can see" and the whole class of failure disappears. If not,
P3 is behavioural (unstack the pile, or derive the offset from
neighbour count). **This probe is the highest-value five minutes in
the plan** — run it first, and it sends no input.

## Success criteria (the T72 lesson: a drill must not pass on a partial run)

PASS requires: at least the solo and pile arrangements measured for at
least two classes, with per-offset hit/miss and the identity of the
item each hit produced. Anything less is INCOMPLETE, not PASS — a
calibration that measured only the easy case would license exactly the
wrong fix.

## Files

- `drills/t76_pickup_calibration.py` (new)
- `docs/drill-log.md`, `docs/instruction-log.md` (protocol)
- Captured output into this directory as `t76-calibration.md`

## Implementation notes

- Follow the existing drill shape: `Drill` + body via `run_drill`,
  `DrillRun` for chat/cursor, abort paths (chat `abort`, cancel file,
  ESC, the mouse), announce in game chat, `sends_input=True`.
- T60/T63/T65 are the closest precedents for a click-probe drill; reuse
  their structure rather than inventing a third shape.
- The clicking must go through the normal guarded path
  (`GatedInput` / the executor), not a bypass — the M1 contract.
- Chicken/safety stack stays live; this runs in town or a cleared area
  by the operator's choice, and the drill states which it expects.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

The drill's own dry paths unit-tested (round construction, the
hit-attribution logic, the skip-and-say-so path). **Do not launch it
without the operator's go.**

## Review gate — stop here

Present to the operator:

1. Is the winning offset **stable** between solo and pile? (Yes → the
   hypothesis is dead; report what the data says instead.)
2. When a click hits the wrong item, is the wrong item predictable
   (always the neighbour drawn lower/on top)?
3. Is label geometry readable from memory?

P3's direction follows from these, and the plan should not guess it in
advance.

## Agent reminders

Do not commit unless asked. Do not implement the fix in this phase.
Do not launch the drill until the operator says they are tabbed in.
Report faithfully — including a round that could not be staged.

## Definition of done

The drill exists, is unit-tested, ruff-clean, and is **ready to
launch**; the phase completes only when it has been run and its answer
recorded. Until then this phase is `blocked: awaiting game time`.
