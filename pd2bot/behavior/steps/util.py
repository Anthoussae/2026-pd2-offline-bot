"""Step helpers: hop geometry, route legs, default alert/log plumbing.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pd2bot.behavior.steps.services import RunServices

def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _hop(
    origin: tuple[int, int], destination: tuple[int, int], step: int
) -> tuple[int, int]:
    """One short leg toward `destination`, capped at `step` subtiles.

    `walk_to` BLOCKS until arrival (navigate.py), so a leg is time the
    reflex ladder is not being consulted — the same discipline, and the
    same reason, as `NecroCombat._dash_target`. A patrol built out of one
    `walk_to` per point would cross a Hell field with survival switched
    off for the whole crossing.
    """
    dx, dy = destination[0] - origin[0], destination[1] - origin[1]
    span = max(abs(dx), abs(dy))
    if span <= step:
        return destination
    scale = step / span
    return (round(origin[0] + dx * scale), round(origin[1] + dy * scale))


# How close counts as "at" a route waypoint. The navigator's own
# ARRIVAL_RADIUS, restated here because the steps follow routes without
# owning the walking.
_ROUTE_WAYPOINT_REACH = 3

# How far inside its own area's bounds a patrol ring point must sit
# (R189 c): a point ON the seam has the T55 run 2 problem — reaching it
# crosses the border, and the crossing flips which area's grid plans
# the next walk.
_SEAM_INSET = 4


def _next_route_waypoint(
    route: list[tuple[int, int]], origin: tuple[int, int]
) -> tuple[int, int] | None:
    """The first waypoint of `route` not already underfoot, or None when
    the whole route is within reach (i.e. we are effectively there)."""
    for waypoint in route:
        if _chebyshev(waypoint, origin) > _ROUTE_WAYPOINT_REACH:
            return waypoint
    return None


def _route_leg(
    services: RunServices,
    origin: tuple[int, int],
    target: tuple[int, int],
) -> tuple[int, int] | None:
    """The next short leg toward `target`, following the MAP's answer.

    R181, watched live twice: the atlas answered every navigator question
    and no step ever asked it. Legs were straight-line bearings, so a
    far-corner target had each hop plan locally, clamp at the fence, and
    burn the no-progress budget while the bot visibly shuffled at dead
    edges — and a bearing hop happily leads through a zone exit the
    target is not behind (T53 run 2 wandered into Stony Field that way).

    With a route service wired, the leg aims at the route's next waypoint
    — a route planned on the area's grid never crosses an exit — capped
    at `patrol_step`, because the reflex ladder must get its look between
    legs (the whole reason hops exist). None means the map says NO ROUTE
    EXISTS, and the caller writes the target off on the spot: the honest
    fast-fail the R174 closure wrongly claimed already happened. Without
    a service (open-ground sims, drills), the bearing hop stands.
    """
    if services.route_to is None:
        return _hop(origin, target, services.patrol_step)
    route = services.route_to(target)
    if route is None:
        return None
    waypoint = _next_route_waypoint(route, origin)
    if waypoint is None:
        return _hop(origin, target, services.patrol_step)
    return _hop(origin, waypoint, services.patrol_step)


def _point_away(
    origin: tuple[int, int], repel: tuple[int, int], distance: int
) -> tuple[int, int]:
    """A point `distance` from `repel`, on the far side of `origin`.

    The cleanse hygiene's direction chooser: walk directly away from the
    thing the junk must not land near. Standing exactly ON the repel point
    has no away direction, so any fixed one serves — the distance is what
    matters, not the bearing.
    """
    dx, dy = origin[0] - repel[0], origin[1] - repel[1]
    span = max(abs(dx), abs(dy))
    if span == 0:
        dx, dy, span = 1, 1, 1
    scale = distance / span
    return (round(repel[0] + dx * scale), round(repel[1] + dy * scale))


def _default_alert(reason: str) -> None:  # pragma: no cover - exercised live
    print(f"\n!!  {reason}\n", flush=True)


def _default_log(line: str) -> None:  # pragma: no cover - exercised live
    print(f"  {line}", flush=True)


def _note_unsurveyed(services: RunServices, exc: Exception) -> None:
    """R176 Q2: a give-up caused by UNKNOWN ground gets said loudly, once.

    The navigator's error message already distinguishes "solidly blocked"
    from "never been seen"; only the second has a permanent fix the user
    can order (a survey run), so only the second earns an alert. No
    auto-survey here by decision: a clearance that detours into a survey
    stops being a clearance.
    """
    if services.unsurveyed_alerted or "never been seen" not in str(exc):
        return
    services.unsurveyed_alerted = True
    services.alert(
        "a target sits on UNSURVEYED ground — this run walks around the "
        "gap, but a survey run (runs/survey-*.toml) would map it once and "
        "fix this permanently."
    )



