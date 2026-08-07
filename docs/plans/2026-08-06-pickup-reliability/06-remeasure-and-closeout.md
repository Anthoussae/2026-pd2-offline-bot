# P5 — Re-measure, document, close out

Part of [plan.md](plan.md). Size: `sm`. **Needs game time** (one full
run). Depends on P3 and P4. Review gate: none — the number is the
verdict.

## Scope

### 1. The re-measurement

One full Countess run (`runs/countess.toml`, chicken 35), then:

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog --pickup
```

Compare against `baseline-t71-run4.txt` (18/31, 58%). Capture the
output here as `remeasured.txt` with the run's log directory named.

**Report the number honestly whatever it is.** A fix that moved 58% to
70% is a partial fix and should be written down as one, not rounded up
into success. If misses remain, each one must be explained by the log —
that was P1's whole purpose.

The same run doubles as evidence for the M6 P5 battery (its Stage B
shape) and for whether the descent's pickup time changed, though speed
is not this plan's acceptance criterion.

### 2. Documentation

- `docs/architecture/behavior.md` — the pickup section: how an aim
  point is chosen now, what each write-off reason means, what the
  closed loop verifies. This is the section a future agent reads before
  touching pickup, so it must carry the *why*, including the measured
  facts that closed the pointer path.
- `docs/architecture/run-log.md` — final event table.
- `docs/architecture/perception.md` — only if P3 took Direction A.
- ADR if P3 took Direction A (label geometry as a memory read).

### 3. Teach step

Per CLAUDE.md, the teach step is part of done. Write
`docs/learning/<date>-pickup-reliability.md` and update the glossary.
Candidate concepts: open-loop vs closed-loop control; why a bimodal
failure distribution means "systematic" rather than "flaky";
attribution (knowing *which* thing your action affected); and the
difference between reading a structure the program maintains and
scraping what it drew.

### 4. Cleanup sweep

Grep for TODOs, debug prints (house-style operator output exempt),
commented-out code, scratch files, suppressed warnings, disabled tests,
stale docs, scope creep. Check specifically:

- the throwaway correlation scripts from 2026-08-06 are not in the repo
- `units.hovered_item_id` — now provably uncalled by production. Either
  document it as a measured dead end **at the function**, or remove it.
  Do not leave it looking like a live capability; that is how the next
  agent re-derives T58–T61.
- `_PICKUP_OFFSETS`'s comment still describes reality after P3.

### 5. Logs and state

Drill-log rows for every run; instruction-log outcomes filled;
`docs/project-state.md` updated (counters checked against
`request-index.md` and `drill-log.md` — the M5 T-counter slip is the
cautionary tale); this plan archived to
`docs/archive/plans/2026-08-06-pickup-reliability/` with `_DONE.md`.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Agent reminders

Do not commit unless asked — offer the closing commit as a decision.
Report the measured number faithfully, including a partial result.
Do not quietly re-scope the acceptance criterion to match what was
achieved.

## Definition of done

The run measured and compared against the baseline; remaining misses
each explained by the log; docs, ADR (if warranted), teach step and
glossary done; cleanup swept; logs and project-state current; the plan
archived with `_DONE.md`.
