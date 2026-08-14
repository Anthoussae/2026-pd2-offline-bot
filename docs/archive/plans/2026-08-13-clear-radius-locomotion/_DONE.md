---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-14
commit: pending
adrs:
  - docs/adr/2026-08-14-bounded-pathfinding.md
---

# The clear_radius locomotion speed pass — done

## Outcome

**Accepted and closed by the operator** ("Looked pretty good"; "accept
and close"), 2026-08-14 ~01:00. Cold Plains went from the 454 s
baseline to **~150–180 s typical** (best 149 s), with every named
stall family eliminated and the residual precisely characterized. Two
of the three R256 QB targets met at typical rolls (CP < 180 s; zero
ticks > 4 s — solved outright in every run since P2); the idle < 45 s
target closed at 48–95 s and was accepted-as-revised with the
remainder queued as future work.

## Completed work

- **P1** — `nav.plan` plan-cost telemetry (navigator + route_service,
  per-run runlog repoint) and the locomotion report
  (`pd2bot/runlog/locomotion.py`): duty cycle, gross-vs-net route,
  attributed idle spans, slow ticks with their inner nav events.
- **P2** — bounded A* (`default_node_budget`: floor 2 000 / cap 25 000,
  distance-scaled; exhaustion = the standing no-route None). The
  replayed 20.15 s flood answers in 0.057 s. The never-caught
  `SearchLimitExceeded` raise removed. ADR accepted.
- **P3** — `default_posture = "berserk"` (R256 QA operator ruling,
  applied at module construction, per-step overrides intact);
  `patrol_step` 12 → 20; `describe()` prints the standing posture.
- **P4** — eleven live launches with four operator-approved structural
  fixes shipped mid-battery: **walk-in attacks** (R259 — charge
  attacks at range via the client's own unit-aware pathing;
  `AttackUnit.walk_in`), the **seam gate** (R260 — no engagement
  across the area border, module + step), the **stall-family bucket +
  shake-first** (R261), and the **chase gate + ring give-up at 2**
  (R262). Two changes falsified by measurement and reverted the same
  hour: dash_step 16, and the 1 s walk budget (broke town NPC
  approaches; the constant now carries a do-not-lower warning).
- **P5** — performance-notes re-priced with a what-bought-what table;
  navigation.md, behavior.md, run-log.md and the necro module
  docstring updated; ADR written; cleanup grep clean.

## Validation

Full suite grew 1299 → **1345 tests, all green**, ruff clean at every
commit. Live: eleven launches, monitor silent throughout, hp never
below 1009/1335, pickup census across the battery **5/5 whitelisted
collected, 0 junk**. Every claim in the docs traces to a named run log
under `logs/runs/` and the battery tables in notes.md.

## Deviations from the plan

- The battery became eleven launches instead of three: each fix
  revealed the next family (the plan's stop-and-report rule was
  followed at every structural turn, with operator approval before
  each change).
- Formal three-consecutive-pass acceptance was not achieved (149 s and
  178 s passes, then a 246 s roll whose extra 78 s was the by-design
  sighting re-walk); the operator accepted at revised terms instead.
- BUDGET_CAP 50k → 25k and the two same-night reverts, all recorded
  in the phase files and constants.

## Documentation

navigation.md (search budget), behavior.md (berserk default + seam
gate), run-log.md (`nav.plan`), performance-notes.md (re-price),
necro.py docstring, config comments carrying the rulings verbatim.

## ADRs

`docs/adr/2026-08-14-bounded-pathfinding.md` (accepted). The berserk
default is config plus an operator ruling recorded in the instruction
log — deliberately not an ADR.

## Follow-ups outside this scope

- The intermittent town stash-open failure (two run kills 2026-08-14)
  — spun off as its own task at battery time.
- The diffuse ~2 s click-vs-unit-collision blocks (~30-40/run, the
  remaining idle) — the "continuous movement" redesign idea, plus
  connectivity caching if the A* budget ever proves blunt (future work
  in notes.md).
- Town preamble slow ticks (13–37 s observed).
- The TEACH step for this cycle rides the combat-logistics P6 closeout
  and MUST cover: the human-benchmark method (T92), bounded search,
  berserk/postures, and the walk-in mechanism.
- The standing queue behind this plan: R246 census ruling, then the
  combat-logistics P6 closeout and merge.
