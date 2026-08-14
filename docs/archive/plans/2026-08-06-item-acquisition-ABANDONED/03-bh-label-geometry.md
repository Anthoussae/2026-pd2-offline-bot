# P3 — The BH.dll label-geometry hunt

Part of [plan.md](plan.md). Size: `sm`. **Read-only** live probe.
Independent of P4. Review gate: end — readable, or provably not.

## The idea

Item labels — the `[Nef Rune]` boxes — are drawn by **BH.dll**, PD2's
loot filter, which is where T66 found the label-display flag
(`BH.dll+0x14D2CA`). A label is a screen rectangle the game already
computes every frame. **If BH keeps those rectangles in readable
memory, aim stops being a guess entirely**: click the rect centre and
the click lands, every time, for every item class — the accuracy endgame
for the click path, and useful even if P4's command path wins (a
verified fallback aim).

T76's probe only scanned each item's own unit block (0x140 bytes) and
found nothing. BH's own data sections were never searched. That is the
hunt.

## Scope — a probe drill, not a fix

`drills/t79_label_geometry.py`, read-only, T58/T66 methodology:

1. Operator drops a few labelled items and stands still.
2. For each item, compute its projected screen point (we already can).
3. Sweep BH.dll's data sections for an int pair (or a 4-int rect) near
   that projection, for **every** item at once — the real signal is a
   *table* of rects, one per visible label, not a lone pair.
4. **Correlate across a state change** — move the cursor / toggle labels
   (ALT, readable via T66) / drop another item — and keep only
   candidates that track. A pair that matches once is a coincidence; a
   table that updates as labels move is the structure.

Sends nothing but the ALT toggle (verified, T66) if the correlation
needs it; otherwise pure read.

## What the outcome decides

- **Readable** → P5's actuator aims at the rect centre; the offset
  schedule is retired to a fallback. Likely an ADR note (reading BH's
  computed geometry is new perception territory, though still "read a
  structure the program maintains", not pixel-scraping).
- **Not readable** (bounded search came up empty) → recorded as a closed
  question so it is not re-hunted, and P2's improved schedule stands as
  the click path's best. Either way the finding is durable.

## Files

- **New** `drills/t79_label_geometry.py` + a unit test for its pure
  correlation logic.
- `pd2bot/offsets.py` / a new `pd2bot/labels.py` **only if** something is
  found and worth naming.
- Captured output here as `t79-label-geometry.md`.

## Implementation notes

- Bound the search — BH.dll is large; scan its data sections, not the
  whole module, and cap it so the drill answers in seconds.
- Honest absence: "scanned X bytes across N sections, found no tracking
  rect table" is a real result. Do not overclaim a lone coincidental
  pair as success — that is the R144 failure in a new place.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Review gate

Present: found a label-rect table (with the tracking evidence) or a
bounded negative. P5's aim source depends on it.

## Agent reminders

Do not commit unless asked. Do not trust an un-correlated match. Do not
send input beyond the verified ALT toggle. Report a negative as
faithfully as a positive.

## Definition of done

The probe run; label geometry is either named with tracking evidence or
recorded as a bounded dead end; output captured here.
