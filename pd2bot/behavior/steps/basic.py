"""The bookend steps: town preamble, waypoint travel, done.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.behavior.actions import (
    MoveTo,
)
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.steps.services import RunServices
from pd2bot.behavior.steps.util import (
    _chebyshev,
)
from pd2bot.perception.snapshot import GameSnapshot


@dataclass
class TownPreambleStep:
    """Run P3's verified preamble: heal, repair, the R75 inventory loop, merc."""

    services: RunServices
    name: str = "town_preamble"

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        report = self.services.run_preamble()
        note = "; ".join(getattr(report, "log", []) or []) or "preamble complete"
        return StepOutcome(done=True, acted=True, note=note)


@dataclass
class WaypointStep:
    """Take the waypoint to `dest`, then record where we landed.

    The arrival position goes on the shared blackboard under "arrival",
    which is how `clear_radius` learns where its centre is without either
    step knowing the other exists.
    """

    services: RunServices
    dest: int
    name: str = "waypoint"
    # The post-arrival settle. Small numbers on purpose: this runs once
    # per area change, and its whole job is to outlast a load stutter.
    settle_timeout_s: float = 8.0
    settle_poll_s: float = 0.2
    stable_reads: int = 3

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        self.services.travel_to(self.dest)
        settled = self.settle(ctx)
        # Read the position AFTER travelling: the snapshot handed to this
        # tick was taken in town, before the trip.
        arrival = None
        fresh = None
        if ctx.snapshot is not None:
            fresh = ctx.snapshot()
            arrival = fresh.player.position if fresh.player is not None else None
        if arrival is None and snap.player is not None:
            arrival = snap.player.position
        if arrival is not None:
            ctx.notes["arrival"] = arrival
        stepped = self.step_off(arrival, fresh if fresh is not None else snap, ctx)
        return StepOutcome(
            done=True, acted=True,
            note=f"arrived at {arrival}"
            + ("" if settled else " (never settled)")
            + (f", stepped off to {stepped}" if stepped else ""),
        )

    def step_off(
        self,
        arrival: tuple[int, int] | None,
        snap: GameSnapshot,
        ctx: EngineContext,
    ) -> tuple[int, int] | None:
        """Walk a few subtiles off the waypoint we just arrived on.

        The user's request, from watching the tenth stage-B attempt lock
        itself out: *when travelling through a waypoint it will be right
        under the mouse pointer*, so the arrival point is the one square of
        ground where an ordinary click is likeliest to open a menu instead
        of doing what it meant. Standing there while the combat module
        starts placing casts is asking for it.

        Conditioned on a clickable object ACTUALLY being within stepping
        distance rather than done unconditionally after every trip. That is
        the user's reasoning stated precisely — the hazard is the thing
        under the cursor, not the travelling — and it means a run that
        arrives somewhere harmless pays nothing and behaves exactly as
        before.

        The arrival note is recorded BEFORE this runs, so `clear_radius`
        still centres on the waypoint — the run's landmark does not move
        just because the character does.

        Best effort, and deliberately so: a failed walk here is a nicety
        not delivered, and turning it into a raise would let a cosmetic
        step end a run that was otherwise fine. The panel clear runs first
        for the case where the trip itself left something open.
        """
        if self.services.clear_panels is not None:
            try:
                self.services.clear_panels()
            except Exception as exc:  # noqa: BLE001 - never fatal here
                self.services.log(f"waypoint: could not clear panels ({exc})")
        if arrival is None:
            return None
        offset = self.services.waypoint_step_off
        underfoot = [
            o.position
            for o in snap.objects
            if o.kind in offsets.INTERACTIVE_OBJECT_KINDS
            and _chebyshev(o.position, arrival) <= offset
        ]
        if not underfoot:
            return None
        candidates = [
            (arrival[0] + dx * offset, arrival[1] + dy * offset)
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (0, 1))
        ]
        # Furthest from what we are standing on, first: the direction is the
        # whole point, and a step that ended up beside the waypoint instead
        # of on it would have solved nothing.
        candidates.sort(
            key=lambda t: min(_chebyshev(t, o) for o in underfoot), reverse=True
        )
        for target in candidates:
            try:
                ctx.executor.execute(MoveTo(target))
            except Exception as exc:  # noqa: BLE001 - try the next direction
                self.services.log(f"waypoint: step off to {target} failed ({exc})")
                continue
            return target
        return None

    def settle(self, ctx: EngineContext) -> bool:
        """Wait for the new area to finish arriving before anything is sent.

        `travel_to` returns when the area ID changes, which is the START of
        the new area loading, not the end. The user watched run 5 stutter
        right there — "common when changing areas" — and the bot's next act
        was a hotkey press that the loading client simply dropped. Three
        presses inside 1.8 s all landed in that window, the switch never
        verified, and the run died on an unverified skill.

        So: poll until the world reads back consistently — a player, in one
        area, unchanged across `stable_reads` consecutive looks. Cheap
        insurance measured in a second or two, once per area change, in the
        one place where the client is guaranteed to be busy.

        Returns whether it settled; a timeout is reported, not raised. The
        engine is a loop and the ladder is about to get its look either way,
        which is a better answer than refusing to continue.
        """
        if ctx.snapshot is None:
            return False
        deadline = self.services.clock() + self.settle_timeout_s
        # Bounded by COUNT as well as by time: an injected clock that
        # does not advance (a sim, a test) would never reach a deadline,
        # and a wait that can hang forever is worse than one that gives
        # up early — the caller treats a timeout as reportable, not fatal.
        budget = int(self.settle_timeout_s / max(self.settle_poll_s, 1e-6)) + 1
        stable = 0
        last: tuple[int, object] | None = None
        while self.services.clock() < deadline and budget > 0:
            budget -= 1
            snap = ctx.snapshot()
            here = (
                (snap.area.level_no, snap.player.position)
                if snap.area is not None and snap.player is not None
                else None
            )
            if here is not None and here == last:
                stable += 1
                if stable >= self.stable_reads:
                    return True
            else:
                stable = 0
            last = here
            self.services.sleep(self.settle_poll_s)
        return False


@dataclass
class DoneStep:
    """The run is over. The cycle leaves the game; nothing to do here."""

    services: RunServices
    name: str = "done"

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        return StepOutcome(done=True, note="run complete")


# -- ticked steps ---------------------------------------------------------------



