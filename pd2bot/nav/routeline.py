"""Route lines: an operator-recorded core path through an area, and the leash.

A RouteLine is an ordered polyline of world waypoints for one
(map seed, difficulty, area). It is recorded by walking the route once
(drills/t84_record_line.py), thinned, and stored beside the atlas —
seed-bound save-data, regenerable by re-walking (the mapstore.py
precedent, same directory family). Runs use it as a LEASH: each tick
the step asks "how far am I from my line, and which way is back?", and
returns per the active posture's policy (R241).

Geometry is pure and unit-tested: nothing here reads the game.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from pd2bot.nav.mapstore import DEFAULT_ROOT

FORMAT_VERSION = 1

Point = tuple[int, int]


@dataclass(frozen=True)
class Stray:
    """Where the character stands relative to the line, one tick's answer."""

    distance: float  # subtiles from the nearest point on the line
    nearest: Point  # that nearest point (the leash's return target)
    progress: float  # 0..1 arc-length fraction of the line already passed
    segment: int  # index of the nearest segment (diagnostics)


@dataclass
class RouteLine:
    seed: int
    difficulty: int
    area_id: int
    points: list[Point] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError(
                f"a route line needs at least 2 points, got {len(self.points)}"
            )
        self._cum = _cumulative_lengths(self.points)

    @property
    def length(self) -> float:
        return self._cum[-1]

    def stray_from(self, position: Point) -> Stray:
        """Nearest point on the polyline to `position`, with progress.

        Segment-by-segment perpendicular projection, clamped to segment
        ends; ties go to the EARLIER segment so progress never jumps
        backward on a corner.
        """
        best_d2 = math.inf
        best: tuple[float, float] = self.points[0]
        best_seg = 0
        best_along = 0.0
        for i in range(len(self.points) - 1):
            ax, ay = self.points[i]
            bx, by = self.points[i + 1]
            dx, dy = bx - ax, by - ay
            seg_len2 = dx * dx + dy * dy
            if seg_len2 == 0:
                t = 0.0
            else:
                t = ((position[0] - ax) * dx + (position[1] - ay) * dy) / seg_len2
                t = max(0.0, min(1.0, t))
            px, py = ax + t * dx, ay + t * dy
            d2 = (position[0] - px) ** 2 + (position[1] - py) ** 2
            if d2 < best_d2 - 1e-9:
                best_d2 = d2
                best = (px, py)
                best_seg = i
                best_along = self._cum[i] + t * math.sqrt(seg_len2)
        progress = best_along / self.length if self.length > 0 else 0.0
        nearest = (round(best[0]), round(best[1]))
        return Stray(
            distance=math.sqrt(best_d2),
            nearest=nearest,
            progress=progress,
            segment=best_seg,
        )


def _cumulative_lengths(points: list[Point]) -> list[float]:
    cum = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        cum.append(cum[-1] + math.dist(a, b))
    return cum


def thin(points: list[Point], tolerance: float = 3.0) -> list[Point]:
    """Douglas–Peucker: drop points within `tolerance` subtiles of the
    chord. Purely geometric (no walkability check — the recorded walk
    WAS walkable, which is the whole point of recording it)."""
    if len(points) <= 2:
        return list(points)
    ax, ay = points[0]
    bx, by = points[-1]
    worst_d = -1.0
    worst_i = 0
    for i in range(1, len(points) - 1):
        d = _point_to_chord(points[i], (ax, ay), (bx, by))
        if d > worst_d:
            worst_d = d
            worst_i = i
    if worst_d <= tolerance:
        return [points[0], points[-1]]
    left = thin(points[: worst_i + 1], tolerance)
    right = thin(points[worst_i:], tolerance)
    return left[:-1] + right


def _point_to_chord(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return math.dist(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg_len2
    t = max(0.0, min(1.0, t))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


# -- storage (the mapstore directory family) -----------------------------------


def line_path(
    seed: int, difficulty: int, area_id: int, root: Path | str = DEFAULT_ROOT
) -> Path:
    return Path(root) / f"{seed:08x}-d{difficulty}" / f"line-{area_id:03d}.json"


def save_line(line: RouteLine, root: Path | str = DEFAULT_ROOT) -> Path:
    path = line_path(line.seed, line.difficulty, line.area_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": FORMAT_VERSION,
        "seed": line.seed,
        "difficulty": line.difficulty,
        "area_id": line.area_id,
        "points": [list(p) for p in line.points],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return path


def line_service(session, difficulty: int, root: Path | str = DEFAULT_ROOT):
    """`route_line_for(area_id)` for RunServices (the route_to shape).

    Reads the map seed lazily (it is only knowable in a game) and caches
    loaded lines per (seed, area). A missing line is None — the leash
    simply does not exist for that area.
    """
    from pd2bot.perception.world import read_map_seed

    cache: dict[tuple[int, int], RouteLine | None] = {}

    def route_line_for(area_id: int) -> RouteLine | None:
        seed = read_map_seed(session)
        if seed is None:
            return None
        key = (seed, area_id)
        if key not in cache:
            cache[key] = load_line(seed, difficulty, area_id, root)
        return cache[key]

    return route_line_for


def load_line(
    seed: int, difficulty: int, area_id: int, root: Path | str = DEFAULT_ROOT
) -> RouteLine | None:
    """The stored line, or None — absent and unreadable both read as
    "no line" (the atlas's honest-blank precedent), but unreadable says
    so on stderr via ValueError suppression being NARROW: only missing
    files and structural mismatches return None."""
    path = line_path(seed, difficulty, area_id, root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    if payload.get("version") != FORMAT_VERSION or payload.get("seed") != seed:
        return None
    try:
        points = [(int(x), int(y)) for x, y in payload["points"]]
        return RouteLine(seed, difficulty, area_id, points)
    except (KeyError, TypeError, ValueError):
        return None
