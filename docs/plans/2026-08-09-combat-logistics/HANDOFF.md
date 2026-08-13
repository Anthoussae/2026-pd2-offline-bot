# HANDOFF — 2026-08-13 session end (context migration)

Branch **combat-logistics**, all work committed + pushed, CI green,
**1275 tests**, ruff clean. NOT merged to m6-countess. Next request
number: **R248**. Next test id: **T90**. The bridge is up; the operator
is at the machine and the client was last left at the menu.

## What this session proved and shipped (all live-verified)

1. **The R244 "order-booking discrepancy" was a run-log bug, solved
   OFFLINE**: a field named `kind` clobbered the event kind on disk
   (orders had booked fine all along). Envelope keys are now
   inviolable; emitters renamed (`item_kind`/`monster_kind`); the test
   fake fails on collisions. `run.end` is finally EMITTED (documented
   since birth, called by nobody); `watchdog.down` event added.
2. **Cleanse-on-full-inventory fixed** (pile-ambiguity write-offs now
   queue a cleanse; `service_orders` calls it ungated) — game 3 of the
   pilot batch ran the WHOLE lifecycle live: full grid → queue →
   mid-field cleanse (6 dropped) → retry → budget close → id-churn
   convergence → the rune collected anyway by the sweep.
3. **MAX_CARRIED_ITEMS truncation** (the real restock over-buy root
   cause, operator-corrected diagnosis): the item chain is 560 long,
   the old 512 cap silently dropped belt/gear; cap 4096 +
   `CarriedItems.truncated` + the preamble refuses truncated reads.
   Restock hardened (belt-room check, inventory-landed stop,
   MAX_DEAD_CLICKS, `town.restock` event).
4. **Misclick family**: interact clicks dodge bystander sprite boxes
   (`town.click_dodge`; merc exempt — live-proven it can't intercept);
   `_await_interact` ends the 15 s missed-click stall (trips 25 s →
   13 s; EVERY run used to pay it); the sprite escape is GOAL-AWARE
   with a past-the-head candidate (T88's Charsi loop, fixed + unit-
   pinned).
5. **The stack sampler** (`pd2bot/runlog/sampler.py`) — always on in
   real launches, writes `logs/samples-*.log`, span-compressed main-
   thread stacks; it found the 15 s stall on its first run. The
   watchdog got a faulthandler dead-man (its silent-freeze mystery is
   3 occurrences old; did NOT recur since — next freeze writes its own
   stack to the .err.log).
6. **R247 hotkey config — COMPLETE and archived**
   (`docs/archive/plans/2026-08-13-hotkey-config/`): bindings read from
   the client's per-character `.key` file (self-validating parser),
   one registry (`input/keys.py`), toml verified against the client at
   every game build, T89 demonstrated 6/6 live. ADR accepted.
7. **Pilot batch (R244/R245) complete**: game 1 fixes-verified (ended
   by watchdog freeze), games 2–3 COMPLETE with census. **Two new test
   kinds** established: demonstration (T88 6/6 closures 0.66 s,
   operator satisfied; T89) and the trip battery (T87, 13 runs).

## OPEN — the next session's work, in order

1. **The operator opens with a small detour: item pickup setting
   calibrations** — they will propose the specifics; the deferred
   "(b) item-pickup/whitelist battery" from R244 is likely part of it.
   Hear the proposal before touching anything else.
2. **R246 [verify], STANDING — the P5 census gate**: the operator
   reviews the batch (`logs/runs/20260813-022855/-024533/-025430-*`)
   and rules on `mandatory_pickup` beyond cold-plains: promote / keep
   piloting / adjust (the one tension: combat priority let a diamond
   expire on the floor after ~285 s — T51 window — while the order
   held correctly).
3. **P6 closeout of combat-logistics** after 1–2: remove
   `pickup.order_book_diag` (clear.py step start); delete-or-keep
   scratch runs (leash-acceptance, berserk-acceptance, restock-test,
   pilot-orders-nopre, cold-plains-pilot-orders); teach step (MUST
   also cover the hotkey-config detour's concepts per its _DONE.md);
   `_DONE.md`; archive; resolve R242 in the instruction log; refresh
   the badly stale `docs/project-state.md` (says R236/T82 — reality is
   R248/T90); merge combat-logistics → m6-countess.
4. **Small known items**: waypoint first-click aim still misses from
   the SW approach (~2.8 s/trip; SHELVED low-prio with T83 by the
   operator — general solutions preferred); a ring (kind 537) refused
   one stash-deposit click per game (retries fine); execute.py's cast
   events pass a field named `at` (now preserved as `field_at` — a
   rename to `cast_at` is P6-grade housekeeping).

## Where things are

- Live-run method unchanged (bridge, guarded-run, ALWAYS read
  `logs/runs/<newest>/events.jsonl` first; census via
  `python -m pd2bot.runlog <dir> --pickup`); plus the NEW sampler file
  per launch (`logs/samples-*.log`) for any lost-seconds question.
- Standing mandate: live launches were re-authorized this session for
  the batch + demos; the operator has been present throughout. Confirm
  presence before new launches as usual.
- This plan dir's `notes.md` carries the full session record (three
  dated 2026-08-13 sections); the instruction log has R244–R247
  resolved inline.
