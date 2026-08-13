# P2 — live battery and ruling (sm)

Depends on P1 (suite green). Live protocol: bridge, guarded-run,
watchdog, operator present and tabbed in; ALWAYS read
`logs/runs/<newest>/events.jsonl` after; the sampler file
(`logs/samples-*.log`) answers any lost-seconds question.

## Review gate — the launch request IS the gate

Issue one `execute` request (next free R number) carrying the full
revised protocol: mode interpretation (mode 2 = ALT on + filter tags,
mode 3 = ALT on + F/default tags — correctable in chat), interleaved
(1,2,3)×5 cycles, 30 s cap with early finish, undroppables sit out
(cube/tomes/scrolls/maps/potions), manifest reconciliation between
rounds, full-floor sweep before `done`, and the named residual risk
(a client crash mid-round loses that round's floor items). Wait for
the word.

## Sequence

1. **F-flag probe** (t91 drill, ~2 min, autonomous): if a flag byte
   survives, add it to `offsets.py` + accessor and re-run the suite
   before the battery; if none, the battery falls back to chat
   confirms at mode-3 switches — say which fallback is active in the
   launch announcement.
2. **The battery**: guarded-run with `runs/t90-tagmode-battery.toml`,
   1 game. The step announces the drop manifest in chat before cycle
   1 — if the droppable whitelisted set is thin (< ~4 items), the
   operator may abort and restock the inventory, then relaunch.
3. **Read the event log first**, then tabulate
   (`python -m pd2bot.runlog <dir> --tagmode`), then reconcile the
   manifest one last time against the run's end state.
4. **Register T90/T91** in `docs/drill-log.md`; update
   project-state's next-test counter.
5. **Issue the ruling request** (`verify`): the per-mode table plus
   the raw per-round rows, and the question — which mode becomes the
   bot's standing label policy (that change is a follow-up commit,
   not this plan).

## Definition of done

Battery complete (or honestly aborted with everything gathered), table
delivered, ruling request issued, drill log + instruction log current.
_DONE.md is written by yona-implement at closeout, covering both
phases; the teach step belongs to the combat-logistics P6 closeout
unless the operator asks earlier.

## Reminders

Do not commit unless asked. Confirm operator presence before ANY
launch. On any mid-battery surprise: gather the floor first, diagnose
second. Report deviations plainly.

## Implementation Result

Status: done
Completed: 2026-08-13
Commit: pending

- Six launches total (drill-log T90 rows 1-6 + T91 row 1). The battery
  design was rebuilt twice from live findings (R250 operator redesign
  after the scatter-walk wedge; R251/R252 operator-gathered rounds +
  loss-tolerant census after the drunk-potion stop) — each launch paid
  for a defect the next one no longer had.
- The measurement (15 rounds): A (no tags) 30/30 (100%), mean 12.3 s;
  B (filter tags) 3/30 (10%); C (default tags) 11/30 (36%). All tagged
  rounds timed out.
- Ruling (R254, approved): the executor's label policy INVERTED —
  labels OFF for pickup. Field-validated: cold-plains run COMPLETE,
  census 1/1 first-click, zero misses (log 20260813-083614).
- Collateral hardening shipped along the way: the run abort channel
  (R250; wiring.run_stop_channel — standing for ALL future runs), the
  watchdog staleness grace (R253, operator-approved safety change,
  after reframing five "freezes" as transient stalls with recovery),
  per-drop floor confirmation, misclick panel recovery in every phase.
- Deviations from the phase file: the F-flag probe PASSED so the blind
  fallback never ran live; the ruling request became R254 (numbering
  moved with the session's extra gates R250-R253); the teach step
  stays with the combat-logistics P6 closeout as planned.
