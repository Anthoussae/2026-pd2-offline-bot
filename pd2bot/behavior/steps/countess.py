"""ClearCountessStep: the flagship kill - staging, engage, drop sweep.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.behavior.actions import (
    MoveTo,
)
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.steps.clear import ClearRadiusStep
from pd2bot.behavior.steps.pickup import _PickupMixin
from pd2bot.behavior.steps.services import RunServices
from pd2bot.behavior.steps.util import (
    _chebyshev,
    _next_route_waypoint,
    _route_leg,
)
from pd2bot.nav import mapframe
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception.snapshot import GameSnapshot


def _screen_north_point(
    anchor: tuple[int, int],
    distance: int,
    is_walkable: Callable[[tuple[int, int]], bool] | None = None,
) -> tuple[int, int]:
    """The most-northerly stageable ground within `distance` of `anchor`.

    Delegates to `mapframe.screen_north`, which owns the convention:
    screen-north is the world (-1,-1) diagonal, and the pure -x/-y axes
    are screen NW and NE. ONE definition in the codebase — the log's
    bearings and the endgame's staging must agree, and two copies of an
    isometric convention are two chances to get it backwards.

    Cellar 5's chamber is cut into solid rock, so strictly-north-outside
    ground may simply not exist; the search degrades to the NW/NE
    shoulders and then closer in, which is why the derived staging point
    sits on the chamber's own north-west band.
    """
    return mapframe.screen_north(anchor, distance, is_walkable)


@dataclass
class ClearCountessStep(_PickupMixin):
    """The Cellar 5 endgame: the user's tactics for the Countess, encoded.

    Four beats, in order (R212 Q4 exception, Q7):

    1. **Clear the neighborhood** — a bounded clearance around the
       arrival point so the encounter has no gaggle at our backs. A
       composed `ClearRadiusStep` (modest radius, no patrol): the same
       machinery, the same budgets, not a re-implementation.
    2. **Stage north** — route to a point screen-north of the chamber
       anchor, derived from the atlas at run time and recorded on the
       blackboard (`notes["countess"]`) for the drill and the gate to
       display. Best-effort: staging is a tactic, and a staging point
       the map refuses is logged and skipped, never a hang.
    3. **Advance slowly** — short legs through the module's own
       `approach` (its gates decide what "in a fight" means), held by
       the revive brake: no advancing while the wall is shorter than
       `approach_with_revives`, until the patience bound releases it
       loudly. The on-contact wait-for-revives beat is `engage`'s own.
    4. **Kill and prove it** — the fight itself belongs to `engage`
       (aggressive posture). The step owns the EVIDENCE: her pinned
       identity (kind 734 / unique_no 6, T68+R216) seen with a dead
       mode, or provably absent after the budgeted chamber sweep — one
       short in-and-out pass so a blind corner cannot hide her, run in
       BOTH outcomes (after a seen kill it doubles as drop
       reconnaissance, priming the sightings memo the sweep-after
       relies on). Alive and unreachable is a loud stop-and-report,
       never a silent give-up: this step IS the run's objective.

    On confirmation the chamber region goes on the blackboard as the
    `cleared` circle (`pickup` adopts it unchanged — one region format,
    the M5 handoff), centred on her corpse when one was seen.
    """

    services: RunServices = None  # type: ignore[assignment]
    chamber: tuple[int, int] = (0, 0)
    neighborhood_radius: int = 30
    chamber_radius: int = 25
    posture: str | None = None
    name: str = "clear_countess"
    _phase: str = "clear"
    _posture_applied: bool = False
    _neighborhood: ClearRadiusStep | None = None
    _anchor: tuple[int, int] | None = None
    _anchor_live: bool = False
    _seen_alive: bool = False
    _corpse_at: tuple[int, int] | None = None
    _staging: tuple[int, int] | None = None
    _closest: int | None = None
    _attempts: int = 0
    _walk_fails: int = 0
    _revive_waited: int = 0
    _revives_seen: int = 0
    _brake_logged: bool = False
    _sweep_points: list[tuple[int, int]] | None = None
    _sweep_deadline: float | None = None
    _sweep_narrated: bool = False
    _sweep_skipped: int = 0

    def __post_init__(self) -> None:
        self._anchor = self.chamber
        # The neighborhood clearance, composed. No patrol: the arrival
        # pocket is small and the chamber must not be wandered into as a
        # "ring point". No posture: this step already set the run's.
        self._neighborhood = ClearRadiusStep(
            self.services,
            radius=self.neighborhood_radius,
            centre_note="arrival",
            patrol=False,
        )

    # -- identity ------------------------------------------------------------

    @staticmethod
    def _is_countess(unit) -> bool:
        """The pinned identity (T68 + R216). kind is the monstats row —
        hers alone — and unique_no confirms when readable; a corpse read
        that lost the boss flag (unique_no None) must not un-kill her."""
        return unit.kind == offsets.COUNTESS_KIND and (
            unit.unique_no is None
            or unit.unique_no == offsets.COUNTESS_UNIQUE_NO
        )

    def _scan(self, snap: GameSnapshot) -> object | None:
        """One look for her, live or dead. Returns the live unit if any.

        The live position REPLACES the run file's anchor whenever she is
        in perception — the memory-first, live-read-as-authority rule
        the traverse step already follows for exits.
        """
        for unit in snap.corpses:
            if self._is_countess(unit):
                if self._corpse_at is None:
                    self._corpse_at = unit.position
                    self.services.narrate(
                        f"countess: DOWN — her corpse reads at {unit.position}"
                    )
                return None
        alive = None
        for unit in snap.monsters:
            if not self._is_countess(unit):
                continue
            if unit.is_corpse:
                if self._corpse_at is None:
                    self._corpse_at = unit.position
                    self.services.narrate(
                        f"countess: DOWN — her corpse reads at {unit.position}"
                    )
                return None
            alive = unit
            break
        if alive is not None:
            self._seen_alive = True
            if not self._anchor_live:
                self._anchor_live = True
                self.services.log(
                    f"countess: sighted live at {alive.position} — the "
                    f"anchor {self._anchor} yields to the read"
                )
            self._anchor = alive.position
        return alive

    def _loud_stop(self, why: str) -> None:
        """The run's objective cannot be met and silence is forbidden."""
        self.services.alert(f"COUNTESS UNRESOLVED: {why}")
        raise NavigationError(f"clear_countess: {why}")

    def _confirmed(self, ctx: EngineContext) -> StepOutcome:
        centre = self._corpse_at or self._anchor or self.chamber
        # The M5 region handoff: `pickup` adopts this circle verbatim.
        ctx.notes["cleared"] = {
            "centre": centre,
            "radius": self.chamber_radius,
            "patrol": True,
        }
        if self._corpse_at is not None:
            note = f"the countess is down; drop zone {centre} r{self.chamber_radius}"
        else:
            note = (
                "the countess is provably absent (chamber swept clean); "
                f"drop zone {centre} r{self.chamber_radius}"
            )
        self.services.narrate(f"countess: {note}")
        return StepOutcome(done=True, acted=True, note=note)

    # -- movement bookkeeping ------------------------------------------------

    def _progressing(self, distance: int) -> bool:
        """The patrol's margin rule (R189 b), for whichever walk owns the
        phase. Reset via `_retarget` on every phase or target change."""
        if (
            self._closest is None
            or distance <= self._closest - self.services.patrol_progress_margin
        ):
            self._closest = distance
            self._attempts = 0
            return True
        self._attempts += 1
        return self._attempts < self.services.patrol_attempts

    def _retarget(self) -> None:
        self._closest = None
        self._attempts = 0
        self._walk_fails = 0

    def _leg_toward(
        self, ctx: EngineContext, origin: tuple[int, int], target: tuple[int, int]
    ) -> bool:
        """One capped leg via the map. False = this target is not happening
        (no route twice would be cleaner, but the two-strike rule guards
        WRITE-OFFS of many candidates; here every no-route already falls
        through to the next phase, which re-decides from fresh reads)."""
        leg = _route_leg(self.services, origin, target)
        if leg is None:
            return False
        if not self.send(ctx, MoveTo(leg)):
            self._walk_fails += 1
            return self._walk_fails < 2
        return True

    # -- the tick ------------------------------------------------------------

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.posture is not None and not self._posture_applied:
            set_posture = getattr(self.services.combat, "set_posture", None)
            if set_posture is not None:
                set_posture(self.posture)
                self.services.narrate(f"combat posture: {self.posture}")
            self._posture_applied = True
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        if snap.player is None or snap.area is None:
            return StepOutcome(done=False, waiting=True)
        origin = snap.player.position

        self.confirm_pickups(snap)
        alive = self._scan(snap)
        # Everything the chamber region drops feeds the sightings memo,
        # so the pickup step's ring walk starts with evidence in hand.
        if self._anchor is not None:
            self.note_wanted_sightings(snap, self._anchor, self.chamber_radius)

        # 1 — the neighborhood clearance owns the tick until it is done.
        # It fights, collects and cleanses through its own machinery;
        # running this step's engage beside it would decide twice.
        if self._phase == "clear":
            outcome = self._neighborhood.step(snap, ctx)
            if not outcome.done:
                return outcome
            self._phase = "stage"
            self._retarget()
            self.services.narrate(
                f"countess: neighborhood clear ({outcome.note}) — staging north"
            )
            return StepOutcome(done=False, acted=True, note="neighborhood clear")

        # Her corpse settles the question in any later phase: sweep for
        # the sanity pass (and the drop reconnaissance), then confirm.
        if self._corpse_at is not None and self._phase != "sweep":
            self._enter_sweep()

        # The fight owns any tick it claims — aggressive posture: she and
        # her court are exactly what this step came to fight.
        action = self.services.combat.engage(snap, ctx)
        if action is not None:
            if not self.send(ctx, action):
                blamed = getattr(action, "toward", None)
                if alive is not None and blamed == alive.unit_id:
                    self._walk_fails += 1
                    if self._walk_fails >= 2:
                        self._loud_stop(
                            f"she is alive at {alive.position} and the walk "
                            "to her keeps failing — alive and unreachable"
                        )
            return StepOutcome(done=False, acted=True)

        if self._phase == "stage":
            return self._stage_tick(snap, ctx, origin)
        if self._phase == "advance":
            return self._advance_tick(snap, ctx, origin, alive)
        return self._sweep_tick(snap, ctx, origin, alive)

    # -- 2: staging ----------------------------------------------------------

    def _stage_tick(
        self, snap: GameSnapshot, ctx: EngineContext, origin: tuple[int, int]
    ) -> StepOutcome:
        if self._staging is None:
            self._staging = _screen_north_point(
                self._anchor or self.chamber,
                self.services.staging_distance,
                getattr(self.services.combat, "is_walkable", None),
            )
            # The blackboard record the drill displays and the gate reviews.
            ctx.notes["countess"] = {
                "anchor": self._anchor,
                "staging": self._staging,
                "radius": self.chamber_radius,
            }
            self.services.narrate(
                f"countess: staging north of the chamber at {self._staging} "
                f"(anchor {self._anchor})"
            )
        distance = _chebyshev(origin, self._staging)
        if distance <= self.services.patrol_reach:
            self._to_advance("staged")
            return StepOutcome(done=False, acted=True, note="staged north")
        if not self._progressing(distance) or not self._leg_toward(
            ctx, origin, self._staging
        ):
            # Best-effort by design: the staging point is a tactic, not
            # the objective, and a map that refuses it must not hang the
            # run that came to kill her.
            self.services.log(
                f"countess: staging at {self._staging} not reachable "
                f"(closest {self._closest}); advancing from here"
            )
            self._to_advance("staging written off")
        return StepOutcome(done=False, acted=True, note="staging north")

    def _to_advance(self, why: str) -> None:
        self._phase = "advance"
        self._retarget()
        self.services.narrate(f"countess: advancing on the chamber ({why})")

    # -- 3: the advance ------------------------------------------------------

    def _advance_tick(
        self, snap: GameSnapshot, ctx: EngineContext, origin: tuple[int, int], alive
    ) -> StepOutcome:
        # The revive brake (the user's tactic): no advancing while the
        # wall is short. Released by the wall reaching the module's own
        # `approach_with_revives`, by the wall GROWING resetting the
        # patience, or by the patience bound — loudly, because a cellar
        # with nothing dead nearby can never raise a wall at all.
        needed = getattr(
            getattr(self.services.combat, "config", None),
            "approach_with_revives",
            0,
        )
        standing = len(snap.revives)
        if standing > self._revives_seen:
            self._revive_waited = 0
        self._revives_seen = standing
        if standing < needed:
            self._revive_waited += 1
            if self._revive_waited <= self.services.advance_revive_patience:
                if not self._brake_logged:
                    self._brake_logged = True
                    self.services.log(
                        f"countess: holding the advance for the revive wall "
                        f"({standing}/{needed} up)"
                    )
                return StepOutcome(done=False, waiting=True, note="revive brake")
            if self._brake_logged:
                self._brake_logged = False
                self.services.log(
                    f"countess: the wall never grew past {standing}/{needed} "
                    f"— advancing without it"
                )

        target = self._anchor or self.chamber
        distance = _chebyshev(origin, target)
        if distance <= self.services.patrol_reach:
            if alive is None:
                self._enter_sweep()
                return StepOutcome(done=False, acted=True, note="at the chamber")
            # At her anchor with her alive in sight: `engage`'s fight now;
            # its deliberate pauses (restrike, revives) are not stalls.
            return StepOutcome(done=False, waiting=True)

        via = None
        if self.services.route_to is not None:
            route = self.services.route_to(target)
            if route is not None:
                via = _next_route_waypoint(route, origin)
        closing = self.services.combat.approach(snap, target, via=via)
        if closing is not None:
            if not self.send(ctx, closing):
                self._walk_fails += 1
                if self._walk_fails >= 2:
                    if alive is not None:
                        self._loud_stop(
                            f"she is alive at {alive.position} and every "
                            "approach fails — alive and unreachable"
                        )
                    self.services.log(
                        "countess: the anchor is not approachable — sweeping"
                    )
                    self._enter_sweep()
                return StepOutcome(done=False, acted=True)
            if not self._progressing(distance):
                if alive is not None:
                    self._loud_stop(
                        f"she is alive at {alive.position} and "
                        f"{self._attempts} advance legs got no closer than "
                        f"{self._closest} — alive and unreachable"
                    )
                self.services.log(
                    f"countess: the advance stalled {self._attempts} legs "
                    f"short of the anchor — sweeping from here"
                )
                self._enter_sweep()
            return StepOutcome(done=False, acted=True, note="advancing")
        # approach refused. With her alive in sight that is a deliberate
        # combat beat (wait-for-revives on contact, a restrike window) —
        # engage's next look. With NO live countess it means the module
        # considers the anchor in reach and has nothing to fight there:
        # the chamber is as approached as it gets, and waiting on an
        # empty anchor was this step's own hang (found by the blinded
        # sim scenario, exactly the sweep's case).
        if alive is None:
            self._enter_sweep()
            return StepOutcome(done=False, acted=True, note="at the chamber")
        return StepOutcome(done=False, waiting=True)

    # -- 4: the chamber sweep ------------------------------------------------

    def _enter_sweep(self) -> None:
        if self._phase != "sweep":
            self._phase = "sweep"
            self._retarget()
        if self._sweep_deadline is None:
            # One budget across every entry: a countess blinking in and
            # out of perception must not stretch it.
            self._sweep_deadline = self.services.clock() + self.services.sweep_budget_s
        if self._sweep_points is None:
            anchor = self._anchor or self.chamber
            r = self.chamber_radius
            walkable = getattr(self.services.combat, "is_walkable", None)
            south = (anchor[0] + r, anchor[1] + r)
            if walkable is not None:
                for d in range(r, 7, -4):
                    candidate = (anchor[0] + d, anchor[1] + d)
                    try:
                        if walkable(candidate):
                            south = candidate
                            break
                    except Exception:  # noqa: BLE001 - torn read
                        continue
            # In-and-out: the heart of the chamber, its far (south) side,
            # and back to the heart — a pass, not a patrol.
            self._sweep_points = [anchor, south, anchor]
        if not self._sweep_narrated:
            self._sweep_narrated = True
            self.services.narrate(
                f"countess: sweeping the chamber ({self.services.sweep_budget_s:.0f}s "
                f"budget) — {self._sweep_points}"
            )

    def _sweep_tick(
        self, snap: GameSnapshot, ctx: EngineContext, origin: tuple[int, int], alive
    ) -> StepOutcome:
        self._enter_sweep()  # idempotent: fills points/deadline if entered abruptly
        if alive is not None and self._corpse_at is None:
            # The sweep fed the scan and the scan answered: she lives.
            # Back to the approach — the budget clock keeps running.
            self._to_advance("she is in sight")
            return StepOutcome(done=False, acted=True, note="sighted her")
        if self.services.clock() > self._sweep_deadline:
            if self._corpse_at is not None:
                return self._confirmed(ctx)
            self._loud_stop(
                f"the {self.services.sweep_budget_s:.0f}s chamber sweep "
                "budget is spent with the kill unproven — she is neither "
                "dead on the ground nor provably absent"
            )
        while self._sweep_points:
            point = self._sweep_points[0]
            distance = _chebyshev(origin, point)
            if distance <= self.services.patrol_reach:
                self._sweep_points.pop(0)
                self._retarget()
                continue
            if not self._progressing(distance) or not self._leg_toward(
                ctx, origin, point
            ):
                self.services.log(
                    f"countess: sweep point {point} not reachable — skipped"
                )
                self._sweep_points.pop(0)
                self._sweep_skipped += 1
                self._retarget()
                continue
            return StepOutcome(done=False, acted=True, note=f"sweeping via {point}")
        # The pass is complete. A corpse settles it regardless — the sweep
        # was only drop reconnaissance then. But ABSENCE is only proven by
        # ground actually walked: a pass whose points were skipped as
        # unreachable saw nothing, and calling that "provably absent"
        # would hand the flagship drill a PASS on a partial run — the
        # review-001 shape, one layer down.
        if self._corpse_at is None and self._sweep_skipped:
            self._loud_stop(
                f"the chamber sweep skipped {self._sweep_skipped} of its "
                "points as unreachable — she was never seen and absence "
                "is unproven"
            )
        return self._confirmed(ctx)

