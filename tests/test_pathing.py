"""A*, path simplification, and the walkability helpers — all pure."""

import pytest

from pd2bot.pathing import (
    OverlayGrid,
    SearchLimitExceeded,
    astar,
    line_walkable,
    nearest_walkable,
    simplify,
)


class MapGrid:
    """A grid built from ASCII art: '.' walkable, '#' blocked."""

    def __init__(self, art: str) -> None:
        self.rows = [line for line in art.strip("\n").split("\n")]

    def is_walkable(self, x: int, y: int) -> bool:
        if 0 <= y < len(self.rows) and 0 <= x < len(self.rows[y]):
            return self.rows[y][x] == "."
        return False

    def is_known(self, x: int, y: int) -> bool:
        return 0 <= y < len(self.rows) and 0 <= x < len(self.rows[y])


OPEN = MapGrid("""
..........
..........
..........
..........
..........
""")


def test_straight_line():
    path = astar(OPEN, (0, 0), (9, 0))
    assert path is not None
    assert path[0] == (0, 0) and path[-1] == (9, 0)
    assert len(path) == 10


def test_diagonal_preferred_over_staircase():
    path = astar(OPEN, (0, 0), (4, 4))
    assert path is not None
    assert len(path) == 5  # pure diagonal


def test_wall_forces_detour():
    grid = MapGrid("""
.....
.###.
.....
""")
    path = astar(grid, (2, 0), (2, 2))
    assert path is not None
    assert all(grid.is_walkable(*node) for node in path)
    assert len(path) > 3  # had to go around the wall


def test_u_trap():
    grid = MapGrid("""
.......
..###..
..#.#..
..###..
.......
""")
    # The (3,2) pocket is fully sealed.
    assert astar(grid, (0, 0), (3, 2)) is None


def test_unwalkable_goal_is_no_path():
    grid = MapGrid("..#")
    assert astar(grid, (0, 0), (2, 0)) is None


def test_start_may_be_unwalkable():
    # The player can be standing on a cell the mask dislikes (doorway,
    # clutter); that must not strand them.
    grid = MapGrid("#..")
    path = astar(grid, (0, 0), (2, 0))
    assert path is not None and path[0] == (0, 0)


def test_no_corner_cutting():
    grid = MapGrid("""
.#
#.
""")
    # (0,0) -> (1,1) diagonally would clip both blocked shoulders.
    assert astar(grid, (0, 0), (1, 1)) is None


def test_search_limit():
    with pytest.raises(SearchLimitExceeded):
        # Goal behind a solid wall row: A* must exhaust the whole open field
        # before it could conclude "no path", and the cap fires first.
        big = MapGrid("\n".join(["." * 300] * 300 + ["#" * 300, "." * 300]))
        astar(big, (0, 0), (150, 301), max_expansions=1000)


def test_line_walkable():
    grid = MapGrid("""
.....
..#..
.....
""")
    assert line_walkable(grid, (0, 0), (4, 0))
    assert not line_walkable(grid, (0, 1), (4, 1))  # through the wall
    assert line_walkable(grid, (0, 2), (4, 2))


def test_simplify_collapses_straight_runs():
    path = astar(OPEN, (0, 0), (9, 0))
    waypoints = simplify(grid=OPEN, path=path, max_spacing=5)
    assert waypoints[0] == (0, 0) and waypoints[-1] == (9, 0)
    assert len(waypoints) == 3  # 0 -> 5 -> 9 under a 5-cell cap
    # And every hop respects the spacing cap.
    for a, b in zip(waypoints, waypoints[1:], strict=False):
        assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 5


def test_simplify_keeps_corners():
    grid = MapGrid("""
.....
.###.
.....
""")
    path = astar(grid, (0, 0), (4, 0))
    assert path == simplify(grid, path, max_spacing=50) or len(
        simplify(grid, path, max_spacing=50)
    ) <= len(path)
    # The straight line (0,0)->(4,0) is walkable here, so with a big cap it
    # should collapse to just the endpoints.
    assert simplify(grid, path, max_spacing=50) == [(0, 0), (4, 0)]


def test_overlay_live_truth_wins():
    generated = MapGrid("""
....
....
""")

    class LivePatch:
        """Knows only cell (1,0), and disagrees with the generated map there."""

        def is_known(self, x, y):
            return (x, y) == (1, 0)

        def is_walkable(self, x, y):
            return False

    grid = OverlayGrid(base=generated, overlay=LivePatch())
    assert not grid.is_walkable(1, 0)  # live overrides generated
    assert grid.is_walkable(2, 0)  # generated fills the rest
    assert grid.is_known(1, 0) and grid.is_known(3, 1)
    assert not grid.is_known(9, 9)


def test_nearest_walkable():
    grid = MapGrid("""
###..
###..
#####
""")
    assert nearest_walkable(grid, 0, 0) == (3, 0)
    assert nearest_walkable(grid, 4, 1) == (4, 1)  # already walkable
    sealed = MapGrid("###")
    assert nearest_walkable(sealed, 1, 0, radius=2) is None
