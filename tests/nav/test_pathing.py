"""A*, path simplification, and the walkability helpers — all pure."""

from pd2bot.nav.pathing import (
    BUDGET_CAP,
    BUDGET_FLOOR,
    OverlayGrid,
    astar,
    default_node_budget,
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


def test_budget_exhaustion_answers_none_not_an_exception():
    """The R257 P2 semantics: an exhausted budget is the same honest
    no-route answer an exhausted open set gives. The old cap RAISED —
    and nothing in production caught it, so had it ever bound, a walk
    would have crashed the tick instead of writing off a target."""
    # Goal behind a solid wall row: A* must exhaust the whole open field
    # before it could conclude "no path", and the budget fires first.
    big = MapGrid("\n".join(["." * 300] * 300 + ["#" * 300, "." * 300]))
    stats: dict = {}
    assert astar(big, (0, 0), (150, 301), max_expansions=1000, stats=stats) is None
    assert stats["budget_exhausted"] is True
    assert stats["expanded"] > 1000


def test_the_default_budget_binds_a_disconnected_flood_quickly():
    """The 2026-08-13 stall shape: two walkable regions, a nearby goal in
    the other one, a large open field to flood. Unbounded, this is the
    20.15 s answer; the distance-scaled default must answer in well
    under 100 ms."""
    import time

    # 300x300 open field, a full wall column, a thin far strip: ~90k
    # cells reachable from the start, goal 8 subtiles away behind the wall.
    art = ["." * 300 + "#" + "." * 5 for _ in range(300)]
    big = MapGrid("\n".join(art))
    start, goal = (296, 150), (304, 150)
    stats: dict = {}
    began = time.perf_counter()
    result = astar(big, start, goal, stats=stats)
    took = time.perf_counter() - began
    assert result is None
    assert stats["budget_exhausted"] is True
    assert stats["budget"] == default_node_budget(start, goal) == BUDGET_FLOOR
    assert took < 0.1, f"budgeted no-path took {took:.3f}s"


def test_a_long_real_path_is_found_under_the_default_budget():
    """The budget must never take away a path that exists: a snake
    corridor several hundred cells long still resolves."""
    # 5 corridors of 100, connected at alternating ends: path ~500 cells.
    rows = []
    for corridor in range(5):
        rows.append("." * 100)
        if corridor < 4:
            connector = ("." + "#" * 99) if corridor % 2 else ("#" * 99 + ".")
            rows.append(connector)
    snake = MapGrid("\n".join(rows))
    start, goal = (0, 0), (99, 8)
    stats: dict = {}
    path = astar(snake, start, goal, stats=stats)
    assert path is not None
    assert len(path) > 400
    assert stats["budget_exhausted"] is False


def test_default_budget_shape():
    assert default_node_budget((0, 0), (0, 0)) == BUDGET_FLOOR
    assert default_node_budget((0, 0), (8, 0)) == BUDGET_FLOOR
    assert default_node_budget((0, 0), (1000, 1000)) == BUDGET_CAP
    mid = default_node_budget((0, 0), (20, 0))
    assert BUDGET_FLOOR < mid < BUDGET_CAP


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
