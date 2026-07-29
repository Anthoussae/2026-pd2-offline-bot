"""Units: the player, monsters, and items lying on the ground.

Everything in the game world is a `UnitAny`. This module holds the primitives
for reading one (type, position, stats) and for enumerating the units around
the player.

Enumeration walks the game's own room structures rather than looking for D2's
unit hash table: the room chain is fully documented in BH, the hash table is
not (BH runs inside the game and calls its functions instead).

    Path.pRoom1        -> the player's room
    Room1.pUnitFirst   -> first unit in it
    UnitAny.pRoomNext  -> next unit in the same room
    Room1.pRoomsNear   -> adjacent rooms, dwRoomsNear of them

Reads happen while the game is running and mutating these structures, so a
torn or transient read is normal. Traversal is bounded and skips units it
cannot make sense of rather than raising.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from pd2bot import offsets
from pd2bot.memory import GameSession

# Defensive bounds. A live linked list can be torn mid-read; these stop a bad
# pointer from becoming an infinite loop.
MAX_ROOMS = 64
MAX_UNITS_PER_ROOM = 256

# How far around the player counts as "nearby", in subtiles. Roughly what
# the old room-neighbourhood covered, and comfortably beyond one screen
# (~24 subtiles) so nothing the player can see is missed.
PERCEPTION_RADIUS = 80
MAX_STATS = 256


def player_unit(session: GameSession) -> int | None:
    """Address of the player's UnitAny, or None when not in a game."""
    return session.ptr(session.client(offsets.PLAYER_UNIT_PTR))


def read_stats(session: GameSession, unit: int) -> dict[int, int]:
    """Read a unit's fully-computed stats, keyed by stat index.

    Uses the *full* array (item and skill bonuses applied), not the base one:
    reading the base array gives values like hp=961 with max_hp=920, a current
    value above its own maximum. Fixed-point stats are decoded here so callers
    never have to remember which ones need shifting.
    """
    stat_list = session.ptr(unit + offsets.UNIT_STATS)
    if stat_list is None:
        return {}

    array = session.ptr(stat_list + offsets.STATLIST_FULL_ARRAY)
    count = session.u16(stat_list + offsets.STATLIST_FULL_COUNT)
    if array is None or not 0 < count <= MAX_STATS:
        return {}

    raw = session.raw(array, count * offsets.STAT_ENTRY_SIZE)
    stats: dict[int, int] = {}
    for i in range(count):
        entry = raw[i * offsets.STAT_ENTRY_SIZE : (i + 1) * offsets.STAT_ENTRY_SIZE]
        index = int.from_bytes(entry[2:4], "little")
        value = int.from_bytes(entry[4:8], "little")
        stats[index] = value >> 8 if index in offsets.FIXED_POINT_STATS else value
    return stats


def unit_position(session: GameSession, unit: int, unit_type: int) -> tuple[int, int] | None:
    """World coordinates of a unit.

    Units that move keep a `Path`; items on the ground keep an `ItemPath`, whose
    coordinates sit at different offsets and are full DWORDs.
    """
    path = session.ptr(unit + offsets.UNIT_PATH)
    if path is None:
        return None
    if unit_type == offsets.UNIT_TYPE_ITEM:
        return session.u32(path + offsets.ITEM_PATH_X), session.u32(path + offsets.ITEM_PATH_Y)
    return session.u16(path + offsets.PATH_X), session.u16(path + offsets.PATH_Y)


# --- room traversal --------------------------------------------------------


def _player_room(session: GameSession) -> int | None:
    unit = player_unit(session)
    if unit is None:
        return None
    path = session.ptr(unit + offsets.UNIT_PATH)
    if path is None:
        return None
    return session.ptr(path + offsets.PATH_ROOM1)


def nearby_rooms(session: GameSession) -> list[int]:
    """The player's room plus its immediate neighbours."""
    try:
        room = _player_room(session)
    except Exception:
        return []
    if room is None:
        return []

    rooms = [room]
    try:
        near_array = session.ptr(room + offsets.ROOM1_ROOMS_NEAR)
        near_count = session.u32(room + offsets.ROOM1_ROOMS_NEAR_COUNT)
        if near_array is None or not 0 < near_count <= MAX_ROOMS:
            return rooms

        for i in range(near_count):
            neighbour = session.ptr(near_array + i * 4)
            if neighbour is not None and neighbour not in rooms:
                rooms.append(neighbour)
    except Exception:
        pass  # keep whatever rooms we did resolve; the player's own is enough
    return rooms


def iter_units(session: GameSession, room: int) -> Iterator[int]:
    """Walk the units in one room, bounded against torn reads.

    Following the chain is itself a read that can fail — a unit freed between
    one step and the next leaves a dangling pointer. That ends the walk rather
    than raising, since the caller cannot do anything more useful about it.
    """
    try:
        unit = session.ptr(room + offsets.ROOM1_UNIT_FIRST)
    except Exception:
        return

    seen = 0
    while unit is not None and seen < MAX_UNITS_PER_ROOM:
        yield unit
        seen += 1
        try:
            unit = session.ptr(unit + offsets.UNIT_ROOM_NEXT)
        except Exception:
            return


# --- domain models ---------------------------------------------------------


@dataclass(frozen=True)
class Monster:
    """Any dwType==1 unit: hostile monsters *and* your own side.

    D2 files mercenaries, summons and friendly NPCs under the same unit
    type as everything hostile; `alignment` is what tells them apart (see
    `is_ally`). Scans return the two groups in separate lists so nothing
    downstream has to remember the distinction.
    """

    unit_id: int
    kind: int  # dwTxtFileNo — which monster type
    position: tuple[int, int]
    hp: int
    max_hp: int
    is_champion: bool
    is_boss: bool
    is_minion: bool
    alignment: int = 0

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @property
    def is_ally(self) -> bool:
        """Your merc, your summons, friendly NPCs — never a target."""
        return self.alignment == offsets.ALIGNMENT_FRIENDLY

    @property
    def merc_kind(self) -> str | None:
        """Which mercenary this is, if it is one."""
        return offsets.MERC_CLASS_IDS.get(self.kind)

    @property
    def hp_fraction(self) -> float | None:
        return self.hp / self.max_hp if self.max_hp else None


@dataclass(frozen=True)
class GroundItem:
    unit_id: int
    kind: int  # dwTxtFileNo — which item type
    position: tuple[int, int]
    quality: int

    @property
    def quality_name(self) -> str:
        return offsets.QUALITY_NAMES.get(self.quality, f"quality_{self.quality}")


@dataclass(frozen=True)
class UnitScan:
    """What one sweep of the nearby rooms found.

    `monsters` is hostiles only. Your mercenary and summons are in
    `allies` — counting them as monsters made the dump report a threat
    when the only thing nearby was the player's own Rogue (instruction
    log R21).
    """

    monsters: list[Monster]
    ground_items: list[GroundItem]
    skipped: int  # units that could not be read; nonzero is worth noticing
    allies: list[Monster] = field(default_factory=list)


def _read_monster(session: GameSession, unit: int) -> Monster | None:
    position = unit_position(session, unit, offsets.UNIT_TYPE_MONSTER)
    if position is None:
        return None
    data = session.ptr(unit + offsets.UNIT_DATA)
    flags = session.u8(data + offsets.MONSTER_FLAGS) if data else 0
    stats = read_stats(session, unit)
    return Monster(
        unit_id=session.u32(unit + offsets.UNIT_ID),
        kind=session.u32(unit + offsets.UNIT_TXT_FILE_NO),
        position=position,
        hp=stats.get(offsets.STAT_HP, 0),
        max_hp=stats.get(offsets.STAT_MAX_HP, 0),
        alignment=stats.get(offsets.STAT_ALIGNMENT, 0),
        is_champion=bool(flags & offsets.MONSTER_FLAG_CHAMPION),
        is_boss=bool(flags & offsets.MONSTER_FLAG_BOSS),
        is_minion=bool(flags & offsets.MONSTER_FLAG_MINION),
    )


def _read_ground_item(session: GameSession, unit: int) -> GroundItem | None:
    data = session.ptr(unit + offsets.UNIT_DATA)
    if data is None:
        return None
    # Items held in an inventory or equipped are in these lists too. The
    # reliable "actually lying on the floor" signal is the unit's MODE
    # (ground / mid-drop) — the ItemData location byte at 0x45 lied to us
    # live: a carried item read 0xFF there and showed up as a ground item
    # at its inventory grid slot (instruction log R17).
    mode = session.u32(unit + offsets.UNIT_MODE)
    if mode not in (offsets.ITEM_MODE_ON_GROUND, offsets.ITEM_MODE_DROPPING):
        return None
    position = unit_position(session, unit, offsets.UNIT_TYPE_ITEM)
    if position is None:
        return None
    return GroundItem(
        unit_id=session.u32(unit + offsets.UNIT_ID),
        kind=session.u32(unit + offsets.UNIT_TXT_FILE_NO),
        position=position,
        quality=session.u32(data + offsets.ITEM_QUALITY),
    )


def iter_units_of_type(session: GameSession, unit_type: int) -> Iterator[int]:
    """Every distinct unit of one type the client knows about.

    Two guards, both earned live (instruction log R23, R24):

    - each unit's own `dwType` must match the table it came from, so a
      wrong layout assumption fails visibly instead of returning nonsense;
    - units are de-duplicated by id, because walking `pListNext` from every
      bucket head re-encounters units that are themselves bucket heads —
      the raw sweep returned 49 rows for ~13 real units. De-duplicating
      here rather than in each caller keeps every consumer honest.
    """
    base = session.client(offsets.UNIT_TABLE_PTR)
    yielded: set[int] = set()
    for bucket in range(offsets.UNIT_HASH_BUCKETS):
        try:
            unit = session.ptr(base + (unit_type * offsets.UNIT_HASH_BUCKETS + bucket) * 4)
        except Exception:
            continue
        seen = 0
        while unit is not None and seen < MAX_UNITS_PER_ROOM:
            seen += 1
            try:
                if session.u32(unit + offsets.UNIT_TYPE) == unit_type:
                    unit_id = session.u32(unit + offsets.UNIT_ID)
                    if unit_id not in yielded:
                        yielded.add(unit_id)
                        yield unit
                unit = session.ptr(unit + offsets.UNIT_LIST_NEXT)
            except Exception:
                break  # torn read mid-chain: abandon this bucket, keep the rest


def scan_units(session: GameSession, radius: int = PERCEPTION_RADIUS) -> UnitScan:
    """Everything worth knowing about near the player.

    The hash table lists every unit the client knows about — the whole
    stash, units from other levels, expired summons — so "near the player"
    has to be enforced here. Room traversal used to supply that locality
    for free; losing it made the dump report a stash's worth of items and
    phantom allies (instruction log R23). `radius` is in subtiles;
    positionless units are dropped, since we cannot say where they are.
    """
    try:
        player = player_unit(session)
        origin = (
            unit_position(session, player, offsets.UNIT_TYPE_PLAYER)
            if player is not None
            else None
        )
    except Exception:
        origin = None  # mid-transition: report everything rather than nothing

    def near(position: tuple[int, int]) -> bool:
        if origin is None:
            return True  # cannot judge distance; do not silently hide things
        return abs(position[0] - origin[0]) <= radius and abs(position[1] - origin[1]) <= radius

    monsters: list[Monster] = []
    allies: list[Monster] = []
    items: list[GroundItem] = []
    skipped = 0
    seen_ids: set[int] = set()

    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_MONSTER):
        try:
            unit_id = session.u32(unit + offsets.UNIT_ID)
            if unit_id in seen_ids:
                continue
            monster = _read_monster(session, unit)
            if monster is not None and near(monster.position):
                seen_ids.add(unit_id)
                (allies if monster.is_ally else monsters).append(monster)
        except Exception:
            # The game mutates these structures as we read them; a malformed
            # unit is expected occasionally, not exceptional.
            skipped += 1

    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_ITEM):
        try:
            unit_id = session.u32(unit + offsets.UNIT_ID)
            if unit_id in seen_ids:
                continue
            item = _read_ground_item(session, unit)
            if item is not None and near(item.position):
                seen_ids.add(unit_id)
                items.append(item)
        except Exception:
            skipped += 1

    return UnitScan(monsters=monsters, ground_items=items, skipped=skipped, allies=allies)
