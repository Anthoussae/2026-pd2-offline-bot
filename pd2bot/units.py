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

# How far around the player counts as "nearby", in subtiles.
#
# **This is a ceiling, not the actual reach** — MEASURED, 2026-08-01 (T50,
# read-only, in Cold Plains with 44 live monsters and 12 on screen). Scans
# at 80, 120, 160, 240, 320 and an effectively unlimited radius all returned
# the identical 65 units, with the furthest at 64 subtiles and **nothing
# whatsoever between 64 and infinity**. So the binding constraint is the
# CLIENT's own horizon, not this number: D2 only populates its unit hash
# table for the rooms it has loaded, which is a ~3x3 room neighbourhood, and
# 8x8-tile rooms make that ~60 subtiles of half-extent. Raising this
# constant would buy nothing at all; covering more ground needs the
# character to MOVE.
#
# The old comment here claimed this was "comfortably beyond one screen
# (~24 subtiles)". T50 Part A measured the screen too, and that was wrong
# in a way that mattered: the drawn region is a DIAMOND in world space, 19
# to 38 subtiles from the player to the edge depending on direction — i.e.
# 38 to 76 across, not 24. Every sizing figure derived from "~24" (R147,
# and the patrol's whole radius table) understated a screen by 2-3x.
#
# Cost is not a reason to keep it small either: T50 timed the scan at ~7 ms
# over 30 units and ~19 ms over 65, identically at every radius. The price
# is the number of units, never the radius.
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

    Units that move keep a `Path`; items keep an `ItemPath` and static objects
    an `ObjectPath`, whose coordinates sit at different offsets and are full
    DWORDs. (For carried items the same DWORDs hold container grid coords or
    the belt slot instead of world subtiles — the caller knows which world it
    is in from the unit's mode.)
    """
    path = session.ptr(unit + offsets.UNIT_PATH)
    if path is None:
        return None
    if unit_type == offsets.UNIT_TYPE_ITEM:
        return session.u32(path + offsets.ITEM_PATH_X), session.u32(path + offsets.ITEM_PATH_Y)
    if unit_type == offsets.UNIT_TYPE_OBJECT:
        return (
            session.u32(path + offsets.OBJECT_PATH_X),
            session.u32(path + offsets.OBJECT_PATH_Y),
        )
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
    # UNIT_MODE animation state; 0/12 mean dead (a corpse). Defaults to 1
    # (Standing) because mode 0 is the Death animation — a hand-built value
    # that omitted the field would otherwise silently classify as a corpse.
    mode: int = 1
    # Super-unique identity (M6 P1): wUniqueNo indexes superuniques.txt,
    # wName is the display name the client renders ("The Countess"). Both
    # read only for boss-flagged units — scan cost stays flat for the
    # ordinary crowd — and raw otherwise: which values mean "not a
    # super-unique" is settled by the P2 descent drill, not assumed.
    unique_no: int | None = None
    name: str = ""

    @property
    def is_alive(self) -> bool:
        return self.hp > 0 and not self.is_corpse

    @property
    def is_corpse(self) -> bool:
        """Dead on the ground — desecrate makes these, revive consumes them."""
        return self.mode in (offsets.MONSTER_MODE_DEATH, offsets.MONSTER_MODE_DEAD)

    @property
    def is_ally(self) -> bool:
        """Your merc, your summons, friendly NPCs — never a target."""
        return self.alignment == offsets.ALIGNMENT_FRIENDLY

    @property
    def merc_kind(self) -> str | None:
        """Which mercenary this is, if it is one."""
        return offsets.MERC_CLASS_IDS.get(self.kind)

    @property
    def is_super_unique(self) -> bool:
        """Boss-flagged with a readable superuniques.txt id. WEAK signal.

        The original theory — only true super-uniques carry a non-empty
        wName — was killed by the FIRST live read (T68, Cellar 5,
        2026-08-04): wName holds garbage wide characters on live boss
        units, not a display name (the client evidently renders names
        from MonStats + wUniqueNo instead). What held is wUniqueNo
        itself: the Countess-candidate read unique_no 6, superuniques.
        txt's Countess row. Champion-pack leaders also set fBoss and
        their wUniqueNo semantics are uncatalogued, so anything
        load-bearing (the endgame's kill condition) matches the
        Countess's own learned (kind, unique_no) constants — never this
        property alone. `name` stays readable as a raw diagnostic only.
        """
        return self.is_boss and self.unique_no is not None

    @property
    def hp_fraction(self) -> float | None:
        """hp over the MAX-HP stat. Wrong for life-percent questions on
        non-player units (see `life_pct`); kept for callers comparing
        the two raw stats."""
        return self.hp / self.max_hp if self.max_hp else None

    @property
    def life_pct(self) -> float:
        """Life as a percent, on the client's own scale for NON-PLAYER
        units: current hp is stored 0-128 (full = 128) while max_hp is
        the real maximum, so hp/max_hp lies. Probed live 2026-08-02: a
        full-health rogue merc read hp 128 / max_hp 1620 — "8%" — and
        the merc-heal rung fed her all game (T54 run 3). Clamped, so a
        torn read above 128 says full rather than >100%."""
        return min(100.0, 100.0 * self.hp / offsets.NONPLAYER_HP_SCALE)


@dataclass(frozen=True)
class GroundItem:
    unit_id: int
    kind: int  # dwTxtFileNo — which item type
    position: tuple[int, int]
    quality: int
    # Socket count from the item's stat list — 0 for an item with none, and
    # None only when the stat list did not read at all (see
    # `read_socket_count` for why that distinction is load-bearing).
    # `offsets.STAT_NUM_SOCKETS` was live-verified by the T38 drill (R124).
    # Consumers must still treat None as "unknown", never as zero.
    sockets: int | None = None

    @property
    def quality_name(self) -> str:
        return offsets.QUALITY_NAMES.get(self.quality, f"quality_{self.quality}")


@dataclass(frozen=True)
class GameObject:
    """A dwType==2 unit: waypoints, the stash chest, doors, shrines, portals.

    Static scenery with a position — the things the bot walks to and clicks.
    `kind` (dwTxtFileNo) says which object; only the kinds in
    `offsets.OBJECT_KINDS` are named, everything else is scenery we ignore.
    """

    unit_id: int
    kind: int  # dwTxtFileNo — which object type
    position: tuple[int, int]
    mode: int  # objects animate too (a waypoint glows, a door opens)

    @property
    def name(self) -> str | None:
        return offsets.OBJECT_KINDS.get(self.kind)


@dataclass(frozen=True)
class UnitScan:
    """What one sweep of the nearby rooms found.

    `monsters` is hostiles only. Your mercenary and summons are in
    `allies` — counting them as monsters made the dump report a threat
    when the only thing nearby was the player's own Rogue (instruction
    log R21). Dead type-1 units go to `corpses` (M5: revive fuel), so
    neither combat targeting nor the ally count ever sees a body.
    """

    monsters: list[Monster]
    ground_items: list[GroundItem]
    skipped: int  # units that could not be read; nonzero is worth noticing
    allies: list[Monster] = field(default_factory=list)
    corpses: list[Monster] = field(default_factory=list)
    objects: list[GameObject] = field(default_factory=list)


def _read_monster(session: GameSession, unit: int) -> Monster | None:
    position = unit_position(session, unit, offsets.UNIT_TYPE_MONSTER)
    if position is None:
        return None
    data = session.ptr(unit + offsets.UNIT_DATA)
    flags = session.u8(data + offsets.MONSTER_FLAGS) if data else 0
    # Identity fields only for boss-flagged units (M6 P1): the ordinary
    # crowd never pays the extra reads, and a torn name read must not
    # cost the whole monster — identity is a bonus, position is the job.
    unique_no: int | None = None
    name = ""
    if data is not None and flags & offsets.MONSTER_FLAG_BOSS:
        try:
            unique_no = session.u16(data + offsets.MONSTER_UNIQUE_NO)
            name = session.wstring(
                data + offsets.MONSTER_NAME, offsets.MONSTER_NAME_CHARS
            )
        except Exception:  # noqa: BLE001 - identity is best-effort
            unique_no = None
            name = ""
    stats = read_stats(session, unit)
    return Monster(
        unit_id=session.u32(unit + offsets.UNIT_ID),
        kind=session.u32(unit + offsets.UNIT_TXT_FILE_NO),
        position=position,
        hp=stats.get(offsets.STAT_HP, 0),
        max_hp=stats.get(offsets.STAT_MAX_HP, 0),
        alignment=stats.get(offsets.STAT_ALIGNMENT, 0),
        mode=session.u32(unit + offsets.UNIT_MODE),
        is_champion=bool(flags & offsets.MONSTER_FLAG_CHAMPION),
        is_boss=bool(flags & offsets.MONSTER_FLAG_BOSS),
        is_minion=bool(flags & offsets.MONSTER_FLAG_MINION),
        unique_no=unique_no,
        name=name,
    )


def _read_object(session: GameSession, unit: int) -> GameObject | None:
    position = unit_position(session, unit, offsets.UNIT_TYPE_OBJECT)
    if position is None:
        return None
    return GameObject(
        unit_id=session.u32(unit + offsets.UNIT_ID),
        kind=session.u32(unit + offsets.UNIT_TXT_FILE_NO),
        position=position,
        mode=session.u32(unit + offsets.UNIT_MODE),
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
    # The socket count rides along from the item's stat list because the
    # pickit needs it (R117: "3-socket archon plate"). One extra stats read
    # per nearby ground item; items on screen number in the dozens at worst.
    return GroundItem(
        unit_id=session.u32(unit + offsets.UNIT_ID),
        kind=session.u32(unit + offsets.UNIT_TXT_FILE_NO),
        position=position,
        quality=session.u32(data + offsets.ITEM_QUALITY),
        sockets=read_socket_count(session, unit),
    )


def read_socket_count(session: GameSession, unit: int) -> int | None:
    """Sockets on one item: a real count, or None when nothing was read.

    The distinction is the whole point, and it is why this is not just
    `read_stats(...).get(STAT_NUM_SOCKETS)`. That expression collapses two
    different facts into None — "this item has no socket stat, i.e. it has
    ZERO sockets" and "the stat list did not read at all, i.e. we know
    nothing". The pickup path could live with the conflation because it
    fails closed either way (an unknown socket count never picks). The
    inventory CLEANSE cannot: it runs the same rules permissively, where an
    unevaluable condition counts as satisfied, so None means "keep" — and a
    plain 0-socket necro head would be kept and stashed forever on the
    strength of a rule that only ever wanted 3-socket ones (R132).

    So: a non-empty stat list without `STAT_NUM_SOCKETS` means zero. Only an
    empty read — a null stat list, a torn count — stays None. Armour and
    weapons always carry stats (durability at minimum), so the items the
    socket rules name reach the honest branch, not the fallback.
    """
    stats = read_stats(session, unit)
    if not stats:
        return None
    return stats.get(offsets.STAT_NUM_SOCKETS, 0)


def label_display_on(session: GameSession) -> bool | None:
    """Is the ground-item label display (the ALT toggle) currently ON?

    Reads BH.dll's own flag (T66). None = unreadable (BH.dll absent?) —
    callers must treat that as 'unknown', never guess a direction.
    """
    try:
        base = next(
            m.base for m in session.modules()
            if m.name == offsets.BH_LABEL_MODULE
        )
        return bool(session.u8(base + offsets.BH_LABEL_DISPLAY))
    except Exception:
        return None


def hovered_item_id(session: GameSession) -> int | None:
    """The unit id of the ground item under the cursor, or None.

    Reads `player_unit + PLAYER_HOVER_ITEM` (T58) and believes it only
    after validation: whatever it holds must read back as an ITEM-type
    unit, because the drill measured the pointer retaining its last item
    while the cursor sat on a living unit. Null, garbage, or a non-item
    all answer None — the pickup path treats that as "not confirmed" and
    falls back to the blind click, which is exactly the pre-T58 behavior.
    """
    try:
        player = player_unit(session)
        if player is None:
            return None
        target = session.ptr(player + offsets.PLAYER_HOVER_ITEM)
        if target is None:
            return None
        if session.u32(target + offsets.UNIT_TYPE) != offsets.UNIT_TYPE_ITEM:
            return None
        return session.u32(target + offsets.UNIT_ID)
    except Exception:
        # Includes "not a real session at all" (sims pass None): a hover
        # that cannot be read is a hover that never confirms, and the
        # pickup path degrades to the blind click rather than breaking.
        return None


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
    corpses: list[Monster] = []
    items: list[GroundItem] = []
    objects: list[GameObject] = []
    skipped = 0
    # Keyed by (TYPE, id), not by id alone. **D2 unit ids are only unique
    # within a unit type** — a monster and an object can both be id 11, and
    # in the live Rogue Encampment they both were. With one shared set, the
    # first pass to claim an id silently deleted the other unit from the
    # snapshot, and since objects are enumerated last they lost every time.
    #
    # That is what killed stage B's second attempt: the Act 1 waypoint (id
    # 11) sat 24 subtiles away, plainly inside the 80-subtile radius and
    # present in the unit table, while `snap.objects` reported objects at
    # d=31, 35, 46 and 57 and simply omitted it. `_approach_object` then
    # walked to its configured position and correctly reported that it could
    # not see what it had been told to click.
    #
    # The dedup itself is still needed and still per type: the hash table
    # can list one unit more than once.
    seen: set[tuple[int, int]] = set()

    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_MONSTER):
        try:
            key = (offsets.UNIT_TYPE_MONSTER, session.u32(unit + offsets.UNIT_ID))
            if key in seen:
                continue
            monster = _read_monster(session, unit)
            if monster is not None and near(monster.position):
                seen.add(key)
                if monster.is_corpse:
                    corpses.append(monster)
                else:
                    (allies if monster.is_ally else monsters).append(monster)
        except Exception:
            # The game mutates these structures as we read them; a malformed
            # unit is expected occasionally, not exceptional.
            skipped += 1

    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_ITEM):
        try:
            key = (offsets.UNIT_TYPE_ITEM, session.u32(unit + offsets.UNIT_ID))
            if key in seen:
                continue
            item = _read_ground_item(session, unit)
            if item is not None and near(item.position):
                seen.add(key)
                items.append(item)
        except Exception:
            skipped += 1

    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_OBJECT):
        try:
            key = (offsets.UNIT_TYPE_OBJECT, session.u32(unit + offsets.UNIT_ID))
            if key in seen:
                continue
            obj = _read_object(session, unit)
            if obj is not None and near(obj.position):
                seen.add(key)
                objects.append(obj)
        except Exception:
            skipped += 1

    return UnitScan(
        monsters=monsters,
        ground_items=items,
        skipped=skipped,
        allies=allies,
        corpses=corpses,
        objects=objects,
    )
