---
kind: implementation-log
status: in-progress
repo: 2026-pd2-offline-bot
plan: plan.md
completed: (roadmap in progress — M1 only)
commit: pending
adrs:
  - docs/adr/2026-07-28-python-out-of-process-perception.md
---

# Implementation log — PD2 bot from scratch

This is a roadmap plan (M1–M7); the log accumulates per milestone. The
plan directory stays in `docs/plans/` until the roadmap completes.

## M1 — Perception + input spike (2026-07-28) — done, passed

### Outcome

**Spike passes at T3 (all tiers).** Plan B's two pillars are proven
against the live Season 13 client: out-of-process memory reading returns
correct live state and tracks it in real time, and OS-level synthetic
input moves the character.

### Completed work

- Python environment: pymem 1.14.0 in `spike/.venv38` (Python 3.8.2;
  3.12.10 installed for M2+).
- Offsets derived from Project-Diablo-2/BH @ main and **verified live**,
  each cited to its BH source line in `spike-log.md`.
- `spike/m1_spike.py` — consolidated spike tool (`read`, `click X Y`)
  with foreground + in-game guards; `spike/probe_*.py` — the raw
  step-by-step probes, kept as the record.
- ADR written: `docs/adr/2026-07-28-python-out-of-process-perception.md`.

### Validation commands and results

Empirical, against the live client (all elevated):

- `probe_attach.py` → attached pid 24996, 115 modules;
  `ProjectDiablo.dll` / `PD2_EXT.dll` / `BH.dll` confirm the real PD2
  client; `D2CLIENT.dll` @ 0x6FAB0000.
- `probe_state.py` → `name='MaqiuDoubing' lvl=91 act=1 pos=(12622,5095)`.
- `probe_stats.py` → base vs full stat arrays dumped; full array gives
  coherent `hp=961/1141 mana=378/378`.
- `probe_click.py 250 550` → `(5866,5742) → (5862,5757) moved=YES`,
  intermediate positions sampled at 10 Hz.

### Deviations from the plan

1. Used pre-existing Python 3.8.2 instead of waiting for the 3.12
   install (the phase file asked for 3.11+; the spike did not need it).
2. 32-bit Python fallback anticipated by the phase file was **not**
   needed — 64-bit Python reads the 32-bit client fine.
3. An early test click hit "Save and Exit Game" (ESC menu was open).
   No data lost; became the milestone's key finding.
4. First max-HP read was semantically wrong (base vs full stat array);
   caught by the user, corrected, both arrays documented.

### Documentation updated

- `spike-log.md` (full record), phase file `Implementation Result`,
  `.gitignore` (Python artifacts), ADR as above. The Administrator
  requirement and the setup steps are captured in the spike log and are
  **inputs to the M7 manual**; no `docs/manual/` exists yet by design.

### ADRs created

`docs/adr/2026-07-28-python-out-of-process-perception.md` — Python +
out-of-process memory reading + synthetic input, with the rejected
alternatives (pixels, injection, C#/Go) and the consequences
(Administrator requirement, seasonal offset maintenance, input danger).

### Follow-up work outside M1's scope

- **M2 (blocking for input work):** find a readable UI-state indicator
  (BH `Constants.h:65-89` defines the enum; `GetUiVar_I` is a function,
  so the underlying array or another readable signal must be located).
- **M2:** full game-state model — monsters, ground items, map seed,
  area, menu/in-game detection; semantic cross-checks against the game's
  own display.
- **M3:** input layer must refuse to act unless window-foreground **and**
  `UI_GAME` **and** player unit non-NULL.
- **M7:** manual must document the Administrator requirement.
