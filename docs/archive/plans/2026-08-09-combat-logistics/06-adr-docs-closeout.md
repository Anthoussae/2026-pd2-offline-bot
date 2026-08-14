# P6 — ADRs, docs, teach, closeout

Size: sm. Dependencies: P1–P5. Review gate: none.

## Scope

1. **ADR `2026-08-09-posture-fight-styles.md`** (accepted): postures
   may name a fight STYLE from a bounded enum the class module
   implements; skills stay excluded; alternatives rejected (strategy
   plugins; per-run choreography knobs). Cites the R241 decision and
   updates the combat.py comment's citation.
2. **ADR `2026-08-09-vendor-buying.md`** (accepted): supersedes R48's
   buy half — the bot may BUY from vendors (restock chore); selling
   remains excluded; the Q4 stock-read-per-visit principle recorded.
   Cross-reference from game-cycle/behavior docs where R48 is cited.
3. Docs: behavior.md (styles, orders, restock in the preamble),
   run-log.md (new event kinds), README's operator-tunables section
   (new config keys), pd2bot/README.md + behavior/README.md one-liners
   if new files landed (routeline.py, orders.py), drill-log entries
   for T84/T85 and the acceptance runs.
4. Teach step (`/teach`): explainer on the cycle's concepts (likely:
   priority queues and lifecycle state machines; calibration vs
   perception split in the shop grid; the leash) + glossary.
5. Cleanup grep (TODO/debug prints/disabled tests/stale docs), full
   suite + ruff, all commands spot-check, CI green.
6. Merge `combat-logistics` → `m6-countess` after the live batch is
   green and the P5 census gate passed; archive the plan dir with
   `_DONE.md`; resolve the standing-mandate request in the logs.

## Reminders

_DONE.md records deviations honestly, including any live findings that
changed the design mid-flight (expected for P4's shop geometry). Do
not rename phase files.
