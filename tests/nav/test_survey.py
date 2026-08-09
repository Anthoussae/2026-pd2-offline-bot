"""Frontier extraction over hand-built atlases (pd2bot/survey.py)."""

import struct
from pathlib import Path

from pd2bot import offsets
from pd2bot.nav.collision import RoomCollision
from pd2bot.nav.mapstore import ExploredArea
from pd2bot.nav.survey import CLUSTER, coverage, frontier_targets

WALL = offsets.COLL_BLOCK_WALL


def room(origin, width=40, height=40, walls=()):
    """A room grid, all-walkable except the world subtiles in `walls`."""
    words = []
    for cy in range(height):
        for cx in range(width):
            world = (origin[0] + cx, origin[1] + cy)
            words.append(WALL if world in walls else 0)
    return RoomCollision(
        origin=origin, width=width, height=height,
        cells=struct.pack(f"<{len(words)}H", *words),
    )


def area_of(*rooms):
    keyed = {
        (r.origin[0], r.origin[1], r.width, r.height): r for r in rooms
    }
    return ExploredArea(
        Path("unused.json"), seed=0xABCD, difficulty=2, area_id=3, rooms=keyed,
    )


def test_bounds_clamp_makes_a_covered_area_frontierless():
    # One room filling its area's entire box: every outside probe lands
    # beyond the bounds, so there is nothing left to survey.
    area = area_of(room((0, 0)))
    assert frontier_targets(area, (0, 0, 40, 40)) == []


def test_unknown_ground_inside_the_bounds_is_frontier():
    # The area's box is twice the room's width: the right edge borders
    # unrecorded ground that IS in the area, and only the right edge.
    area = area_of(room((0, 0)))
    targets = frontier_targets(area, (0, 0, 80, 40))
    assert targets, "unrecorded in-bounds ground must be offered"
    assert all(x == 39 for x, _ in targets), f"only the right edge: {targets}"


def test_a_walled_edge_offers_no_target():
    # The whole right edge (and the strip behind it, past the inward
    # probe) is wall: there is nothing to stand on, so nothing to offer.
    walls = {(x, y) for x in range(36, 40) for y in range(40)}
    area = area_of(room((0, 0), walls=walls))
    assert frontier_targets(area, (0, 0, 80, 40)) == []


def test_adjacent_rooms_do_not_read_each_other_as_unknown():
    # Two rooms sharing an edge: the shared border is covered ground, so
    # the only frontier is the outer right edge of the second room.
    area = area_of(room((0, 0)), room((40, 0)))
    targets = frontier_targets(area, (0, 0, 120, 40))
    assert targets and all(x == 79 for x, _ in targets), targets


def test_candidates_cluster():
    # A 40-subtile edge sampled every 8 yields five raw candidates; the
    # cluster radius collapses neighbours that load the same rooms anyway.
    area = area_of(room((0, 0)))
    targets = frontier_targets(area, (0, 0, 80, 40))
    assert len(targets) < 5
    for i, a in enumerate(targets):
        for b in targets[i + 1:]:
            assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) >= CLUSTER


def test_coverage_reports_rooms_and_open_frontier():
    area = area_of(room((0, 0)))
    line = coverage(area, (0, 0, 80, 40))
    assert "1 room(s) recorded" in line
    assert "frontier point(s) open" in line
    assert "0 frontier" not in line  # the right edge is open
    closed = coverage(area, (0, 0, 40, 40))
    assert "0 frontier point(s) open" in closed


def test_a_narrow_doorway_between_old_stride_samples_is_listed():
    """Session-review issue 002's validation: a ~4-subtile doorway that
    sat between the old 8-stride samples (wall-faced on both, thicker
    than the inward probe) must be offered as a frontier — a premature
    '0 frontier open' understates coverage exactly where the cellars
    need it most."""
    # The top rows are wall 4 deep (past PROBE_IN) except a 4-wide
    # doorway at x=3..6 — centered between the old samples at 0 and 8.
    walls = {
        (x, y)
        for x in range(16)
        for y in range(4)
        if not 3 <= x <= 6
    }
    area = area_of(room((0, 0), width=16, height=16, walls=walls))
    targets = frontier_targets(area, (0, -50, 50, 50))
    assert any(
        0 <= x <= 8 and y <= 4 for x, y in targets
    ), f"the doorway frontier never appeared: {targets}"
