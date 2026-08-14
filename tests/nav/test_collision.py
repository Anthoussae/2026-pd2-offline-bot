"""CollMap reading: grid decode, stitching, and the torn-read paths."""

import struct

from pd2bot import offsets
from pd2bot.nav.collision import (
    LocalCollision,
    RoomCollision,
    ascii_map,
    read_room_collision,
)
from tests.conftest import FakeMemory, FakeSession, u32

ROOM1 = 0x0C000000
COLL = 0x0C100000
CELLS = 0x0C200000


def write_collmap(
    memory: FakeMemory,
    origin=(1000, 2000),
    size=(20, 15),
    grid: list[int] | None = None,
    room_size=None,
    room_origin=None,
) -> None:
    """Build a CollMap as the live client lays it out.

    Defaults are internally consistent: the header states the same
    rectangle in subtiles and in tiles, five subtiles per tile (verified
    live 2026-07-28). `room_size`/`room_origin` override the tile fields to
    simulate a torn or misread struct.
    """
    width, height = size
    cells = grid if grid is not None else [0] * (width * height)
    room_origin = room_origin or (origin[0] // 5, origin[1] // 5)
    room_size = room_size or (width // 5, height // 5)
    memory.write_fields(ROOM1, {offsets.ROOM1_COLL: u32(COLL)})
    memory.write_fields(
        COLL,
        {
            offsets.COLLMAP_POS_GAME_X: u32(origin[0]),
            offsets.COLLMAP_POS_GAME_Y: u32(origin[1]),
            offsets.COLLMAP_SIZE_GAME_X: u32(width),
            offsets.COLLMAP_SIZE_GAME_Y: u32(height),
            offsets.COLLMAP_POS_ROOM_X: u32(room_origin[0]),
            offsets.COLLMAP_POS_ROOM_Y: u32(room_origin[1]),
            offsets.COLLMAP_SIZE_ROOM_X: u32(room_size[0]),
            offsets.COLLMAP_SIZE_ROOM_Y: u32(room_size[1]),
            offsets.COLLMAP_MAP_START: u32(CELLS),
        },
    )
    memory.write(CELLS, struct.pack(f"<{len(cells)}H", *cells))


def test_reads_grid_and_looks_up_flags():
    memory = FakeMemory()
    # 20x15 grid, row-major; cell (2,1) is a wall.
    grid = [0] * (20 * 15)
    grid[1 * 20 + 2] = offsets.COLL_BLOCK_WALL
    write_collmap(memory, grid=grid)

    room = read_room_collision(FakeSession(memory), ROOM1)
    assert room is not None
    assert room.origin == (1000, 2000)
    assert (room.width, room.height) == (20, 15)
    assert room.flags(1002, 2001) == offsets.COLL_BLOCK_WALL
    assert room.flags(1000, 2000) == 0
    assert room.flags(999, 2000) is None  # outside the room


def test_tile_subtile_consistency_check_rejects_torn_struct():
    """The header states its rectangle twice, in subtiles and tiles. If the
    two disagree at 5 subtiles per tile, we are not looking at a coherent
    CollMap — the live client's own rooms always agree."""
    memory = FakeMemory()
    write_collmap(memory, room_size=(3, 3))  # 3*5=15 != 20 wide
    assert read_room_collision(FakeSession(memory), ROOM1) is None

    memory = FakeMemory()
    write_collmap(memory, room_origin=(1, 1))  # 1*5=5 != 1000
    assert read_room_collision(FakeSession(memory), ROOM1) is None


def test_grid_stored_inline_after_the_header():
    """Regression for the layout error the live client caught: pMapStart
    points at Coll+0x24, so the dword at 0x24 is grid data, not pMapEnd."""
    memory = FakeMemory()
    grid = [offsets.COLL_BLOCK_WALL] * (20 * 15)
    memory.write_fields(ROOM1, {offsets.ROOM1_COLL: u32(COLL)})
    inline = struct.pack("<9I", 1000, 2000, 20, 15, 200, 400, 4, 3, COLL + 0x24)
    memory.write(COLL, inline + struct.pack(f"<{len(grid)}H", *grid))

    room = read_room_collision(FakeSession(memory), ROOM1)
    assert room is not None
    assert room.flags(1000, 2000) == offsets.COLL_BLOCK_WALL


def test_null_coll_pointer_is_none():
    memory = FakeMemory()
    memory.write_fields(ROOM1, {offsets.ROOM1_COLL: u32(0)})
    assert read_room_collision(FakeSession(memory), ROOM1) is None


def test_dangling_coll_pointer_is_none():
    memory = FakeMemory()
    memory.write_fields(ROOM1, {offsets.ROOM1_COLL: u32(0x0DEAD000)})  # unmapped
    assert read_room_collision(FakeSession(memory), ROOM1) is None


def test_absurd_dimensions_rejected():
    memory = FakeMemory()
    write_collmap(memory, size=(70000, 15), grid=[0])
    assert read_room_collision(FakeSession(memory), ROOM1) is None


def room(origin, size, blocked=()):
    width, height = size
    cells = bytearray(2 * width * height)
    for bx, by in blocked:
        index = ((by - origin[1]) * width + (bx - origin[0])) * 2
        cells[index : index + 2] = struct.pack("<H", offsets.COLL_BLOCK_WALL)
    return RoomCollision(origin=origin, width=width, height=height, cells=bytes(cells))


def test_stitching_and_known_vs_blocked():
    local = LocalCollision(
        [
            room((0, 0), (5, 5), blocked=[(4, 4)]),
            room((5, 0), (5, 5)),  # adjacent to the right
        ]
    )
    assert local.is_walkable(2, 2)
    assert local.is_walkable(7, 2)  # in the second room
    assert not local.is_walkable(4, 4)  # a wall: known and blocked
    assert local.is_known(4, 4)
    assert not local.is_walkable(2, 9)  # beyond both rooms...
    assert not local.is_known(2, 9)  # ...and honestly unknown
    assert local.bounds == (0, 0, 10, 5)


def test_walkability_uses_the_full_mask():
    cells = struct.pack("<2H", 0, offsets.COLL_CLOSED_DOOR)
    local = LocalCollision([RoomCollision(origin=(0, 0), width=2, height=1, cells=cells)])
    assert local.is_walkable(0, 0)
    assert not local.is_walkable(1, 0)  # closed doors count as blocked in M3


def test_ascii_map_marks_player_walls_and_void():
    local = LocalCollision([room((0, 0), (3, 3), blocked=[(1, 0)])])
    art = ascii_map(local, center=(1, 1), half_size=1)
    rows = art.split("\n")
    assert rows[0] == ".#."
    assert rows[1] == ".@."
    assert rows[2] == "..."
    # One step further out is beyond the room: void, not wall.
    wide = ascii_map(local, center=(1, 1), half_size=2).split("\n")
    assert wide[0] == "     "
