"""Level-exit enumeration (M6 P1): the RoomTile/preset walk over fakes.

The geometry under test is d2mapapi's own algorithm (mapdata.cpp:217-232):
a TILE preset names a warp, the RoomTile whose *nNum matches names the
destination level, and the world position is room origin * 5 + preset
offset. The fakes build exactly those chains, including the torn variants
the defensive rules exist for.
"""

from __future__ import annotations

from pd2bot import offsets
from pd2bot.exits import LevelExit, read_level_exits
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, u32

PLAYER = 0x0C000000
PLAYER_PATH = 0x0C000100
ROOM1 = 0x0C000200
LEVEL = 0x0C001000
DEST_LEVEL = 0x0C002000
ROOM2_A = 0x0C010000
ROOM2_B = 0x0C020000
DEST_ROOM2 = 0x0C030000
TILE_A = 0x0C040000
NUM_A = 0x0C040100
PRESET_NPC = 0x0C050000
PRESET_STAIRS = 0x0C050100

WARP_NUM = 71
DEST_AREA = offsets.AREA_TOWER_CELLAR_1


def _player_chain(mem: FakeMemory, room2: int) -> None:
    """player -> path -> room1 -> room2; the entry into the level."""
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(PLAYER))
    mem.write_fields(PLAYER, {offsets.UNIT_PATH: u32(PLAYER_PATH)})
    mem.write_fields(PLAYER_PATH, {offsets.PATH_ROOM1: u32(ROOM1)})
    mem.write_fields(ROOM1, {offsets.ROOM1_ROOM2: u32(room2)})


def _level(mem: FakeMemory, address: int, level_no: int, first_room2: int = 0) -> None:
    mem.write_fields(
        address,
        {
            offsets.LEVEL_ROOM2_FIRST: u32(first_room2),
            offsets.LEVEL_NO: u32(level_no),
        },
    )


def _room2(
    mem: FakeMemory,
    address: int,
    *,
    level: int,
    pos_tiles: tuple[int, int] = (0, 0),
    tiles: int = 0,
    presets: int = 0,
    next_room2: int = 0,
) -> None:
    mem.write_fields(
        address,
        {
            offsets.ROOM2_NEXT: u32(next_room2),
            offsets.ROOM2_POS_X: u32(pos_tiles[0]),
            offsets.ROOM2_POS_Y: u32(pos_tiles[1]),
            offsets.ROOM2_ROOM_TILES: u32(tiles),
            offsets.ROOM2_LEVEL: u32(level),
            offsets.ROOM2_PRESET: u32(presets),
        },
    )


def _roomtile(
    mem: FakeMemory, address: int, *, dest_room2: int, num_at: int,
    num: int, next_tile: int = 0,
) -> None:
    mem.write(num_at, u32(num))
    mem.write_fields(
        address,
        {
            offsets.ROOMTILE_ROOM2: u32(dest_room2),
            offsets.ROOMTILE_NEXT: u32(next_tile),
            offsets.ROOMTILE_NUM_PTR: u32(num_at),
        },
    )


def _preset(
    mem: FakeMemory, address: int, *, kind: int, txt: int,
    pos: tuple[int, int], next_preset: int = 0,
) -> None:
    mem.write_fields(
        address,
        {
            offsets.PRESET_TXT_FILE_NO: u32(txt),
            offsets.PRESET_POS_X: u32(pos[0]),
            offsets.PRESET_NEXT: u32(next_preset),
            offsets.PRESET_TYPE: u32(kind),
            offsets.PRESET_POS_Y: u32(pos[1]),
        },
    )


def build(*, room_pos=(1000, 2000), preset_pos=(3, 4)) -> FakeSession:
    """One level, two rooms; room A holds a staircase to Cellar 1."""
    mem = FakeMemory()
    _player_chain(mem, ROOM2_A)
    _level(mem, LEVEL, offsets.AREA_FORGOTTEN_TOWER, first_room2=ROOM2_A)
    _level(mem, DEST_LEVEL, DEST_AREA)
    _room2(mem, DEST_ROOM2, level=DEST_LEVEL)
    _roomtile(mem, TILE_A, dest_room2=DEST_ROOM2, num_at=NUM_A, num=WARP_NUM)
    # An npc preset first: the walk must skip past non-tile presets.
    _preset(
        mem, PRESET_NPC, kind=offsets.PRESET_TYPE_NPC, txt=WARP_NUM,
        pos=(9, 9), next_preset=PRESET_STAIRS,
    )
    _preset(
        mem, PRESET_STAIRS, kind=offsets.PRESET_TYPE_TILE, txt=WARP_NUM,
        pos=preset_pos,
    )
    _room2(
        mem, ROOM2_A, level=LEVEL, pos_tiles=room_pos, tiles=TILE_A,
        presets=PRESET_NPC, next_room2=ROOM2_B,
    )
    _room2(mem, ROOM2_B, level=LEVEL)  # an ordinary room: no tiles, no presets
    return FakeSession(mem)


def test_finds_the_staircase_with_world_position_and_destination():
    scan = read_level_exits(build(room_pos=(1000, 2000), preset_pos=(3, 4)))
    assert scan is not None
    assert scan.area == offsets.AREA_FORGOTTEN_TOWER
    assert scan.rooms_walked == 2
    assert scan.exits == (
        LevelExit(position=(5003, 10004), dest_area=DEST_AREA),
    )
    assert scan.exits[0].dest_name == "Tower Cellar Level 1"
    assert scan.toward(DEST_AREA) == scan.exits
    assert scan.toward(offsets.AREA_BLACK_MARSH) == ()


def test_npc_presets_matching_the_warp_number_are_not_exits():
    """The npc preset in the chain shares dwTxtFileNo=71 with the warp —
    only the TILE preset may claim it (type check, not number check)."""
    scan = read_level_exits(build())
    assert scan is not None
    assert len(scan.exits) == 1
    assert scan.exits[0].position == (5003, 10004)  # the stairs, not (9,9)


def test_duplicate_reports_collapse():
    """The same warp visible from two rooms is one exit, not two."""
    session = build()
    mem = session.memory
    # Give room B the same tile chain and preset as room A.
    _room2(
        mem, ROOM2_B, level=LEVEL, pos_tiles=(1000, 2000), tiles=TILE_A,
        presets=PRESET_NPC,
    )
    scan = read_level_exits(session)
    assert scan is not None
    assert len(scan.exits) == 1


def test_room_chain_cycle_stops_instead_of_spinning():
    """A torn chain that loops back must end the walk, not hang it."""
    session = build()
    mem = session.memory
    # Room B's next pointer loops back to room A.
    _room2(mem, ROOM2_B, level=LEVEL, next_room2=ROOM2_A)
    scan = read_level_exits(session)
    assert scan is not None
    assert scan.rooms_walked == 2  # A, B, then the cycle guard fires
    assert len(scan.exits) == 1


def test_unreadable_destination_is_skipped_and_counted():
    """A tile whose destination room is unmapped memory costs that tile,
    not the scan."""
    session = build()
    mem = session.memory
    # Point the tile at an unmapped destination room.
    _roomtile(
        mem, TILE_A, dest_room2=0x0DEAD000, num_at=NUM_A, num=WARP_NUM
    )
    scan = read_level_exits(session)
    assert scan is not None
    assert scan.exits == ()
    assert scan.skipped >= 1


def test_none_when_not_in_a_game():
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(0))
    assert read_level_exits(FakeSession(mem)) is None
