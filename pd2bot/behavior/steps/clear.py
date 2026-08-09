"""Clearance steps: ClearRadiusStep and PickupStep.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.steps.patrol import _PatrolMixin
from pd2bot.behavior.steps.pickup import _PickupMixin
from pd2bot.behavior.steps.util import (
    _chebyshev,
    _next_route_waypoint,
)
from pd2bot.perception.snapshot import GameSnapshot


@dataclass
class ClearRadiusStep(_PatrolMixin, _PickupMixin):
    """Kill everything within `radius` of the centre, then settle.

    Termination is deliberately not "no monsters right now": a pack can be
    mid-spawn, a poisoned monster is still alive for a few seconds, and a
    revive can drag something into range. So the step requires the radius to
    read EMPTY continuously for `clear_settle_s` before it calls the job
    done — the same "wait for it to stay true" discipline the town layer's
    verifications use.

    **With `patrol` on, it walks the circle before believing it.** The
    standstill version is only sound while the radius fits inside
    perception, and T51 measured perception at **46-67 subtiles** — not
    the 80 the constant claims. Past that, "no monster within `radius`"
    means "no monster within ~50", and the rest of the circle is being
    declared clear unobserved. `runs/cold-plains.toml` has asked for 150
    since it was written. Both 2026-08-01 runs also completed without
    ever fighting, because nothing happened to be inside stage B's 50 —
    a trial run that can pass without doing the thing it tests.

    The patrol is deliberately unclever (user: *we don't need this to
    become enormously onerous*): a fixed ring of sample points, a visited
    set, one short leg per tick. Fighting always wins the tick; the
    patrol is only what happens when there is nothing to clear.
    """

    radius: int = 150
    centre_note: str = "arrival"
    patrol: bool = False
    # The combat posture this step fights in (M6 P3, R212 Q5). None =
    # leave the module as it is (pre-M6 runs change nothing). Validated
    # against the loaded posture names at registry-build time, so an
    # unknown name never reaches a game.
    posture: str | None = None
    name: str = "clear_radius"
    _empty_since: float | None = None
    _posture_applied: bool = False
    _centre: tuple[int, int] | None = None
    # Monsters inside the radius that we have given up reaching, and where
    # each was standing when we did. The position is what allows the
    # write-off to expire (see `_reachable`); a bare set could not.
    _unreachable: dict[int, tuple[int, int]] = field(default_factory=dict)
    # Per monster: the closest we have got, and how many closing ticks have
    # achieved nothing since. Same shape as the patrol's own two fields.
    _closest_to: dict[int, int] = field(default_factory=dict)
    _no_progress: dict[int, int] = field(default_factory=dict)
    # No-route strikes per monster (T55 run 1's torn grid read): one
    # answer is a reading, two consecutive answers is a fact.
    _no_route: dict[int, int] = field(default_factory=dict)

    # -- monsters we cannot get to -------------------------------------------

    def _reachable(self, monster) -> bool:
        """Does this monster still count toward the clearance?

        False once it has been written off — and the write-off EXPIRES the
        moment the monster leaves the spot it was written off at, because
        the only evidence behind it was "we could not get there from here"
        and it is no longer where "there" was.
        """
        where = self._unreachable.get(monster.unit_id)
        if where is None:
            return True
        if _chebyshev(monster.position, where) <= self.services.unreachable_forget:
            return False
        self._unreachable.pop(monster.unit_id, None)
        self._closest_to.pop(monster.unit_id, None)
        self._no_progress.pop(monster.unit_id, None)
        self.services.log(
            f"clearance: monster {monster.unit_id} moved from {where} to "
            f"{monster.position}, so it gets another try"
        )
        return True

    def _write_off(self, unit_id: int, position: tuple[int, int], why: str) -> None:
        if unit_id in self._unreachable:
            return
        self._unreachable[unit_id] = position
        self.services.log(
            f"clearance: writing off monster {unit_id} at {position} — {why}. "
            "It stops counting toward the radius unless it moves."
        )
        self.services.narrate(
            f"clearance: wrote off monster {unit_id} at {position} ({why})"
        )

    def _closing_progress(self, monster, origin: tuple[int, int]) -> None:
        """Book one closing tick against `monster`, and write it off at budget.

        Only called on the ticks where the STEP decided to close on it, never
        during a fight `engage` is running: the module's deliberate pauses —
        a restrike cooldown, holding off for the revives — are not failures
        to reach anything, and counting them here would write off the monster
        we are in the middle of killing.
        """
        unit_id = monster.unit_id
        distance = _chebyshev(monster.position, origin)
        best = self._closest_to.get(unit_id)
        if best is None or distance < best:
            self._closest_to[unit_id] = distance
            self._no_progress[unit_id] = 0
            return
        count = self._no_progress.get(unit_id, 0) + 1
        self._no_progress[unit_id] = count
        if count >= self.services.monster_attempts:
            self._write_off(
                unit_id,
                monster.position,
                f"{count} closing ticks got no closer than {best} subtiles",
            )

    def centre(self, snap: GameSnapshot, ctx: EngineContext) -> tuple[int, int] | None:
        if self._centre is None:
            noted = ctx.notes.get(self.centre_note)
            if isinstance(noted, tuple):
                self._centre = noted
            elif snap.player is not None:
                # No note (a run that starts mid-area): here is as good a
                # centre as any, and saying so beats refusing to run.
                self._centre = snap.player.position
            if self._centre is not None:
                # Publish the circle for whoever sweeps it afterwards.
                #
                # The sweep has to cover the same ground this step cleared,
                # and the alternative — restating the radius in the run file
                # under `pickup` — is two numbers that mean one thing and can
                # drift apart silently. It would also quietly break the
                # `--radius` override, which only rewrites `clear_radius`
                # (the user's request was to make the radius easy to alter,
                # and "alter it in two places" is not that).
                ctx.notes["cleared"] = {
                    "centre": self._centre,
                    "radius": self.radius,
                    "patrol": self.patrol,
                }
        return self._centre

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.posture is not None and not self._posture_applied:
            # First tick: fight this step in its declared posture. The
            # module keeps all its bookkeeping across the swap — a
            # posture is a manner, not a new fight — and modules without
            # postures (fakes, sims) are simply left alone.
            set_posture = getattr(self.services.combat, "set_posture", None)
            if set_posture is not None:
                set_posture(self.posture)
                self.services.narrate(f"combat posture: {self.posture}")
            self._posture_applied = True
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        centre = self.centre(snap, ctx)
        if centre is None or snap.player is None:
            return StepOutcome(done=False)
        now = self.services.clock()
        self.confirm_pickups(snap)
        # The sightings memo (T3): whatever the pickit wants and this
        # step does not collect is the sweep's work order — and its only
        # reason to re-walk the ring.
        self.note_wanted_sightings(snap, centre, self.radius)

        in_radius = [
            m for m in snap.live_monsters
            if _chebyshev(m.position, centre) <= self.radius and self._reachable(m)
        ]
        if in_radius:
            self._empty_since = None
            # A fight is not a failed patrol leg. The character walks
            # TOWARD the monster, which is away from wherever the patrol
            # was heading, so a `_closest` recorded before the fight makes
            # every leg after it look like no progress — and three such
            # ticks abandon a point that was never unreachable. Live,
            # 2026-08-01: two points given up on from 20 subtiles, which
            # is walking distance, not a wall. The budget measures one
            # attempt, so an interruption ends the attempt.
            self._closest = None
            self._attempts = 0
            action = self.services.combat.engage(snap, ctx)
            if action is not None:
                if not self.send(ctx, action):
                    # The walk failed. `MoveTo.toward` names the monster the
                    # module was dashing at, which is the only honest way to
                    # know — `_select_target` prefers never-struck over
                    # nearest, so the step cannot recover it by guessing, and
                    # blaming the wrong monster would write off a reachable
                    # one. Nothing is blamed for a retreat or a drift, which
                    # carry no `toward` because they aim at open ground.
                    blamed = getattr(action, "toward", None)
                    target = next(
                        (m for m in in_radius if m.unit_id == blamed), None
                    )
                    if target is not None:
                        # Straight to a write-off rather than onto the
                        # no-progress budget: `walk_to` has already spent
                        # five plan cycles and a shake-loose before raising,
                        # so this is not one hopeful attempt, and the
                        # expiry-on-movement rule is what keeps it honest.
                        self._write_off(
                            target.unit_id, target.position, "the walk to it failed"
                        )
                return StepOutcome(done=False, acted=True)
            # Nothing to do offensively this tick (everything freshly
            # poisoned, or waiting for the revives): pick up loot instead of
            # standing still. Potions especially — the belt is the supply.
            items = self._draw_order(
                self.wanted_items(snap, snap.player.position, self.services.pickup_radius)
            )
            if items and self.collect(snap, ctx, items[0]):
                return StepOutcome(done=False, acted=True)
            if self.maybe_cleanse(snap, ctx):
                return StepOutcome(done=False, acted=True, note="inventory cleansed")
            # Before calling this patience, check it IS patience. This step
            # measures from the arrival point and the combat module measures
            # from the player, so a monster can be inside the clearance and
            # outside the fight — and then the module has nothing to say
            # while the step still wants that monster dead. Waiting there is
            # waiting for a kill nobody is going to make (review 001), so
            # ask the module to close the distance. It refuses whenever a
            # fight is actually in progress, which is what keeps this from
            # overriding a deliberate pause.
            nearest = min(
                in_radius,
                key=lambda m: _chebyshev(m.position, snap.player.position),
            )
            # Route-aware closing (R181): ask the map first. No route =
            # an instant write-off (expiry-on-movement keeps it honest),
            # and otherwise the route's next waypoint steers the hop —
            # the module stays grid-ignorant, it just dashes where told.
            via = None
            if self.services.route_to is not None:
                route = self.services.route_to(nearest.position)
                if route is None:
                    # Two-strike like the patrol's (T55 run 1): one torn
                    # grid read must not write off a reachable monster.
                    strikes = self._no_route.get(nearest.unit_id, 0) + 1
                    self._no_route[nearest.unit_id] = strikes
                    if strikes < 2:
                        return StepOutcome(
                            done=False, acted=True,
                            note=f"no route to monster {nearest.unit_id} — asking again",
                        )
                    self._write_off(
                        nearest.unit_id, nearest.position, "no route exists"
                    )
                    return StepOutcome(
                        done=False, acted=True,
                        note=f"no route to monster {nearest.unit_id}",
                    )
                self._no_route.pop(nearest.unit_id, None)
                via = _next_route_waypoint(route, snap.player.position)
            closing = self.services.combat.approach(
                snap, nearest.position, via=via
            )
            if closing is not None:
                if self.send(ctx, closing):
                    # Walked. Whether it ACHIEVED anything is the question,
                    # and the silent version of the hang is the one where
                    # every leg succeeds and none of them gets closer.
                    self._closing_progress(nearest, snap.player.position)
                else:
                    self._write_off(
                        nearest.unit_id, nearest.position, "the walk to it failed"
                    )
                return StepOutcome(
                    done=False, acted=True,
                    note=f"closing on monster {nearest.unit_id} at {nearest.position}",
                )
            # Nothing to send, nothing to pick up, hostiles still standing:
            # this is the skirmish pattern deliberately holding off —
            # `restrike_s` since the last dagger, or `wait_for_revives_s` for
            # the revives to take the front. Poison is doing the killing and
            # the ladder still gets its look every tick. Declared as a wait
            # so the never-idle watchdog does not read patience as a hang
            # (review 003); the worst realistic case is a 6 s restrike
            # against a 10 s limit, which was margin nobody had declared.
            return StepOutcome(done=False, waiting=True)

        # The radius reads clear — but "clear" is only a claim about what
        # we can SEE, and the settle timer must not start while there is
        # still circle we have never looked at. Starting it here was the
        # whole bug: the step would finish on an 80-subtile look at a
        # 150-subtile promise.
        if not self.patrol_complete:
            self._empty_since = None
            return self.walk_the_circle(snap, ctx)

        if self._empty_since is None:
            self._empty_since = now
            return StepOutcome(done=False, acted=True, note="radius reads clear")
        if now - self._empty_since >= self.services.clear_settle_s:
            # Say when "clear" means "clear except for the ones we gave up
            # on". A step that finishes with monsters still standing is the
            # right outcome — finishing beats hanging — but it is not the
            # same outcome as an empty field, and a note that reported both
            # identically would hide the write-off working too hard.
            written_off = (
                f", {len(self._unreachable)} monster(s) written off as "
                "unreachable"
                if self._unreachable
                else ""
            )
            return StepOutcome(
                done=True, acted=True,
                note=f"clear for {self.services.clear_settle_s:.0f}s{written_off}",
            )
        # Sweep loot while the settle timer runs; it is free time — and so
        # is a queued cleanse, with nothing alive to punish standing still.
        items = self._draw_order(self.wanted_items(snap, centre, self.radius))
        if items and self.collect(snap, ctx, items[0]):
            return StepOutcome(done=False, acted=True)
        if self.maybe_cleanse(snap, ctx):
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        # The settle timer itself: the radius reads clear and the step is
        # waiting to be sure. `clear_settle_s` is a knob that LOOKS
        # independent of `idle_bail_s`, so raising it used to make the run
        # abandon itself mid-settle (review 003).
        return StepOutcome(done=False, waiting=True)


@dataclass
class PickupStep(_PatrolMixin, _PickupMixin):
    """Sweep the cleared ground for anything the pickit wants.

    **It walks the same circle the clearance did.** Standing where the
    clearance happened to finish and collecting what is visible was the
    bug: visible means the client's loaded-room horizon, which T51 measured
    at 46-67 subtiles (2026-08-01, seven dropped potions watched vanishing)
    — so against a 96-radius circle the far side was not merely dim, it was
    never in the bot's world at all. The user watched a whitelisted Tir
    rune left behind on ground the sweep had no way to see. The pickit
    rules were right the whole time; nothing ever asked them about that
    rune.

    This is the identical flaw the clearance had before it got a patrol,
    and it gets the identical fix from the identical code (`_PatrolMixin`).

    The circle comes from the clearance over the shared blackboard rather
    than from this step's own parameters, so the radius stays ONE number
    (user request) and the `--radius` override reaches the sweep too. A run
    with no clearance falls back to the defaults below and does not patrol,
    because there is no circle to walk.
    """

    radius: int = 150
    centre_note: str = "arrival"
    patrol: bool = False
    name: str = "pickup"
    _centre: tuple[int, int] | None = None
    _resolved: bool = False

    def resolve(self, snap: GameSnapshot, ctx: EngineContext) -> None:
        """Adopt the clearance's circle, or fall back to our own."""
        if self._resolved:
            return
        cleared = ctx.notes.get("cleared")
        if isinstance(cleared, dict):
            centre = cleared.get("centre")
            if isinstance(centre, tuple):
                self._centre = centre
            self.radius = int(cleared.get("radius", self.radius))
            self.patrol = bool(cleared.get("patrol", self.patrol))
            self.services.log(
                f"sweep: covering the cleared circle — centre {self._centre}, "
                f"radius {self.radius}, patrol {'on' if self.patrol else 'off'}"
            )
        if self._centre is None:
            noted = ctx.notes.get(self.centre_note)
            self._centre = (
                noted if isinstance(noted, tuple)
                else (snap.player.position if snap.player else None)
            )
        self._resolved = self._centre is not None

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        self.resolve(snap, ctx)
        if self._centre is None:
            return StepOutcome(done=True, note="nowhere to sweep")
        self.confirm_pickups(snap)
        if self.maybe_cleanse(snap, ctx):
            # Space first, sweep second: a written-off item may be liftable
            # once the junk is gone.
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        items = self._draw_order(self.wanted_items(snap, self._centre, self.radius))
        if items:
            acted = self.collect(snap, ctx, items[0])
            return StepOutcome(done=False, acted=acted)
        # Nothing WE CAN SEE is wanted — which is not the same as nothing
        # left, and treating the two as one is what left the rune behind.
        # But the ring walk now needs EVIDENCE (T3, R186): the clearance
        # already patrolled this circle recording every wanted sighting,
        # so the sweep re-walks only while the memo holds something
        # unaccounted for. No sightings pending = the rune-class item
        # provably does not exist this run, and the old unconditional
        # re-walk spent 60-120 s confirming emptiness.
        if not self.patrol_complete and snap.player is not None:
            self.note_wanted_sightings(snap, self._centre, self.radius)
            pending = self.pending_sightings()
            if not pending:
                return StepOutcome(
                    done=True, acted=True,
                    note="nothing left to pick — every sighting accounted "
                    "for, ring walk skipped",
                )
            return self.walk_the_circle(snap, ctx)
        return StepOutcome(
            done=True, acted=True,
            note="nothing left to pick"
            + (f" (circle walked, {len(self._visited)} points)" if self.patrol else ""),
        )



