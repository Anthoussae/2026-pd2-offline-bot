"""_PatrolMixin: patrol legs between clearance anchors.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pd2bot.behavior.actions import (
    MoveTo,
)
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.steps.util import (
    _SEAM_INSET,
    _chebyshev,
    _note_unsurveyed,
    _route_leg,
)
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception.snapshot import GameSnapshot


@dataclass
class _PatrolMixin:
    """Walking a ring, so that a standstill reading means something.

    Shared by the clearance and the sweep because they have the identical
    problem and it would be the identical code twice. That is not a style
    preference here: `_PickupMixin` exists for the same reason and its
    docstring records what the alternative cost — two steps doing the same
    thing and differing in how robust they are is the shape that cost P3
    three live runs, where the heal retried a missed click and the repair
    did not.

    **The premise, measured.** A step that decides something about a circle
    of `radius` from a standstill is only sound while perception reaches
    that far, and T51 (2026-08-01) measured what it actually reaches: 12
    potions dropped along a walk, seven of them watched vanishing, at
    **46, 46, 54, 55, 61, 63 and 67 subtiles**. Every one far inside the
    `PERCEPTION_RADIUS` of 80 we had been quoting, and five of the seven
    lost at the same distance whether the radius filter was applied or
    lifted entirely — so the bound is the CLIENT's loaded-room horizon, not
    a constant we can raise. The spread rather than a crisp circle is what
    room-quantised loading predicts.

    Worst case ~46 subtiles. Anything above that has to be walked.
    """

    _points: list[tuple[int, int]] | None = None
    _visited: set[int] = field(default_factory=set)
    _index: int = 0
    _attempts: int = 0  # legs since we last got closer to the current point
    _closest: int | None = None
    # No-route strikes per target (T55 run 1): a torn live-collision read
    # walled the origin in for ~a second and FIVE reachable ring points
    # were written off on single "no route" answers. One answer is a
    # reading; two consecutive answers over fresh grids is a fact — the
    # same distinction the warp's position-verify draws. Genuine
    # no-routes still die in two ticks with zero legs spent.
    _route_denied: dict[tuple[int, int], int] = field(default_factory=dict)

    def patrol_points(
        self, centre: tuple[int, int], area=None
    ) -> list[tuple[int, int]]:
        """The ring, computed once from the centre and the radius.

        Sized as a fraction of `radius` so that changing the radius — the
        one number the user tunes — moves the whole pattern with it. At
        radius 96 the ring sits at ~63: adjacent points are ~49 apart and
        the furthest edge of the circle is ~33 from the nearest point,
        which is inside even T51's worst-case 46.

        Points outside the AREA's own bounds (with a small seam inset)
        are dropped at birth (R189 c): "clear Cold Plains" must never
        chase ground that belongs to Blood Moor — the seam is where T55
        run 2 livelocked, with each border crossing flipping which
        area's grid planned the next walk.
        """
        if self._points is None:
            if area is None:
                # A mid-transition read (review 003, potions-live-
                # validation): without the area's bounds the seam filter
                # cannot run, and CACHING an unfiltered ring would re-open
                # the T55 run 2 border surface for the whole step. Plan
                # nothing this tick; the next tick with the area readable
                # computes and caches the filtered ring.
                return []
            ring = max(1, round(self.radius * self.services.patrol_ring))
            count = max(1, self.services.patrol_points)
            points = [
                (
                    centre[0] + round(ring * math.cos(2 * math.pi * i / count)),
                    centre[1] + round(ring * math.sin(2 * math.pi * i / count)),
                )
                for i in range(count)
            ]
            inset = _SEAM_INSET
            left, top, right, bottom = area.bounds_subtiles
            kept = [
                (x, y)
                for x, y in points
                if left + inset <= x < right - inset
                and top + inset <= y < bottom - inset
            ]
            if len(kept) < len(points):
                self.services.log(
                    f"patrol: dropped {len(points) - len(kept)} ring "
                    "point(s) outside the area's bounds"
                )
            self._points = kept
        return self._points

    @property
    def patrol_complete(self) -> bool:
        if not self.patrol:
            return True
        if self._points is None:
            return False  # not even planned yet, let alone walked
        return len(self._visited) >= len(self._points)

    def _advance(self) -> None:
        """Done with the current point, for whatever reason. Next."""
        self._visited.add(self._index)
        self._attempts = 0
        self._closest = None
        points = self._points or []
        for _ in range(len(points)):
            self._index = (self._index + 1) % max(1, len(points))
            if self._index not in self._visited:
                return

    def walk_the_circle(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        """One leg of the patrol. Only called with nothing else to do.

        Every exit from here reports `acted`, because every one of them
        either sent a walk or made a decision that moved the patrol on —
        which is what keeps both watchdogs fed without either of them
        needing to know a patrol exists.
        """
        points = self.patrol_points(self._centre, snap.area)  # type: ignore[arg-type]
        if not points:
            return StepOutcome(
                done=False, acted=True,
                note="patrol ring empty (every point outside the area)",
            )
        target = points[self._index]
        here = snap.player.position  # type: ignore[union-attr]

        distance = _chebyshev(here, target)
        if distance <= self.services.patrol_reach:
            self.services.log(f"patrol: reached {target}")
            self._advance()
            return StepOutcome(done=False, acted=True, note=f"patrol reached {target}")

        # Progress, not effort — and progress must beat the best by a
        # MARGIN (R189 b): T55 run 2's ping-pong landed a subtile closer
        # now and then, and that hair kept this budget resetting forever.
        if (
            self._closest is None
            or distance <= self._closest - self.services.patrol_progress_margin
        ):
            self._closest = distance
            self._attempts = 0
        else:
            self._attempts += 1

        if self._attempts >= self.services.patrol_attempts:
            # Walkable in principle, unreachable in practice. Visited
            # means "dealt with", not "stood on" — otherwise one awkward
            # corner holds the whole step open.
            self.services.log(
                f"patrol: giving up on {target} after {self._attempts} legs "
                f"that got no closer (still {distance} away)"
            )
            self._advance()
            return StepOutcome(done=False, acted=True, note=f"patrol gave up on {target}")

        leg = _route_leg(self.services, here, target)
        if leg is None:
            # The map says no route exists (R181) — believed only when a
            # SECOND ask over a fresh grid agrees (T55 run 1: a torn
            # grid read produced five spurious no-routes in one second).
            strikes = self._route_denied.get(target, 0) + 1
            self._route_denied[target] = strikes
            if strikes < 2:
                return StepOutcome(
                    done=False, acted=True,
                    note=f"no route to {target} — asking again",
                )
            self.services.log(f"patrol: no route to {target} — written off")
            self.services.narrate(f"patrol: no route to ring point {target}")
            self._advance()
            return StepOutcome(
                done=False, acted=True, note=f"patrol wrote off {target} (no route)"
            )
        self._route_denied.pop(target, None)
        try:
            ctx.executor.execute(MoveTo(leg))
        except NavigationError as exc:
            # Unknown ground is impassable BY DESIGN (navigate.py: "that
            # ground has never been seen — survey it first"), and a ring
            # several screens out will often name ground nobody has read.
            # Left uncaught this fails the whole cycle. Deliberately NOT
            # `except Exception`: InputRefused and SkillSwitchFailed must
            # keep reaching the engine, which absorbs them and re-decides
            # — swallowing those would mark a point visited that we never
            # actually tried to walk to.
            self.services.log(f"patrol: skipping {target} ({exc})")
            self.services.narrate(f"patrol: gave up ring point {target}")
            _note_unsurveyed(self.services, exc)
            self._advance()
            return StepOutcome(done=False, acted=True, note=f"patrol skipped {target}")
        return StepOutcome(done=False, acted=True, note=f"patrol leg to {leg}")



