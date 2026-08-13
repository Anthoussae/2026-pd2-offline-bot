# Notes — pickup name-tag calibration battery (R248 detour)

## The request (R248, resolved 2026-08-13 05:35)

The operator's proposal, verbatim in intent:

- Objective: determine the optimal name-tag display setting for
  whitelisted-item pickup accuracy.
- Three modes: (1) no tags (ALT off — the game's current state),
  (2) loot-filter tags (ALT on), (3) default non-filter tags
  ("F" to toggle; currently off). Double-check the keys against the
  known hotkey list.
- Method: drop all inventory items (NEVER the Horadric Cube), pick up
  whitelisted items only, ~30 s per round, ~5 rounds per mode, all
  back-to-back in one game. Town chores suspended during the test.
  Pick everything up between rounds; gather EVERYTHING at the end —
  no whitelisted item may be lost.
- Output: tabulate accuracy per mode — whitelisted collected, speed,
  non-whitelisted accidentally collected per round — and rule.
- Authorization: review/edit the proposal and run it if reasonable;
  query only on trouble. (The deferred R244 "(b)" pickup battery is
  this, defined by the operator as promised.)

## Discovery — the hotkey double-check (operator asked for it)

- **ALT confirmed.** The character keyfile
  (`C:\Program Files (x86)\Diablo II\Save\ProjectD2\MaqiuDoubing.key`,
  108 entries, parsed by `pd2bot.input.keyfile`) binds **Show Items =
  entry 37, primary ALT (0x12)** — the R247 registry already resolves
  it (`KeyBindings.show_items`). ALT acts as a TOGGLE (not hold)
  because `BH.json → game.always_show_items: true`; this matches T63's
  live finding and keys.py's note.
- **ALT state is READABLE from memory**: `offsets.BH_LABEL_DISPLAY`
  (BH.dll+0x14D2CA, found by T66; 1 = labels showing), accessor
  `perception.units.label_display_on`. Mode 1 vs 2/3 is therefore
  machine-verifiable — no blind toggle parity risk for ALT.
- **"F" is NOT recorded in any config.** Scanned: the keyfile (no
  entry binds 0x46 at all — so pressing F cannot fire a game
  function by accident, a useful safety fact), `BH.json` (all
  lootfilter hotkeys `"None"`), `ProjectDiablo.cfg` (no F). Best
  hypothesis: F is a PD2-hardcoded filter-level toggle —
  `BH.json` carries `filter_level: 0` with `last_filter_level: 8`,
  the flip-between pair such a toggle would maintain. Consequence:
  the F toggle must be PROVEN live before the battery trusts it —
  a T66-shape probe (press F 4×, diff BH.dll writable memory for the
  alternating byte) makes the F state readable too; if no flag
  survives, fall back to operator visual confirmation in chat at each
  mode switch (they are present throughout anyway).

## Discovery — the machinery (all of it already exists)

- **Drop**: `behavior/town/inventory.py::drop_item` — ctrl+right-click
  one inventory item to the floor, effect-verified ("gone from
  inventory"), stash must be CLOSED (R64), modifier settled (R113),
  stop-on-first-failure policy (Stage B run 4's portal incident).
- **What may be dropped**: the item-exception registry
  (`offsets.ITEM_EXCEPTIONS` → `RIGHT_CLICK_HAZARD_KINDS`,
  `UNMOVABLE_KINDS`) already protects the Cube (policy bit), tomes,
  scrolls, dungeon maps (right-click side effects) and ALL potions (a
  slipped ctrl drinks one). So "drop everything except the cube"
  becomes "drop every DROPPABLE item" — strictly safer than the
  request, and the cube constraint falls out of existing policy. The
  undroppable jumble members simply sit out the test (reported, not
  silent).
- **Whitelist verdicts**: `pickit.Pickit.wants` (ground items, the
  live pickup's own judge) and `pickit.cleanse_keep` (carried items,
  permissive mode). The drop phase classifies each dropped item as
  whitelisted-or-not at drop time, so the per-round denominator is
  exact.
- **Pickup**: the engine's real path — `steps` pickup machinery →
  `execute.py::_pick_up` (sprite-aimed schedule, `_await_interact`,
  goal-aware sprite escape — all of yesterday's fixes). Measuring
  anything else (e.g. a T76-style raw click loop) would measure the
  aim schedule, not the bot; the operator asked for the bot.
- **The label-policy conflict**: `execute.py::_pick_up` currently
  FORCES labels ON when `label_display_on()` reads False (the T66
  policy — "labels must be showing for the small classes to be
  clickable at all"). Mode 1 (tags off) is impossible until the
  executor grows a knob to leave the toggle alone. This is the one
  real code change to production behavior (default unchanged:
  enforce).
- **Run architecture**: runs are TOML step lists; town chores are
  suspended by simply NOT listing `town_preamble`. The run event log
  (always on) plus `python -m pd2bot.runlog --pickup` is the
  measurement substrate — per-item `action.pickup_attempt` /
  `item.collected` (with `attributed_to` for clicked-A-got-B) /
  `item.abandoned` already exist. The battery adds a small
  `battery.round` event (mode, round, dropped census, start/end) so
  the tabulator can cut the existing item stream by round.
- **Precedent shape**: T76 (archived pickup-reliability plan) staged
  arrangements and measured per-click outcomes; its lessons are
  carried (loose staging measured by the floor, not demanded of the
  operator; out-loud skips; solo-only rounds cannot PASS). T86 shows
  the drill-drives-town-layer pattern. T89 shows the demonstration
  kind.

## Design decisions (recorded before implementation)

1. **Engine step, not a freestanding drill.** A new step
   `tagmode_battery` + run file `runs/t90-tagmode-battery.toml`
   (steps: battery → done; no preamble). Reasons: the real pickup
   path comes for free; the run event log and census tooling are the
   tabulation substrate; the game cycle, safety monitor, watchdog and
   guarded-run protocol all apply unchanged. The step is test kit,
   clearly marked, like the pilot run files.
2. **Mode interpretation** (assumption the operator can correct in
   chat at zero cost): mode 2 = ALT on + filter tags (F off, the
   current styling); mode 3 = ALT on + default tags (F pressed);
   mode 1 = ALT off (F irrelevant — no tags drawn). The battery
   announces each mode switch in chat and (if the F flag was found)
   verifies memory state; a wrong interpretation is caught in
   seconds live.
3. **Interleaved mode order** — cycles of (1, 2, 3) × 5, not three
   blocks of five. Item attrition (anything lost or vanished mid-
   battery) then degrades all modes equally instead of biasing the
   later blocks. Toggles are cheap (one or two key presses).
4. **Round = drop phase → test phase (30 s cap, ends EARLY when every
   droppable whitelisted item is collected — time-to-done is the
   speed metric) → reset phase (gather ALL ground items, verified
   against the drop manifest).** The reset gather aims at every
   dropped item regardless of whitelist (direct PickUpItem actions,
   no pickit gate), because losing junk clutters the floor for the
   next round and losing whitelisted items is forbidden outright.
5. **Loss containment**: floor items vanish when the game ends, so
   exposure is capped at one round's droppables (~30–90 s window).
   The battery refuses to advance a round while any manifest item is
   unaccounted for; on abort/interrupt the standing rule is gather
   first, and the final act before `done` is a full-floor sweep +
   manifest reconciliation announced in chat. Residual risk (client
   crash mid-round) is named to the operator at the launch gate.
6. **F-flag probe precedes the battery** (same live session): T66's
   protocol pointed at F — 4 presses, diff BH.dll writable pages,
   keep the byte that alternates in lockstep. Found → `offsets.py`
   constant + accessor beside `label_display_on`, and the battery
   verifies mode 3 by read. Not found → blind toggle + operator
   visual confirmation at each switch (2 chat confirms per cycle).
7. **Tabulation** lives in the runlog package (a `--tagmode` report or
   a small script in the plan dir): per round — mode, dropped
   whitelisted/junk counts, whitelisted collected within cap,
   time-to-last-whitelisted, junk collected during test phase
   (accidental pickups, `attributed_to` cases), abandoned reasons.
   Per mode — means over its 5 rounds. The ruling stays the
   operator's (R-numbered verify request when the table is ready).

## Test set caveat (known before launch)

The character stands at the menu, so the inventory census cannot be
read until a game is up. If the droppable-and-whitelisted subset of
the jumble turns out thin (maps/scrolls are undroppable by registry;
potions never drop), the battery announces the manifest in chat
before round 1 and the operator may abort and restock the inventory.
The step must not silently run a 15-round battery over 2 items.

## Open items / future work

- If mode 1 scores near zero for small classes (T63 predicts labels
  are REQUIRED for charms/gems/runes to be clickable), the ruling may
  be quick — the battery still quantifies it honestly.
- The winning mode becomes the label policy the executor enforces
  (today it only enforces ON); wiring that in is a follow-up commit
  after the operator's ruling, not part of the battery.
- `filter_level` semantics (0 vs 8) were not needed for the battery
  design; if the F probe finds the flag, record what the two values
  mean in offsets.py at that time.

## P1 implemented (2026-08-13, same session)

Suite 1289 green, ruff clean. Deviations recorded in
01-offline-build.md's Implementation Result: no gather deadline
(hold-open-and-nag; losing an item outranks finishing the battery),
4-point drop scatter (a single mega-pile would confound the mode
comparison), and a fuller event family (`battery.begin/mode/round/
loss/end`). The engine's own guards were the design constraints: the
gather keeps clicking (acted) so never-idle stays honest, and the F
confirm window is ticked waits, so a chat `abort` lands between ticks.

One live-relevant note for P2: the battery anchors wherever the
character stands at each round's first drop tick — a guarded-run game
starts at the town spawn, which has NPC traffic nearby. If round 1
shows bystander interference (click dodges, stolen clicks), abort
cheaply and reconsider a walk-to-clear-ground preamble tick.

## R250 — the operator's redesign (2026-08-13, after launch 1)

Launch 1 (drill-log T90 row 1): round 1A ran clean — **4/4 whitelisted
in 5.7 s with labels OFF** — and reconciled; round 1B then exposed the
scatter-walk design's failure family live (walk clicks re-collect
labeled drops; a stash misclick wedged the drop-walk; the wedge ticks
all read "acted" so nothing tripped), and the abort exposed that RUNS
never wire `should_stop` at all. Nothing was lost.

The operator's edit spec, implemented the same session:

1. "abort the test" (chat) and the cancel file stop RUNS within a tick
   — `wiring.run_stop_channel`, standing for every future run.
2. Stray blocking panels (stash/NPC dialog) are closed in any phase and
   the battery carries on; the chat console is never touched.
3. Structure per the operator, replacing R248's interleave + scatter:
   one pile at the feet; drop everything but cube + tomes (potions,
   scrolls, maps INCLUDED — a deliberate registry override inside this
   battery, slip risk carried by the R113 settle + reconciliation);
   blocks 1A..5A / ALT / 1B..5B / F / 1C..5C; announce round before
   and score after; gather escalates to the operator ("resuming.").
4. Census reconciles over inventory + belt: a gathered potion routes
   to the belt (proven by the fake-world test — pile composition
   drifts by the belt-bound potions after round 1, which is honest
   client behavior, not loss).

Validation: 1293 tests, ruff clean. The relaunch gate is R250.

## The answer, and the R254 ruling (2026-08-13)

Fifteen measured rounds across four launches (T90 rows 1-5; the two
data runs are logs 20260813-074021 and -082022):

| mode              | accuracy       | mean time | timeouts |
|-------------------|----------------|-----------|----------|
| A - no name tags  | 30/30 (100%)   | 12.3 s    | 0/5      |
| B - filter tags   | 3/30  (10%)    | 30 s cap  | 5/5      |
| C - default tags  | 11/30 (36%)    | 30 s cap  | 5/5      |

**No tags wins by a landslide** — and the finding inverts standing
code: `_pick_up` had FORCED labels ON since T63/T66 ("labels must be
showing for the small classes to be clickable"), which this battery
falsified with its own instrument — the executor had been switching
itself into its worst mode before every pickup.

Operator ruling (R254, approved): invert the policy — pickup ensures
labels OFF, same parity-safe flag mechanics. The battery suspends
enforcement in ALL modes now (it owns the display). Field validation:
one ordinary cold-plains run's census vs the 18/31 (T71) and 5/11
(R240 smoke) baselines.

Also learned along the way, each now guarded in code:
- RUNS had no abort channel at all (`should_stop` never wired) — fixed
  for every future run (`wiring.run_stop_channel`; "abort the test").
- The watchdog "silent freeze" is a transient ~4-10 s stall WITH
  RECOVERY (5 occurrences); the engine now gives staleness a 15 s
  grace (operator-approved safety change), with stale/recovered on the
  record.
- A slipped ctrl during a drop DRINKS a potion and reads identically
  to a successful drop from the inventory side (3 healing potions paid
  across the session); the battery confirms every drop against the
  floor.
- Stackables merging on pickup read as census losses; discrepancies
  are announced-and-recorded, never fatal, while an operator watches.
