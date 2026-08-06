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

Every spatial field carries three frames (`pd2bot/mapframe.py`):

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
unit id in a throwaway script. Its `reason` mirrors the decision the
step is making rather than second-guessing it: `clicks did not land`,
`belt full for <type>`, or `inventory full (inferred from persistence)`.
`aim_points` is the slice of `actions.PICKUP_AIM_POINTS` actually spent,
so "all 8 attempts failed" is a statement with contents. `neighbours`
counts other ground items within 2 subtiles, because item density is the
leading hypothesis for why these clicks miss.

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
`unit_id`, `kind`, `strikes`, `hp`, `signature`.

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
- `run.end` — the outcome.

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
