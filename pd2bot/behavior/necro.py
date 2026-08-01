"""The poison dagger necromancer: the user's own skirmish pattern, encoded.

R47.2, in the user's description: *on contact, wait briefly for the revives
to engage, dash in, left-click the monster, run back out of danger, recast
bone armor if low, repeat until the pack is dead.* That is what this module
implements — encoded, not invented. Where a number was not given (how far
"in" a dash is, how long "briefly" lasts) it is a commented config default
in `config/necro.toml`, never a literal in here.

Three things about this class shape the code:

**Offense never switches skills.** The left skill is permanently Poison
Strike (R47.1), so an attack is a plain left-click on the monster — with
SHIFT, so it strikes rather than walking into the pack. The right-hand
skills are utility only, and every one of them goes through a verified
switch in the executor.

**Poison does the killing, not the dagger.** So re-stabbing one monster
until it drops is wasted time: a struck monster is already dying. Target
selection therefore prefers monsters that have not been struck, and only
re-strikes one after `restrike_s` if it somehow survived the poison.

**Standing still is what kills this character** (R47.9, user danger
assessment: groups stun-lock). Hence the retreat after every strike, and
hence the dash being taken in SHORT HOPS rather than one long walk: a
blocking `walk_to` into a pack is time the reflex ladder is not being
consulted, and the ladder is the thing keeping the character alive. Each
hop is at most `dash_step` subtiles, so the engine gets a tick — and the
ladder a look — between them.

The module decides only; it returns declarative actions and never sends.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot import offsets
from pd2bot.behavior.actions import Action, AttackUnit, CastAtPoint, MoveTo
from pd2bot.behavior.reflex import retreat_point
from pd2bot.snapshot import GameSnapshot
from pd2bot.units import Monster


@dataclass(frozen=True)
class CombatConfig:
    """Every combat number. Defaults mirror config/necro.toml's [combat]."""

    # Engagement.
    engage_radius: int = 40  # hostiles this close mean "we are in a fight"
    melee_range: int = 3  # close enough to strike
    dash_step: int = 8  # max subtiles per approach hop (ladder responsiveness)
    retreat_subtiles: int = 12  # how far back out after a strike
    # How long to leave a poisoned survivor before hitting it again.
    # Was 6.0, on the theory that poison does the killing and a re-hit
    # is wasted. Watching it play, the user disagreed: whole seconds
    # standing still, and 'the best defense is a good offense'. The
    # number is the passivity — with a small pack, everything is on
    # cooldown almost all the time.
    restrike_s: float = 2.0
    # How far a small idle step moves. Deliberately much shorter than
    # `retreat_subtiles`: this is drift, not a withdrawal.
    reposition_subtiles: int = 4
    # How far a ground-targeted cast stays away from a clickable OBJECT.
    # Larger than the 2 used for units because an object's sprite is
    # larger than a monster's, and because the cost is asymmetric: a cast
    # placed 2 subtiles from a waypoint opens the waypoint menu, and a
    # panel outside town blocks every send until something closes it.
    object_clearance: int = 6
    # Revives as aggro tanks (R47.4).
    wait_for_revives_s: float = 1.5  # let them get in front before dashing
    revive_engaged_range: int = 8  # a revive this close to a hostile is engaged
    revive_target: int = 3
    revive_search_radius: int = 15  # corpses this close are revive fuel
    desecrate_rounds: int = 2  # bounded: stop if it makes no corpses
    desecrate_settle_s: float = 1.0  # wait for corpses before casting again
    revive_settle_s: float = 0.6  # do not re-target the same corpse instantly
    # Skill ids, filled from the class config (defaults are the live ids).
    desecrate_skill_id: int = 83
    revive_skill_id: int = 95


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


@dataclass
class NecroCombat:
    """The skirmish pattern and the revive maintenance, as a ticked module.

    Satisfies P4's `CombatModule` protocol: `engage` advances the fight by
    one decision, `upkeep` keeps the revive wall standing. Both are called
    once per tick and both may return None ("nothing to do this tick").
    """

    config: CombatConfig = field(default_factory=CombatConfig)
    is_walkable: Callable[[tuple[int, int]], bool] = lambda p: True
    clock: Callable[[], float] = time.monotonic
    # Bookkeeping.
    _last_strike: dict[int, float] = field(default_factory=dict)
    _engagement_start: float | None = None
    _retreat_after_strike: bool = False
    _desecrate_rounds: int = 0
    _last_desecrate: float | None = None
    _last_revive: float | None = None
    _last_revive_target: int | None = None

    # -- engagement ------------------------------------------------------------

    def _hostiles(self, snap: GameSnapshot) -> list[Monster]:
        if snap.player is None:
            return []
        origin = snap.player.position
        return [
            m
            for m in snap.live_monsters
            if _chebyshev(m.position, origin) <= self.config.engage_radius
        ]

    def _revives_engaged(self, snap: GameSnapshot, hostiles: list[Monster]) -> bool:
        """Have the revives actually gone in? The wait is for them to tank,
        so it ends when one of them is next to something — not on a timer
        alone, which would wait out the full delay even when they are
        already fighting."""
        for revive in snap.revives:
            for hostile in hostiles:
                if (
                    _chebyshev(revive.position, hostile.position)
                    <= self.config.revive_engaged_range
                ):
                    return True
        return False

    def _building_wall(self, snap: GameSnapshot, origin: tuple[int, int]) -> bool:
        """Can the revive wall still grow? Corpses to raise, or budget to
        make some. False means `upkeep` has run out of ways to help, and
        holding offense back any longer would be waiting for nothing."""
        if any(
            _chebyshev(c.position, origin) <= self.config.revive_search_radius
            for c in snap.corpses
        ):
            return True
        if self._desecrate_rounds >= self.config.desecrate_rounds:
            return False
        # Nowhere legal to put a desecrate is the same answer as no budget
        # left, and saying so matters more now that clickable objects are
        # avoided: standing beside a waypoint can rule out every candidate
        # spot. `upkeep` returns None in that case WITHOUT spending a round,
        # so a gate that only counted rounds would hold offense back forever
        # on that ground — the deadlock this method's own docstring exists
        # to prevent, reached by a different road.
        return self._open_ground(snap, origin) is not None

    def _reposition(
        self, origin: tuple[int, int], hostiles: list[Monster]
    ) -> Action | None:
        """A small step instead of standing still.

        Called wherever the module used to return None with hostiles alive:
        waiting out restrike timers, and holding back until the revive wall
        is up. Both are deliberate waits, and both used to be spent standing
        perfectly still in Hell — which the user judged riskier than moving,
        and which is the same thing the never-idle invariant says about a
        character that stops acting.

        The step is SMALL and away from the pack, so it never becomes an
        accidental charge and never crosses the ground the skirmish pattern
        is about to use. Nowhere to go is not a failure: None still means
        "nothing to do", and the ladder gets its look either way.

        **It never steps out of the fight** (review 001). Nothing bounded
        the drift when this was written: 4 subtiles per idle tick, every
        idle tick, accumulating until the pack fell outside `engage_radius`
        — after which `engage` had nothing to say while `clear_radius`,
        which measures from the ARRIVAL POINT rather than from the player,
        still wanted those monsters dead. The step then reported a
        deliberate wait forever, and a declared wait suppresses the
        never-idle watchdog: a permanent hang with the alarm switched off.
        The engagement itself is the bound — drift is only drift while we
        are still in the fight we are drifting inside.

        The bound is expressed as a condition on `retreat_point`'s rotation
        ladder rather than as a veto on its answer, and that is deliberate:
        a straight-back step that would leave the fight becomes a SIDEWAYS
        one, so the character keeps moving. Standing still is what the user
        has now twice called the dangerous option, and a bound that bought
        safety with stillness would be trading one danger for the other.
        """
        in_reach = lambda spot: any(  # noqa: E731 - reads better inline
            _chebyshev(spot, h.position) <= self.config.engage_radius
            for h in hostiles
        )
        spot = retreat_point(
            origin,
            [h.position for h in hostiles],
            self.config.reposition_subtiles,
            self.is_walkable,
            accept=in_reach,
        )
        return MoveTo(spot) if spot is not None else None

    def approach(
        self, snap: GameSnapshot, position: tuple[int, int]
    ) -> Action | None:
        """One hop toward something the RUN wants dead that we are not fighting.

        The two radii are measured from different points and never had to
        agree: `clear_radius` counts monsters from the arrival point,
        `_hostiles` counts them from the player. So a monster can sit inside
        the clearance and outside the fight, and then nobody moves — the
        module has nothing to say, and the step waits for a kill nobody is
        going to make (review 001). This is the clearance's way of asking
        for that gap to be closed, and it is the reason `engage_radius` no
        longer has to be a promise about what the run can want.

        Refused while there IS a fight. `engage` owns those ticks, and its
        deliberate pauses — a restrike cooldown, waiting for the revives to
        take the front — must not be overridden by a walk into the pack.
        Refused too when the target is already in reach, because then the
        answer is `engage`'s to give.

        A HOP, capped at `dash_step` like every other approach here, for
        the same reason: a blocking walk is time the reflex ladder is not
        being consulted.
        """
        if snap.player is None or snap.in_town:
            return None
        origin = snap.player.position
        if self._hostiles(snap):
            return None
        if _chebyshev(position, origin) <= self.config.engage_radius:
            return None
        return MoveTo(self._dash_target(origin, position))

    def _select_target(
        self, origin: tuple[int, int], hostiles: list[Monster], now: float
    ) -> Monster | None:
        """Nearest strikeable hostile, with the dangerous ones first.

        Preference order, as the pattern implies:
        1. Anything already adjacent to us — that is the stun-lock risk, and
           backing off from it without hitting it just gets us chased.
        2. Anything never struck — poison is already working on the rest.
        3. Survivors off their restrike cooldown.
        Nearest wins inside each tier.
        """
        candidates = []
        for hostile in hostiles:
            struck_at = self._last_strike.get(hostile.unit_id)
            if struck_at is not None and now - struck_at < self.config.restrike_s:
                continue  # poisoned recently; let it work
            distance = _chebyshev(hostile.position, origin)
            adjacent = distance <= self.config.melee_range + 1
            candidates.append((not adjacent, struck_at is not None, distance, hostile))
        if not candidates:
            return None
        candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3].unit_id))
        return candidates[0][3]

    def _dash_target(
        self, origin: tuple[int, int], destination: tuple[int, int]
    ) -> tuple[int, int]:
        """One short hop toward the monster, so the ladder gets a look in
        between. A single long walk into a pack is exactly the unattended
        stretch the ladder exists to prevent."""
        dx, dy = destination[0] - origin[0], destination[1] - origin[1]
        span = max(abs(dx), abs(dy))
        if span <= self.config.dash_step:
            return destination
        scale = self.config.dash_step / span
        return (round(origin[0] + dx * scale), round(origin[1] + dy * scale))

    def engage(self, snap: GameSnapshot, ctx: object = None) -> Action | None:
        """One decision of the fight, or None when there is nothing to do."""
        if snap.player is None or snap.in_town:
            return None  # combat logic must never target in town (P1 drill D)
        hostiles = self._hostiles(snap)
        if not hostiles:
            # The pack is dead (or we left it): the next contact is a fresh
            # engagement, so the wait-for-revives timer starts over.
            self._engagement_start = None
            self._retreat_after_strike = False
            return None

        now = self.clock()
        origin = snap.player.position
        if self._engagement_start is None:
            self._engagement_start = now

        # Phase 2 — let the tanks get in front. Ends early once they have.
        if (
            snap.revives
            and not self._revives_engaged(snap, hostiles)
            and now - self._engagement_start < self.config.wait_for_revives_s
        ):
            return None

        # Phase 5 — back out of the pack after a strike, before choosing
        # again. Deliberately before target selection: the retreat is part
        # of the strike, not an alternative to it.
        if self._retreat_after_strike:
            self._retreat_after_strike = False
            spot = retreat_point(
                origin,
                [h.position for h in hostiles],
                self.config.retreat_subtiles,
                self.is_walkable,
            )
            if spot is not None:
                return MoveTo(spot)
            # Nowhere to back off to: keep fighting rather than stand still.

        target = self._select_target(origin, hostiles, now)
        if target is None:
            # Everything nearby is freshly poisoned. The original design
            # stood still here and let the poison work; the user watched it
            # and judged the stillness itself the bigger risk — "better to
            # move often, even small movements". An idle character is what
            # R47.9 already says gets killed, so drift rather than freeze.
            return self._reposition(origin, hostiles)

        distance = _chebyshev(target.position, origin)
        if distance > self.config.melee_range:
            # Do not walk into a pack without the wall up (user protocol):
            # three revives BEFORE approaching, and desecrate makes its own
            # corpses so there is never a reason to go in short-handed. The
            # ladder's upkeep rung is already building them; this only stops
            # offense from advancing through the gaps between its casts.
            #
            # It releases once the wall CANNOT be built, which is the
            # difference between a protocol and a deadlock: `upkeep` gives up
            # after `desecrate_rounds` fruitless casts, and a gate that did
            # not know that would hold offense back forever on ground where
            # no corpse can be raised.
            if len(snap.revives) < self.config.revive_target and self._building_wall(
                snap, origin
            ):
                return self._reposition(origin, hostiles)
            return MoveTo(self._dash_target(origin, target.position))  # phase 3

        self._last_strike[target.unit_id] = now  # phase 4
        self._retreat_after_strike = True
        return AttackUnit(target.unit_id, target.position)

    # -- desecrate -> revive maintenance (R47.4) --------------------------------

    def _open_ground(self, snap: GameSnapshot, origin: tuple[int, int]) -> tuple[int, int] | None:
        """A walkable spot near us with nothing standing on it.

        Desecrate goes on the GROUND. A right-click that lands on a unit is
        a click on that unit — the same hazard that made travel clicks open
        NPC dialogs all through P3 (R111), and in combat it would target
        rather than cast.

        **Objects are the expensive version of that hazard**, and they were
        missing here until a live run paid for it. Stage B's tenth attempt
        arrived at the Cold Plains waypoint at (5268, 5713) and put its
        first desecrate at (5272, 5713) — four subtiles away, still on the
        waypoint's sprite. The right-click opened the waypoint menu, which
        blocks input, so every send afterwards was refused until the
        navigator gave up 10 s later and the run chickened out with the
        area untouched.

        The navigator has avoided exactly this since R111, filtered to
        `INTERACTIVE_OBJECT_KINDS` because avoiding all 15 pieces of Cold
        Plains scenery made the area unwalkable. Casts never went through
        the navigator, so they never got the filter. They do now, with a
        wider berth than units get: an object's sprite is bigger, and the
        two mistakes do not cost the same — clicking a monster is an
        attack, clicking a waypoint ends the run.
        """
        occupied = [
            u.position
            for u in (*snap.live_monsters, *snap.allies, *snap.corpses)
        ]
        clickable = [
            o.position
            for o in snap.objects
            if o.kind in offsets.INTERACTIVE_OBJECT_KINDS
        ]
        for radius in (4, 6, 8):
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1),
                           (1, 1), (-1, 1), (1, -1), (-1, -1)):
                spot = (origin[0] + dx * radius, origin[1] + dy * radius)
                if not self.is_walkable(spot):
                    continue
                if any(_chebyshev(spot, o) <= 2 for o in occupied):
                    continue
                if any(
                    _chebyshev(spot, o) <= self.config.object_clearance
                    for o in clickable
                ):
                    continue
                return spot
        return None

    def upkeep(self, snap: GameSnapshot, ctx: object = None) -> Action | None:
        """Keep `revive_target` revives up: desecrate for corpses, revive them.

        Called from the ladder's rung 8, which already refuses in town; the
        town check is repeated here because neither of the two rules
        (R47.4: not castable in town) should depend on the other's caller.
        """
        if snap.player is None or snap.in_town:
            return None
        if len(snap.revives) >= self.config.revive_target:
            # The wall is up. Reset the bounded-round counter so the NEXT
            # shortfall gets a full budget rather than inheriting this one's.
            self._desecrate_rounds = 0
            return None

        now = self.clock()
        origin = snap.player.position
        corpses = [
            c
            for c in snap.corpses
            if _chebyshev(c.position, origin) <= self.config.revive_search_radius
        ]

        if corpses:
            if (
                self._last_revive is not None
                and now - self._last_revive < self.config.revive_settle_s
            ):
                return None  # the last revive is still resolving
            corpse = next(
                (c for c in corpses if c.unit_id != self._last_revive_target),
                corpses[0],
            )
            self._last_revive = now
            self._last_revive_target = corpse.unit_id
            self._desecrate_rounds = 0  # corpses exist; the budget is unspent
            return CastAtPoint(self.config.revive_skill_id, corpse.position)

        # No corpses: make some. Bounded, because a desecrate that produces
        # nothing (no bodies in range, skill on cooldown) would otherwise be
        # recast forever, and every one of those ticks is a tick not fighting.
        if (
            self._last_desecrate is not None
            and now - self._last_desecrate < self.config.desecrate_settle_s
        ):
            return None  # corpses arrive a beat after the cast
        if self._desecrate_rounds >= self.config.desecrate_rounds:
            return None
        spot = self._open_ground(snap, origin)
        if spot is None:
            return None
        self._desecrate_rounds += 1
        self._last_desecrate = now
        return CastAtPoint(self.config.desecrate_skill_id, spot)
