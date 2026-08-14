---
kind: plan
size: md
depth: implementation
status: done
repo: 2026-pd2-offline-bot
created: 2026-08-13
completed: 2026-08-13
commit: see the 2026-08-13 commit series on combat-logistics
adr: none
---

# Pickup name-tag calibration battery (R248 detour, T90)

## Goal

Measure whitelisted-item pickup accuracy under three name-tag display
modes — (1) no tags / ALT off, (2) loot-filter tags / ALT on,
(3) default tags / ALT on + "F" — and hand the operator a per-mode
table (accuracy, speed, accidental junk pickups) to rule on. The
operator authorized review-edit-run (R248); the live launch still goes
through the standard presence gate.

## Size

`md` — two phases: everything buildable offline (step, run file,
executor knob, probe drill, tabulator, tests), then the live battery.
One review gate: the live-launch request itself carries the revised
protocol for the operator's eyes before anything touches the game.

## Acceptance criteria

- The battery runs 5 interleaved cycles of the three modes in ONE
  game, town chores suspended, on the engine's REAL pickup path.
- The Horadric Cube is never dropped (enforced by the existing
  exception registry, verified by test), and no other undroppable
  kind is aimed at.
- Every round's drop manifest is reconciled before the next round; the
  run ends with a full-floor sweep and a chat-announced reconciliation
  — zero whitelisted items lost on any non-crash path.
- Mode 1 genuinely runs with labels OFF (the executor's force-on
  policy is suppressed for the battery, default behavior unchanged —
  pinned by unit test).
- ALT state verified by memory read each switch; F state verified by
  memory read if the probe finds the flag, else by operator confirm.
- A tabulated per-round + per-mode report exists from the run's own
  event log, and the ruling is issued as a `verify` request.

## Out of scope

- Changing the bot's standing label policy to the winner (follow-up
  commit after the operator's ruling).
- The R246 census gate and P6 closeout of combat-logistics (queued
  behind this detour).
- Any pickit rule changes.

## Discovery summary

See [notes.md](notes.md). Key facts: ALT = Show Items (keyfile entry
37, R247 registry) and acts as a toggle (`BH.json`
`always_show_items: true`); ALT state readable
(`offsets.BH_LABEL_DISPLAY`, T66); **F is bound nowhere on disk** —
plausibly PD2's hardcoded filter-level toggle (`filter_level: 0` /
`last_filter_level: 8` pair in BH.json), so it gets its own T66-shape
flag probe before the battery trusts it; drop machinery
(`drop_item`), protection registry (cube/tomes/scrolls/maps/potions),
and whitelist verdicts (`pickit.wants` / `cleanse_keep`) all exist;
the one production change is an executor knob to stop forcing labels
ON during mode-1 rounds.

## Files expected to change

- `pd2bot/behavior/steps/` — new `tagmode_battery` step + registry row
- `runs/t90-tagmode-battery.toml` — new run file (no `town_preamble`)
- `pd2bot/behavior/execute.py` — label-policy knob (default: today's
  behavior)
- `pd2bot/offsets.py` — F-flag constant IF the probe finds it
- `pd2bot/perception/units.py` — F-state accessor beside
  `label_display_on` (same condition)
- `drills/t91_filter_flag.py` — the F-flag probe (T66 protocol on key
  F; test id per drill-log at implementation time)
- `pd2bot/runlog/` — `battery.round` event kind + the tagmode
  tabulation report
- `tests/` — step logic (round/manifest/verdict, mode sequencing),
  executor knob, event schema
- Docs: `docs/architecture/run-log.md` (new event),
  `pd2bot/behavior/steps/README.md` (step row),
  `docs/drill-log.md` (T90/T91 rows at run time)

## Validation

- `~\.venvs\pd2bot\Scripts\python.exe -m pytest` (1275+ green)
- `ruff check .`
- Live: the battery run itself (P2), read
  `logs/runs/<newest>/events.jsonl` first, standing method.

## Phases

| Phase | Size | Summary | Review gate |
|---|---|---|---|
| P1 | sm | Offline build: step, run file, executor knob, F probe drill, run-log event + tabulator, tests, docs | none (all offline, suite-gated) |
| P2 | sm | Live: F-flag probe, then the battery (15 rounds), tabulate, issue the ruling request | the launch request itself (operator presence + protocol review); the ruling is theirs |

ADR: none — test kit plus one default-preserving knob; no direction
with lasting architectural consequence is chosen here. (If the ruling
later changes the standing label policy, that commit cites the data,
still no ADR.)
