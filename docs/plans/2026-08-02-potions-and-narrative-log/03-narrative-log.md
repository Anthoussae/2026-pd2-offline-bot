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
