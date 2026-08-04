# Perception: how the bot sees the game

The bot never runs inside Diablo II. It is a separate Python process that reads
the game client's memory and interprets what it finds. This document explains
how that works, where the numbers come from, and what to do when a patch breaks
them.

Background on why this approach:
[ADR: Python + out-of-process memory reading](../adr/2026-07-28-python-out-of-process-perception.md).

## The shape of it

```
Game.exe (PD2 client, 32-bit, elevated)
   |
   |  ReadProcessMemory
   v
GameSession          pd2bot/memory.py     attach, resolve module base, typed reads
   |
   +-- offsets       pd2bot/offsets.py    every constant, each citing its source
   +-- units         pd2bot/units.py      unit primitives + hash-table sweep
   +-- player        pd2bot/player.py     the character's own state
   +-- world         pd2bot/world.py      current area, map seed
   +-- uistate       pd2bot/uistate.py    which panels are open, may we act
   |
   v
Perception.snapshot() pd2bot/snapshot.py  one coherent view per tick
```

Everything above perception consumes `GameSnapshot`. Nothing else in the
codebase should read memory or know an offset.

(As of M4, the *menus* are perceived too — which screen is up, where its
buttons are — via the D2Win control list, out of the player-unit world
this document describes. See [game-cycle.md](game-cycle.md).)

## Attaching

`GameSession` opens `Game.exe` and resolves `D2Client.dll`'s base address at
runtime — the client is relocatable, so every module-relative offset is added to
that base rather than hardcoded absolutely. The module reports itself as
`D2CLIENT.dll`, so matching is case-insensitive.

**The bot must run as Administrator.** The PD2 client runs elevated, and Windows
refuses `OpenProcess` from a lower-integrity process. `GameSession` detects this
and says so rather than failing obscurely later.

## Where the offsets come from

PD2 ships its own open-source maphack, [Project-Diablo-2/BH](https://github.com/Project-Diablo-2/BH),
which is maintained alongside the mod and therefore describes *the exact client
we target*. `pd2bot/offsets.py` is derived from its `D2Structs.h` and
`D2Ptrs.h`, and every entry cites the file and line it came from.

BH lists offsets per game version, 1.13c first. PD2's client is 1.13c, so the
first address in each of BH's macros is ours.

**These are not a contract.** A season patch can move them. When the bot starts
reading nonsense after an update, re-fetch BH and re-derive; the citations exist
precisely so that is a mechanical job rather than an investigation.

## Reading the player

```
D2Client + PLAYER_UNIT_PTR  ->  UnitAny*      (null when not in a game)
UnitAny.pPlayerData         ->  name
UnitAny.pPath               ->  position
UnitAny.pStats              ->  StatList      ->  everything numeric
UnitAny.pAct                ->  Act.dwMapSeed
UnitAny.pPath -> Room1 -> Room2 -> Level      ->  which area
```

Any pointer in these chains can be null during a loading screen or area
transition. That is a normal state to poll through, so reads return `None`
rather than raising.

### The stat trap

`StatList` holds **two** arrays:

| array | offset | contents |
|---|---|---|
| base | `pStat` +0x24 | stats *before* item and skill bonuses |
| full | `pSetStat` +0x48 | the computed totals ← **use this one** |

Reading the base array during M1 produced `hp = 961, max_hp = 920` — a current
value above its own maximum. The offsets were right; the meaning was wrong. This
is the failure mode to watch for in memory reading: structurally valid,
semantically nonsense. It was caught by a human noticing an impossible number,
which is why live verification against the game's own display is part of the
process and not an optional nicety.

Separately, only some stats are fixed-point: hit points, mana and stamina need
`>> 8`; attributes, level, gold and experience are plain integers, and shifting
them silently yields zero. `offsets.FIXED_POINT_STATS` is the authority;
`units.read_stats` applies it so no caller has to remember.

## Finding monsters and items

Enumeration goes through the client's **unit hash table**
(`D2CLIENT.pUnitTable`, BH `D2Ptrs.h`): one table per unit type, each a row
of buckets whose chains are linked by `UnitAny.pListNext`.

M2 originally walked rooms instead (`Room1.pUnitFirst` → `pRoomNext` across
`pRoomsNear`), on the reasoning that BH documents the room chain and not the
table. That was wrong, and the live client said so during M3 closeout: with a
mercenary, two skeletons and an item on the floor, the room walk found **one**
type-1 unit and **zero** items. Rooms are the right structure for collision
maps and the wrong one for units.

Three consequences worth knowing:

- **The table is global, so locality is our job.** It lists everything the
  client knows — the whole stash, units from elsewhere, expired summons.
  `scan_units` filters to `PERCEPTION_RADIUS` (80 subtiles) around the player;
  without that the dump reported a stash's worth of ground items.
- **The same unit is reachable from several bucket heads**, so
  `iter_units_of_type` de-duplicates by unit id. Before it did, a sweep
  returned 49 rows for ~13 real units.
- **Reads race the game.** Structures mutate while we walk them, so traversal
  is bounded and unreadable units are skipped and counted rather than raising.
  A nonzero `skipped` is occasionally normal; a large one means trouble.

Two classification traps, both found live:

- **Mercenaries and summons are unit type 1**, exactly like hostiles. Only
  `STAT_ALIGNMENT` (172; friendly == 2) separates them, so scans return
  `monsters` (hostile) and `allies` (merc, summons, friendly NPCs) as separate
  lists. Reporting a player's own Rogue as a nearby monster is what surfaced
  this.
- **"On the floor" is the item's unit mode** (3 on-ground, 5 dropping), *not*
  the ItemData location byte BH's header suggests: a dropped item reads 247
  there, while belt and equipped items read 255. Filtering on that byte both
  hid real drops and invented phantom ones at inventory grid coordinates.

Corpses stay in the table. `Monster.is_alive` exposes that rather than
filtering silently, so callers decide.

One non-issue worth recording because it was asked and answered (R179),
then sharpened by M5's live pickup work: **ALT item-name visibility
cannot affect what the bot SEES.** Perception reads the unit table from
memory; holding ALT (or not) only changes what the client *renders*.
But it does affect what the bot can *click* — small item classes
(runes, gems, charms) are effectively only clickable at their rendered
label (T65/T66) — so the executor reads the label-display flag from
memory (`units.label_display_on`, BH.dll+0x14d2ca) and presses ALT only
when it is provably off. Seeing is memory's job; clicking is the
renderer's territory. See behavior.md's executor section.

## What M5 added to the perception surface

The trial run needed the bot to see its own belongings and its own
skill, not just the world:

- **Carried items** (`items.py`): every item in the inventory, belt,
  stash, charm inventory, or on the cursor, with container, grid
  position, belt column/slot, and potion typing. All ten potion tiers
  are in the code table (hp1–hp5 = kinds 602–606, mp1–mp5 = 607–611 —
  T42/T58; the original table knew only the top tiers, and the bot read
  its own hp1–hp4 as foreign potions, a live-run root cause). Belt
  geometry matters: pressing key N consumes the *bottom* row of column
  N, so `belt_column`/`belt_slot` are what the drink logic reasons over.
  `read_equipped_durability` feeds the town repair decision.
- **Ground items** (`units.GroundItem`): on-the-floor detection by unit
  mode (3 on-ground, 5 dropping), with the class/quality fields the
  pickit matches on. Ground items EXPIRE if left long — measured live
  (T51), which is why clearance and pickup share one circle.
- **Objects** (`units.GameObject`): waypoints, stashes, doors, shrines.
  `offsets.INTERACTIVE_OBJECT_KINDS` marks the clickable subset — the
  navigator and every ground-targeted cast keep a berth from those
  (a right-click on a waypoint opens its menu, which blocks all input).
- **Allies, split finer**: the merc and revives are distinguished from
  other allies (`snapshot.merc`, `snapshot.revives`), which the merc
  first-aid rung and the revive wall depend on. A non-player unit's
  current hp reads on the client's **0–128 scale**, not real hp — use
  `Monster.life_pct` (the full-health rogue that read "128/1620 = 8%"
  and got fed the whole belt is the cautionary tale).
- **The active right skill** (`skills.py`): read from memory, which is
  what makes the verified switch possible — press the hotkey, then
  *confirm* the game agrees before any cast (`ensure_right_skill`,
  `SkillSwitchFailed` on timeout with a full failure context).
- **A dead end, documented** (T60–T62): the hover slot at player+0xE8
  tracks only REAL mouse motion — synthetic cursor moves (SetCursorPos
  and SendInput alike) never update it — and clicks do not need it.
  Do not build on hover state.

## Knowing when it is safe to act

This is the part that exists because of a specific mistake. During M1 a test
click was sent while the in-game ESC menu happened to be open, and it landed on
**"Save and Exit Game"**. A screen coordinate means whatever the currently-open
panel says it means.

BH exposes UI state only through a function, `GetUiVar_I`, because it runs
in-process and can call it. From outside we need the data, so `uistate.py` reads
the function's own machine code and extracts the array address from it:

```
+00: 83 F8 26            cmp eax, 0x26              ; bounds check, 38 panels
+03: 72 1F               jb  +0x24
      ...                                           ; assert path
+24: 8B 04 85 <abs32>    mov eax, [eax*4 + abs32]   ; <- the array
+2B: C3                  ret
```

The address is therefore *discovered at runtime*, not hardcoded — a patch that
moves the array is picked up automatically instead of silently returning
garbage. The result is sanity-checked before being trusted: it must lie inside
the module, and its `UI_AUTOMAP` slot must coincide with `AutomapOn`, which BH
documents separately. Two unrelated BH facts agreeing is good evidence we found
the right array.

`can_act()` combines "in a game" with "no blocking panel open". Anything that
sends input must check it **and** confirm the game window is in the foreground —
that second check belongs to the input layer, not here.

## Verifying after a patch

1. Re-fetch BH's headers and diff the structures cited in `offsets.py`.
2. Run `python -m pd2bot.dump` next to the running game and compare every field
   to what the game displays: character screen for stats, inventory for gold,
   your own eyes for position, monsters and items.
3. `pytest` will not catch a moved offset — it tests decoding logic against
   fixed buffers. Only the live comparison catches that.
