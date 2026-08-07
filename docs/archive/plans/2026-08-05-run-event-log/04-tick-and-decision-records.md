# P4 — Tick and decision records

Part of [plan.md](plan.md). Size: `sm`. Dependencies: P1, P2, P3.
Review gate: none.

## Scope

The phase that closes the actual T71 hole: what the bot decided on every
tick, and where the time went.

Out of scope: fixing whatever this reveals (P5), layer events (P6),
perception events (P7).

## Why this is the critical phase

T71's Forgotten Tower: ~150 ticks, 5 recorded decisions, and — with the
room now known to be empty — an arithmetic gap nothing can explain.
`TraverseStep` should have fallen through to the click branch every tick
and clicked every 3 s (~48 clicks). It clicked 5 times, one per ~29 s.
Two numbers are missing and both belong here:

1. **What each tick decided** — the engine only logs a tick whose
   outcome carries a `note`, so every silent path vanished.
2. **Where each tick's time went** — 193 ticks over 203 s is ~1.05 s per
   tick against a configured 0.2 s interval, so ~0.85 s of work per tick
   is unaccounted. Candidates: `Perception.snapshot()`,
   `read_carried_items` (this character carries hundreds of items, and
   the M6 P4 traverse-collect calls `carried()` every tick),
   `read_level_exits`, the executor's `maintain`.

## Implementation

1. **`tick` events** from `BehaviorEngine.tick()` — one per tick:

   ```json
   {"kind": "tick", "n": 412, "dur_s": 1.04, "step": "traverse",
    "step_index": 3, "outcome": "waiting", "note": "...",
    "player": {...describe...}, "hp": 1737, "mana": 402,
    "hostiles_in_perception": 0, "ground_items": 0,
    "timing": {"snapshot": 0.62, "ladder": 0.03, "step": 0.31, "maintain": 0.08}}
   ```

   The `timing` split is the measurement that answers "where did 0.85 s
   go". Measure with the injected clock, so the sim's fake clock does not
   produce nonsense.

   `hostiles_in_perception` and `ground_items` are counts, not lists —
   cheap, and they settle "was there anything to fight?" without a
   reader having to infer it. In the Tower this would have read `0`
   every tick and killed both dead hypotheses on sight.

2. **`step.decision` events** — every step, every tick, not just the ones
   with notes. Generalize the T71 traverse wrapper: the engine records
   the step's returned `StepOutcome` (done / acted / waiting / note)
   plus whatever the step chose to attach. Consecutive identical
   decisions collapse in the *renderer*, not in the writer — the file
   keeps every tick, so counts stay exact.

   Give every currently-silent return path in every step a note. The
   traverse step's paths were named during the T71 investigation; do the
   same sweep for `clear_radius`, `pickup`, `survey`, `clear_countess`.

3. **`refusal` events** — `InputRefused` / `CastInFlight` /
   `SkillSwitchFailed` / `NavigationError` caught by the engine or by
   `_PickupMixin.send`, with the action that was refused and why. Today
   these reach `EngineReport.log` as prose or are swallowed silently by
   `send`.

4. **`reflex` events** — which rung fired and its inputs. The ladder
   already names its rungs for `EngineReport.reflex_fires`.

5. **`run.start` / `run.end`** — the run file, its step list, and the
   ending (completed / chickened / idle-bailed / aborted / raised, with
   the exception message).

## What to be careful about

**Volume.** ~200 ticks per run × a handful of events is small (tens of
KB) — acceptable, and the user asked to keep everything. But the timing
instrumentation must not itself distort the measurement: use one clock
read per boundary, not a profiler.

**The renderer must stay readable** at this volume — collapse
consecutive identical decisions with a count and a span, excluding
volatile fields from the collapse key (the mistake found while demoing
the T71 trace: an elapsed-seconds value in the label defeated collapsing
entirely).

## Testing

- A scripted engine run emits one `tick` per tick with a timing split
  that sums to roughly the tick duration.
- Every step kind emits a `step.decision` on a tick where it returns
  silently today.
- A refused send emits a `refusal` with the action and reason.
- The renderer collapses 40 identical decisions into one line with the
  count and span.
- The sim's tick count equals the `tick` event count.

## Style and conventions

- Timing uses the injected clock throughout (the sim's clock is fake and
  advances only when the sim says so).
- No behavior change: this phase observes only.

## Docs

Running schema list; `docs/architecture/behavior.md` gains a paragraph
on the tick record.

## ADR expectation

**None** — covered by P1's ADR.

## Agent reminders

- Do not commit unless asked.
- Do not change any decision the engine or steps make; only record them.
- Do not suppress warnings or disable tests.
- Stop and report if adding timing measurably slows a tick.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus: run the sim and read the rendered log end to end. If a human
cannot follow what the bot did from that output alone, this phase is not
done.

## Definition of done

Every tick, every step decision, every refusal and every reflex fire is
recorded with timing; the renderer stays readable at full volume; the
sim's counts agree with the log's; suite green and ruff clean.
