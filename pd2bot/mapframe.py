"""Coordinate frames: the same point, said three ways.

World subtiles are what every unit reports and they are correct, but
they are unreadable. The Forgotten Tower failure reads as *"the player
was at (10006, 8002), the staircase at (10002, 8013)"* — where the
interesting fact, **eleven subtiles apart inside a nineteen-wide room**,
has to be recomputed by hand every single time somebody looks at it.

So every spatial event in the run log carries three frames (R220 Q3):

- **world** — absolute game subtiles, e.g. (10002, 8013). Unambiguous,
  and what you compare against anything else the game reports.
- **local** — the area's own origin subtracted, so the Tower staircase
  becomes (2, 13) in a 40x40 room. This is the "simple X/Y coordinate
  system encompassing the surveyed map area" the operator asked for, and
  it costs exactly one subtraction.
- **rel** — the offset from the character, with a Chebyshev distance and
  a compass bearing, so a movement command reads as "eleven subtiles
  south-west of me" without arithmetic.

Two conventions, both load-bearing, both stated here so nobody has to
rediscover them:

**Chebyshev distance**, not Euclidean. Every reach, radius and budget in
this codebase already uses it (`steps.py::_chebyshev`, `necro.py`), so a
distance in the log compares directly against `click_range`,
`engage_radius` and `pickup_reach` with no conversion. A log whose
distances mean something subtly different from the code's distances is a
trap.

**Screen-north is the world (-1, -1) diagonal** (R219, user-confirmed).
D2 renders isometrically: `sx = wx - wy`, `sy = wx + wy`, so decreasing
BOTH world coordinates moves up the screen. Pure `-x` is screen NW and
pure `-y` is screen NE. Bearings here are therefore what the operator
sees, not world axes — "the staircase is SE of you" means it is
down-and-right on their monitor. An agent reading `(-1,-1) == north`
without this paragraph will "fix" it into a bug.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from pd2bot import offsets
from pd2bot.world import SUBTILES_PER_TILE

# Screen compass, 45-degree sectors clockwise from up.
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def bearing(delta: tuple[int, int]) -> str | None:
    """The SCREEN compass point a world delta points toward.

    None for a zero delta — "no direction" is a real answer and inventing
    one would be the guessed-value failure the log forbids.
    """
    dx, dy = delta
    if dx == 0 and dy == 0:
        return None
    # World -> screen (isometric): x right-ish, y down-ish on the monitor.
    screen_x = dx - dy
    screen_y = dx + dy
    # Angle clockwise from screen-up, where up is -screen_y.
    angle = math.degrees(math.atan2(screen_x, -screen_y)) % 360
    return _COMPASS[int((angle + 22.5) % 360 // 45)]


def chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


@dataclass(frozen=True)
class MapFrame:
    """One area's local coordinate system: an origin and a size.

    Built from the live `Area` when there is one, from the atlas when
    there is not, and NEVER invented — an event whose frame is unknown
    says `world` and reports local == world, because a made-up origin
    would silently shift every coordinate a reader compares.
    """

    origin: tuple[int, int]
    size: tuple[int, int] | None = None
    name: str = "world"
    area_id: int | None = None

    @classmethod
    def unknown(cls) -> MapFrame:
        """The honest fallback: local coordinates equal world ones."""
        return cls(origin=(0, 0), size=None, name="world", area_id=None)

    @classmethod
    def from_area(cls, area: Any | None) -> MapFrame:
        """The live area's own frame, or the honest fallback."""
        if area is None:
            return cls.unknown()
        try:
            left, top, right, bottom = area.bounds_subtiles
            area_id = area.level_no
        except Exception:  # noqa: BLE001 - a torn read is not a frame
            return cls.unknown()
        return cls(
            origin=(left, top),
            size=(right - left, bottom - top),
            name=f"area-{area_id:03d}",
            area_id=area_id,
        )

    @classmethod
    def from_atlas(cls, explored: Any, area_id: int) -> MapFrame:
        """A frame from stored room grids, for when no live area is
        readable. The atlas bounds are the union of recorded rooms, which
        is a floor on the real area rather than its true extent — good
        enough for readable local coordinates, and labelled so a reader
        knows which it got."""
        bounds = getattr(explored, "bounds", None)
        if not bounds:
            return cls.unknown()
        left, top, right, bottom = bounds
        return cls(
            origin=(left, top),
            size=(right - left, bottom - top),
            name=f"atlas-{area_id:03d}",
            area_id=area_id,
        )

    @property
    def known(self) -> bool:
        return self.name != "world"

    def to_local(self, world: tuple[int, int]) -> tuple[int, int]:
        return (world[0] - self.origin[0], world[1] - self.origin[1])

    def to_world(self, local: tuple[int, int]) -> tuple[int, int]:
        return (local[0] + self.origin[0], local[1] + self.origin[1])

    def contains(self, world: tuple[int, int]) -> bool:
        if self.size is None:
            return False
        x, y = self.to_local(world)
        return 0 <= x < self.size[0] and 0 <= y < self.size[1]

    def describe(
        self,
        world: tuple[int, int] | None,
        player: tuple[int, int] | None = None,
    ) -> dict | None:
        """The payload every spatial event embeds.

            {"world": [10002, 8013], "local": [2, 13], "rel": [-4, 11],
             "dist": 11, "bearing": "SW", "frame": "area-020"}

        `rel`, `dist` and `bearing` are omitted rather than faked when no
        player position is available.
        """
        if world is None:
            return None
        world = (int(world[0]), int(world[1]))
        payload: dict = {
            "world": list(world),
            "local": list(self.to_local(world)),
            "frame": self.name,
        }
        if player is not None:
            delta = (world[0] - player[0], world[1] - player[1])
            payload["rel"] = list(delta)
            payload["dist"] = chebyshev(world, player)
            payload["bearing"] = bearing(delta)
        return payload


def describe(
    world: tuple[int, int] | None,
    player: tuple[int, int] | None = None,
    frame: MapFrame | None = None,
) -> dict | None:
    """Module-level convenience: `frame` defaults to the honest fallback."""
    return (frame or MapFrame.unknown()).describe(world, player)


def area_name(area_id: int | None) -> str | None:
    """The area's display name, or an honest `area <n>`. Never a guess."""
    if area_id is None:
        return None
    return offsets.AREA_NAMES.get(area_id, f"area {area_id}")


def screen_north(
    anchor: tuple[int, int],
    distance: int,
    is_walkable=None,
) -> tuple[int, int]:
    """The most-northerly stageable ground within `distance` of `anchor`.

    THE one definition of screen-north in the codebase (M6 P4's
    `clear_countess` staging delegates here). Bearings are tried
    north-first at each distance, distance descending, so the answer
    degrades gracefully: full distance due north when the map allows it,
    then the NW/NE shoulders, then closer in. Without a walkability
    oracle the full-distance north point stands as asked.
    """
    bearings = ((-1, -1), (-1, 0), (0, -1))  # N, NW, NE in screen terms
    if is_walkable is not None:
        for step in range(distance, 7, -4):
            for bx, by in bearings:
                candidate = (anchor[0] + bx * step, anchor[1] + by * step)
                try:
                    if is_walkable(candidate):
                        return candidate
                except Exception:  # noqa: BLE001 - a torn read is not a wall
                    continue
    return (anchor[0] - distance, anchor[1] - distance)


__all__ = [
    "SUBTILES_PER_TILE",
    "MapFrame",
    "area_name",
    "bearing",
    "chebyshev",
    "describe",
    "screen_north",
]
