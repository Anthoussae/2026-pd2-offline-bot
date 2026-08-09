"""Pathfinding over collision grids: pure logic, no game, no OS.

Works against anything that answers `is_walkable(x, y)` / `is_known(x, y)`
in world subtiles — the live stitched view (`collision.LocalCollision`) and
generated area maps (`mapdata`) both do. Unknown cells are treated as
unwalkable for planning: the follow loop re-plans as reality comes into
view, which beats optimistically walking into the void.

A* here is textbook: 8 directions, straight moves cost 1, diagonals √2
(scaled by 10/14 to stay in integers), octile-distance heuristic. One
deliberate rule: **no corner cutting** — a diagonal step is allowed only if
both adjacent orthogonal cells are walkable, because the character is not a
point and the game will wall-slide or stop where the math happily clipped
a corner.
"""

from __future__ import annotations

import heapq
from typing import Protocol

Point = tuple[int, int]

_STRAIGHT_COST = 10
_DIAGONAL_COST = 14  # ~10 * sqrt(2)

# Waypoints must stay inside the range a single click reliably carries the
# character. Measured 2026-07-28 (navdemo calibrate): clicks up to ~320 px
# from centre land on target, while 360-480 px complete only 60-70% of the
# distance. At the calibrated 20 px/subtile that is ~16 subtiles, so 12
# leaves margin — and coincides with kolbot's 10-15 node spacing.
MAX_WAYPOINT_SPACING = 12


class Grid(Protocol):
    def is_walkable(self, x: int, y: int) -> bool: ...
    def is_known(self, x: int, y: int) -> bool: ...


class OverlayGrid:
    """Two grids, one truth: the overlay wins wherever it has knowledge.

    Built for "generated map underneath, live memory collision on top" —
    the generated picture covers the whole area, and the live grids
    correct it wherever the game has actually loaded rooms (live is ground
    truth; see the hybrid map-knowledge ADR)."""

    def __init__(self, base: Grid, overlay: Grid) -> None:
        self.base = base
        self.overlay = overlay

    def is_known(self, x: int, y: int) -> bool:
        return self.overlay.is_known(x, y) or self.base.is_known(x, y)

    def is_walkable(self, x: int, y: int) -> bool:
        if self.overlay.is_known(x, y):
            return self.overlay.is_walkable(x, y)
        return self.base.is_walkable(x, y)

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        """Combined extent of both layers, for reporting what is known."""
        extents = [
            b for b in (getattr(self.base, "bounds", None), getattr(self.overlay, "bounds", None))
            if b is not None
        ]
        if not extents:
            return None
        return (
            min(e[0] for e in extents),
            min(e[1] for e in extents),
            max(e[2] for e in extents),
            max(e[3] for e in extents),
        )


class SearchLimitExceeded(RuntimeError):
    """A* touched more cells than the cap — target likely unreachable in a
    huge open area; treat as no-path rather than hanging."""


def _octile(a: Point, b: Point) -> int:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return _STRAIGHT_COST * max(dx, dy) + (_DIAGONAL_COST - _STRAIGHT_COST) * min(dx, dy)


_NEIGHBOURS = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)


def astar(
    grid: Grid,
    start: Point,
    goal: Point,
    max_expansions: int = 200_000,
) -> list[Point] | None:
    """Shortest walkable path from start to goal inclusive, or None.

    `start` is not required to be walkable (the player can stand on a cell
    the mask dislikes — doorways, floor clutter); `goal` is.
    """
    if not grid.is_walkable(*goal):
        return None
    if start == goal:
        return [start]

    open_heap: list[tuple[int, int, Point]] = [(_octile(start, goal), 0, start)]
    g_cost: dict[Point, int] = {start: 0}
    came_from: dict[Point, Point] = {}
    expanded = 0

    while open_heap:
        _, cost_here, current = heapq.heappop(open_heap)
        if cost_here > g_cost.get(current, cost_here):
            continue  # stale heap entry
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        expanded += 1
        if expanded > max_expansions:
            raise SearchLimitExceeded(
                f"gave up after {max_expansions} expansions from {start} toward {goal}"
            )

        cx, cy = current
        for dx, dy in _NEIGHBOURS:
            nx, ny = cx + dx, cy + dy
            if not grid.is_walkable(nx, ny):
                continue
            if dx and dy and not (
                grid.is_walkable(cx + dx, cy) and grid.is_walkable(cx, cy + dy)
            ):
                continue  # no corner cutting
            step = _DIAGONAL_COST if dx and dy else _STRAIGHT_COST
            new_cost = g_cost[current] + step
            neighbour = (nx, ny)
            if new_cost < g_cost.get(neighbour, new_cost + 1):
                g_cost[neighbour] = new_cost
                came_from[neighbour] = current
                heapq.heappush(
                    open_heap, (new_cost + _octile(neighbour, goal), new_cost, neighbour)
                )
    return None


def line_walkable(grid: Grid, a: Point, b: Point) -> bool:
    """Every cell on the segment a->b is walkable, with the same
    no-corner-cutting rule A* uses (diagonal steps check both shoulders)."""
    x, y = a
    dx, dy = abs(b[0] - x), abs(b[1] - y)
    step_x = 1 if b[0] > x else -1
    step_y = 1 if b[1] > y else -1
    error = dx - dy

    while True:
        if not grid.is_walkable(x, y):
            return False
        if (x, y) == b:
            return True
        double_error = 2 * error
        move_x = double_error > -dy
        move_y = double_error < dx
        if move_x and move_y:  # diagonal step: check both shoulders
            if not (grid.is_walkable(x + step_x, y) and grid.is_walkable(x, y + step_y)):
                return False
        if move_x:
            error -= dy
            x += step_x
        if move_y:
            error += dx
            y += step_y


def simplify(
    grid: Grid, path: list[Point], max_spacing: int = MAX_WAYPOINT_SPACING
) -> list[Point]:
    """Collapse an A* path into sparse waypoints.

    Greedy: from each waypoint, jump to the furthest later node that is both
    within `max_spacing` (Chebyshev — keeps hops on screen) and reachable in
    a straight walkable line. The final node always survives.
    """
    if len(path) <= 2:
        return list(path)

    waypoints = [path[0]]
    index = 0
    while index < len(path) - 1:
        best = index + 1
        for candidate in range(len(path) - 1, index, -1):
            a, b = path[index], path[candidate]
            if max(abs(a[0] - b[0]), abs(a[1] - b[1])) > max_spacing:
                continue
            if line_walkable(grid, a, b):
                best = candidate
                break
        waypoints.append(path[best])
        index = best
    return waypoints


def nearest_walkable(
    grid: Grid, x: int, y: int, radius: int = 15
) -> Point | None:
    """The closest walkable cell to (x, y) within `radius`, ring by ring.

    For targets that land on a wall (mis-clicked, or a generated map slightly
    off): kolbot does the same before giving up on a node."""
    if grid.is_walkable(x, y):
        return (x, y)
    for ring in range(1, radius + 1):
        best: Point | None = None
        best_distance = None
        for dx in range(-ring, ring + 1):
            for dy in (-ring, ring) if abs(dx) != ring else range(-ring, ring + 1):
                cx, cy = x + dx, y + dy
                if grid.is_walkable(cx, cy):
                    distance = dx * dx + dy * dy
                    if best_distance is None or distance < best_distance:
                        best, best_distance = (cx, cy), distance
        if best is not None:
            return best
    return None
