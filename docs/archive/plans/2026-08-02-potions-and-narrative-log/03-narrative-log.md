# P3 — The narrative log: broad actions, wall-clock stamps, waits that explain themselves

Size: sm (wide but mechanical). Dependencies: none.

## The ask (user, R179)

A human-readable per-run log of the BROAD actions, timestamped, where
apparent idleness is visible and explicable — "bot runs up to an NPC,
then dawdles for several seconds; I'm curious what it's doing." The
existing micro-log is not it and stays as-is.

## Design

- `pd2bot/narrate.py`: a tiny `Narrator` — `narrate(text)` writes
  `HH:MM:SS  text` to `logs/run-<YYYYMMDD-HHMMSS>.log` (dir gitignored,
  created on first line) AND stdout (prefixed `»` so it stands apart
  from the micro-log). A `span(label)` context helper stamps
  completion lines with duration: `heal: verified after 3.8s (vitals
  read full)` — one call site per wait, the duration computed for it.
- **Coarseness contract, stated in the module docstring**: one line
  per meaningful act (step transitions, each preamble station with
  duration + what was verified, waypoint travel, fight summaries on
  ENGAGE/DISENGAGE not per swing, pickups, cleanse, write-offs,
  chicken/leave/game summary). If a line could fire more than ~once a
  second it belongs in the micro-log. The narrative log's value IS its
  sparseness.
- Plumbing: a `narrate` callable on RunServices and TownLayer (same
  pattern as `log`/`alert`; default no-op so tests and drills are
  unaffected); wiring constructs one Narrator per run and hands it to
  both. The engine narrates step transitions; the town layer narrates
  each station's completion WITH its duration and verification reason —
  that is the "dawdle" answer.

## Tests

- Narrator: format, file creation, span durations (fake clock).
- One sim assertion: a full sim run produces a narrative whose line
  count is O(actions), not O(ticks) — the coarseness contract held.

## Reminders

Do not commit unless asked · resist promoting micro-lines wholesale —
each narrate call is an editorial decision · stop if blocked · report.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .
```

Done when: a sim run reads as a story; suite green; ruff clean.

## Implementation Result

Status: done
Completed: 2026-08-02
Commit: 26857c1

- Changed: new `pd2bot/narrate.py` (Narrator: per-run
  `logs/run-<stamp>.log`, lazy file creation, wall-clock stamps, `span`
  helper, stdout echo prefixed `>>`; coarseness contract in the module
  docstring), `behavior/steps.py` (RunServices.narrate default no-op +
  editorial call sites: pickup decisions, clearance write-offs, cleanse
  drops, patrol give-ups), `behavior/engine.py` (narrate param; run
  header on first tick, one line per step completion with duration, run
  summary), `town.py` (narrate param; run_preamble narrates one line per
  station — its report lines plus duration; failures narrate too),
  `wiring.py` (one Narrator per run in engine_factory; narrate_ref
  holder so the session-scoped TownLayer reaches the current run's
  narrator; BELT_ROWS now sourced from offsets), `.gitignore` (`logs/`),
  `tests/simworld.py` (narrate passthrough).
- Tests: test_narrate.py (naming, lazy creation, stamps, span duration +
  detail + failure); preamble narration (4 lines with durations,
  failure line); engine transition test (header + per-step + summary,
  never per tick); sim coarseness test (O(actions) vs O(ticks) ratio).
- Validated: full suite 811 passed, ruff clean.
- Deviations: fight ENGAGE/DISENGAGE lines are carried by the clearance
  step's completion note rather than a per-fight narrate call in the
  combat module — the module is deliberately service-blind, and the
  step-done line already summarizes the fight outcome. Revisit only if a
  live narrative reads too sparse in combat.
