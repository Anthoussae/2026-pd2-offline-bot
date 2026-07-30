"""Tests for room traversal and unit decoding."""

from pd2bot import offsets
from pd2bot.units import (
    MAX_UNITS_PER_ROOM,
    iter_units,
    iter_units_of_type,
    nearby_rooms,
    scan_units,
)
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, stat_array, u32

PLAYER = 0x0B000000
PLAYER_PATH = 0x0B000100
ROOM_A = 0x0B001000
ROOM_B = 0x0B002000
NEAR_ARRAY = 0x0B003000


def add_monster(mem, address, unit_id, kind, pos, hp, max_hp, flags=0, alignment=0, mode=1):
    # mode defaults to 1 (Standing): mode 0 is the Death animation, and a
    # fake that leaves the field unwritten would read as a corpse.
    path = address + 0x100
    data = address + 0x200
    stats = address + 0x300
    stat_arr = address + 0x400
    mem.write_fields(
        address,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_MONSTER),
            offsets.UNIT_TXT_FILE_NO: u32(kind),
            offsets.UNIT_ID: u32(unit_id),
            offsets.UNIT_MODE: u32(mode),
            offsets.UNIT_DATA: u32(data),
            offsets.UNIT_PATH: u32(path),
            offsets.UNIT_STATS: u32(stats),
            offsets.UNIT_ROOM_NEXT: u32(0),
        },
    )
    mem.write_fields(path, {offsets.PATH_X: u32(pos[0])[:2], offsets.PATH_Y: u32(pos[1])[:2]})
    mem.write_fields(data, {offsets.MONSTER_FLAGS: bytes([flags])})
    values = {offsets.STAT_HP: hp << 8, offsets.STAT_MAX_HP: max_hp << 8}
    if alignment:
        values[offsets.STAT_ALIGNMENT] = alignment
    mem.write_fields(
        stats,
        {
            offsets.STATLIST_FULL_ARRAY: u32(stat_arr),
            offsets.STATLIST_FULL_COUNT: u32(len(values))[:2],
        },
    )
    mem.write(stat_arr, stat_array(values))
    return address


def add_item(mem, address, unit_id, kind, pos, quality, mode=offsets.ITEM_MODE_ON_GROUND):
    path, data = address + 0x100, address + 0x200
    mem.write_fields(
        address,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_ITEM),
            offsets.UNIT_TXT_FILE_NO: u32(kind),
            offsets.UNIT_ID: u32(unit_id),
            offsets.UNIT_MODE: u32(mode),
            offsets.UNIT_DATA: u32(data),
            offsets.UNIT_PATH: u32(path),
            offsets.UNIT_STATS: u32(0),
            offsets.UNIT_ROOM_NEXT: u32(0),
        },
    )
    mem.write_fields(path, {offsets.ITEM_PATH_X: u32(pos[0]), offsets.ITEM_PATH_Y: u32(pos[1])})
    mem.write_fields(data, {offsets.ITEM_QUALITY: u32(quality)})
    return address


def link(mem, unit, next_unit):
    mem.regions[unit][offsets.UNIT_ROOM_NEXT : offsets.UNIT_ROOM_NEXT + 4] = u32(next_unit)


def hash_table(mem, units_by_type):
    """Populate the client unit hash table — how `scan_units` enumerates.

    Room walking misses units entirely in the live client (instruction log
    R20), so unit enumeration goes through this table; each unit chain is
    linked by UNIT_LIST_NEXT.
    """
    size = offsets.UNIT_TYPE_COUNT * offsets.UNIT_HASH_BUCKETS * 4
    table = bytearray(size)
    for unit_type, units in units_by_type.items():
        for index, unit in enumerate(units):
            slot = (unit_type * offsets.UNIT_HASH_BUCKETS + index) * 4
            table[slot : slot + 4] = u32(unit)
            mem.regions[unit][offsets.UNIT_LIST_NEXT : offsets.UNIT_LIST_NEXT + 4] = u32(0)
    mem.write(CLIENT_BASE + offsets.UNIT_TABLE_PTR, bytes(table))


def build() -> FakeSession:
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(PLAYER, {offsets.UNIT_PATH: u32(PLAYER_PATH)})
    # The player needs a position: scans are relative to it (see
    # PERCEPTION_RADIUS). Standing among the units below.
    mem.write_fields(
        PLAYER_PATH,
        {
            offsets.PATH_ROOM1: u32(ROOM_A),
            offsets.PATH_X: u32(100)[:2],
            offsets.PATH_Y: u32(200)[:2],
        },
    )

    boss = add_monster(mem, 0x0B010000, 101, 55, (100, 200), 500, 1000,
                       flags=offsets.MONSTER_FLAG_BOSS)
    corpse = add_monster(mem, 0x0B011000, 102, 56, (110, 210), 0, 800,
                         mode=offsets.MONSTER_MODE_DEAD)
    link(mem, boss, corpse)

    item = add_item(mem, 0x0B020000, 201, 12, (120, 220), 7)
    # The live R17 case: a carried item (mode 0 = in storage) whose ItemPath
    # x/y are inventory GRID coordinates, not world coordinates. It must not
    # be reported as lying on the floor at (5, 0).
    carried = add_item(mem, 0x0B021000, 202, 13, (5, 0), 4, mode=0)
    link(mem, item, carried)

    mem.write_fields(
        ROOM_A,
        {
            offsets.ROOM1_UNIT_FIRST: u32(boss),
            offsets.ROOM1_ROOMS_NEAR: u32(NEAR_ARRAY),
            offsets.ROOM1_ROOMS_NEAR_COUNT: u32(1),
        },
    )
    mem.write(NEAR_ARRAY, u32(ROOM_B))
    mem.write_fields(
        ROOM_B,
        {
            offsets.ROOM1_UNIT_FIRST: u32(item),
            offsets.ROOM1_ROOMS_NEAR: u32(0),
            offsets.ROOM1_ROOMS_NEAR_COUNT: u32(0),
        },
    )
    hash_table(
        mem,
        {
            offsets.UNIT_TYPE_MONSTER: [boss, corpse],
            offsets.UNIT_TYPE_ITEM: [item, carried],
        },
    )
    return FakeSession(mem)


def test_walks_the_players_room_and_its_neighbours():
    assert nearby_rooms(build()) == [ROOM_A, ROOM_B]


def test_finds_monsters_across_rooms_with_their_class_and_health():
    scan = scan_units(build())
    assert len(scan.monsters) == 1  # the corpse routes to scan.corpses

    boss = next(m for m in scan.monsters if m.unit_id == 101)
    assert boss.is_boss and not boss.is_champion
    assert boss.position == (100, 200)
    assert (boss.hp, boss.max_hp) == (500, 1000)
    assert boss.hp_fraction == 0.5
    assert boss.is_alive


def test_dead_monsters_route_to_corpses_not_targets():
    """A dead type-1 unit is revive fuel (M5), never a combat target and
    never an ally — it gets its own list so neither consumer can trip on
    a body."""
    scan = scan_units(build())
    assert [c.unit_id for c in scan.corpses] == [102]
    corpse = scan.corpses[0]
    assert corpse.is_corpse and not corpse.is_alive
    assert all(m.unit_id != 102 for m in scan.monsters)
    assert all(a.unit_id != 102 for a in scan.allies)


def build_with_allies():
    """A room holding the player's Rogue merc, a summoned skeleton, and one
    genuine hostile."""
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(PLAYER, {offsets.UNIT_PATH: u32(PLAYER_PATH)})
    mem.write_fields(
        PLAYER_PATH,
        {
            offsets.PATH_ROOM1: u32(ROOM_A),
            offsets.PATH_X: u32(100)[:2],
            offsets.PATH_Y: u32(200)[:2],
        },
    )

    merc = add_monster(mem, 0x0B030000, 301, 271, (100, 200), 500, 600,
                       alignment=offsets.ALIGNMENT_FRIENDLY)
    skeleton = add_monster(mem, 0x0B032000, 303, 363, (105, 205), 80, 80,
                           alignment=offsets.ALIGNMENT_FRIENDLY)
    fiend = add_monster(mem, 0x0B031000, 302, 58, (110, 210), 400, 400)
    hash_table(mem, {offsets.UNIT_TYPE_MONSTER: [merc, skeleton, fiend]})

    mem.write_fields(
        ROOM_A,
        {
            offsets.ROOM1_UNIT_FIRST: u32(merc),
            offsets.ROOM1_ROOMS_NEAR: u32(0),
            offsets.ROOM1_ROOMS_NEAR_COUNT: u32(0),
        },
    )
    return FakeSession(mem)


def test_mercenary_and_summons_are_allies_not_monsters():
    """D2 files mercs and summons under the same unit type as hostiles;
    only the alignment stat separates them. The live dump reported the
    player's Rogue (classid 271) as a nearby monster — log R21."""
    scan = scan_units(build_with_allies())
    assert [m.unit_id for m in scan.monsters] == [302]
    assert sorted(a.unit_id for a in scan.allies) == [301, 303]
    assert all(a.is_ally for a in scan.allies)


def test_distant_units_are_not_reported_as_nearby():
    """The hash table is global — it holds the whole stash and units from
    elsewhere. Without a locality filter the dump reported phantom allies
    and a stash's worth of items (instruction log R23)."""
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(PLAYER, {offsets.UNIT_PATH: u32(PLAYER_PATH)})
    mem.write_fields(PLAYER_PATH, {offsets.PATH_X: u32(5000)[:2], offsets.PATH_Y: u32(5000)[:2]})

    close = add_monster(mem, 0x0B060000, 501, 55, (5010, 5010), 100, 100)
    far = add_monster(mem, 0x0B061000, 502, 55, (9000, 9000), 100, 100)
    stashed = add_item(mem, 0x0B062000, 503, 12, (4, 30), 5, mode=0)
    dropped = add_item(mem, 0x0B063000, 504, 610, (5012, 5012), 2)
    hash_table(
        mem,
        {
            offsets.UNIT_TYPE_MONSTER: [close, far],
            offsets.UNIT_TYPE_ITEM: [stashed, dropped],
        },
    )

    scan = scan_units(FakeSession(mem))
    assert [m.unit_id for m in scan.monsters] == [501]
    assert [i.unit_id for i in scan.ground_items] == [504]


def test_merc_is_named_but_a_summon_is_not():
    scan = scan_units(build_with_allies())
    by_id = {a.unit_id: a for a in scan.allies}
    assert by_id[301].merc_kind == "rogue"
    assert by_id[303].merc_kind is None  # a summon, not a hireling


def test_ground_items_use_their_own_position_offsets():
    scan = scan_units(build())
    assert len(scan.ground_items) == 1
    item = scan.ground_items[0]
    assert item.unit_id == 201
    assert item.position == (120, 220)
    assert item.quality_name == "unique"


def test_carried_items_are_not_reported_as_lying_on_the_ground():
    scan = scan_units(build())
    assert all(item.unit_id != 202 for item in scan.ground_items)


def test_a_unit_in_two_rooms_is_only_reported_once():
    session = build()
    boss = 0x0B010000
    session.memory.write_fields(
        ROOM_B,
        {
            offsets.ROOM1_UNIT_FIRST: u32(boss),
            offsets.ROOM1_ROOMS_NEAR: u32(0),
            offsets.ROOM1_ROOMS_NEAR_COUNT: u32(0),
        },
    )
    scan = scan_units(session)
    assert [m.unit_id for m in scan.monsters].count(101) == 1


def test_a_cycle_in_the_unit_list_terminates():
    """A torn read can make a list point at itself; traversal must be bounded."""
    session = build()
    boss = 0x0B010000
    link(session.memory, boss, boss)
    units = list(iter_units(session, ROOM_A))
    assert len(units) == MAX_UNITS_PER_ROOM


def test_absurd_neighbour_count_is_ignored():
    session = build()
    session.memory.write_fields(
        ROOM_A,
        {
            offsets.ROOM1_UNIT_FIRST: u32(0),
            offsets.ROOM1_ROOMS_NEAR: u32(NEAR_ARRAY),
            offsets.ROOM1_ROOMS_NEAR_COUNT: u32(0xFFFFFF),
        },
    )
    assert nearby_rooms(session) == [ROOM_A]


def test_unreadable_units_are_counted_not_fatal():
    """A unit whose innards dangle must be skipped, not abort the sweep —
    the rest of the table still has to come back."""
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    good = add_monster(mem, 0x0B010000, 101, 55, (100, 200), 500, 1000)
    broken = 0x0B040000
    mem.write_fields(
        broken,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_MONSTER),
            offsets.UNIT_ID: u32(999),
            offsets.UNIT_PATH: u32(0xDEAD0000),  # unmapped
            offsets.UNIT_DATA: u32(0),
            offsets.UNIT_STATS: u32(0),
            offsets.UNIT_LIST_NEXT: u32(0),
        },
    )
    hash_table(mem, {offsets.UNIT_TYPE_MONSTER: [good, broken]})

    scan = scan_units(FakeSession(mem))
    assert scan.skipped >= 1
    assert any(m.unit_id == 101 for m in scan.monsters)


def test_units_reachable_from_several_buckets_are_yielded_once():
    """Live sweeps re-encountered the same units from multiple bucket heads
    — 49 rows for ~13 real units (instruction log R24). The iterator must
    de-duplicate, or every consumer counts phantoms."""
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(PLAYER, {offsets.UNIT_PATH: u32(PLAYER_PATH)})
    mem.write_fields(
        PLAYER_PATH, {offsets.PATH_X: u32(10)[:2], offsets.PATH_Y: u32(10)[:2]}
    )
    one = add_monster(mem, 0x0B070000, 601, 55, (10, 10), 100, 100)
    two = add_monster(mem, 0x0B071000, 602, 55, (12, 12), 100, 100)
    # Both units are bucket heads AND chained together — the live shape.
    hash_table(mem, {offsets.UNIT_TYPE_MONSTER: [one, two]})
    mem.regions[one][offsets.UNIT_LIST_NEXT : offsets.UNIT_LIST_NEXT + 4] = u32(two)

    session = FakeSession(mem)
    assert len(list(iter_units_of_type(session, offsets.UNIT_TYPE_MONSTER))) == 2
    assert sorted(m.unit_id for m in scan_units(session).monsters) == [601, 602]


def test_chain_of_units_in_one_bucket_is_followed():
    """Hash buckets hold chains; missing the chain would lose units — which
    is how room-walking lost the player's merc and summons live (R20)."""
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    first = add_monster(mem, 0x0B050000, 401, 55, (10, 10), 100, 100)
    second = add_monster(mem, 0x0B051000, 402, 56, (12, 12), 100, 100)
    hash_table(mem, {offsets.UNIT_TYPE_MONSTER: [first]})
    mem.regions[first][offsets.UNIT_LIST_NEXT : offsets.UNIT_LIST_NEXT + 4] = u32(second)

    scan = scan_units(FakeSession(mem))
    assert sorted(m.unit_id for m in scan.monsters) == [401, 402]


def test_empty_table_means_no_units():
    """Out of a game the client's table is empty; nothing should be invented."""
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(0))
    hash_table(mem, {})
    scan = scan_units(FakeSession(mem))
    assert scan.monsters == [] and scan.ground_items == [] and scan.allies == []
    assert scan.corpses == [] and scan.objects == []


def add_object(mem, address, unit_id, kind, pos, mode=0):
    path = address + 0x100
    mem.write_fields(
        address,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_OBJECT),
            offsets.UNIT_TXT_FILE_NO: u32(kind),
            offsets.UNIT_ID: u32(unit_id),
            offsets.UNIT_MODE: u32(mode),
            offsets.UNIT_DATA: u32(0),
            offsets.UNIT_PATH: u32(path),
            offsets.UNIT_ROOM_NEXT: u32(0),
        },
    )
    mem.write_fields(
        path,
        {offsets.OBJECT_PATH_X: u32(pos[0]), offsets.OBJECT_PATH_Y: u32(pos[1])},
    )
    return address


def test_objects_are_scanned_with_dword_positions_and_names():
    """Waypoints and the stash chest are type-2 units (M5): world-DWORD
    coordinates like items, named only when their kind is in the table."""
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(PLAYER, {offsets.UNIT_PATH: u32(PLAYER_PATH)})
    mem.write_fields(
        PLAYER_PATH, {offsets.PATH_X: u32(100)[:2], offsets.PATH_Y: u32(200)[:2]}
    )
    waypoint = add_object(mem, 0x0B080000, 701, offsets.OBJ_WAYPOINT_A1, (110, 205))
    scenery = add_object(mem, 0x0B081000, 702, 9999, (105, 195))
    far_stash = add_object(mem, 0x0B082000, 703, offsets.OBJ_STASH, (900, 900))
    hash_table(mem, {offsets.UNIT_TYPE_OBJECT: [waypoint, scenery, far_stash]})

    scan = scan_units(FakeSession(mem))
    by_id = {o.unit_id: o for o in scan.objects}
    assert by_id[701].name == "waypoint"
    assert by_id[701].position == (110, 205)
    assert by_id[702].name is None  # unnamed scenery is present but anonymous
    assert 703 not in by_id  # locality applies to objects too
