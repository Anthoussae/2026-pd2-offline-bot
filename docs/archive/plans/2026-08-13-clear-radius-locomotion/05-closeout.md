# P5 â€” closeout

Size: sm. Dependencies: P4 passed its gate. Review gate: none.

## Scope

Documentation, ADR decision, re-pricing, cleanup. No behavior changes.

## Work

1. **performance-notes.md**
   (`docs/plans/2026-08-03-m6-countess/performance-notes.md`): add a
   dated section re-pricing Cold Plains with the P4 numbers â€” the
   before (454 s / 178 s idle / 6.0 st/s), the human benchmark
   (53 s / 16 s / 16.5), and the after. Name which fix bought what
   (A* budget vs berserk vs leg length), as measured by the locomotion
   report, not reasoned. Note the implications for the Countess 5â€“6
   minute budget (the descent's transitions and cellar clears inherit
   all three fixes).
2. **Architecture docs**:
   - `docs/architecture/navigation.md`: the node budget â€” what it is,
     the honest-no-route semantics, the 20.15 s measurement that
     forced it.
   - `docs/architecture/behavior.md`: the default posture knob and the
     R256 QA ruling (berserk default, skirmish shelved-but-defined).
   - `docs/architecture/run-log.md`: confirm `nav.plan` documented
     (P1 should have done it; verify).
3. **ADR decision** (plan frontmatter says `possible`): create
   `docs/adr/2026-08-<dd>-bounded-pathfinding.md` ONLY if the change
   meets the CLAUDE.md bar (a direction chosen among plausible
   alternatives with lasting consequences â€” the alternatives were
   connectivity caching and unbounded-with-timeout; the budget's
   false-negative semantics are a lasting behavioral contract, which
   argues FOR). The berserk default is config + an operator ruling
   already recorded in the instruction log â€” no ADR.
4. **Cleanup grep** over the changed files: TODOs, debug prints,
   commented-out code, scratch files (the astar probe lives in the
   session scratchpad, not the repo â€” verify nothing leaked), stale
   comments contradicted by the new behavior (e.g. any comment still
   claiming "back out after every strike" is the standing default â€”
   `services.py`'s patrol_step comment, necro.py's module docstring
   which opens with the skirmish doctrine: update it to name berserk
   as the default and the skirmish as the shelved alternative).
5. **notes.md**: final constants table (budget numbers, patrol_step,
   any P4 tunings) and the future-work list (connectivity caching;
   pipelined clicks/leg overlap if the duty cycle still lags the
   human; the remaining low-prio items ride the combat-logistics
   HANDOFF, not this plan).
6. **_DONE.md** is written by yona-implement at completion (outcome,
   validation, deviations, docs, ADR-or-why-not, follow-ups) â€” this
   file is the checklist for it.

## Explicitly NOT this phase

The combat-logistics P6 closeout (order_book_diag removal, scratch
runs, review P3s, the TEACH step covering all detours, archive, R242,
project-state refresh, merge to m6-countess) remains its own queued
work â€” this plan's closeout must not absorb it. The teach step there
MUST now also cover this detour (bounded search, postures/berserk,
the human-benchmark method); leave that pointer in notes.md.

## Validation

Full suite + ruff green; docs build is plain markdown (read your own
diffs); every doc claim cross-checked against the P4 record.

## Reminders

Do not commit unless asked (the operator has historically ordered
commit + /yona-review + /yona-push at cycle end â€” ask, don't assume).

## Definition of done

Docs updated and consistent with measured reality, ADR decided with
reasoning recorded either way, cleanup grep clean, notes.md closed out.

## Implementation Result

Status: done
Completed: 2026-08-14
Commit: 4e9be26 (docs; code landed 13d0c6b..bd0cde4)

- performance-notes.md re-priced (what-bought-what table + Countess
  implications); navigation.md documents the search budget;
  behavior.md documents the berserk default + seam gate; run-log.md
  already carried nav.plan (P1); necro.py module docstring rewritten
  (berserk is the standing default, skirmish preserved and selectable).
- ADR CREATED: docs/adr/2026-08-14-bounded-pathfinding.md (accepted) â€”
  the budget-exhausted-is-honest-no-route contract met the bar; the
  berserk default is config + an operator ruling in the instruction
  log, no ADR.
- Cleanup grep clean (one hit = an accurate knob comment). The teach
  step is deliberately deferred to the combat-logistics P6 closeout,
  which MUST cover this detour too (bounded search, postures/berserk,
  the human-benchmark method, the walk-in mechanism).

