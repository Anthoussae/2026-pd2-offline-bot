# P5 — Adopt the winner, re-measure, document

Part of [plan.md](plan.md). Size: `sm`. Depends on P2 (always) and P4's
go/no-go (which mechanism). One full run. Review gate: none — the number
is the verdict.

## Scope

### 1. Adopt

- **If P4 is GO**: `CommandActuator` becomes the Actuator's primary
  mechanism, `ClickActuator` (P2's improved click, aimed by P3's rects
  if found) the fallback — kolbot's exact shape. The write path
  graduates from spike-only to a normal, guarded capability. This part
  lands **on the isolated branch**, and merges to the stable line only
  once the run below proves it.
- **If P4 is NO-GO**: the branch is abandoned per the rewind contract;
  P2/P3's improved click *on the stable line* is the delivered answer.
  Nothing further to adopt.

### 2. Re-measure

One full Countess run (chicken 35), then:

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog --pickup
```

Compare against `2026-08-06-pickup-reliability/baseline-t71-run4.txt`
(18/31, 58%) and report **honestly** — a partial win is a partial win.
Report per-item latency too: the speed claim needs a number, not an
adjective.

### 3. ADR

Write the actuation ADR regardless of outcome — it extends and partially
reopens `2026-07-28-python-out-of-process-perception`. A GO records the
new write capability, its guard, and why the crash risk is acceptable
behind supervision-then-proof. A NO-GO records that command-by-GID was
attempted out-of-process and why it was not adopted — precisely the kind
of decision that is expensive to re-litigate without a written record.

### 4. Docs, teach, cleanup

- `behavior.md` / `perception.md`: the detection↔acquisition split, the
  Actuator, the chosen mechanism and its fallback.
- Teach (`docs/learning/`, per CLAUDE.md): candidate concepts —
  addressing a thing by identity vs by screen position; command vs
  synthetic input; the safety cost of a write capability; fallback
  layering. Glossary updated.
- Cleanup sweep: TODOs, debug prints, scratch drills, the throwaway
  analysis scripts; confirm the spike's write path is either graduated
  (GO) or gone (NO-GO), never left half-wired.

### 5. Logs and state

Drill-log rows; instruction-log outcomes; `project-state.md` and
counters (checked against `request-index.md` / `drill-log.md`); archive
this plan to `docs/archive/plans/2026-08-06-item-acquisition/` with
`_DONE.md`. Reconcile with `2026-08-06-pickup-reliability`: its P3/P4 are
superseded here; note that in its own dir.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus the re-measured run captured as `remeasured.txt`.

## Agent reminders

Do not commit unless asked — offer the closing/merge commit as a
decision. Report the measured number faithfully. Do not merge the
isolated branch to the stable line until the run proves the adopted
mechanism. Write the ADR even on a NO-GO.

## Definition of done

The winning mechanism adopted (or the branch cleanly abandoned); the run
measured vs baseline; ADR written; docs/teach/cleanup done; logs and
state current; plan archived with `_DONE.md`.
