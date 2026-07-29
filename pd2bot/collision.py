"""Reading walkability from the live game: the ground truth.

Each loaded Room1 carries a CollMap — a grid of 16-bit flag words, one per
subtile, saying what the game will actually let you do there. This is the
authority every other map source is judged against: generated maps (M3 P3)
are convenient, but if they disagree with these grids, these grids win.

Reach is inherently local: only the player's room and its neighbours are
loaded (M2 finding), so `read_local_collision` stitches those into one
queryable surface and is honest about the difference between "blocked" and
"outside what is loaded" — pathfinding must treat the two differently.

Layout citations and the flag words live in offsets.py (CollMap section);
the struct is deliberately absent from BH, see there.

    python -m pd2bot.collision          ASCII dump around the player
    python -m pd2bot.collision --size 40   wider view (subtiles per side)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.memory import GameSession
from pd2bot.units import nearby_rooms
from pd2bot.world import SUBTILES_PER_TILE

# A room's grid is normally tens of subtiles per side. A size beyond this is
# a torn read (dangling Coll pointer mid-transition), not a big room.
_MAX_GRID_SIDE = 1024


@dataclass(frozen=True)
class RoomCollision:
    """One room's collision grid, in world subtile coordinates."""

    origin: tuple[int, int]  # world subtile of cell (0, 0)
    width: int
    height: int
    cells: bytes  # raw little-endian WORDs, row-major, width*height of them

    def flags(self, x: int, y: int) -> int | None:
        """Collision word at world subtile (x, y); None outside this room."""
        cx, cy = x - self.origin[0], y - self.origin[1]
        if not (0 <= cx < self.width and 0 <= cy < self.height):
            return None
        index = (cy * self.width + cx) * 2
        return int.from_bytes(self.cells[index : index + 2], "little")


class LocalCollision:
    """The stitched view of every loaded room around the player.

    `is_walkable` answers for cells we can see; `is_known` distinguishes a
    wall from the void beyond the loaded rooms. Planning code must check
    `is_known` before trusting `is_walkable` — unknown is not walkable, but
    it is not a wall either.
    """

    def __init__(self, rooms: list[RoomCollision]) -> None:
        self.rooms = rooms

    def _flags(self, x: int, y: int) -> int | None:
        for room in self.rooms:
            flags = room.flags(x, y)
            if flags is not None:
                return flags
        return None

    def is_known(self, x: int, y: int) -> bool:
        return self._flags(x, y) is not None

    def is_walkable(self, x: int, y: int) -> bool:
        flags = self._flags(x, y)
        return flags is not None and not flags & offsets.COLL_UNWALKABLE_MASK

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        """(left, top, right, bottom) covering every loaded room, or None."""
        if not self.rooms:
            return None
        lefts, tops, rights, bottoms = zip(
            *(
                (r.origin[0], r.origin[1], r.origin[0] + r.width, r.origin[1] + r.height)
                for r in self.rooms
            ),
            strict=True,
        )
        return (min(lefts), min(tops), max(rights), max(bottoms))


def read_room_collision(session: GameSession, room1: int) -> RoomCollision | None:
    """One room's grid, or None when unreadable (normal during transitions).

    Every read sits inside the try: M2's torn-read lesson — a dangling
    pointer must surface as None here, not as an exception in a caller that
    thought it was iterating safe data.
    """
    try:
        coll = session.ptr(room1 + offsets.ROOM1_COLL)
        if coll is None:
            return None
        header = session.raw(coll, offsets.COLLMAP_HEADER_SIZE)

        def field(offset: int) -> int:
            return int.from_bytes(header[offset : offset + 4], "little")

        origin_x = field(offsets.COLLMAP_POS_GAME_X)
        origin_y = field(offsets.COLLMAP_POS_GAME_Y)
        width = field(offsets.COLLMAP_SIZE_GAME_X)
        height = field(offsets.COLLMAP_SIZE_GAME_Y)
        if not (0 < width < _MAX_GRID_SIDE and 0 < height < _MAX_GRID_SIDE):
            return None

        # The header states the same rectangle twice — in subtiles and in
        # tiles — so it must agree with itself at five subtiles per tile.
        # This is the integrity check (a torn read or a wrong address fails
        # it); the struct carries no usable end pointer to check instead.
        if (
            origin_x != field(offsets.COLLMAP_POS_ROOM_X) * SUBTILES_PER_TILE
            or origin_y != field(offsets.COLLMAP_POS_ROOM_Y) * SUBTILES_PER_TILE
            or width != field(offsets.COLLMAP_SIZE_ROOM_X) * SUBTILES_PER_TILE
            or height != field(offsets.COLLMAP_SIZE_ROOM_Y) * SUBTILES_PER_TILE
        ):
            return None

        map_start = session.ptr(coll + offsets.COLLMAP_MAP_START)
        if map_start is None:
            return None
        cells = session.raw(map_start, 2 * width * height)
    except Exception:
        return None
    return RoomCollision(origin=(origin_x, origin_y), width=width, height=height, cells=cells)


def read_local_collision(session: GameSession) -> LocalCollision:
    """Grids for the player's room and its loaded neighbours (may be empty)."""
    rooms = []
    for room1 in nearby_rooms(session):
        grid = read_room_collision(session, room1)
        if grid is not None:
            rooms.append(grid)
    return LocalCollision(rooms)


def strip_transient(cells: bytes) -> bytes:
    """Clear the occupancy bits, leaving only terrain.

    What survives is what will still be true next game: walls, water edges,
    doors, static objects. What goes is where monsters, players, items and
    corpses happened to be standing. Only the persistent atlas uses this;
    live reads keep the full flags, because right now the occupancy is real.
    """
    keep = ~offsets.COLL_TRANSIENT_MASK & 0xFFFF
    count = len(cells) // 2
    values = struct.unpack(f"<{count}H", cells)
    return struct.pack(f"<{count}H", *(value & keep for value in values))


def diagnose(session: GameSession) -> str:
    """Explain, field by field, why collision reading produces what it does.

    `read_room_collision` deliberately turns every failure into None so the
    caller cannot trip over a torn read. That is right for production and
    useless for debugging, so this walks the same chain with the guards
    reported rather than applied.
    """
    lines = []
    rooms = nearby_rooms(session)
    lines.append(f"nearby_rooms: {len(rooms)} room(s)")
    if not rooms:
        lines.append(
            "  none — the player's Room1 chain is unreadable. Since unit "
            "scanning uses the same chain, check `python -m pd2bot.dump` too."
        )
        return "\n".join(lines)

    for index, room1 in enumerate(rooms):
        lines.append(f"\nroom {index} @ 0x{room1:08X}")
        try:
            head = session.raw(room1, 0x30)
            words = " ".join(
                f"{int.from_bytes(head[i:i+4], 'little'):08X}" for i in range(0, 0x30, 4)
            )
            lines.append(f"  first 0x30 bytes as dwords: {words}")
        except Exception as exc:
            lines.append(f"  unreadable: {exc}")
            continue

        try:
            coll = session.ptr(room1 + offsets.ROOM1_COLL)
        except Exception as exc:
            lines.append(f"  Coll pointer (+0x{offsets.ROOM1_COLL:02X}) unreadable: {exc}")
            continue
        if coll is None:
            lines.append(f"  Coll pointer (+0x{offsets.ROOM1_COLL:02X}) is NULL")
            continue
        lines.append(f"  Coll -> 0x{coll:08X}")

        try:
            raw = session.raw(coll, 0x28)
        except Exception as exc:
            lines.append(f"  CollMap unreadable at that address: {exc}")
            continue
        fields = [int.from_bytes(raw[i : i + 4], "little") for i in range(0, 0x28, 4)]
        names = [
            "posGameX", "posGameY", "sizeGameX", "sizeGameY",
            "posRoomX", "posRoomY", "sizeRoomX", "sizeRoomY",
            "pMapStart", "(first grid cells)",
        ]
        for name, value in zip(names, fields, strict=True):
            lines.append(f"    {name:<18} {value:>10} (0x{value:08X})")

        pos_x, pos_y, width, height = fields[0], fields[1], fields[2], fields[3]
        room_x, room_y, room_w, room_h = fields[4], fields[5], fields[6], fields[7]
        start = fields[8]

        consistent = (
            pos_x == room_x * SUBTILES_PER_TILE
            and pos_y == room_y * SUBTILES_PER_TILE
            and width == room_w * SUBTILES_PER_TILE
            and height == room_h * SUBTILES_PER_TILE
        )
        lines.append(
            f"  tile/subtile check: room {room_w}x{room_h} @({room_x},{room_y}) "
            f"x{SUBTILES_PER_TILE} vs game {width}x{height} @({pos_x},{pos_y})"
            f" -> {'OK' if consistent else 'MISMATCH'}"
        )
        offset_from_coll = start - coll
        lines.append(
            f"  pMapStart is Coll+0x{offset_from_coll:02X} "
            f"(expected +0x{offsets.COLLMAP_HEADER_SIZE:02X}: grid stored inline)"
        )
        lines.append(f"  grid would be {2 * width * height} bytes for {width * height} cells")
        if not (0 < width < _MAX_GRID_SIDE and 0 < height < _MAX_GRID_SIDE):
            lines.append(f"  dimension check FAILED: {width}x{height}")
    return "\n".join(lines)


# --- human-readable dump (the live-verification tool) ------------------------


def ascii_map(
    local: LocalCollision,
    center: tuple[int, int],
    half_size: int = 30,
) -> str:
    """The world around `center`: '@' player, '.' walkable, '#' blocked,
    ' ' outside the loaded rooms. One character per subtile; y grows down,
    matching how the game's automap is oriented."""
    lines = []
    for y in range(center[1] - half_size, center[1] + half_size + 1):
        row = []
        for x in range(center[0] - half_size, center[0] + half_size + 1):
            if (x, y) == center:
                row.append("@")
            elif not local.is_known(x, y):
                row.append(" ")
            else:
                row.append("." if local.is_walkable(x, y) else "#")
        lines.append("".join(row))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from pd2bot.memory import GameNotRunning, NeedsAdministrator
    from pd2bot.units import player_unit, unit_position

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=30, help="half-width in subtiles")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="report the CollMap chain field by field instead of drawing",
    )
    args = parser.parse_args(argv)

    try:
        session = GameSession()
    except (GameNotRunning, NeedsAdministrator) as exc:
        print(exc, file=sys.stderr)
        return 1

    unit = player_unit(session)
    position = (
        unit_position(session, unit, offsets.UNIT_TYPE_PLAYER) if unit is not None else None
    )
    if position is None:
        print("not in a game", file=sys.stderr)
        return 1

    if args.debug:
        print(f"player at {position}\n")
        print(diagnose(session))
        return 0

    local = read_local_collision(session)
    print(f"player at {position}; {len(local.rooms)} room grids loaded; bounds {local.bounds}")
    if not local.rooms:
        # Drawing 60 blank lines is a terrible way to say "no data".
        print(
            "\nNo collision data — nothing to draw.\n"
            "Run `python -m pd2bot.collision --debug` to see which step of the "
            "Room1 -> CollMap chain fails."
        )
        return 1
    for room in local.rooms:
        print(f"  room grid origin {room.origin} size {room.width}x{room.height}")

    # The dump is in WORLD coordinates; the game draws the world rotated 45
    # degrees. Without this legend, comparing the picture to the screen means
    # doing that rotation in your head, which is how a correct reading gets
    # mistaken for a broken one.
    print(
        "\nOrientation — this map is in world coordinates, the game view is "
        "rotated 45 degrees:\n"
        "    right/+x here  = DOWN-RIGHT on your screen\n"
        "    down/+y here   = DOWN-LEFT on your screen\n"
        "    up-left corner = the TOP of your screen\n"
        "  '@' you   '.' walkable   '#' blocked   ' ' not loaded"
    )
    print(_nearest_obstacle_summary(local, position))
    print()
    print(ascii_map(local, position, args.size))
    return 0


def _nearest_obstacle_summary(local: LocalCollision, position: tuple[int, int]) -> str:
    """Where the nearest blocked cell lies, named in screen directions."""
    directions = [
        ((1, 0), "down-right"), ((-1, 0), "up-left"),
        ((0, 1), "down-left"), ((0, -1), "up-right"),
        ((1, 1), "straight down"), ((-1, -1), "straight up"),
        ((1, -1), "straight right"), ((-1, 1), "straight left"),
    ]
    reports = []
    for (step_x, step_y), name in directions:
        outcome = "clear as far as the loaded map goes"
        for distance in range(1, 61):
            x = position[0] + step_x * distance
            y = position[1] + step_y * distance
            if not local.is_known(x, y):
                # Say so rather than omitting the direction: a missing line
                # looks like a bug, and "ran out of map" is a real answer.
                outcome = f"open, then unloaded past {distance - 1} subtiles"
                break
            if not local.is_walkable(x, y):
                outcome = f"blocked at {distance} subtiles"
                break
        reports.append(f"    {name:<14} {outcome}")
    return "  nearest obstacle, in screen directions:\n" + "\n".join(reports)


if __name__ == "__main__":
    raise SystemExit(main())
