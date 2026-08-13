# HANDOFF — combat-logistics live batch, paused 2026-08-10

> **SUPERSEDED 2026-08-13.** Open items 1, 2 and 4a were solved OFFLINE
> from the 2026-08-10 logs themselves — see the "2026-08-13 session"
> section of `notes.md`. The order discrepancy was a run-log bug (a
> `kind=` field clobbered the event kind on disk; orders booked fine),
> the cleanse starvation was a two-cause branch gap (fixed +
> instrumented), and the stash misclick was the T83 sprite rule missing
> from deliberate clicks (fixed, `town.click_dodge`). What remains live:
> the R244 verification batch + the P5 census gate, then P6 closeout.

Written at the operator's request at end of session (context limit).
Branch: **combat-logistics** (all work committed + pushed, CI green,
1226 tests). NOT merged to m6-countess. Next request number: **R244**.

## State: what is DONE and live-proven

- **P1 config trio** — heal 75; El–Sol runes skipped (both variants);
  socket rules removed. `0236efe`.
- **P2 route leash** — routeline.py geometry + per-seed store; T84
  recorder (map-agnostic; Cold Plains line recorded, `line-003.json`);
  TraverseStep leash with posture return policy + goal-off-line guard
  (two live-found fixes). Live PASS: traverse to the Cave hugging the
  line, 3 route.stray events, returned, arrived.
- **P3 berserk** — style enum ('skirmish'|'charge'), posture-only
  armor_recast override wired into the ladder; shipped berserk posture.
  Live PASS supervised (operator judged charge correct; safety silent).
  NOTE: only proven on low-threat Cold Plains.
- **P4 Akara restock** — read_vendor_stock (cells fresh per visit),
  T85c calibration (config/shop_calibration.json, 1536x864),
  _RestockMixin in the preamble (akara.trade row 2, buys verified by
  belt count, gold floor 5000 counting carried+stash). Live PASS:
  "bought 3 healing, 2 mana". Q5 executed: healing/mana OUT of pickit
  (`45254cd`); REJUVS KEPT (unbuyable, R47.6). deplete_belt test step
  exists for self-contained re-tests (runs/restock-test.toml).
- **P6 partial** — ADRs written (posture-fight-styles, vendor-buying);
  run-log.md event kinds documented.

## OPEN — the next session's work

1. **Order-booking discrepancy (P5 blocker).** OrderBook arms live
   (pickup.order_book_diag armed:true) and whitelisted non-potion items
   drop (item.dropped fired for amethysts/ring/diamonds), but NO
   pickup.order_open ever appears — while the same path books correctly
   offline (tests/behavior/test_clear_orders.py + test_traverse_orders,
   7 tests). An unconditional instrument is IN PLACE: booking now emits
   order_open OR order_resight per sighting (pickup.py,
   log_wanted_drops). **One live run with any whitelisted drop is
   decisive**: neither event firing means log_wanted_drops is not the
   item.dropped emitter path we think, or book is None on that call
   path. Runs: runs/pilot-orders-nopre.toml (preamble-less). Read the
   newest logs/runs/*pilot-orders-nopre* events.jsonl.
2. **Cleanse never runs on a full inventory (operator-observed).** The
   bot attempted pickups on a full inventory without cleansing.
   Cleanse IS enabled (no pending names; cleanse_keep present), so
   suspect: services.cleanse_queued never set on that path, or
   maybe_cleanse unreached / declining (hostile radius? in_town?).
   Instrument collect()/_mark_inventory_full/maybe_cleanse decision
   points, run full-inventory live, read the log.
3. **P5 census gate — NOT passed.** After 1+2, one pilot run whose
   census shows every order collected/gone/budget with trails; the
   OPERATOR reviews before mandatory_pickup is allowed beyond
   cold-plains. Note: whitelisted drops are now rare in Cold Plains
   (potions/low-runes removed) — the drop-driven drill option (operator
   drops a Shael+/gem, deterministic lifecycle incl. walk-away-return)
   remains the fast alternative the operator previously declined.
4. **NPC-dialog misclick family (operator: "ought to be resolved").**
   Two live manifestations this session:
   (a) **stash-open misclick** — the open-stash click lands on an NPC
   (MISCLICK opened npc_menu), 3 attempts, TownError, preamble aborts
   (~2 of 6 runs!). Spawned as background task task_a372c555 with full
   evidence; the T83/R234 click-clearance work is prior art
   (drills/town_click_clearance.py).
   (b) npc.accidental events during preambles (2x per stalled run).
   Fixing (a) likely fixes the intermittent 2-tick town stalls that
   wasted ~4 launches this session.
5. **Housekeeping at close**: remove diag event pickup.order_book_diag
   (clear.py step start) once item 1 is solved; delete scratch runs
   (leash-acceptance, berserk-acceptance, restock-test,
   pilot-orders-nopre, cold-plains-pilot-orders) or keep deliberately;
   R242 outcome + R243 already logged; then P6 closeout: teach step,
   _DONE.md, archive, merge combat-logistics -> m6-countess, resolve
   R242 in the instruction log.

## Where things are

- Plan dir: docs/plans/2026-08-09-combat-logistics/ (plan.md, phase
  files 01-06, notes.md carries the full live-batch record).
- Live-run method: guarded-run via the bridge —
  `tools/guarded-run.ps1 -Run runs\<file>.toml -Games 1` queued as a
  bridge cmd (see CLAUDE.md bridge protocol); ALWAYS read
  logs/runs/<newest>/events.jsonl before judging.
- Standing mandate R241 Q8 covered THIS batch's live work; it was
  paused by the operator 2026-08-10 ("Let's pause live testing") —
  re-confirm before resuming launches.
