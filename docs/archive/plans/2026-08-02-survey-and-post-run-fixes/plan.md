---
kind: plan
size: md
depth: implementation
status: done
completed: 2026-08-02
repo: 2026-pd2-offline-bot
created: 2026-08-02
adr: none
---

# Survey system + post-run fixes (M5 P6, R175/R176)

## Size and why

`md`: four phases, each `sm`-executable, but they touch three layers
(behavior steps, the reflex ladder, a new module + wiring) and two carry
user-approved numbers that must not drift. One agent can run P1→P4
end-to-end.

## Goal

1. Kill the R173 cleanse loop: junk dropped by the field cleanse must
   never be scooped straight back, and a failed pickup must never be
   re-armed into a retry that cannot differ.
2. Stop standing in fire: a reposition reflex fires on sustained damage
   while stationary (thresholds user-approved, R176 Q3).
3. Automated surveys: a `survey` run step drives frontier exploration
   until an area's reachable ground is fully recorded in the atlas, with
   run files for Cold Plains and the Rogue Encampment. Storage is the
   existing seed-keyed `maps/` store — unchanged.

## Acceptance criteria

- All existing tests pass; new tests cover each fix and the survey step
  against the sim (752+ tests, ruff clean).
- The cleanse-loop shape (full inventory + wanted item + junk to drop)
  terminates in the sim: drops happen away from wanted items, the bot
  steps off the pile, and a second failure of the same item is final for
  the game.
- The reposition rung fires in a scripted "chip damage while still"
  scenario and never outranks rejuv/warp/heal/mana.
- A sim survey of a bounded fake area reaches frontier exhaustion and
  reports coverage; unreachable frontier is written off, not looped on.
- Live: survey runs for Rogue Encampment and Cold Plains complete and
  the atlas files grow (verified by room counts) — via `live-run.ps1`,
  user present (R-request at that point).

## Scope / out of scope

- In: `behavior/steps.py`, `behavior/reflex.py`, new `pd2bot/survey.py`,
  `wiring.py`, `config/necro.toml` ([reflex] keys), `runs/survey-*.toml`,
  tests, `docs/architecture/navigation.md`.
- Out: mapstore format changes (none needed), difficulty-from-memory
  (M4 leftover), auto-survey mid-normal-run (rejected, R176 Q2 — loud
  report instead), cross-area room-bleed cleanup (noted in notes.md),
  atlas visualizer (future work).

## Decisions (user-approved)

- R176 Q1: survey engages hostiles only within ~30 subtiles.
- R176 Q2: no auto-survey mid-run; unknown-ground give-ups are reported
  loudly with a recommendation. Manual surveys remain valid.
- R176 Q3: reposition thresholds — ≥2% max HP lost within 2.5 s AND
  <3 subtiles moved in that window → step 10 subtiles away; 2 s
  cooldown; below rungs 3-6.
- R176 Q4: surveys are normal engine runs (all safety nets in force).

## ADR

`none` — every choice extends existing patterns (atlas ADR covers the
map-knowledge architecture; the survey is its planned "one survey walk
per area" made self-driving).

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Live validation via `tools/live-run.ps1` (bridge), user present.

## Phases

| Phase | Size | Summary | Review gate |
|---|---|---|---|
| P1 | sm | Cleanse drop hygiene + no doomed re-arm | none |
| P2 | sm | Reposition reflex rung | none (numbers fixed by R176 Q3) |
| P3 | md | survey.py + SurveyStep + wiring + run files | none (design fixed by R176) |
| P4 | sm | Docs, cleanup, full validation | end: report before live runs |

Discovery details: [notes.md](notes.md). Implementation log convention:
`_DONE.md` (written by yona-implement, not before).
