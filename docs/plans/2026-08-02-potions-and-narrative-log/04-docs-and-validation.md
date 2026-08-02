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
