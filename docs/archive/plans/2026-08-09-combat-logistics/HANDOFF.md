# HANDOFF — 2026-08-13 ~09:00 session end (context migration)

Branch **combat-logistics** at `646f7f3`, pushed, CI green, **1299
tests**, ruff clean. NOT merged to m6-countess. Next request number:
**R255**. Next test id: **T92**. The bridge is up; the operator is at
the machine; the client was last left at the menu after the R254
validation run.

## What this session proved and shipped (all live-verified)

The whole session was the operator's R248 pickup detour, now COMPLETE
and archived (`docs/archive/plans/2026-08-13-pickup-tagmode-calibration/`
— `_DONE.md` is the record; instruction log R248–R254; drill log T90
rows 1–6 + T91).

1. **The answer: NO NAME TAGS is the optimal pickup mode** — 15
   measured rounds: A (no tags) **30/30, 100%, mean 12.3 s**; B
   (filter tags) 3/30 (10%); C (default tags) 11/30 (36%); every
   tagged round timed out. The executor's force-labels-ON policy
   (T63/T66) was falsified by its own measurement and **INVERTED**
   (R254, approved): `_pick_up` now ensures labels OFF, parity-safe
   against BH.dll's flag. Field-validated: ordinary cold-plains run
   COMPLETE (log `20260813-083614`, 480 s), census 1/1 first-click.
2. **T91 pinned the "F" default-tags flag on the first probe**:
   `offsets.BH_FILTER_STYLE` (BH.dll+0x14D1CC, 1 = filter styling);
   reader `perception.units.default_tags_on`. F is bound NOWHERE on
   disk — the press is blind, the STATE is read.
3. **STANDING: runs finally have an abort channel**
   (`wiring.run_stop_channel`): `abort` / `abort test` / `abort the
   test` typed in game chat, or `tools\drill-cancel.ps1`, stops ANY
   run within a tick, honored mid-walk. Runs had NO `should_stop`
   wired at all before this.
4. **The watchdog "silent freeze" is reframed**: a transient ~4–10 s
   stall WITH RECOVERY (5 occurrences; proven when guarded-run
   stopped killing the evidence — it now waits 12 s for the
   faulthandler dump on a stale heartbeat). The engine gives staleness
   a **15 s grace** (operator-approved R253; `watchdog.stale`/
   `watchdog.recovered` events). ROOT CAUSE STILL OPEN — evidence
   next occurrence.
5. **The tag-mode battery is reusable kit** (`steps/tagmode.py`,
   `runs/t90-tagmode-battery[-c].toml`, `runlog --tagmode`): one-pile
   drops of everything but cube+tomes, operator-gathered rounds
   ("resuming."), per-drop floor confirmation (ctrl slips DRINK
   potions — 3 paid this session, all caught), announced-never-fatal
   census notes, stray-panel recovery, `blocks=` for partial reruns.
6. **Review** (`docs/reviews/2026-08-13-tagmode-cycle/`): ship-it,
   three P3s tracked — chat-abort buffer race (bot says are
   unprefixed and share the one-line buffer), round-boundary
   telemetry, consumed-announce console fallback.

## OPEN — the next session's work, in order

1. **The operator's NEW detour: human-vs-bot Cold Plains speed
   comparison.** The operator will PLAY a Cold Plains run themselves
   while it is RECORDED, to diff against a bot run's log and find the
   MAIN CULPRIT of the speed discrepancy. Nothing records a human run
   today — the run event log is engine-tied. Discovery pointers: the
   engine's per-tick recorder wants a read-only twin (perception
   snapshots on a timer, no input — the watchdog and
   `navigate.py`'s survey mode are precedents for passive processes);
   comparable metrics per phase (town time, travel time,
   clearance time, pickup time, route length) matter more than raw
   events; the bot's own baseline can be any recent cold-plains log
   (e.g. `20260813-083614`, 480 s end-to-end) or a fresh one. Banked
   speed evidence to reuse: `performance-notes.md` (the ~9-min
   descent analysis, navigator oscillation ~120 s, pickup-on-descent
   costs).
2. **R246 [verify], STANDING — the P5 census gate**: the operator
   reviews the pilot batch (`logs/runs/20260813-022855/-024533/
   -025430-*`) and rules on `mandatory_pickup` beyond cold-plains.
3. **P6 closeout of combat-logistics**: remove
   `pickup.order_book_diag` (clear.py step start); delete-or-keep
   scratch runs (leash-acceptance, berserk-acceptance, restock-test,
   pilot-orders-nopre, cold-plains-pilot-orders — and now the t90
   battery runs, which are probably keepers as test kit); the three
   review P3s; teach step (MUST cover the hotkey-config AND tag-mode
   detours per their _DONE.md files); `_DONE.md`; archive; resolve
   R242 in the instruction log; refresh the badly stale
   `docs/project-state.md` (says R236/T82 — reality is R255/T92);
   merge combat-logistics → m6-countess.
4. **Small known items**: waypoint first-click aim from the SW
   (~2.8 s/trip, SHELVED with T83); the ring (kind 537) stash-deposit
   retry; execute.py's `field_at` → `cast_at` rename; the watchdog
   stall root cause (see item 4 above).

## Where things are

- Live-run method unchanged (bridge, guarded-run, ALWAYS read
  `logs/runs/<newest>/events.jsonl` first; census via
  `python -m pd2bot.runlog <dir> --pickup`, battery via `--tagmode`);
  the sampler file per launch (`logs/samples-*.log`) for lost-seconds
  questions.
- **Aborts now work everywhere**: `abort the test` in chat, or
  `tools\drill-cancel.ps1`, stops drills AND runs.
- Standing mandate: the operator has been present throughout; confirm
  presence before new launches as usual.
- The archived detour's `notes.md` carries the full discovery +
  redesign record; the instruction log has R248–R254 resolved inline.
  This file supersedes the 2026-08-13 morning HANDOFF (same file,
  rewritten); where anything disagrees, trust the instruction log.
