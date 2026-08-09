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
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.perception.units import Monster


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
    # Was 6.0, then 2.0, now 1.0 — every cut from the same source, the user
    # watching it play. The theory it keeps losing to is "poison does the
    # killing, so a re-hit is wasted": true about the damage, wrong about
    # the time, because the tick spent not striking is spent standing
    # still. R163: *ducking in for a click and running away, and moving
    # frequently, are good strategies.*
    restrike_s: float = 1.0
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
    wait_for_revives_s: float = 0.8  # let them get in front before dashing
    revive_engaged_range: int = 8  # a revive this close to a hostile is engaged
    revive_target: int = 3
    # -- posture switches (M6 P3, R212 Q5) --------------------------------
    # These four are what the named postures (cautious/brisk/aggressive)
    # override; the defaults ARE cautious, so an empty posture table
    # changes nothing and every pre-M6 run behaves exactly as it did.
    #
    # linger=False (brisk): when everything nearby is freshly poisoned,
    # return None instead of drifting — the run step keeps moving, which
    # is what "brush past them toward the target" means mechanically.
    linger: bool = True
    # retreat_group_size=0: back out after EVERY strike (the cautious
    # skirmish beat). N>0 (aggressive): the post-strike retreat fires
    # only when >=N hostiles stand within retreat_group_radius — an
    # isolated enemy gets struck without the back-out ("attacks more,
    # backs off less"), while a closing group still triggers the full
    # retreat (the user's own definition of aggressive, R212 Q5).
    retreat_group_size: int = 0
    retreat_group_radius: int = 8
    # -- revive urgency (M6 P3, user note 1.5) ----------------------------
    # While hostiles are present, the wall is short, and the wall CAN
    # still grow, offense holds (drift only, no strikes/dashes) so the
    # desecrate->revive casts get the cast pipeline to themselves — the
    # T55 armor lesson one rung down: strike CLICKS colliding with cast
    # animations (CastInFlight) are what made the wall build look like
    # dilly-dallying. Bounded by _building_wall exactly like the
    # approach gate, so it can never hold offense forever.
    revive_urgency_hold: bool = True
    # A desecrate budget burned against the skill's own cooldown used to
    # stay burned until the wall grew (R185 B). This refreshes it on
    # TIME instead — in-combat only (the quiet-field gate still stops
    # empty-field churn), and 0 disables the refresh entirely.
    desecrate_budget_refresh_s: float = 8.0
    # -- right-skill parking (M6 P3, user note 1; consumed by the
    # executor, carried here so the user tunes it with the rest) --------
    # After any right-skill cast resolves with no follow-up cast inside
    # this grace, the executor switches back to the armor hotkey: an
    # active Revive right-skill makes ground corpses selectable, which
    # interferes with pathing and pickup. The grace is what lets a
    # 3-revive burst finish without thrashing the switch.
    park_grace_s: float = 2.0
    # How many revives must be up before OFFENSE may advance — a different
    # question from `revive_target`, which is how many upkeep maintains,
    # and conflating the two is why the bot stood back so much (R163).
    # Waiting for the full wall meant waiting through two desecrates and
    # three revive casts before the first dash; one tank in front is
    # enough to stop being the closest target, and upkeep keeps building
    # the rest while the fight is on.
    approach_with_revives: int = 1
    revive_search_radius: int = 15  # corpses this close are revive fuel
    desecrate_rounds: int = 2  # bounded: stop if it makes no corpses
    # Strikes on ONE unit that move neither its health nor our mana before
    # it stops being a target (T72: 23 strikes each on two decorative bats
    # over 173 s, with nothing in the code able to notice). Small on
    # purpose — poison kills over seconds, so a genuine fight moves the
    # target's health well inside four strikes, and the write-off expires
    # the moment that health does move.
    futile_strikes: int = 4
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
    # The named posture presets (M6 P3): full CombatConfigs built by the
    # class-config loader. Empty = no postures in this environment and
    # set_posture refuses everything but leaving things alone.
    postures: dict[str, CombatConfig] = field(default_factory=dict)
    posture: str = "cautious"
    # Bookkeeping.
    _last_strike: dict[int, float] = field(default_factory=dict)
    # -- the futile-strike write-off (T72/T74, 2026-08-06) -----------------
    #
    # Per unit id: how many strikes have landed on it with NOTHING to show
    # for them, and what the world looked like at the last one. "Nothing to
    # show" is two independent readings that must BOTH hold:
    #
    #   - the target's health has not moved, and
    #   - OUR MANA has not moved either (the operator's insight: a poison
    #     strike costs mana, so mana that does not move means the attack
    #     never actually happened).
    #
    # The pair is what makes the signature readable, and the two halves
    # mean genuinely different things — which is why they are recorded
    # separately rather than collapsed into one counter:
    #
    #   mana spent + health static = "no-damage". The strike landed and
    #       achieved nothing VISIBLE YET. Usually transient: poison is
    #       damage over time and the monster's health is stored on a
    #       coarse 0-128 scale, the swing may simply have missed, or a
    #       resistance has not yet been pierced.
    #   mana NOT spent             = "no-contact". The strike never
    #       happened at all — a phantom, a unit behind a wall, a click
    #       that went nowhere.
    #
    # NEITHER is a durable property, and the earlier version of this
    # comment was wrong to imply the first one was (operator correction,
    # 2026-08-06). Hell "immunity" is 100% resistance, not invulnerability:
    # characters and mercs deal MIXED damage, Poison Dagger carries poison
    # resistance pierce, and the operator's merc runs Pus Spitter, whose
    # Lower Resist on striking breaks immunities outright. A monster that
    # looks unkillable for four strikes may be dying on the fifth — which
    # is exactly why the write-off expires the moment its health moves,
    # and why nothing here is remembered across runs.
    #
    # T72 spent 173 s and 46 strikes on two decorative bats without this.
    # The critter filter (T74) now removes that particular family before
    # combat ever sees it; this exists for the family nobody has met yet.
    _futile: dict[int, int] = field(default_factory=dict)
    _futile_seen: dict[int, tuple[int, int, tuple[int, int]]] = field(
        default_factory=dict
    )
    _written_off: dict[int, tuple[int, int]] = field(default_factory=dict)
    _engagement_start: float | None = None
    _retreat_after_strike: bool = False
    _desecrate_rounds: int = 0
    _last_desecrate: float | None = None
    _last_revive: float | None = None
    _last_revive_target: int | None = None
    # How many revives stood at the last upkeep look. The desecrate budget
    # refills only when this GROWS (R185 B) — see `upkeep`.
    _revive_count_seen: int = 0
    # When upkeep last returned a wall cast (desecrate or revive) — the
    # revive-urgency hold's correlation input (M6 P3).
    _last_wall_cast: float | None = None

    # -- postures (M6 P3) -------------------------------------------------------

    def set_posture(self, name: str) -> None:
        """Swap the active config for a named preset, mid-run safe.

        Only `config` changes; every piece of bookkeeping (`_last_strike`,
        the desecrate budget, the engagement timer) survives — a posture
        is a change of manner, not a new fight. Unknown names are loud:
        the run file was validated against the loaded posture names at
        build time, so reaching here with a bad one is a wiring bug.
        """
        preset = self.postures.get(name)
        if preset is None:
            raise KeyError(
                f"unknown posture {name!r} (loaded: "
                f"{', '.join(sorted(self.postures)) or 'none'})"
            )
        self.config = preset
        self.posture = name

    # -- engagement ------------------------------------------------------------

    def _hostiles(self, snap: GameSnapshot) -> list[Monster]:
        if snap.player is None:
            return []
        origin = snap.player.position
        return [
            m
            for m in snap.live_monsters
            if _chebyshev(m.position, origin) <= self.config.engage_radius
            and self._worth_striking(m)
        ]

    # -- the futile-strike write-off -------------------------------------------

    def _worth_striking(self, monster: Monster) -> bool:
        """False once strikes on this unit have provably achieved nothing.

        The write-off EXPIRES when the monster's health finally moves —
        the same shape as `ClearRadiusStep._reachable`, whose write-off
        expires when the monster moves. A retry that cannot differ from
        the attempt it retries is not a retry; a target whose health has
        started falling is a genuinely different situation.
        """
        recorded = self._written_off.get(monster.unit_id)
        if recorded is None:
            return True
        hp_then, _ = recorded
        if monster.hp < hp_then:
            # Something is hurting it after all (a revive, the merc, a
            # lingering poison stack). It is back on the table.
            del self._written_off[monster.unit_id]
            self._futile.pop(monster.unit_id, None)
            self._futile_seen.pop(monster.unit_id, None)
            return True
        return False

    def _book_strike_outcome(
        self, snap: GameSnapshot, target: Monster, now: float
    ) -> None:
        """Judge the PREVIOUS strike on `target` before issuing another.

        Called just before a strike is committed, because that is the
        moment both readings are available and comparable: what the
        target's health was when we last hit it, and what our mana was.
        """
        player = snap.player
        if player is None:
            return
        previous = self._futile_seen.get(target.unit_id)
        self._futile_seen[target.unit_id] = (
            target.hp, player.mana, target.position
        )
        if previous is None:
            return
        hp_then, mana_then, _ = previous
        health_moved = target.hp < hp_then
        mana_moved = player.mana < mana_then
        if health_moved:
            # The fight is working. Any accumulated futility is stale.
            self._futile.pop(target.unit_id, None)
            return
        strikes = self._futile.get(target.unit_id, 0) + 1
        self._futile[target.unit_id] = strikes
        if strikes < self.config.futile_strikes:
            return
        self._written_off[target.unit_id] = (target.hp, target.kind)
        # Both signatures are reported, and both are TRANSIENT claims
        # about this moment rather than facts about the monster: see the
        # field comments. The log carries them so a pattern across runs
        # can be noticed by a human, never so the bot can teach itself
        # that something is unkillable.
        self.note_write_off(
            unit_id=target.unit_id,
            kind=target.kind,
            strikes=strikes,
            signature="no-damage" if mana_moved else "no-contact",
            hp=target.hp,
        )

    def note_write_off(self, **fields) -> None:
        """Report a write-off. Overridden/patched by the wiring to reach
        the run log; a no-op by default so the module stays loggerless."""
        return None

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

    def _wall_pipeline_s(self) -> float:
        """How long after a wall cast the urgency hold keeps offense out.

        Derived, not a knob: the longest settle plus roughly one cast
        animation (T48 measured 610-640 ms), so tuning the settles moves
        the hold with them and there is no second number to forget.
        """
        return (
            max(self.config.desecrate_settle_s, self.config.revive_settle_s)
            + 1.0
        )

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
        self,
        snap: GameSnapshot,
        position: tuple[int, int],
        via: tuple[int, int] | None = None,
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

        `via` is the route's next waypoint when the step has one (R181):
        the hop takes the ROUTE's direction rather than the bearing when
        they differ, so a monster behind a fence is approached around it.
        The gates stay keyed to `position` (the monster) — whether the
        fight is close enough to refuse is a fact about the monster, not
        about the corner we would round first. This module remains
        grid-ignorant: it dashes where the step says, and the step asked
        the map.
        """
        if snap.player is None or snap.in_town:
            return None
        origin = snap.player.position
        if self._hostiles(snap):
            return None
        if _chebyshev(position, origin) <= self.config.engage_radius:
            return None
        return MoveTo(self._dash_target(origin, via if via is not None else position))

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

        # The revive-urgency hold (M6 P3, user note 1.5): while the wall is
        # short AND a wall cast is actively in the pipeline, strikes and
        # dashes wait — a strike is a CLICK, and clicks landing inside
        # cast animations (CastInFlight) are what made the wall build
        # look like dilly-dallying (the T55 armor lesson, one rung down).
        # Keyed to a RECENT wall cast rather than to wall-shortness alone,
        # so this never re-creates the pre-R163 full-wall passivity: no
        # cast in flight (budget spent, corpses missing) = offense free.
        if (
            self.config.revive_urgency_hold
            and len(snap.revives) < self.config.revive_target
            and self._last_wall_cast is not None
            and now - self._last_wall_cast < self._wall_pipeline_s()
            and self._building_wall(snap, origin)
        ):
            return self._reposition(origin, hostiles)

        target = self._select_target(origin, hostiles, now)
        if target is None:
            if not self.config.linger:
                # Brisk (M6 P3): everything nearby is poisoned and nothing
                # blocks the way — nothing to say, so the RUN keeps moving
                # instead of the module drifting in place.
                return None
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
            if len(
                snap.revives
            ) < self.config.approach_with_revives and self._building_wall(
                snap, origin
            ):
                return self._reposition(origin, hostiles)
            # `toward` names the monster this dash is for, so a caller that
            # absorbs a failed walk knows WHICH target to write off. Only
            # the dash carries it: a retreat and a lateral drift are aimed
            # at open ground, not at anything.
            return MoveTo(  # phase 3
                self._dash_target(origin, target.position), toward=target.unit_id
            )

        # Judge the LAST strike on this target before spending another
        # (the futile-strike write-off). Deliberately here rather than at
        # target selection: this is the one place both readings — the
        # target's health and our mana — are current and comparable.
        self._book_strike_outcome(snap, target, now)
        if not self._worth_striking(target):
            return None  # written off just now; re-decide next tick
        self._last_strike[target.unit_id] = now  # phase 4
        # Aggressive (M6 P3): the post-strike retreat is group-conditioned.
        # 0 keeps the cautious beat — back out after every strike.
        group = self.config.retreat_group_size
        self._retreat_after_strike = group == 0 or (
            sum(
                1
                for h in hostiles
                if _chebyshev(h.position, origin)
                <= self.config.retreat_group_radius
            )
            >= group
        )
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
        if not snap.live_monsters:
            # The quiet-field gate (R185 A, run 4's 854 s clearance): with
            # nothing hostile in perception there is nothing for a revive
            # wall to tank, and maintaining one anyway churned casts for
            # ~10 minutes while the patrol inched between them. The wall
            # rebuilds at the next contact — `wait_for_revives_s` already
            # holds offense while it does.
            return None
        revives = len(snap.revives)
        if revives > self._revive_count_seen:
            # The wall actually GREW: the desecrate budget earned its
            # refill (R185 B). The old reset — "corpses exist" — was
            # self-feeding: desecrate is what CREATES corpses, so the
            # budget refilled itself and the bound never bound.
            self._desecrate_rounds = 0
        self._revive_count_seen = revives
        if revives >= self.config.revive_target:
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
            self._last_wall_cast = now  # feeds the urgency hold (M6 P3)
            # Deliberately NO budget reset here (R185 B): corpses existing
            # is what desecrate manufactures, and refilling the budget on
            # its own product is how run 4 churned for 10 minutes.
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
            # The time-based refresh (M6 P3, user note 1.5): a budget
            # burned against the skill's own cooldown used to stay burned
            # until the wall grew — which it could not, with no corpses to
            # raise. R185 B's only-on-growth rule stands for the churn it
            # was written against (this branch is reached with hostiles
            # PRESENT — the quiet-field gate already returned above), and
            # the refresh is paced at desecrate_budget_refresh_s, so the
            # worst case is desecrate_rounds casts per refresh window, in
            # combat, not run 4's 10-minute empty-field churn.
            if (
                self.config.desecrate_budget_refresh_s > 0
                and self._last_desecrate is not None
                and now - self._last_desecrate
                >= self.config.desecrate_budget_refresh_s
            ):
                self._desecrate_rounds = 0
            else:
                return None
        spot = self._open_ground(snap, origin)
        if spot is None:
            return None
        self._desecrate_rounds += 1
        self._last_desecrate = now
        self._last_wall_cast = now  # feeds the urgency hold (M6 P3)
        return CastAtPoint(self.config.desecrate_skill_id, spot)
