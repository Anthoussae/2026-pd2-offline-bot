# P4 — Docs, cleanup, validation

Size: sm. Dependencies: P1-P3 complete.

## Work

1. `docs/architecture/navigation.md`: a Survey section — what the
   automated survey does, that `--survey` (manual) remains, the
   frontier/coverage model, and the R176 Q2 rule (no auto-survey
   mid-run; loud unknown-ground reporting instead).
2. Cleanup sweep: grep for TODO/FIXME/debug prints/commented-out code
   introduced by P1-P3; check no test was disabled, no warning
   suppressed beyond the file's existing conventions; scratch files
   removed.
3. Full validation: pytest + ruff (commands below).
4. Report to the user (review gate): summary of P1-P3, then the live
   acceptance runs as R-requests — survey-town first (safe), then
   survey-cold-plains, then a fresh patrol run to confirm the cleanse
   fix live. The user must be at the machine (input protocol).

## Review gate

End-of-phase STOP: present the report; live runs only on user go.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: docs updated, sweep clean, suite green, report delivered.
