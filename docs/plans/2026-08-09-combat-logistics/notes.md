# Notes — combat & logistics bundle (route leash, styles, restock, mandatory pickup)

Created 2026-08-09. From the user's seven-item request (assessed in chat
the same day; R240 era). Item 4 (watchdog drinks potions) was assessed
against and the user dropped it: *"I'm convinced it's unwise."*

## Scope as given by the user

1. **Core path / route leash** — emphasize clear waypoints or a line;
   the operator can RECORD a line by walking it (manual calibration);
   the recorder must be map-agnostic so future runs (Blood Raven,
   Arcane Sanctuary) reuse it.
2. **Postures may override fight behavior** — "consider refactoring so
   that postures can override behavior, if reasonable"; add **berserk**
   (always attack closest visible enemy, poison dagger, no skirmish;
   bone armor recast below 60% without interrupting animation; potions
   as usual; returns to core path only at 0 nearby enemies). May prove
   optimal for quick runs.
3. **heal_below_pct → 75** (cooldown already 10 s).
5. **Akara potion restock** town chore; remove potions from pickit —
   motivation: pickup unreliability makes potion-chasing a time sink.
6. **Skip runes El–Sol (ranks 1–12)** — user confirmed the rank
   interpretation and the kept/excluded lists from the assessment.
7. **Mandatory persistent pickup** — non-expiring order per whitelisted
   drop, below combat / above traversal; thread/chain back to items;
   unstack-by-collecting loop; walk-away cleanse + return; interruptible
   by combat; 60–90 s give-up.
8-adj. **Remove the dormant socket rules** (3-socket necro heads,
   3/4-socket Archon Plate) from pickit.

## Discovery findings

- **Vendor UI is not virgin territory.** The repair flow
  (`behavior/town/services.py:85-124`) already goes two clicks deep:
  `charsi.trade_repair` dialog row → shop screen opens (verified) →
  repair button, with `uipoints.py` carrying hover-calibrated points as
  "furniture" that appears at fixed positions. The Akara buy = same
  dialog-row pattern + NEW: clicking a specific potion in the shop item
  grid (grid geometry needs one calibration drill), buy-by-right-click,
  belt/gold verification. R48's no-vendor decision is therefore a
  POLICY boundary, not a capability cliff.
- **The survey tool records grids, not paths** (`nav/survey.py`) — the
  line recorder is new but small: sample player position per tick while
  the operator walks (the T52 manual-survey pattern gives the harness),
  thin with the existing waypoint `simplify()`, store per
  (area id, map seed). **Storage: `maps/`** beside the atlas — lines
  are seed-bound save-data like the grids (gitignored, regenerable by
  re-walking); NOT `runs/` (git, seed-independent).
- **Postures are validated at build time** (`steps/registry.py`
  `_checked_posture`, `services.postures` frozenset) and are override
  TABLES over `CombatConfig` numbers; `_POSTURE_KEYS` explicitly
  excludes skills ("a posture is a manner, not a build",
  `combat.py:250`). A fight-STYLE selector crosses that line
  deliberately → needs the recorded rationale (ADR) and a small enum
  mechanism, not a general strategy-plugin framework.
- **Berserk's survival needs are already layered right**: armor recast
  + potions live in the reflex ladder (layer 1) ABOVE the class module,
  so they apply to any style automatically. Armor threshold per posture
  = a posture number override (armor rung threshold exists in
  `necro.toml`); animation-safety = the measured 610–640 ms cast settle
  already in the executor (T48).
- **Mandatory pickup substrate**: wanted positions + 8-offset schedule +
  write-offs exist (`steps/pickup.py`); the cleanse exists
  (`town/inventory.py` via `_PickupMixin.maybe_cleanse`); ground items
  EXPIRE (T51, measured) so "non-expiring order" MUST distinguish
  item-gone (poll the floor: unit no longer present → close the order)
  from item-unreachable (keep trying inside the budget). The cleanse
  DROPS junk — the user's own walk-away-first-then-cleanse detail is
  what keeps the pile from re-polluting; distance must exceed the
  pickup scan radius of the return trip.
- **Config facts** (verified today): `heal_below_pct = 100.0`,
  `heal_cooldown_s = 10.0` (necro.toml); pickit potion rules are the
  first three rules; "all runes" rule + `runes` group El→Zod in
  item_ids.toml (r01–r33 + PD2 stackable r--s variants in
  item_codes.toml — the skip must cover BOTH plain and `s` variants of
  ranks 1–12); socket rules at pickit.toml:111-121, dormant (T38 never
  ran).
- **Ordering constraint (P4)**: potions must NOT leave pickit before
  the restock chore is live-proven, or runs starve the belt in the gap.
  Same commit at the END of the restock phase.

## Questions

- R241 confirmation batch Q1–Q8 + phase table — see chat/instruction
  log. Notable calls folded in: reopening R48 (Q4) made explicit;
  posture-style line-crossing (Q3) explicit; line storage in maps/
  (Q2).

## User answers / scope changes

- R241 answered **"all yes, then /yona-implement"** (2026-08-09).
  Q1–Q8 as suggested; implementation authorized (commit-per-phase on a
  branch, per the restructure precedent).
- **Q4 refinement (user)**: do not assume potions sit at fixed shop
  grid cells — (a) READ where the potions actually are each visit, (b)
  aim at where the potion is on this occasion. Design answer: Akara's
  stock is carried items owned by HER unit — the same item structures
  `perception/items.py` reads for the player, including grid cell — so
  the chore reads (potion kind → cell) fresh per visit; the one-time
  hover calibration covers only the PANEL's fixed furniture (grid
  origin + cell pixel size). Cell-from-memory × calibrated
  grid-to-pixel = the click. The P4 drill verifies the mapping by
  hover before any buy click.

## Risks

- Live-time appetite: P2–P5 each carry a live acceptance (a recorded
  walk, a berserk supervised run, the Akara drill, the pickup pilot).
  A standing mandate (R207/R217 shape) would collapse the round trips.
- Berserk concentrates the exact risk profile of the Cellar-4 death;
  it must ship behind the unstarvable safety stack unchanged, and its
  acceptance run should be supervised.
- Mandatory pickup is the livelock-richest state machine yet
  (pursue→fight→return→cleanse→retry); run-event-log instrumentation
  from the first line; pilot behind a per-run flag.

## Out of scope / future work

- Watchdog potion-drinking — REJECTED (user concurs, 2026-08-09).
- Command-by-GID acquisition — stays dead (operator decision stands).
- BH label-geometry emulation for pile pickup — future option if the
  mandatory-pickup loop's measured results still disappoint.
- Gold pickup rule; vendor SELLING (buy only, this plan).

## Implementation notes (offline halves, 2026-08-09 session)

- P1 complete `0236efe`; P2 offline `634be1c`; P3 offline `bf33d3f`;
  P4 offline `51abbff`; P5 offline `2fd2e92`. 1221 tests, CI green.
- Deviations of note: ClearRadiusStep did NOT get the leash (its anchor
  + radius already bound it; recorded here rather than coupling two
  route concepts); `require_line` is checked at first in-area tick, not
  build time (the seed is unknowable earlier); mandatory orders skip
  potions by design (item 5 owns potions); the walk-away cleanse
  reuses maybe_cleanse's existing repel hygiene rather than a new
  random-cardinal walk (it already walks away from wanted items).
- LIVE BATCH still owed (standing mandate, R241 Q8): T84 Cold Plains
  line + leash run; supervised berserk run (Q6); T85 + the buy chore +
  pickit potion removal (Q5, same commit); the order-book pilot run +
  census review. Merge to m6-countess only after the batch.

## Live batch progress + OPEN items (2026-08-10, paused by operator)

DONE live-proven this session (branch combat-logistics):
- P1 config trio (no live needed).
- P2 leash: T84 recorded the Cold Plains line; leash run traversed to
  the Cave hugging the line, returned after strays (route.stray x3),
  arrived. PASS.
- P3 berserk: supervised Cold Plains clearance, charge behaviour
  operator-judged correct, safety silent, armor upkeep firing. PASS
  (low-stress; berserk-in-danger still unproven).
- P4 restock: T85c calibrated Akara's two potion spots; the autonomous
  restock station bought "3 healing, 2 mana" (each belt-verified) via
  the akara.trade row and stash gold; potions removed from pickit (Q5).
  PASS. Prereqs found+fixed live: calibration path parents[3]; stash
  gold spendable; akara.trade uipoint (Talk/Trade/Cancel row 2); gold
  reserve (deposit_gold kept 0 -> restock broke).

OPEN (need an instrumented live run when testing resumes):
1. **Order booking discrepancy.** order_book arms live
   (pickup.order_book_diag armed:true), whitelisted NON-potion items
   drop (item.dropped: amethyst/ring/diamond/skull), yet ZERO
   pickup.order_open — despite log_wanted_drops booking correctly
   OFFLINE (test_clear_orders + test_traverse_orders, 7 tests). The
   booking now emits order_open OR order_resight unconditionally, so
   the next run with a whitelisted non-potion drop is decisive: if
   NEITHER fires, log_wanted_drops isn't the item.dropped source we
   think, or book is None on that call.
2. **Cleanse on full inventory.** Operator watched the bot attempt
   pickups on a full inventory without ever cleansing. Cleanse IS
   enabled (no pending names, cleanse_keep present), so the gap is
   cleanse_queued not being set, or maybe_cleanse not reached on the
   pursued path. Needs a full-inventory run with the collect/cleanse
   path instrumented.

The mandatory-pickup pilot census gate is therefore NOT yet passed;
the flag stays pilot-only (cold-plains) and unmerged.

## 2026-08-13 session: both OPEN items solved OFFLINE, from the logs

No live run was needed for either diagnosis. Commits `7a2f7d9` (orders +
cleanse) and `b20bce4` (misclick).

1. **The order "discrepancy" was never a booking failure.** The
   2026-08-10 events with numeric kinds (685, 537, 714, 695, 697) in the
   pilot logs ARE the order events: `pickup.order_open` and
   `pickup.order_gone`, emitted with `kind=<item kind>` as a field —
   and `RunLog.event`'s `record.update(fields)` let that field CLOBBER
   the envelope's event kind on disk. Orders booked, re-sighted and
   reaped live the whole time, invisible to every kind-filtered reader.
   The offline fakes keep `(kind, fields)` apart, which is why seven
   tests stayed green around it. Fixed at the root (envelope identity
   keys are inviolable; colliding fields become `field_<name>`), the
   emitters renamed (`item_kind`, `monster_kind` — `combat.write_off`
   had the same bug), and the test fake now FAILS on a collision.
   run-log.md documents that pre-2026-08-13 logs carry these events
   under numeric kinds.
   - Bonus finding from the same logs: **ground-item unit ids churn on
     room unload/reload** (one amethyst at one subtile = ids 604, 661,
     764). The OrderBook now rebinds an open order to the new id at the
     same kind+position (budget survives; no duplicate orders, no false
     `gone`), and a gone/budget close stays closed across ids
     (convergence). A COLLECTED twin's position books normally — that
     item is in the bag, so a new sighting there is a new drop.
2. **The cleanse starvation had two stacked causes**, both visible in
   run 031347's 89 write-offs: (a) 88 took the pile-ambiguity branch,
   which never queued a cleanse and never marked the inventory full —
   with a full grid, clustered drops ALWAYS read as pile ambiguity, so
   the one branch that queues never fired; (b) even a queued cleanse
   could not run while orders were serviced, because `service_orders`'
   only `maybe_cleanse` call was gated on `inventory_full` and the
   step's own call sits after the `service_orders` return. Pile
   write-offs now queue a cleanse (`cleanse_retried` still caps the
   R173 loop) and `service_orders` calls `maybe_cleanse` ungated. The
   whole path is instrumented: `inventory.full`,
   `inventory.cleanse_queued`, `inventory.cleanse_deferred`.
   - Also fixed from the same evidence: `collect()` re-logged a stuck
     item's write-off every serviced tick (the 88 duplicate
     `item.abandoned` events), and a terminally stuck order (clicks
     spent, post-cleanse retry failed) now closes immediately instead
     of standing out its 75 s budget in "pickup pacing".
3. **The stash misclick (handoff item 4a) is the T83 sprite rule
   missing from DELIBERATE clicks.** The travel path got the
   screen-space sprite box on 2026-08-08; `open_object_panel` aimed
   blind, and its aim-offset rotation is all `dx == dy` — movement
   along exactly the screen axis a sprite is 190 px tall in, so a
   bystander parked in front of the stash defeated every retry.
   Interact clicks now dodge bystanders' sprite boxes (first clear
   offset), wait a bounded `aim_blocker_wait_s` for the pacer when
   every aim is covered, and click anyway when it expires (the
   MISCLICK recovery still backstops). `open_npc_dialog` got the same
   wait for the silent variant (the wrong NPC's menu + keyboard-row
   selection — Akara row 2 trades, Kashya row 2 hires for 50k).
   Events: `town.click_dodge`. 4a's spawned background task is
   superseded by this fix.

State: 1239 tests, ruff clean. Still owed LIVE (R244): one verification
batch — preamble runs confirm the misclick fix and the order/cleanse
event stream under their real kinds, and the P5 census comes from the
same runs for the operator's review.

## 2026-08-13 R244 game 1: ABORTED — the restock over-buy

The first verification run never left town: the restock station bought
healing/mana potions for 127.5 s straight into the INVENTORY until the
client's can't-carry popup stopped everything (operator aborted; the
run then exited on the refusal streak, watchdog clean).

**ROOT CAUSE (operator-corrected).** The first written diagnosis here
blamed belt-column squatting; the OPERATOR's observation disproved it —
they watched the belt sitting FULL (2 mana potions among it) while the
bot bought more, and two bought mana potions visibly ENTER the belt.
With `min_mana = 2` a genuinely-read belt would have had zero mana
shortfall, so the read itself was the lie. Probed live: the player's
item chain is **560 items long** (PD2's expanded stash rides the same
chain and has grown with every game's deposits), and the walk cap
`MAX_CARRIED_ITEMS = 512` — written when "a character can own at most
~200 items" — was silently TRUNCATING the read: everything past entry
512 (the belt, the worn gear, most of the inventory) read as absent,
with `skipped: 0`. Same-run corroboration: `repair: nothing damaged
(0 worn item(s) checked)` on a geared character, where the 2026-08-10
preamble had read `8 worn item(s)`. The chain crossed the cap between
08-10 and 08-13.

Fixes (`87b3131` + follow-up):

1. **The reader confesses.** Cap raised to 4096; `CarriedItems` gains
   `truncated`, set whenever the walk hits the cap (a cycle lands there
   too — indistinguishable, equally untrusted); the town preamble
   REFUSES to run on a truncated read (every station would act on
   hallucinated absences). Live re-probe after the fix: 560 items,
   truncated False, belt 15, equipped 8.
2. **The station is hardened anyway** (defense in depth — these hold
   even when a read lies): `_belt_accepts` is asked before any gold
   moves; a purchase that lands in the inventory STOPS its type
   immediately (the bottle is the proof the belt is out of room); true
   mis-aim clicks are bounded at MAX_DEAD_CLICKS=3 (the old bound
   allowed `need + 12` real purchases per type believing unverified
   clicks were non-events); and the station finally emits the
   `town.restock` event run-log.md had documented but never received.
   The fake town got a vendor that routes purchases the way the game
   does; tests cover happy path, no-room refusal, mid-loop overflow
   stop, dead-click bound, and the preamble's truncation refusal.

Method note, paid for again: the first diagnosis was drawn from code
reading plus a post-cleanup probe; the operator's direct observation of
the LIVE failure was the datum that broke it. When an operator report
contradicts a tidy story, the report wins until the log says otherwise.

## 2026-08-13 R245 game 1 (attempt 2): fixes all VERIFIED live; run
## ended early by a watchdog freeze (unrelated, known, now instrumented)

The relaunched game proved every fix in its first five minutes:

- **Truncation fix**: `repair: 8 worn item(s) checked`, `restock: belt
  at minimums, skipped` (the belt read its true 15/16), `stash: 492
  items stashed` counted, 2 deposits, preamble done in 7 s.
- **Misclick fix live-fired**: one `town.click_dodge` at the stash —
  blocker kind 271 (the MERC standing on it), strategy wait, 4.1 s,
  cleared false, backstop click opened the stash anyway. Finding: the
  merc should be EXEMPT from the blocker check (it cannot intercept an
  interact click — proven by this very event — and it follows the
  player, so it is near-permanently adjacent); costs ~4 s per stash
  visit until fixed.
- **Order events under their real kinds live**: 1 `pickup.order_open`
  (a worldstone shard at (5170, 5762)) + 14 `pickup.order_resight`;
  the order held open while combat owned the ticks (correct priority).

The run then ended at t=310 s mid-clearance (14 hostiles, two boss
packs, hp 84%, fight in progress): **"the watchdog is not answering —
standing down"**. The watchdog's own log shows it healthy through 300 s
then silent with NO error — its process was still alive at teardown but
had stopped heartbeating. This is the THIRD such freeze (2026-08-08 x2,
per the watchdog's own docstring); the stand-down is the safety design
working as intended. Instrumented for the next occurrence (nothing else
can produce the diagnosis):

- `faulthandler.dump_traceback_later` dead-man, re-armed every poll
  pass: a frozen loop writes every thread's stack to the .err.log after
  10 s, even while stuck inside a C call.
- A STALL line for any recovered pass that took > 1 s; wall-clock
  stamps on the still-watching lines.
- `watchdog.down` run-log event at engine stand-down, and `run.end`
  (documented since the log's birth, emitted by NOBODY until now) is
  booked by the runner on every exit path with outcome + detail.

Not proven yet (game ended before): pickup census with collections,
cleanse-on-full live, order collect/close lifecycle. Next: relaunch.

## 2026-08-13 R244/R245 games 2-3: batch COMPLETE — everything fired

**Game 2** (`20260813-024533`, COMPLETE, 451 s, run.end's first-ever
emission): 8 drops all rejuvs → zero orders is CORRECT (orders skip
potions by design). Pickup 1/3: one walk-arrived-short, one honestly
diagnosed "belt full for rejuv". One `stash.refused` (a ring, kind 537,
one deposit click did not take; non-blocking, retries next preamble).
No watchdog freeze.

**Game 3** (`20260813-025430`, COMPLETE, 644 s) — every system under
test fired live, and the whole R241 item-7 design is now observed
end-to-end in one log:

- `town.click_dodge` strategy=offset: a real NPC (kind 155) covered the
  stash aim; the click stepped from (0,0) to (-1,-1) and opened the
  stash with NO wait (the merc exemption kept the merc out of it).
- **Flawless diamond order**: opened t=129, resighted through combat
  (priority held), closed `order_gone` at t=414 after ~285 s on the
  floor — the T51 expiry window; combat owned the ticks that long.
- **Ko rune order**: opened t=359 (unit 804); **id churn REBOUND live**
  (resights continue under unit 874, no duplicate order); clicks spent
  with no neighbours → `inventory.full` (a genuinely full grid this
  time) → `inventory.cleanse_queued` → **`inventory.cleanse` dropped 6
  items seven seconds later, mid-field** — the exact operator-observed
  2026-08-10 gap, closed and live-proven; post-cleanse retry ran;
  order closed `order_abandoned` "active budget spent" (76.3 s); the
  id churned AGAIN (unit 1094) and the closed order STAYED closed
  (convergence across ids, live-proven) — and the ordinary pickup
  sweep then **collected the rune anyway** under the new id.
- Census 2/3 (rejuv + ko rune in the bag; the "miss" is the rune's
  earlier id). The 7-click failure on the rune's first id is the known
  pickup-accuracy signature (T65's kind-class shape), pre-existing
  workstream, not this plan's regression.

Watchdog: no recurrence of the freeze (451 s and 644 s clean runs with
the faulthandler dead-man armed).

**The P5 census gate is now IN THE OPERATOR'S HANDS** (R246): review
the three logs and rule on `mandatory_pickup` beyond cold-plains.

## 2026-08-13 T87 (operator-requested, pre-R246): the 15-second stall

The operator ordered a 5-trip waypoint battery (town -> Black Marsh,
leave, remake) with per-trip logs, then spotted the finding the census
could not: the bot reached the waypoint in ~1.7 s and then STOOD IDLE
~15 s before clicking it — and suspected the same lost seconds plague
every run. Confirmed, and root-caused in three instrumentation rounds
(runs 1-13 in the drill log):

1. `nav.leg` town-walk telemetry: the walk was innocent (1.6 s + 0.9 s
   legs, zero replans); the hole sat BETWEEN instruments.
2. **The stack sampler** (`pd2bot/runlog/sampler.py`, the operator's
   "watch the python code" requirement, now permanent kit): a daemon
   thread samples the main thread's stack at 50 ms and span-compresses;
   always on in the real launcher, writing `logs/samples-*.log`. Its
   first two catches were identical 15.03 s / 15.09 s spans at
   `_await` inside `open_object_panel`: **the waypoint's first click
   misses the sprite from the spawn approach angle, and the code then
   waited the full `npc_walk_timeout_s` (15 s, sized for cross-town NPC
   journeys) for a panel that could never open.** The cold-plains
   pilots' "waypoint: done after 23 s" is the same burn — every run
   paid it on every first-click miss.
3. Fix (`997dec8`): `_await_interact` — a landed interact click either
   opens the panel or WALKS the character, so a character standing
   still 2 s with nothing open is a PROVEN miss and the retry starts
   immediately. Applied to the object path and the NPC-dialog path.
   Proof runs: waypoint.open t=7.0 s (was ~19), trip 13.0 s (was ~25);
   the systematic first-click miss now costs 2.8 s.

Still open, low priority: the waypoint's first click misses
systematically from the south-west approach (the (0,0) aim lands off
the sprite); a measured aim offset for that angle would save the
remaining ~2.8 s. The T83 drill generalises to measure it.
