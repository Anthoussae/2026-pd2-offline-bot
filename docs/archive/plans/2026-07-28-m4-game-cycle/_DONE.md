---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-07-29
commit: pending
adrs: []
---

# Implementation log — M4 game cycle

## Outcome

**Done, live-verified end to end.** The bot cycles games unattended:
it reads the menu screens from memory, clicks them through a second
separately-guarded input path, verifies every entered game as Hell
before proceeding, chickens out of games on vitals thresholds, and
halts permanently (no input, loud alert) on death. Acceptance: **3/3
unattended cycles** `[CVRL]` via the real CLI; chicken demonstrated
live at zero risk (mana threshold, in town, instructions delivered via
the new in-game chat channel); death latch simulation-proven per the
no-live-death decision. 193 tests pass; `ruff check` clean.

This was also the milestone that changed how live work happens: the
**elevated bridge** (`tools/elevated-bridge.ps1`, R31–R33) ended the
copy-paste round-trip era — the agent ran all 29 bridge commands
itself; user requests shrank to game-side actions only.

## Completed work

- **P1** `oog.py` + offsets: D2Win control-list perception (BH
  D2Ptrs.h:624, CommonStructs.h:567–585, d2bs cross-check), screen
  classification by kolbot-mined fingerprints, `read_difficulty` via
  GetDifficulty code-parse, dump CLI. Live: char select exact vs the
  community table; full transition walk with zero unknowns;
  difficulty=2 in a Hell game.
- **P2** `menuinput.py`: the complement guard (GatedInput: in-game+no
  panel; MenuInput: not-in-game OR ESC menu open), menu→screen
  projection, ESC. `input.py` guards untouched. Live: refusals both
  ways; first autonomous menu click.
- **P3** `cycle.py`: leave/create state machine (polling, timeouts,
  bounded re-clicks), the unconditional difficulty guard, error
  taxonomy (focus refocus-once-then-pause; UNKNOWN → stop with dump;
  NavigationError → next game; client gone → stop), CycleReport,
  CLI. Live: acceptance 3/3.
- **P4** `safety.py` + wiring: chicken (floor-trigger thresholds,
  town-suppressed by default), the death latch (alert once, halted
  forever, structurally no input after — cycle sends nothing, not
  even leave-game), CLI flags. Live: mana-chicken drill PASS; inert
  2/2 with monitor silent.
- **User-requested mid-milestone addition**: `chat.py` — the bot posts
  instructions into the in-game chat (console-verified before every
  character; unopened console = hotkey hazard). Live probe + used for
  the chicken drill.
- **P5** docs (`game-cycle.md` + pointers), README, CLAUDE.md, roadmap
  row, sweep (no TODOs, no disabled tests, prints are house-style
  operator output), teach explainer + glossary.

## What live verification caught that tests could not

Continuing the M1–M3 tally:

1. **Save-and-exit lands at the MAIN MENU** in offline SP — kolbot's
   char-select lore is multiplayer lore (user-spotted, R34).
2. **The menu projection is aspect-fit, not stretch**: first click
   missed 140 px right; the 1.44× pillarbox model explained both the
   miss and M3's mysterious config scale; hover calibration confirmed
   ±2 px (R35–R36).
3. **The in-game ESC menu is not in the D2Win control list** → Save
   and Exit is a hover-calibrated fraction of the client rect (R35,
   R37).
4. PS 5.1 `Start-Process` never yields exit codes (bridge development,
   R32–R33) — fixed in-band; and inline `python -c` through the bridge
   loses quotes → all bridge commands write temp scripts.

## Validation commands and results

- `& "$HOME\.venvs\pd2bot\Scripts\python.exe" -m pytest -q` → **193
  passed** (121 at M3 close; +72).
- `& "$HOME\.venvs\pd2bot\Scripts\python.exe" -m ruff check .` → clean.
- Live: bridge commands 001–029; outcomes in `docs/instruction-log.md`
  R30–R43.

## Deviations from the plan

1. Wrong-difficulty live test skipped (all risk, no information — the
   guard aborts before any callback and is unit-tested; its memory
   read verified live). R40 gate approved.
2. MenuInput's planned death-screen guard arm dropped: dead code under
   the death→full-stop policy.
3. `chat.py` added mid-P4 at user request (R41 detour) — the
   instruction channel the live tests then used.
4. The chicken demo drove GameCycle+SafetyMonitor from a script (so
   instructions could be chatted); the CLI wiring was exercised by the
   inert run.
5. The blind-coordinate fallback was never built — the control list
   proved fully stock under PD2 (pre-approved either way).

## Documentation updated

`docs/architecture/game-cycle.md` (new); pointers/updates in
`perception.md`, `navigation.md`; `README.md` (M4 tools section);
`CLAUDE.md` (M4 done-line, input-gate paragraph rewritten for three
guarded paths + the death invariant); roadmap M4 row; teach explainer
`docs/learning/2026-07-29-the-game-cycle.md` + 6 new / 1 improved
glossary entries; `docs/instruction-log.md` R30–R43.

## ADRs created

None. Rationale: the complement guard is incident-forced (M1) like the
original gate — architecture-doc material by the M3 precedent, not a
choice among live alternatives; OOG control-list reading extends the
already-ADR'd out-of-process perception approach; the fail-stop death
policy is a user scope decision recorded in the plan, notes, CLAUDE.md
and game-cycle.md. Nothing here sets a new architectural direction.

## Follow-up work outside this milestone

- **M5 planning inputs** (next `yona-plan` run): the survival toolkit
  reflex ladder (bone shield ≥75%, 3 revives via desecrate→revive,
  belt/potions, walk-away, blood warp escape, chicken as last rung) —
  captured verbatim in this dir's `notes.md`; robustness-before-live-
  runs is a standing constraint (sim-first, staged acceptance).
- **M5 must include a town-heal preamble** (visit the healer NPC before
  leaving town, kolbot-style): PD2 carries HP/mana between games, so a
  below-threshold character would chicken out of every game it enters
  (user-spotted post-acceptance, R45). M4 ships the backstop —
  `max_consecutive_chickens` (default 2) halts the loop loudly — but
  the heal is the real fix.
- Deferred (low priority, user decision): death recovery + corpse
  retrieval. Deferred to M5/M6: doors, merc/golem chicken, potions.
- The two calibrations (menu pillarbox is derived; Save-and-Exit
  fractions are measured) need re-checking after any window/resolution
  change — noted in README and game-cycle.md.
- Bridge niceties if friction ever warrants: kill-current-command
  file, per-command working-dir override.
