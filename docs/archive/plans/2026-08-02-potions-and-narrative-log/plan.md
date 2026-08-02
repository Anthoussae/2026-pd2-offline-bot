---
kind: plan
size: md
depth: implementation
status: done
repo: 2026-pd2-offline-bot
created: 2026-08-02
completed: 2026-08-02
commit: 26857c1
adr: none
---

# Potion overhaul + narrative log (M5 P6, R179)

## Size and why

`md`: three feature phases plus validation, spanning the reflex ladder,
the town layer's refill, a new input primitive, and a logging channel
threaded through several layers. Each phase is `sm` on its own.

## Goal and acceptance

1. **Type-based belt** — the belt's contract becomes the user's rule:
   full when possible, >=1 column-equivalent each of healing/mana/rejuv
   when stock allows, column order irrelevant, emptiness never a crash
   and never a needless halt. The R178 mixed-belt halt shape (mana
   potion in a healing column) refills around the misplacement and
   proceeds.
2. **Merc first aid** — merc hp < 50% and a healing potion in the belt
   → Alt+NUM chord delivers it; paced; never outranks the player's own
   survival rungs.
3. **Narrative log** — a per-run, wall-clock-stamped, human-readable
   file of broad actions where every wait explains itself. The user can
   answer "what was it doing while it dawdled at Akara?" by reading it.

Acceptance: unit/sim tests for each; full suite + ruff clean; live
validation rides the next runs (the narrative log needs only one run of
any kind to prove itself; the belt logic gets a deliberately mixed belt
as its live test).

## Scope / out of scope

- In: `behavior/reflex.py`, `town.py` (fill_belt + halt condition),
  `input.py` (Alt-chord), `behavior/steps.py` + `wiring.py` (narrate
  plumbing), `config/necro.toml` (merc threshold), tests, docs.
- Out: vendor purchasing (user: not wanted); ALT label toggling
  (deferred, evidence-gated on the run-3 audit); belt column
  re-sorting (reading around misplacement suffices — moving potions
  between columns is input-heavy for zero functional gain).

## Phases

| Phase | Size | Summary | Review gate |
|---|---|---|---|
| P1 | sm | Type-based belt: drink-any-column, refill by type minimums, halt only on real failure | none |
| P2 | sm | Merc first aid: Alt+NUM chord + rung at 50% | none |
| P3 | sm | The narrative log channel + per-run file | none |
| P5 | sm-md | Route-aware legs: steps walk A*'s waypoints, no-path targets fail fast (R181) | none |
| P4 | sm | Docs, cleanup, validation, live-gate report | end-of-phase stop |

Phase files: 01-type-based-belt.md, 02-merc-first-aid.md,
03-narrative-log.md, 05-route-aware-legs.md (R181 addition; runs
before the closing 04), 04-docs-and-validation.md. Discovery record:
[notes.md](notes.md). ADR: none — extensions of existing patterns.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```
