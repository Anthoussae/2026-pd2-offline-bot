"""Tests for room traversal and unit decoding."""

from pd2bot import offsets
from pd2bot.units import MAX_UNITS_PER_ROOM, iter_units, nearby_rooms, scan_units
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, stat_array, u32

PLAYER = 0x0B000000
PLAYER_PATH = 0x0B000100
ROOM_A = 0x0B001000
ROOM_B = 0x0B002000
NEAR_ARRAY = 0x0B003000


def add_monster(mem, address, unit_id, kind, pos, hp, max_hp, flags=0):
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
            offsets.UNIT_DATA: u32(data),
            offsets.UNIT_PATH: u32(path),
            offsets.UNIT_STATS: u32(stats),
            offsets.UNIT_ROOM_NEXT: u32(0),
        },
    )
    mem.write_fields(path, {offsets.PATH_X: u32(pos[0])[:2], offsets.PATH_Y: u32(pos[1])[:2]})
    mem.write_fields(data, {offsets.MONSTER_FLAGS: bytes([flags])})
    mem.write_fields(
        stats,
        {
            offsets.STATLIST_FULL_ARRAY: u32(stat_arr),
            offsets.STATLIST_FULL_COUNT: u32(2)[:2],
        },
    )
    mem.write(stat_arr, stat_array({offsets.STAT_HP: hp << 8, offsets.STAT_MAX_HP: max_hp << 8}))
    return address


def add_item(mem, address, unit_id, kind, pos, quality, location=offsets.ITEM_LOCATION_NONE):
    path, data = address + 0x100, address + 0x200
    mem.write_fields(
        address,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_ITEM),
            offsets.UNIT_TXT_FILE_NO: u32(kind),
            offsets.UNIT_ID: u32(unit_id),
            offsets.UNIT_DATA: u32(data),
            offsets.UNIT_PATH: u32(path),
            offsets.UNIT_STATS: u32(0),
            offsets.UNIT_ROOM_NEXT: u32(0),
        },
    )
    mem.write_fields(path, {offsets.ITEM_PATH_X: u32(pos[0]), offsets.ITEM_PATH_Y: u32(pos[1])})
    mem.write_fields(
        data,
        {offsets.ITEM_QUALITY: u32(quality), offsets.ITEM_LOCATION: bytes([location])},
    )
    return address


def link(mem, unit, next_unit):
    mem.regions[unit][offsets.UNIT_ROOM_NEXT : offsets.UNIT_ROOM_NEXT + 4] = u32(next_unit)


def build() -> FakeSession:
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(PLAYER, {offsets.UNIT_PATH: u32(PLAYER_PATH)})
    mem.write_fields(PLAYER_PATH, {offsets.PATH_ROOM1: u32(ROOM_A)})

    boss = add_monster(mem, 0x0B010000, 101, 55, (100, 200), 500, 1000,
                       flags=offsets.MONSTER_FLAG_BOSS)
    corpse = add_monster(mem, 0x0B011000, 102, 56, (110, 210), 0, 800)
    link(mem, boss, corpse)

    item = add_item(mem, 0x0B020000, 201, 12, (120, 220), 7)
    carried = add_item(mem, 0x0B021000, 202, 13, (0, 0), 4, location=0)
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
    return FakeSession(mem)


def test_walks_the_players_room_and_its_neighbours():
    assert nearby_rooms(build()) == [ROOM_A, ROOM_B]


def test_finds_monsters_across_rooms_with_their_class_and_health():
    scan = scan_units(build())
    assert len(scan.monsters) == 2

    boss = next(m for m in scan.monsters if m.unit_id == 101)
    assert boss.is_boss and not boss.is_champion
    assert boss.position == (100, 200)
    assert (boss.hp, boss.max_hp) == (500, 1000)
    assert boss.hp_fraction == 0.5
    assert boss.is_alive


def test_dead_monsters_are_returned_but_marked_not_alive():
    """Corpses stay in the room; callers decide, we do not filter silently."""
    scan = scan_units(build())
    corpse = next(m for m in scan.monsters if m.unit_id == 102)
    assert not corpse.is_alive
    assert corpse not in [m for m in scan.monsters if m.is_alive]


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
    session = build()
    link(session.memory, 0x0B010000, 0xDEAD0000)  # points at unmapped memory
    scan = scan_units(session)
    assert scan.skipped >= 1
    assert any(m.unit_id == 101 for m in scan.monsters)


def test_no_game_means_no_units():
    session = build()
    session.memory.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(0))
    scan = scan_units(session)
    assert scan.monsters == [] and scan.ground_items == []
