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
