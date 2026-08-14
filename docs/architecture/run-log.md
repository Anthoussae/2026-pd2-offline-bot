# The run event log

Every run writes a structured, machine-readable record of what it did.
This document is the reference: where the files live, what an event looks
like, and what every event kind means.

**Read this before diagnosing a run.** It exists so that a future agent
or operator answers questions from data instead of reconstructing a
story — which is what produced two confident wrong diagnoses on
2026-08-05 before the log existed.

## Where

    logs/runs/<YYYYMMDD-HHMMSS>-<runname>/
        run.json        the header, written once at open
        events.jsonl    one JSON object per line, appended and flushed

One directory per run, nothing pruned (R220 Q2). `logs/` is gitignored:
this is machine-local run history, not source.

Read one with the renderer:

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog --kind step.decision
```

No argument renders the most recent run. `--kind` filters by prefix
(`action.`, `item.`, `step.`), `--since`/`--until` by seconds, `--raw`
passes the JSON through, `--no-collapse` prints one line per event.

## The envelope

Every event carries these, filled by `RunLog` rather than by the
emitter — an emitter that has to remember to stamp its own events will
eventually forget:

| field | meaning |
|---|---|
| `seq` | monotonic counter; ordering survives equal timestamps |
| `at` | ISO wall clock, local — what the operator saw on screen |
| `t` | seconds since run start, monotonic — what arithmetic uses |
| `kind` | dotted namespace, so a reader can filter by prefix |
| `area` / `area_name` | stamped from the tick's snapshot |

## Coordinates

Every spatial field carries three frames (`pd2bot/nav/mapframe.py`):

```json
{"world": [10002, 8013], "local": [2, 13], "rel": [-4, 11],
 "dist": 11, "bearing": "SW", "frame": "area-020"}
```

- **world** — absolute game subtiles, comparable with anything the game
  reports.
- **local** — the area's origin subtracted. The Forgotten Tower's
  staircase reads `(2, 13)` in a 40x40 room instead of `(10002, 8013)`.
- **rel** — offset from the character, with `dist` (Chebyshev, the same
  metric every reach and radius in the codebase uses, so a logged
  distance compares directly against `click_range`, `engage_radius`,
  `pickup_reach`) and `bearing`.
- **bearing** — the **screen** compass. Screen-north is the world
  (-1, -1) diagonal (R219): D2 renders isometrically, so decreasing both
  world coordinates moves up the monitor. "SE" means down-and-right on
  the operator's screen.
- **frame** — `area-020`, or `world` when the area could not be read.
  `world` means local == world and is stated, never silently assumed.

## Event kinds

### `tick` — one per engine tick

The record that closes the hole T71 fell into: 144 s in one room
produced five log lines out of ~150 decisions, because only ticks
carrying a note were recorded.

| field | meaning |
|---|---|
| `n`, `dur_s` | tick number and wall duration |
| `timing` | `snapshot` / `ladder` / `step` / `maintain` seconds — where the tick went |
| `step`, `step_index`, `outcome`, `note` | what owned the tick and what it decided |
| `player`, `hp`, `max_hp`, `mana`, `max_mana` | position (all three frames) and vitals |
| `hostiles`, `allies`, `ground_items`, `critters` | counts — cheap, and they settle "was there anything to fight?" without inference |
| `hostile_detail` | nearest four hostiles: `id`, `kind`, `hp`, `life_pct`, `dist`, boss/champion flags |

`critters` is the decorative-unit count (see `combat.write_off` below);
if it reads 0 in a room full of bats, the classifier has regressed.

### `step.decision` — one per step per tick

`step`, `outcome` (`done`/`acted`/`waiting`/`idle`), `note`. Emitted for
**every** decision, including the silent ones. The renderer collapses
consecutive identical decisions; the file keeps them all, so counts stay
exact.

### `action.*` — what actually reached the game

Emitted from `GameActionExecutor._record`, the single funnel every
executed action passes through. An `action.*` event means the send
completed; a refusal is a `refusal` event instead, and the two are never
blurred.

| kind | fields beyond the envelope |
|---|---|
| `action.move` | `target`, `origin`, `toward` (unit id when the walk was for one) |
| `action.attack` | `unit_id`, `target` |
| `action.cast` | `skill_id`, `skill`, `target` |
| `action.cast_self` | `skill_id`, `skill`, `at` |
| `action.interact` | `target`, `click_screen` — where the click actually aimed |
| `action.pickup_attempt` | `unit_id`, `item`, `item_kind`, `attempt`, `click_screen` |
| `action.drink` | `column`, `potion`, `hp`, `max_hp`, `mana`, `max_mana` |
| `action.merc_feed` | `column`, vitals |
| `action.park_skill` | `skill_id`, `skill` |

`origin` on a move is captured **before** the send: `walk_to` blocks
until arrival, so reading it afterwards would report every destination
as "0 away".

### `item.*` — what perception saw and what came of it

| kind | when | fields |
|---|---|---|
| `item.dropped` | a **wanted** item is seen for the first time this run | `unit_id`, `item`, `item_kind`, `quality`, `sockets`, `rule`, `position` |
| `item.collected` | a clicked item provably left the ground | `unit_id`, `item`, `potion`, `position`, `took_s`, `accidental`, and `attributed_to` + `attributed_aim` when another item's click produced it |
| `item.abandoned` | an item is written off | `unit_id`, `item`, `reason`, and then either `walks` (walk budget) or `clicks` + `aim_points` + `neighbours` + `position` (click budget) |

`item.abandoned` covers **both** write-off paths. The walk-budget one
("walks kept arriving short") has always fired; the **click**-budget one
was silent until 2026-08-06, and its silence is why T71 run 4's thirteen
misses — a Nef rune and a flawless emerald among them — could only be
found by correlating `action.pickup_attempt` against `item.collected` by
unit id in a throwaway script. Its `reason` names the diagnosis, as far
as observation allows (P4), distinguishing four causes rather than
blaming the inventory for all of them:
- `clicks did not land (belt has room)` — a potion missed, belt not full;
- `belt full for <type>` — a potion the belt genuinely cannot take;
- `pile ambiguity — clicks likely landed on a neighbour (<n> near)` — a
  non-potion with items packed around it; **not** a full inventory, and
  it no longer suppresses other loot;
- `aim failure for this item class, or a full inventory (unreadable)` —
  a non-potion, nothing nearby, nothing moved; persistence cannot tell
  the two apart, so the reason says both.

`aim_points` is the slice of `actions.PICKUP_AIM_POINTS` actually spent,
so "all 8 attempts failed" is a statement with contents. `neighbours`
counts other ground items within 2 subtiles — the signal that separates
pile ambiguity from a full inventory.

`item.collected`'s **`attributed_to`** names the unit a click was aimed
at when a *different* item came up — the "clicked A, got B" case. Nine
of T71 run 4's thirteen misses lay within 1–2 subtiles of an item that
did come up (a Nef rune missed while a Hel rune one subtile away was
collected), and the bot booked a clean success for the neighbour while
continuing to spend clicks on the target. The attribution is
deliberately conservative — it speaks only when the most recent click
targeted a different unit, is recent enough to still be resolving, and
was within 2 subtiles — because a loose attribution would poison the
measurement it exists to produce.

`item.dropped` fires on the transition into the wanted set, so a rune
lying on the floor for thirty ticks is one event. Pair it with
`action.pickup_attempt` to measure pickup accuracy per run without a
drill. An item that appears and vanishes with no attempt between is the
signature of the T70 Thul bug — a wanted item invisible to behaviour
while perception listed it.

**It is emitted from `_PickupMixin.log_wanted_drops`, called by
`wanted_items` — the one enumerator every collecting step shares.** That
placement is deliberate and was bought the hard way: until 2026-08-06 it
fired from `note_wanted_sightings` instead, which the clearance, the
sweep and the endgame call and **`TraverseStep` does not** — so T71 run
4 recorded four drops on the single floor that ran a clearance and none
on the four floors it descended through, collecting all the way. Any
future step that learns to collect gets the logging for free; a step
that grows its own item enumerator must call `log_wanted_drops` itself.

Two properties the emitter guarantees, both load-bearing:

- **Whitelist verdict only.** `pickit.decide` returning anything but
  `skip` is what logs. A full belt, a full inventory, or a walk that
  already gave up are facts about *us*; the drop is recorded either way.
- **Independent of any circle.** Radius filters belong to collection,
  not to the record. An item perception can see is logged even when no
  step is in a position to go and get it.

### `area.transition`

`from_area`, `from_name`, `to_area`, `to_name`, `via`, `exit_position`,
`arrival`, `clicks`. Both ends named, because "arrived in X" does not
say what you left.

### `combat.write_off`

A target that strikes have provably achieved nothing against:
`unit_id`, `monster_kind`, `strikes`, `hp`, `signature`.

(`monster_kind` was `kind` until 2026-08-13, when the field was found
clobbering the event kind on disk — see "the envelope's identity keys"
below. Logs written before that date carry these events with the
monster's kind NUMBER as the event kind.)

### `nav.failed`

One walk the navigator gave up on, absorbed by a step rather than
ending the run: `where` (the step), `action`, `target` (three-frame),
`toward`, `elapsed_s`, `detail` (the navigator's own trail).

`_PickupMixin.send` has always swallowed `NavigationError` — correct,
because one unreachable target is information about that target, not a
reason to end a game — but until 2026-08-06 it swallowed the event too.
T71 run 4's endgame spent **four ticks of 25–35 s each** in exactly this
path, visible only as tick durations with nothing inside them. The
absorb behaviour is unchanged; the silence is not.

### `nav.capped`

One `walk_to` that returned on its **wall-clock budget** rather than by
arriving or by giving up: `target`, `arrived_at`, `seconds`, `short_by`,
`clicks`, `replans`. Emitted by the executor, which is the only place a
`WalkResult` exists.

### `nav.plan`

One pathfinding attempt and its **price**: `source` (`walk` from the
navigator's plan cycle, `route_service` from the steps' read-only route
asks), `start`, `goal`, `target`, `duration_s`, `outcome` (`path` /
`no_path` / `no_walkable_cell`), and on success `path_cells` and
`waypoints`. Added 2026-08-13 (R257 P1) after the T92 human-vs-bot
comparison exposed a 47 s stall that was two unbounded A* floods —
~21 s each, visible only as tick durations with nothing inside them:
`nav.failed` reports a walk's verdict, never the plan's cost, so the
most expensive thing a tick can do was the one thing the log could not
see. Once the search is budgeted (R257 P2) the event also carries
`nodes` and `budget_exhausted`, which is how a genuine "no path" is
told apart from a budget stop.

A capped leg is not a failure and by itself not even a problem — the
step re-checks distance and asks again, which is what "capped legs" has
always meant here. But it is otherwise **invisible**: a short walk and a
normal walk look identical from outside. This event is what keeps "the
bot walked" and "the bot spent the whole run being capped" different
facts. Watch the rate, not the individual event.

### `safety.interrupt`

A safety condition detected **inside a blocking call** rather than at a
tick boundary: `verdict` (`life` / `mana` / `death` / `stop`), `reason`,
`hp`, `max_hp`, `pct`, `step`.

This event is the whole point of the 2026-08-07 fix, and it is the one
to look for when asking "would the bot have chickened in time?". Before
it existed, a chicken could only ever be raised between ticks — so a
walk that blocked for 24 seconds was 24 seconds in which the monitor was
not consulted, and the character died with the log still showing 100 %
HP from the snapshot taken before the block. See
`docs/reviews/2026-08-07-chicken-starvation-death/`.

The field is `verdict`, **not** `kind`: the writer merges fields over an
envelope that already owns `kind`, so a field by that name used to
rename the event out of the log it exists to appear in. This paragraph
predicted the exact bug that then shipped anyway: every
`pickup.order_*` event of the 2026-08-10 pilot batch carried
`kind=<item kind>` and was written with a NUMBER as its event kind,
invisible to every kind-filtered reader — a working order system was
misread live as never booking. Since 2026-08-13 the envelope's identity
keys (`seq`, `at`, `t`, `kind`) are inviolable: a colliding field is
preserved under `field_<name>` instead of clobbering. Emitters still
name such fields properly (`item_kind`, `npc_kind`, `monster_kind`) so
the rename never fires; the offline test fake goes further and FAILS on
a collision, because the fake's tolerance is how this one stayed
invisible through seven green tests.

### `watchdog.fired`

The out-of-process chicken watchdog (`pd2bot.watchdog`) pressed ESC:
`reason`, `pct`, `hp`, `max_hp`. Emitted by the BOT when it first sees
the watchdog's latch — so one artifact holds both processes' account of
the moment.

Its companion is the narration: an open ESC menu out of town used to
mean "the operator took the controls", and after a watchdog fire that
would be the only, and false, record of what happened.

## Reading a run

Beyond the timeline, `--pickup` prints the pickup census — wanted
against collected, per floor, with each miss's click count, neighbour
count and write-off reason, plus the attempts histogram:

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog --pickup
```

It derives from the **attempt** stream (a click is proof the pickit
wanted the item), so it works on logs written before the newer events
existed and reports missing fields as unknown rather than as zero.

- `no-contact` — our mana did not move, so the strike never connected
  (a phantom, a wall, a miss).
- `no-damage` — mana moved but the target's health did not, yet.

**Neither is a durable property.** Hell "immunity" is 100% resistance,
not invulnerability: characters and mercs deal mixed damage, Poison
Dagger pierces poison resistance, and a Lower Resist curse breaks
immunities outright. The write-off expires the instant a target's health
moves, and nothing is remembered across runs. These events exist so a
human can notice a pattern, never so the bot can teach itself that
something is unkillable.

### `chicken` and `death`

`reason` (`life`/`mana`), `hp`, `max_hp`, `pct`, `threshold`, `mana`,
`max_mana`, `area`. The two moments an operator most wants a precise
record of; previously the reason was a printed string that survived only
if a drill captured stdout.

### `inventory.cleanse`, `reflex`, `refusal`, `run.end`

- `inventory.cleanse` — `dropped`, `position`.
- `reflex` — `rung`, `reason`, `action`: which survival rung outbid the
  run step for this tick.
- `refusal` — `where`, `error`, `detail`, `streak`: a send that did not
  land (`InputRefused`, `CastInFlight`, `NavigationError`).
- `run.end` — `outcome` (COMPLETE / CHICKEN / IDLE BAIL / TOWN STEP
  FAILED / FAILED / …), `detail`. Documented from day one, EMITTED only
  since 2026-08-13: nothing ever called `close`, so every run's event
  stream just stopped — and a clean watchdog stand-down was
  indistinguishable from a crash until the narrative log was
  cross-read. The runner books it on every exit path.
- `watchdog.down` — the engine stood down because the required
  watchdog's heartbeat went stale (`WatchdogDown`, a clean
  ChickenExit-shaped leave). Distinct from `watchdog.fired`, which is
  the watchdog ACTING; this is it going silent. First live occurrence
  2026-08-13 (the watchdog froze at ~300 s with no error — the third
  such freeze; `faulthandler` dead-man dumps now instrument the
  watchdog loop for the next one).

## The rules the log obeys

1. **Never raises.** A logging failure disables the log, says so once,
   and the run continues. Instrumentation is not a dependency.
2. **Never blocks.** Append and flush; no rotation, no network. The file
   is readable while the bot runs and survives a crash.
3. **Never interprets.** Events record "clicked at X, the player was at
   Y", never "the click failed". Conclusions belong to the reader — the
   direct lesson of two wrong diagnoses drawn from silence.
4. **Honest absence.** An unreadable field is `null` with a reason where
   one exists, never a plausible default. A guessed value in a
   diagnostic log is indistinguishable from a real one.
5. **Always on.** `build_bot` opens a log unconditionally. The only
   silent path is `NullRunLog`, passed explicitly by tests and the sim.
   Optional instrumentation means the one run you most need to explain
   is the one where the flag was forgotten.

A disabled log costs nothing: emitters check `runlog.enabled` before
gathering anything, because `_here()` and `_vitals()` are live memory
reads and a silent log that still paid for them would make the
instrument observable in the behaviour it instruments.

## Deliberately not logged

**Enemy deaths** (R220 Q6, deferred by the operator as "might be too
complicated"). The reliable signal is an observed alive→corpse
transition; a unit that merely stops appearing has left perception, and
logging that as a kill would be exactly the false signal this log
exists to eliminate. The design is recorded in the plan's `notes.md` for
a later revival. **Nothing in the log claims a kill.**

## Adding an event

Instrumentation is part of the definition of done for a behaviour
change, not an optional extra (`docs/adr/2026-08-05-run-event-log.md`).
A new decision path emits, or it is a path nobody can debug. Call
`runlog.event("namespace.thing", **fields)`, put spatial values through
`mapframe.describe`, name items through the pickit's `ItemTable` with an
honest `kind <n>` fallback, and add the kind to the table above.

## Event kinds added by the combat & logistics bundle (2026-08-09, R241)

- `route.stray` — the leash: distance/nearest/progress when the
  character is beyond `[route] stray_subtiles` from the area's recorded
  line; emitted on the crossing and ~5 s heartbeats while out, with
  `returning` saying whether the posture policy allowed walking back.
- `pickup.order_open` / `pickup.order_resight` / `pickup.order_collected`
  / `pickup.order_gone` / `pickup.order_abandoned` — the mandatory-pickup
  lifecycle (pilot flag `mandatory_pickup` in a run file): every wanted
  non-potion drop is booked (`item_kind`, `item`, `unit_id`, `position`),
  and every order ends in exactly one of the three closes, with its
  accumulated ACTIVE pursuit seconds. `order_abandoned` carries `reason`:
  `"active budget spent"`, or `"click budget spent; the post-cleanse
  retry failed"` for an order closed early because everything a cleanse
  can change was already tried. Ground-item unit ids are NOT stable
  across room unload/reload (2026-08-10: one amethyst carried three ids
  in one run); the book rebinds an open order to the item's new id at
  the same kind+position — logged as a resight — and a CLOSED order
  stays closed whatever the id says.
- `town.restock` — one per restock station visit that reached (or
  skipped at) the buying decision: `bought` (belt-verified buys per
  type), `no_room` (types short by count but with no belt column to
  take them — not bought), `overflowed` (types stopped because a
  purchase landed in the inventory), `gold_before`/`gold_after`.
  First emitted 2026-08-13, with the over-buy fix: the station's
  2026-08-13 failure bought ~30 potions into the inventory precisely
  because an unverified vendor click was believed to be a non-event.

## Event kinds added by the cleanse-starvation fix (2026-08-13)

The 2026-08-10 diagnosis had to be made from the log's silence; the
cleanse path's decision points now speak (`docs/plans/
2026-08-09-combat-logistics/notes.md` carries the full story):

- `inventory.full` — `_mark_inventory_full` suppressed non-potion
  pickups for the rest of the game: `unit_id`, `item`, `position` of the
  item whose failed pickup triggered it.
- `inventory.cleanse_queued` — the cleanse flag went up (once per
  transition, not per tick): `reason` (`"pile-ambiguity write-off"` /
  `"no-neighbour write-off"`), `unit_id`, `item`.
- `inventory.cleanse_deferred` — a QUEUED cleanse did not run this tick:
  `reason` (hostiles in radius, or no cleanse service wired). Once per
  streak of the same reason, so a lingering fight is one event.
- `town.click_dodge` — a deliberate interact click found a bystander's
  sprite box over its aim (the T83 rule, applied to interact clicks
  after the 2026-08-10 stash misclicks): `target`, `strategy`
  (`"offset"` = a clear aim offset existed; `"wait"` = every aim was
  covered and the click waited for the pacer, `cleared` saying whether
  she moved before `aim_blocker_wait_s` ran out), `blocker_kind`,
  `blocker_position`, and the offsets involved.

## Event kinds added by the tag-mode battery (2026-08-13, R248/R250 — TEST KIT)

Emitted only by the `tagmode_battery` step (`runs/t90-tagmode-battery.toml`);
tabulate with `python -m pd2bot.runlog <dir> --tagmode`. Rounds run in
BLOCKS (the operator's R250 structure): 1A..5A no tags, 1B..5B loot
filter tags, 1C..5C default tags.

- `battery.begin` — the battery accepted its environment: `rounds`,
  `round_seconds`, the droppable census (`droppable`, `whitelisted`,
  `kept` — the cube and the two tomes), `wanted_kinds`,
  `labels_initial`, `filter_on`, `filter_readable` (True since T91
  pinned `offsets.BH_FILTER_STYLE`).
- `battery.mode` — one block's mode set and flag-verified: `block`
  (A/B/C), `mode` (1/2/3), `labels_on`, `filter_on`, `enforcement`
  (False = the executor's label force-on is suspended, block A only).
- `battery.round` — the round's phase boundaries, distinguished by
  `stage`: `drop_end` (`dropped` — one pile at the feet), `test_start`
  (`wanted_on_ground`, `junk_on_ground`, `wanted_kinds` — the
  tabulator's window opener and wantedness key; kind-based because
  ground unit ids churn), `test_end` (`elapsed_s`, `timed_out`,
  `collected`, `wanted_left`, `junk_collected` — the announced score),
  `gather_end` (`elapsed_s`, `reconciled`, `operator_assisted`). All
  carry `block`/`round_no`/`mode`. The per-item evidence between
  `test_start` and `test_end` is the ordinary item stream.
- `battery.assist` — the between-round gather handed to the operator
  (R251: it is THEIR job, immediately — the bot never collects between
  rounds): `block`, `round_no`, `remaining`. The battery holds
  hands-off until the floor clears, then says "resuming.".
- `battery.consumed` — a drop left the inventory but never landed on
  the floor (a slipped ctrl fires the bare right-click; launch 3 drank
  a healing potion this way): `item_kind`, `block`, `round_no`. The
  item is excluded from the census and the battery continues.
- `battery.loss` — the floor read empty but the census (inventory +
  belt) still did not reconcile: `missing`/`gained` kind counts.
  Announced and RECORDED, never fatal (stackables merge on pickup,
  which a count census reads as loss) — the battery continues; the
  operator is present and `abort` is theirs.
- `battery.end` — `completed` (False carries `why`), `rounds_done`.

Same change set (R250): RUNS now honor the abort channel drills always
had — `abort` / `abort the test` typed in game chat, or
`tools\drill-cancel.ps1` — via `wiring.run_stop_channel`, polled every
tick and from inside every walk.

## Watchdog staleness grace (2026-08-13, R253 — operator-approved)

The watchdog transiently stalls ~4–10 s and RECOVERS (five healthy
runs died to instant declaration before the diagnosis; the T90 row 4
teardown caught the recovery in the act). The engine now requires the
heartbeat to read stale continuously for `watchdog_stale_grace_s`
(15 s) before declaring the watchdog down. Track A (the in-process
safety poll, ADR 2026-08-07) is untouched. New event kinds:

- `watchdog.stale` — the first stale read; carries `grace_s`. The
  transient stalls were invisible for five runs because nothing spoke
  until the run was already being ended.
- `watchdog.recovered` — the heartbeat came back inside the grace.
- `watchdog.down` — staleness outlasted the grace (carries `stale_s`),
  or no heartbeat channel is wired at all; the run stands down.
