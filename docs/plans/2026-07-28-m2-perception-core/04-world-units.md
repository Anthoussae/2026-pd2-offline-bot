# P4 — World model: monsters and ground items

**Work item:** P4 · **Size:** sm · **Depends on:** P1 ·
**Parallel with:** P2, P3 · **Review gate:** none

## Scope

Enumerate the units around the player by walking the game's room
structures.

`pd2bot/units.py`:

- `Monster` dataclass: unit id, `txt_file_no` (monster type id),
  position, hp fraction, and class flags (normal / champion / boss /
  minion), plus `is_alive`.
- `GroundItem` dataclass: unit id, `txt_file_no` (item type),
  position, quality, and whether it is actually on the ground.
- `read_monsters(session)`, `read_ground_items(session)`.

## How enumeration works

D2 stores units per room. From the player:

```
Path.pRoom1 (+0x1C)              -> the player's room
Room1.pUnitFirst (+0x74)         -> first unit in that room
UnitAny.pRoomNext (+0xE4)        -> next unit in the same room
Room1.pRoomsNear (+0x00)         -> array of adjacent Room1*
Room1.dwRoomsNear (+0x24)        -> how many
```

So: player's room plus its neighbours, each walked unit-by-unit. This is
deliberately chosen over hunting for D2's unit hash table — the room
chain is fully documented in BH, the hash table is not (BH runs
in-process and calls game functions instead).

Filter by `UnitAny.dwType (+0x00)`: monsters and items are distinct unit
types; `dwTxtFileNo (+0x04)` identifies which monster or item.
`pMonsterData` / `pItemData` share the union at `+0x14` — read the one
matching the unit type, never both.

- Monsters: `MonsterData` (D2Structs.h:610) — flag bitfield at `+0x16`
  gives `fNormal/fChamp/fBoss/fMinion`; hp comes from the same StatList
  mechanism as the player (**full array**, fixed-point).
- Items: `ItemData` (D2Structs.h:510) — `dwQuality +0x00`,
  `dwItemFlags +0x0C`, `ItemLocation +0x45`. Distinguish items lying on
  the ground from items in inventories/equipped; only ground items
  matter here.

## Out of scope

- Monster resistances and immunities — **explicitly cut** (user
  decision: assume the character and hireling handle every resistance
  and that all enemies are defeatable). Do not add "just in case".
- Monster enchantments, ai state, targeting logic (M5).
- Item affix/name resolution beyond type and quality (M5 pickit may
  revisit).
- Objects, portals, waypoints, NPCs, missiles — worth having eventually
  (M4 needs portals/waypoints), out of scope here.
- Distance-based filtering policy: return what is in range of the room
  walk; let callers filter.

## Implementation notes

- Cap the traversal defensively: rooms and unit lists are linked lists
  in a live, concurrently-mutating process. Bound iteration counts and
  bail on absurd values rather than looping forever on a torn read.
- A torn or transient read is normal, not exceptional — the game is
  running while we read. Prefer skipping a malformed unit to raising.
- Dead monsters remain in the list; expose `is_alive` rather than
  filtering silently, so callers decide.

## Files

- New: `pd2bot/units.py`, `tests/test_units.py`.
- Updated: `pd2bot/offsets.py`, `pd2bot/world.py` (wire enumeration in).

## Validation

- `pytest`: traversal over synthetic room/unit buffers, including
  cycles, null pointers, and absurd counts (the defensive caps must
  actually trigger).
- **Live, semantic**: stand in a populated area and compare the monster
  list to what is visibly on screen — count, rough positions, and boss
  or champion status against their visible name plates. Drop an item on
  the ground and confirm it appears; pick it up and confirm it leaves
  the list. Record the comparison in the Implementation Result.
- Confirm the list changes appropriately when moving between rooms.

## ADR expectation

None. (Room traversal vs hash table is recorded in the plan and
notes; it is a technique choice inside one module, not an architectural
commitment.)

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope — especially not into resistances (explicitly
  cut) or combat/targeting logic.
- Reads only — no input, no writes.
- Do not silently swallow malformed data without a way to notice it;
  count skips and expose the count.
- Stop and report if blocked by ambiguity or an unexpected design issue.
- Report what changed, what was validated, and any deviations.

## Definition of done

Monsters and ground items around the player are enumerated correctly and
verified against what is visible on screen, traversal is bounded and
survives transient reads, and tests plus lint pass.
