# P4 — Docs, cleanup, validation

Size: sm. Dependencies: P1-P3.

## Work

1. Docs: the belt contract (type-based, minimums, halt semantics) in
   the architecture docs where the old layout was described; the
   narrative log's location + coarseness contract; a line in
   perception.md that ALT item-name visibility cannot affect the bot
   (R179-1a, asked and answered).
2. `.gitignore`: `logs/`.
3. Cleanup sweep: TODOs, debug prints, disabled tests, scratch files.
4. Full validation (below), then the end-of-phase STOP: report to the
   user; live validation is one run of anything (narrative log) plus a
   deliberately mixed belt (P1) and a merc chip-damage moment (P2),
   which the normal run cadence will supply.

## Review gate

End-of-phase stop before any live run.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: docs updated, sweep clean, suite green, report delivered.

## Implementation Result

Status: done
Completed: 2026-08-02
Commit: 26857c1

- Docs: belt contract + merc rung + narrative channel + route service
  recorded as an Amendments section in
  docs/adr/2026-07-29-behavior-architecture.md (where the superseded R53
  layout-as-requirement was written down); route service section added
  to docs/architecture/navigation.md; ALT-cannot-affect-the-bot note
  (R179-1a) added to docs/architecture/perception.md.
- .gitignore: logs/ added (done in P3, with the feature).
- Cleanup sweep: no TODOs, debug prints, disabled/skipped tests, or
  scratch files in the diff; no stray logs/ dir from the test suite.
- Teach step: docs/learning/2026-08-02-honest-halts-and-logs-for-humans.md
  + 5 glossary entries (alert fatigue, cache/cache key, closure,
  failure semantics, log level).
- Validation: full suite 823 passed, ruff clean.
- End-of-phase STOP: report delivered as R182; live validation rides
  the next runs (any run proves the narrative log; a deliberately mixed
  belt proves P1; a merc chip-damage moment proves P2; the next patrol
  proves P5).
