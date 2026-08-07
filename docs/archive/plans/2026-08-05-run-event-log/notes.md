# Notes — the run event log

Discovery log for the structured-logging upgrade. Live document: user
answers, scope changes and new questions land here as they happen.

## Why this exists (the driving failure)

T71 run 1 (2026-08-05) died in the **Forgotten Tower**, and the
investigation that followed could not say why — not because the bot did
something subtle, but because **the artifact did not record it**.

The numbers, which are the whole argument for this plan:

| Measure | Value |
|---|---|
| Time in the room | 144 s |
| Ticks (whole run) | 193 over 203 s (~1.05 s/tick) |
| Estimated ticks in the room | ~140–170 |
| Decisions recorded | **5** (all "clicked the staircase") |
| Reflex fires, whole run | 6 (none in the Tower) |

**The room is empty.** User, 2026-08-05: *"There were no monsters in the
forgotten tower floor, and there never are. It is just an empty square
with an entrance and an exit."* This is decisive and it kills both
hypotheses the agent produced from the silence:

- *"the entrance fight owned the ticks"* — there is no fight. Dead.
- *"monsters were standing on the staircase"* — there are no monsters.
  Dead. (The `exit_block_radius` rule added on the strength of it is
  now unmotivated; see Open Questions.)

And it makes the arithmetic much sharper. In an empty room with no
ground items, `TraverseStep` should fall through to the click branch on
**every** tick and click every `exit_retry_s` (3 s) — roughly 48 clicks
in 144 s. It made **5**, i.e. one per ~29 s. So ~26 s per cycle went
somewhere that nothing in the codebase records.

Candidate sinks, none of them yet evidenced (this is exactly the
guesswork the plan exists to end):

1. **Tick cost.** 1.05 s/tick against a 0.2 s configured interval means
   ~0.85 s of work per tick. Where? `Perception.snapshot()`,
   `read_carried_items` (this character carries hundreds of items and
   the M6 P4 traverse-collect now calls `carried()` every tick),
   `read_level_exits` (walks the room chain), the executor's `maintain`.
2. **The progress-aware click pacing.** `_clicked_at` resets on every
   subtile of progress toward the stairs, so a character creeping
   forward suppresses its own re-clicks indefinitely.
3. **The click landing as a walk order.** `InteractObject` clicks the
   raw tile projection with no offset, while T63 measured tile clicks
   missing item sprites ~29/30 (hence pickup's 8-point aim schedule).
4. Something not on this list — which is the point.

**The template argument** (user): a square empty box with one entrance
and one exit is the simplest space in the game. If the bot cannot cross
it swiftly and reliably, navigation or mapping is wrong in a way that
affects every space. The fix must come from debugging, never from
special-casing this room.

## What is already proven (do not re-derive)

- **The atlas is correct and current for area 20.** Loaded with the
  bot's own `MapStore`: the Tower is one 40×40 room at origin
  (10000, 8000) holding a 19×19-subtile walkable box. Arrival
  (10006, 8002) and staircase (10002, 8013) are both `known` and
  `walkable`, 11 subtiles apart.
- **Pathfinding works on it.** The bot's own `astar` returns 12 steps,
  `simplify` reduces it to one leg: `[(10006,8002), (10002,8013)]`.
- **The seed matches** (`maps/4e52715f-d2/` is the only seed directory;
  `area-020.json` was rewritten *during* the run).
- **Routing was never invoked in that room.** 11 ≤ `click_range` 18, so
  the step goes straight to clicking and never plans a walk. Whatever
  is wrong, A* was not asked to do anything.

Full working: `docs/plans/2026-08-03-m6-countess/navigation-diagnosis.md`
(T71 addendum) and `t71-tower-decision-log.md`.

## Current logging surfaces (the state of the art in this repo)

| Surface | Module | Shape | Problem for this purpose |
|---|---|---|---|
| Narrative log | `pd2bot/narrate.py` | `HH:MM:SS  text` → `logs/run-<stamp>.log` | Human prose, deliberately coarse ("one line per meaningful act"), no schema, no coordinates, no tick data. Good story, unusable as data. |
| Micro-log | `RunServices.log` | `print("  " + line)` | stdout only — survives only if a drill captured it. Unstamped. No schema. |
| Engine report | `EngineReport.log` | in-memory list | Only records ticks whose outcome carries a `note`; every silent path vanishes. This is the T71 hole. |
| Executor trace | `TraceEntry(at, action, detail)` | in-memory list | Monotonic stamp + action + detail — the closest thing to an event log, but in-memory, never persisted, no coordinates beyond the action's own. |
| Drill log | `docs/drill-log.md` | markdown table | One row per drill run. Summary, not detail. |
| Preamble/travel reports | `PreambleReport`, `TravelReport` | `.log` string lists | Per-operation prose, folded into the narrative. |

**Nothing is persisted as structured data, and nothing is timestamped
uniformly.** Reconstructing a run means correlating prose across three
in-memory lists and one file — which is what produced the guesswork.

## Instrumentation points found during discovery

- **`GameActionExecutor._record(action, detail)`** — the single funnel
  every executed action passes through (`MoveTo`, `AttackUnit`,
  `CastAtPoint`, `CastSelf`, `PickUpItem`, `InteractObject`,
  `DrinkPotion`, `GiveMercPotion`, `ParkSkill`). One hook here covers
  most of the user's list. `RecordingExecutor` shares the shape.
- **`BehaviorEngine.tick()`** — the natural home for per-tick records
  (duration, phase, step, refusals, ladder decisions).
- **`TownLayer`** — `deposit_to_stash`, `deposit_all`, `open_npc_dialog`,
  `open_object_panel`, `heal_at_akara`, `repair_at_charsi`, `fill_belt`,
  `cleanse_inventory`, `close_panels`, `_clear_stray_ui`.
- **`WaypointTravel`** — `open_panel`, `select_tab`, `click_destination`,
  `await_arrival`, `take`.
- **`SafetyMonitor.tick`** — chicken (life and mana thresholds).
- **`ReflexLadder`** — potion drinks, merc feed, armor recast, escape.
- **`TraverseStep`** — area transitions (proven by area id).
- **`Perception.snapshot()`** — the source for drops, collections and
  deaths.

## Item naming

A vocabulary already exists and is trustworthy: `config/item_ids.toml`
(verified ids with provenance, `[codes]` anchored to D2 item codes) plus
`config/item_codes.toml` (T42-generated, kind → code) and
`item_ids.learned.toml` (T39 drill discoveries). `load_item_table` /
`load_item_codes` in `pickit.py` load them.

Names are anchored to **codes, not numeric kinds** (R144: numeric review
approved six wrong elite armours and the bot picked up a Wire Fleece
believing it was a Kraken Shell). The log must reuse this table rather
than invent a second naming path, and must fall back honestly to
`kind <n>` when a kind has no verified name — never guess a name.

## Coordinates

Three frames are wanted, and all three are cheap:

- **World subtiles** — what units already report, e.g. (10006, 8002).
  Absolute and global, but unreadable and area-ambiguous at a glance.
- **Area-local** — world minus the area's origin
  (`Area.bounds_subtiles`, i.e. `Area.position × SUBTILES_PER_TILE`).
  The Tower arrival becomes ~(6, 2) and the staircase ~(2, 13). This is
  the "simple X/Y coordinate system encompassing the surveyed map area"
  the user asked for, and it costs one subtraction.
- **Character-relative** — target minus player position, so a movement
  command reads as "11 subtiles south-west of me".

Screen-north (the world (−1,−1) diagonal, R219) should be carried as a
compass label so the log reads in the operator's terms.

## Decisions (R220, answered 2026-08-05)

| # | Decision | Answer |
|---|---|---|
| Q1 | JSONL on disk + a renderer for the human timeline | **yes** |
| Q2 | `logs/runs/<stamp>-<runname>/` with `events.jsonl` + `run.json`; keep all runs | **yes** |
| Q3 | Every spatial event carries world, area-local and character-relative frames | **yes** |
| Q4 | Every event carries ISO wall-clock and monotonic seconds-since-start | **yes** |
| Q5 | Item names from the existing code-anchored tables; honest `kind <n>` fallback | **yes** |
| Q6 | Enemy-death events on alive→corpse transitions | **NO — DEFERRED** (see below) |
| Q7 | "Accidental" = unrequested state change (item/panel nobody asked for) | **yes** |
| Q8 | Narrative log kept alongside the event log | **yes** |
| Q9 | Per-tick timing (tick duration; snapshot/ladder/step/send split) | **yes** |
| Q10 | Revert the `exit_block_radius` contested-staircase rule | **yes** |
| Q11 | Logging MANDATORY for anything touching the live game | **yes** |

**Q6 deferred** (user: *"defer for now; might be too complicated"*).
Enemy-death events are **out of scope** for this plan and move to future
work. Nothing in the plan may emit a death event, and the corpse-based
transition tracking is not built. Rationale accepted: the reliable
signal requires per-unit alive→corpse bookkeeping across ticks and area
changes, which is real state with real false-signal risk, and the log is
worth more delivered sooner without it.

**Q11 accepted — logging is mandatory.** `build_bot` opens a run log
unconditionally; the only silent path is an explicitly-passed null sink
for unit tests and the sim. The reasoning that carried it: optional
instrumentation means the one run you most need to explain is the one
where the flag was forgotten — which is exactly how T71 happened.

## Enemy deaths — what is unequivocal (DEFERRED, Q6)

*Kept for the future-work entry; nothing in this plan implements it.*

`GameSnapshot.corpses` holds dead type-1 units; `Monster.is_corpse` is
`mode in (MONSTER_MODE_DEATH, MONSTER_MODE_DEAD)`. The reliable signal
is a **transition**: a `unit_id` observed alive in this area on an
earlier tick, later observed with a corpse mode. A unit that simply
stops appearing has left perception (fog of war) and must **never** be
logged as a death — which is exactly the false-signal case the user
ruled out.

## Out of scope

- Log pruning/rotation. The user wants every run kept for now.
- Any change to what the bot *does*, except where P5's diagnosis proves
  a defect and fixes it.
- Re-deriving the atlas/A* findings above.

## Open questions carried into the plan

- ~~The `exit_block_radius` rule~~ — **resolved (Q10): revert it.**
  Unmotivated once the room is known to be empty, and it adds a 10 s
  hold. P1 removes it and its three tests.
- `EngineReport.log` stays as the in-memory summary it is; the event log
  does not replace it (it has a different consumer — the drill's
  one-line result row).

## Future work

- **Enemy-death events (Q6, deferred).** The reliable signal is a
  transition: a `unit_id` seen alive in this area on an earlier tick,
  later seen with a corpse mode (`Monster.is_corpse` —
  `MONSTER_MODE_DEATH`/`MONSTER_MODE_DEAD`). A unit that merely stops
  appearing has left perception and must never count. Needs per-unit
  bookkeeping that survives ticks and resets on area change. Revisit
  once the log has proven itself.
- Log pruning once the format has settled (the user wants everything
  kept for now).
- A log-diff tool ("what changed between run 4 and run 5") once several
  comparable runs exist.
- The collision recorder writing rooms under the wrong area id during an
  area flip (found in `area-020.json` and `area-025.json`) — a real
  robustness bug, unrelated to logging.

## T72 — the first run under the log (2026-08-06)

The probe reproduced the failure and the log answered the question that
two rounds of speculation could not. Run:
`logs/runs/20260806-005512-m6-tower-probe/` — 620 events, 230 ticks,
204 s, `PASS` (a reproduced failure WITH a log is what the probe was for).

### What the log says, as data

- **173 s in the Forgotten Tower**, 184 ticks.
- **Two hostiles present on essentially every tick** — `hostiles=2`
  almost unbroken from arrival to give-up.
- **46 attacks: unit 650119 x23 and unit 650120 x23.** Both were still
  alive at the end. Twenty-three strikes each, no death.
- **Only 5 staircase clicks got through in 173 s**, and the click budget
  is 5. Every one was sent from close range — `dist` 4, 4, 5, 9 — with
  the character 1-5 subtiles from the exit while "waiting out the last
  click".
- 4 `CastInFlight` refusals, all in the first 11 s (the known arrival
  contention, already priced in performance-notes).
- The step decisions read `fighting: MoveTo` / `fighting: AttackUnit`
  in an unbroken alternation for the whole stay.

### The defect this names

**The bot has no concept of "I cannot kill this."** It struck two units
23 times each, neither died, and it never re-decided. Because brisk's
`engage_radius` is 12 and the Tower's walkable box is 19x19, a hostile
anywhere in the room is always in range — so `engage` owned nearly every
tick and the traverse step only slipped a click through occasionally.
The 5-click budget then expired against a transition that was never
given a fair attempt.

Note what this is NOT: not the atlas, not A*, not the click aim (still
unproven either way), and not a monster "contesting" the staircase.

**Strong hypothesis for why they would not die:** immunity. This is Hell
difficulty and the character is a poison-dagger necromancer whose only
offense is poison; poison-immune monsters are common in Hell and a
poison-immune monster is literally unkillable by this build's attack.
That is a build-level fact the bot currently cannot represent.

**Correction to a stated premise.** The user's *"there were no monsters
in the forgotten tower floor, and there never are"* does not hold for
this game: the log shows two hostiles in area 20 throughout. Worth
knowing why the two can both be true — **the map is fixed per
character+difficulty, but the monster population is re-rolled every
game.** The bot creates a fresh game per cycle, so "that room is empty"
is not a property any run can rely on. (It also means my earlier
"the fight owned the ticks" guess happened to be right about T71 — but
it was still a guess at the time, made from silence, and the code change
built on it was correctly reverted.)

### Instruments added in response (the discipline this plan exists for)

The log could not answer two follow-ups, so it grew rather than being
argued with:

1. `hostile_detail` on every tick — the nearest four hostiles with
   `kind`, `hp`, `life_pct`, `dist`, boss/champion flags. "Is this fight
   going anywhere?" is unanswerable from a count, and it is the first
   question a stalled run raises.
2. **The area stamp was never wired.** `RunLog.area()` existed and
   nothing called it, so all 620 events came back with no `area` field
   and "how long was it in the Tower?" had to be reconstructed from
   coordinates. Now stamped from the snapshot at the top of every tick.

### Open for P5

- Confirm immunity from `hostile_detail` (a flat `life_pct` across 20+
  strikes is the signature) and identify the monster kind.
- Then decide the general rule — this must not be a Tower special case.
  Candidates: a per-unit "damage is not landing" write-off feeding the
  existing unreachable machinery; brisk disengaging from anything it has
  struck N times without progress; treating an unkillable blocker as a
  reason to route around rather than through.
- The click-aim question (tile projection vs sprite) is STILL OPEN and
  now clearly secondary: with the fight owning the ticks, the clicks
  never got a fair trial.

## The hostile-detection defect (T72 -> T73)

**The user's correction, accepted:** there were no hostiles and no real
attacks in the Forgotten Tower. The bot was chasing phantoms. My previous
message read a broken sensor as ground truth and reported it as fact —
the same error as the two guesses before it, one layer down.

**Proof from T72's own log, independent of anyone's recollection:** the
run counted `hostiles=2` and then `hostiles=5` while standing in the
**Rogue Encampment**, which contains no hostile monsters. A classifier
that finds enemies in town is wrong wherever else it is used.

### How a hostile is decided today

`pd2bot/units.py`:

```python
alignment = stats.get(offsets.STAT_ALIGNMENT, 0)   # _read_monster
def is_ally(self): return self.alignment == offsets.ALIGNMENT_FRIENDLY  # 2
(allies if monster.is_ally else monsters).append(monster)   # scan_units
```

Two independent faults:

1. **Hostility is inferred from ABSENCE.** `read_stats` returns `{}` for
   an unreadable stat list, `.get(172, 0)` turns that into 0, and 0 is
   not 2, so the unit is an enemy. A torn read, a stat-less unit and a
   real monster are indistinguishable — and the fail direction is
   "attack it". Everything else in this codebase fails safe; this does
   not.
2. **Locality is a radius, not a level.** `scan_units` keeps anything
   within 80 subtiles. Its own docstring says the hash table holds "the
   whole stash, units from other levels, expired summons". Every unit's
   level is readable — Path -> Room1 -> Room2 -> Level -> dwLevelNo —
   and nothing checks it.

Fault 1 was **already documented** in `offsets.py`: *"generic townsfolk
(e.g. the kind-149 rogue guards) lack the friendly-alignment stat
entirely, so they show up in the monster list in town — one more reason
combat logic never runs there."* The defect was found, written down, and
worked around by not fighting in town. Nobody asked whether it happens
outside town. It does, and outside town combat runs.

### What kolbot does (checked, not assumed)

`d2bs/kolbot/libs/SoloPlay/Modules/Clear.js:120`:

```js
getUnits(1, -1).filter(m => m.area === me.area && m.attackable && ...)
```

- **`m.area === me.area`** — an explicit AREA filter, the exact check we
  are missing.
- **`m.attackable`** — a d2bs property implemented in C++. This clone
  carries only the JS scripts and `sdk/globals.d.ts` (`readonly
  attackable: boolean`); the C++ source is NOT present, so its algorithm
  cannot be read here and must not be guessed at. What transfers is the
  shape: *same area* AND *a positive attackability test* — never
  "did not prove itself friendly".

### The overhaul, pending T73's evidence

Direction, not yet implemented — the probe decides between these:

- **Positive hostility, not absence of friendliness.** `is_ally` becomes
  a three-state read: FRIENDLY (stat says 2), HOSTILE (stat says
  something else), UNKNOWN (no stat / unreadable list). Only proven
  HOSTILE is fought. UNKNOWN is surfaced loudly and left alone — the
  fail-safe direction, matching the rest of the codebase.
- **An area filter** on `scan_units`, kolbot's `m.area === me.area`, via
  the room chain that is already readable.
- **Whatever T73 shows** — if the phantoms carry the alignment stat and
  sit in the right level, both fixes above are insufficient and the real
  discriminator is something else (the MonStats `npc` column via
  `pMonstatsTxt` is the next candidate).

### Why the counts are odd (open)

Expected in the Tower: merc + 3 revives = 4 allies. Observed: 4 allies
AND 2 hostiles — six type-1 units where four were expected. So the
phantoms are not simply the revives misclassified (that would be 3 and
0). T73 answers what they are.

## T73 — the census, and the fix it killed (2026-08-06)

Two read-only censuses. The first settled what the phantoms are; the
second destroyed the fix the first appeared to justify.

### Census 1 — the Forgotten Tower (stable across 4 samples)

| verdict | id | kind | stats | align | what |
|---|---|---|---|---|---|
| ALLY | 1 | 271 | 76 | `2` | the merc |
| ALLY | 49, 50, 51 | 24 | 14 | `2` | the 3 revives |
| HOSTILE | 650373, 650374 | **159** | **5** | **ABSENT** | the phantoms |

Exactly the room the operator described — character, merc, three
revives — plus two kind-159 units carrying a readable 5-stat list with
**no alignment stat in it**, in the correct level (20), moving
(modes 1 and 2), persisting across every sample.

So: **the level filter is NOT implicated** (all lvl 20), and the
phantoms are not misclassified revives (those read correctly as
allies). The bot attacked two non-combat units 23 times each because
they failed to prove they were friendly.

### Census 2 — Tower Cellar 1, with real monsters

**39 hostiles, and ALL 39 read `align ABSENT`. Zero carry the stat.**

That kills the fix census 1 seemed to license. "Absent means unknown,
never attack" would have made the bot completely pacifist. It was one
step from being written.

| class | kinds | stats | hp | align |
|---|---|---|---|---|
| ally (merc) | 271 | 76 | 128 | `2` |
| real monsters | 21, 55 | 9-10 | 128 | ABSENT |
| phantoms | 159 | 5 | 100 | ABSENT |

### What is now established

1. **Alignment separates ALLY from everything else** — and nothing more.
   Allies have stat 172 == 2; monsters and dummies alike have no stat
   172 at all.
2. **Nothing in the current code separates a real monster from a
   non-combat unit.** That is the whole defect, stated precisely.
3. The `flags` byte at `MONSTER_FLAGS` is `0x00` for real monsters AND
   phantoms here, so it is not the discriminator either (it does carry
   the boss bit — T68 read the Countess through it).
4. Kind 159 appears in BOTH the Forgotten Tower and Cellar 1, always
   with 5 stats and hp 100. Ubiquitous, non-combat, and currently
   indistinguishable from an enemy.

### The route to the fix (T74, built, not yet run)

kolbot's `sdk/globals.d.ts` declares `readonly isNPC: boolean` on a
unit, so D2 carries this distinction; d2bs reads it in C++ that is not
in our reference clone. In game data it comes from MonStats.txt, reached
via `MonsterData -> pMonstatsTxt` (first field).

`drills/t74_monstats_diff.py` does what this project always does with an
unknown offset: read the same structure for a known-good and a
known-bad example and **diff the bytes**. It dumps, per kind in range,
the MonsterData block and the MonStats record, then prints the
differing byte offsets between a real monster and a kind-159 unit, plus
the stat indices each has that the other lacks.

Whatever separates them is the flag. Found by measurement, not by
guessing at a struct layout — three guesses have already been wrong in
this investigation and each one cost a live run.

### Independent of all the above

A **"damage is not landing" write-off** is needed regardless: 23 strikes
on one unit with no health change should end that unit's candidacy as a
target, whatever it is. It bounds this class of failure even when the
classifier is wrong, and it is also the answer to Hell immunities, which
a poison-only build will meet constantly. Design it after T74 so the two
fixes are not confused with each other.

## T74 — the phantoms identified, and the discriminator found (2026-08-06)

**The operator's theory was right.** From the chair: *"I think they might
be cosmetic bats. When I stand in the tower room, there are
uninteractable bats that fly back and forth... Similarly, in the rogue
encampment there are some cows and chickens."*

The MonStats records confirm it. Each record carries D2's four-character
monster code at +0x10:

| kind | code | what |
|---|---|---|
| 21 | `FA` | Fallen — real monster |
| 55 | `GM` | Goatman — real monster |
| **159** | **`B9`** | **the bat** |
| 271 | `RG` | Rogue — the merc |

So the bot spent 173 s of T72 attacking two **decorative bats**, and the
2-then-5 "hostiles" in the Rogue Encampment are the operator's cows and
chickens. Every observation now has one explanation.

### The discriminator: STAT_LEVEL (12)

The stat lists settle it more cleanly than any byte in the record:

| unit | stats |
|---|---|
| Fallen (21) | 6, 7, **12**, 36, 39, 41, 43, 45, 67, 68, 69, 190, 328 |
| Goatman (55) | 6, 7, **12**, 36, 39, 67, 68, 69, 328 |
| merc (271) | 6, 7, **12**, 39, 41, 43, 45, ... (76 total) |
| **bat (159)** | **6, 7, 67, 68, 69** — and nothing else |

The bat's five stats are hp, max-hp and three movement/animation rates:
exactly enough to draw and move a sprite. It has **no level, no
resistances, no experience** — none of the machinery of a thing that can
fight or be fought.

**Rule: a combatant carries combat stats. Scenery does not.**

Implemented as an OR of combat markers rather than a single stat, and
deliberately so — the failure direction that frightens us now is a
PACIFIST bot (the mistake T73 caught one step from being written), so
the test is generous about what counts as a combatant and strict only
about what carries none of it:

    combat-rated = has STAT_LEVEL
                or has any resistance stat (36/39/41/43/45)
                or has STAT_EXPERIENCE

Any real monster has a level. The bat has none of the three. A monster
whose resistances all happen to be zero still has a level, so the OR
costs nothing and guards against D2 omitting zero-valued stats.

### Why not the record bytes

The 21-vs-159 diff produced 39 differing bytes, several of them plainly
combat-shaped (+0x56/+0x58/+0x5a/+0x5c/+0x5e are non-zero for the Fallen
and zero for the bat). Any of them would probably work. None of them has
a NAME we can defend, and this investigation has already cost four
wrong-but-plausible conclusions. A stat index the codebase already
names (`STAT_LEVEL = 12`) is checkable by anyone reading the code; an
unnamed byte at +0x5c is a second thing to be wrong about later.
