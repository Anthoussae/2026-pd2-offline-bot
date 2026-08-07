# P2 — Track 1: close the click loop, fix the pacing

Part of [plan.md](plan.md). Size: `sm`. Depends on P1 (the seam). One
live run to validate. Review gate: none.

The safe floor: make the click actuator as good as a click can be. It
will not be frame-perfect — T76 proved a dense pile defeats any offset —
but it banks real reliability at zero architectural risk, and it is P4's
permanent fallback.

## Changes, each independently measurable

### 1. Tight confirm poll (the biggest speed win)

Today a click's success is noticed on a *later engine tick* (0.25–0.8 s)
and the next attempt waits `pickup_retry_s = 1.5 s`. kolbot polls the
item's own mode at 10–40 ms for up to 1 s. Replace the fixed 1.5 s pace
with: after a click, poll perception for the target leaving the ground
at ~50 ms for a measured window (T76 saw sub-0.9 s confirms — measure
the real distribution first, do not guess). Attempt N+1 starts the
moment N provably failed, not 1.5 s later.

**Measure before setting the window.** The eager version of "retry
sooner" is T70's staircase bug; the guard is the same as there — a
re-click is only earned once the prior click has provably not landed.

### 2. Draw-order collection for piles

Collect the **topmost sprite first** (screen depth = `wx + wy`
descending) so lifting it uncovers the next. Today the sort is
world-distance-to-player, unrelated to what occludes what — which is why
T76's pile clicks kept hitting the neighbour drawn on top. This is the
single most likely fix for the 7/8 pile failure, and it is free.

### 3. Reposition on repeated miss

After a small number of failed offsets from one spot, **step 2–3
subtiles and re-project** rather than spending the whole budget in place.
T76: the same offsets from the same standoff simply fail again; a
changed projection is a genuinely different attempt (this codebase's own
"a retry must differ" rule).

### 4. Reorder the schedule from the data

T76 winners: `(0,-40)` and `(-16,-40)` outperformed the current leader
`(0,-28)`. Reorder best-measured-first, and consider per-class tails
(the label band `(0,-48)` for runes/gems/charms, which T65/T76 show are
label-clicked). Keep the write-off firing when the schedule is spent.

## Files

- `pd2bot/acquire.py` — `ClickActuator` gains the poll, the ordering
  hook, the reposition step.
- `pd2bot/behavior/steps.py` — collection order feeds the actuator.
- `pd2bot/behavior/execute.py` — `PICKUP_AIM_POINTS` reorder.
- `tests/` — the poll window, draw-order sort, reposition trigger.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: **re-run T76** (the calibration is the natural regression check —
same staged piles, the failures should shrink) and report the new
per-item latency. Include charms this time (T76's gap).

## Agent reminders

Do not commit unless asked. Measure the confirm window before setting
it. Do not touch the belt/inventory diagnosis. A reordered schedule
must not silently change the budget length invariant (a write-off still
means every aim point was tried).

## Definition of done

The four changes in, tested; T76 re-run shows fewer pile failures;
per-item latency reported against the 1.5 s-per-attempt baseline.
