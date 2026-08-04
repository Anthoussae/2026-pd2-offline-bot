"""Frontier extraction: where does the atlas end? (M5 P6, R175/R176.)

The map store remembers every room the client has ever loaded
(`mapstore.py`), and every walk records the rooms around the player as a
side effect. What nothing did before this module is choose WHERE to walk
so an area gets *finished*: the atlas grew wherever runs happened to go,
and route planning treats unknown ground as blocked (navigate.py — "that
ground has never been seen"), so targets in the unvisited parts of an
area were unreachable until someone wandered there.

The survey closes that loop. A frontier is a spot on recorded, walkable
ground with unrecorded ground just beyond it. Standing near one loads the
rooms beyond (the client keeps a ~3x3 room neighbourhood in memory —
measured at 46-67 subtiles by T51), the passive recorder stores them, and
the frontier moves outward. When no reachable frontier remains inside the
area's bounds, the area is done — permanently, because single-player maps
are fixed per character+difficulty (the atlas premise, M3 ADR).

Pure functions over an `ExploredArea`: no session access, no walking.
The behavior layer's `survey` step does the walking; the wiring owns the
store. Everything here is unit-testable with hand-built rooms.
"""

from __future__ import annotations

from pd2bot.mapstore import ExploredArea

Point = tuple[int, int]

# Sample spacing along a room edge, in subtiles. Rooms are typically 40
# on a side, so this probes each edge a handful of times — enough that a
# door cannot hide between samples of the walkable scan below, cheap
# enough to recompute when the atlas grows.
EDGE_STRIDE = 8
# How far past the room's edge the "is anything recorded there?" probe
# sits. 2 rather than 1 so an off-by-one on a shared room border cannot
# read the neighbour's own edge row as terra incognita.
PROBE_OUT = 2
# How far back inside the room to look for a walkable cell to stand on.
# The edge cell itself is often a wall (rooms meet at walls); a doorway's
# floor is within a few cells of it.
PROBE_IN = 4
# Candidates closer together than this collapse into one: walking to
# either loads the same room neighbourhood, so keeping both would buy a
# second walk for nothing.
CLUSTER = 12


def _chebyshev(a: Point, b: Point) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def frontier_targets(
    area: ExploredArea, bounds: tuple[int, int, int, int]
) -> list[Point]:
    """Walkable points on the edge of the unknown, inside `bounds`.

    `bounds` is the target area's own box (`Area.bounds_subtiles`), and it
    is what stops the survey chasing the map's edges forever: Cold Plains
    borders three other areas, and a frontier probe landing in Blood Moor
    is Blood Moor's problem, not this survey's.

    Returns an unordered list; callers sort by their own distance. Empty
    means the area is done: every recorded edge either has recorded
    ground beyond it, leads out of the area, or has no walkable approach
    (solid wall — nothing to survey through).
    """
    left, top, right, bottom = bounds
    candidates: list[Point] = []

    def consider(probe: Point, edge: Point, inward: tuple[int, int]) -> None:
        px, py = probe
        if not (left <= px < right and top <= py < bottom):
            return  # beyond the area: someone else's ground
        if area.is_known(px, py):
            return  # already recorded: not a frontier
        for i in range(PROBE_IN):
            inside = (edge[0] + inward[0] * i, edge[1] + inward[1] * i)
            if area.is_walkable(*inside):
                candidates.append(inside)
                return
        # No walkable cell behind this edge sample: a wall faces the
        # unknown here, and there is nothing to stand on. Not a target.

    for room in area.rooms:
        ox, oy = room.origin
        w, h = room.width, room.height
        for x in range(ox, ox + w, EDGE_STRIDE):
            consider((x, oy - PROBE_OUT), (x, oy), (0, 1))  # top edge
            consider((x, oy + h - 1 + PROBE_OUT), (x, oy + h - 1), (0, -1))
        for y in range(oy, oy + h, EDGE_STRIDE):
            consider((ox - PROBE_OUT, y), (ox, y), (1, 0))  # left edge
            consider((ox + w - 1 + PROBE_OUT, y), (ox + w - 1, y), (-1, 0))

    # Collapse near-duplicates: first-come wins, order is stable because
    # the room dict preserves insertion order, so the surviving point for
    # a cluster does not jitter between recomputations.
    kept: list[Point] = []
    for candidate in candidates:
        if all(_chebyshev(candidate, existing) >= CLUSTER for existing in kept):
            kept.append(candidate)
    return kept


def coverage(
    area: ExploredArea, bounds: tuple[int, int, int, int]
) -> str:
    """One line for logs and the pre-flight: how much of the area is held.

    Room counts rather than percentages on purpose: the walkable fraction
    of an area's bounding box is unknowable without full knowledge — the
    exact thing a partial survey lacks — so a percentage would be a
    guess wearing a number. Frontier count is the honest progress figure:
    zero means done.
    """
    open_frontier = len(frontier_targets(area, bounds))
    return (
        f"{area.room_count} room(s) recorded, "
        f"{open_frontier} frontier point(s) open"
    )
