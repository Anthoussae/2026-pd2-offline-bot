# P6 — M6 closeout

Part of [plan.md](plan.md) (M6). Size: `sm`. Dependencies: P5 complete
(Stage D 3/3). The final phase: docs, ADR decision, teach, sweep,
logs, archive. Mirrors the M5 closeout item list, which worked.

## Work items

1. **ADR decision**: write the exit-perception ADR if the P2/P5
   experience shows the choice had genuine alternatives worth
   recording (memory-read RoomTiles vs the calibration survey — if
   the fallback was never needed, a short ADR extending
   `2026-07-28-hybrid-map-knowledge.md` or an amendment to it;
   `possible`, not forced). Posture presets need no ADR (config
   mechanism over existing knobs) unless implementation set a
   precedent worth recording.
2. **`behavior.md`**: postures section final (three presets, per-step
   selection, the boundary that survival never changed); parking,
   revive urgency, the Countess endgame; future notes updated
   (doors-as-interactive-objects bundle — chests, barrels, teleporter
   gates; aggressive/brisk tuning follow-ups; speed tuning if the
   5–6 min target was missed).
3. **`perception.md`** (exits, boss identity — final form),
   **`navigation.md`** (cross-area traversal section final),
   **`game-cycle.md`** only if the cycle was touched (not expected).
4. **README**: the countess run (how to run it, the new waypoint
   destinations, posture knobs). **CLAUDE.md**: M6 done-line in the
   M1–M5 style; next-milestone pointer per the roadmap's state.
5. **Roadmap** (`docs/plans/2026-07-28-bot-from-scratch/plan.md`): M6
   row → done + archive link. Consider the M7 row (manual,
   architecture docs, cleanup) — likely the next pass.
6. **Teach step** (`/teach`): explainer for the cycle's concepts
   (likely: reading linked structures for world topology, presets
   over knobs / policy vs mechanism, encoding human tactics, time
   budgets as instrumentation); glossary updates.
7. **Cleanup sweep**: TODOs, debug prints (house-style operator
   output exempt), commented-out code, scratch files, suppressed
   warnings, disabled tests, stale docs, scope creep; config/runs
   comments + calibration provenance dates present; the four P3
   review issues verified closed in their review summaries.
8. **Instruction log**: all M6 requests resolved with outcomes;
   reduction-analysis observations (did the standing-mandate pattern
   hold? what clustered?).
9. **Archive**: move this dir to
   `docs/archive/plans/2026-08-03-m6-countess/`; `_DONE.md` per the
   convention (outcome, validation incl. the stage record and timing
   table, deviations, docs, ADRs, follow-ups — next-milestone inputs:
   speed tuning if needed, the interactive-objects bundle, other
   runs/classes per the roadmap's future goals).
10. **project-state.md**: next milestone, counters checked against
    `docs/request-index.md` and `docs/drill-log.md` (the M5 T-counter
    slip is the cautionary tale).

## Agent reminders

Do not commit unless asked — offer the milestone commit as a 🔶
decision (M4/M5 precedent). Text transforms via Python (R44). Report
faithfully.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

All ten items done; tests + ruff green; plan archived with `_DONE.md`;
project-state current; the milestone commit offered.
