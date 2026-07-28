"""Where the player is: the current area and the map seed.

The map seed matters beyond curiosity — D2 generates each game's random layouts
from it, so the same seed reproduces the same maps. M3's navigation uses it to
generate collision maps offline instead of exploring blindly.
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.memory import GameSession
from pd2bot.units import player_unit


# D2 measures levels in tiles but units in subtiles, five to a tile. Mixing them
# silently produces coordinates that look plausible and are wrong by 5x — the
# live dump caught this: a player at subtile (12679, 5180) sits in a level whose
# tile origin is (2500, 1000).
SUBTILES_PER_TILE = 5


@dataclass(frozen=True)
class Area:
    """The level the player is currently in.

    `position` and `size` are in **tiles**, as the game stores them.
    `bounds_subtiles` converts to the subtile coordinates that units use.
    """

    level_no: int
    position: tuple[int, int]
    size: tuple[int, int]

    @property
    def bounds_subtiles(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) in subtiles, comparable to unit positions."""
        left = self.position[0] * SUBTILES_PER_TILE
        top = self.position[1] * SUBTILES_PER_TILE
        return (
            left,
            top,
            left + self.size[0] * SUBTILES_PER_TILE,
            top + self.size[1] * SUBTILES_PER_TILE,
        )

    def contains(self, point: tuple[int, int]) -> bool:
        """True if a **subtile** position (as units report) lies in this level."""
        x, y = point
        left, top, right, bottom = self.bounds_subtiles
        return left <= x < right and top <= y < bottom


def read_area(session: GameSession) -> Area | None:
    """Read the current area, or None when not in a game or mid-transition.

    Chain: player -> Path -> Room1 -> Room2 -> Level. Any link can be null
    during a load, which is normal; callers poll until it isn't.
    """
    unit = player_unit(session)
    if unit is None:
        return None

    path = session.ptr(unit + offsets.UNIT_PATH)
    if path is None:
        return None
    room1 = session.ptr(path + offsets.PATH_ROOM1)
    if room1 is None:
        return None
    room2 = session.ptr(room1 + offsets.ROOM1_ROOM2)
    if room2 is None:
        return None
    level = session.ptr(room2 + offsets.ROOM2_LEVEL)
    if level is None:
        return None

    return Area(
        level_no=session.u32(level + offsets.LEVEL_NO),
        position=(
            session.u32(level + offsets.LEVEL_POS_X),
            session.u32(level + offsets.LEVEL_POS_Y),
        ),
        size=(
            session.u32(level + offsets.LEVEL_SIZE_X),
            session.u32(level + offsets.LEVEL_SIZE_Y),
        ),
    )


def read_map_seed(session: GameSession) -> int | None:
    """The current game's map seed: constant within a game, new in the next one."""
    unit = player_unit(session)
    if unit is None:
        return None
    act = session.ptr(unit + offsets.UNIT_ACT)
    if act is None:
        return None
    return session.u32(act + offsets.ACT_MAP_SEED)
