---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-13
commit: see the 2026-08-13 commit series on combat-logistics
adrs: []
---

# Done — the tag-mode pickup calibration (R248 detour, T90/T91)

## Outcome

The operator's question is answered decisively, and the answer changed
the bot: **no name tags is the optimal pickup mode** — 30/30 (100%,
mean 12.3 s) against 3/30 (10%) under loot-filter tags and 11/30 (36%)
under default tags, every tagged round timing out. The executor's
standing label policy (force labels ON before pickup, T63/T66) was
falsified by the measurement and INVERTED (R254, approved): pickup now
ensures labels OFF, parity-safe against BH.dll's display flag.
Field-validated by a complete ordinary cold-plains run (census 1/1,
first click, zero misses; log `20260813-083614`).

## Completed work

- **T91** (`drills/t91_filter_flag.py`): the "F" default-tags toggle's
  state flag found on the first probe — `offsets.BH_FILTER_STYLE`
  (BH.dll+0x14D1CC), reader `perception.units.default_tags_on`. All
  three display modes machine-verified; F is bound NOWHERE on disk
  (keyfile/BH.json/ProjectDiablo.cfg all scanned), documented at
  `input/keys.py::VK_F`.
- **T90** (`pd2bot/behavior/steps/tagmode.py` + both registries +
  `runs/t90-tagmode-battery.toml` / `-c.toml`): the battery step —
  blocks 1A..5A / ALT / 1B..5B / F / 1C..5C, one-pile stand-still
  drops of everything but the cube and tomes, flag-verified mode
  transitions with settle windows, 30 s rounds ending early when
  clean, chat-announced rounds and scores, operator-gathered resets
  ("resuming."), per-drop floor confirmation (`battery.consumed`),
  announced-never-fatal census notes (`battery.loss`), stray-panel
  recovery every tick, `blocks` param for partial reruns.
- **The run abort channel** (`wiring.run_stop_channel`): `abort` /
  `abort the test` in game chat, or the drill-cancel file, stops ANY
  run within a tick — runs had no `should_stop` wired at all before
  this (found when the agent's abort had no way into launch 1).
- **The watchdog staleness grace** (`EngineConfig.watchdog_stale_grace_s`
  = 15 s, operator-approved R253): five "silent freezes" reframed as
  transient ~4–10 s stalls WITH RECOVERY once guarded-run stopped
  killing the evidence (it now waits 12 s for the faulthandler dump on
  a stale heartbeat). `watchdog.stale`/`watchdog.recovered` events.
- **The executor knob + inversion** (`enforce_label_display`, default
  True): pickup presses Show Items only when labels provably read ON.
- **Tabulation**: `python -m pd2bot.runlog <dir> --tagmode`.

## Validation

- `pytest`: **1299 passed** (from 1275 at session start); `ruff` clean.
- Live: six T90 launches (drill-log rows 1–6) + T91. Full battery
  data across launches 4 and 5; field validation run 6.

## Deviations from the plan

The battery was redesigned twice mid-cycle by operator instruction
(R250: one-pile drops + immediate misclick recovery after the
scatter-walk wedge; R251/R252: operator-gathered rounds +
loss-tolerant census after a ctrl-slip drank a potion and stopped a
healthy battery). Each launch's defect is recorded in the drill log
and was fixed before the next. Three healing potions were consumed by
ctrl slips across the session (all caught by the floor confirmation).

## Documentation

`docs/architecture/run-log.md` (battery events, abort channel, the
staleness grace), `pd2bot/behavior/steps/README.md`, `input/keys.py`
(the corrected label-protocol note), plan `notes.md` (full discovery
and redesign record), drill log rows T90×6 + T91, instruction log
R248–R254.

## ADRs

None — test kit plus one measured policy inversion inside existing
mechanics. The safety-grace change is recorded in `EngineConfig` and
the run-log doc; it adjusts a threshold within ADR 2026-08-07's
architecture rather than choosing a new direction.

## Follow-ups (outside this scope)

- The watchdog stall's ROOT CAUSE is still open — the grace is
  mitigation, and the instrumented dump has yet to catch a stall
  longer than 10 s. Evidence next occurrence.
- The tagged-mode failure MECHANISM (labels burying sprites vs
  displacing click geometry) is measured but not explained; only
  worth pursuing if tags are ever needed during pickup again.
- The teach step for this cycle rides the combat-logistics P6
  closeout, per the phase file.
