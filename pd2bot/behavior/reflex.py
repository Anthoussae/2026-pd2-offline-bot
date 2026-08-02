"""The survival reflex ladder (R49): evaluated every tick, above offense.

Priority-ordered rungs; the first that fires wins the tick and everything
below it — including the run's own step — is skipped. Rungs 1-2 (the death
latch and the chicken) live in `SafetyMonitor` and are deliberately NOT
reimplemented here: the monitor raises through the engine's tick before the
ladder is even consulted, and stays the untouched last line.

The rungs this module owns (numbers are the R49-approved defaults; every one
is config, sourced from the class TOML):

    3  rejuv      hp < 50%: drink the rejuv column (no cooldown). Column
                  empty with >=2 hostiles within 10: escalate to rung 4.
    4  blood warp (>=4 hostiles within 8 AND hp < 60%) OR >25% of max hp
                  lost within 2 s. Guards: mana >= 10, hp > 2x the warp
                  cost. Retreat point ~20 subtiles from the hostile
                  centroid on known-walkable ground.
    5  heal       hp < 100%: healing column, 10 s cooldown (backup column
                  when the primary is empty).
    6  mana       mana < 25%: mana column, 15 s cooldown (R49 amendment).
    7  disengage  bone armor down AND on cooldown AND hp < 70%: retreat
                  from the pack; no attacking until rearmored.
    8  upkeep     bone armor off cooldown and absorb < 75% (fallback when
                  the stat is unreadable: after being hit): recast.
                  Revive raising is DELEGATED to the combat module's
                  upkeep() — the ladder does not know what a revive is.

Town suppression: rungs 3-7 never fire in town. Drink rules are out-of-town
only (R47.6), and — the sharper reason — town guards without an alignment
stat read as MONSTERS (P1, drill D), so any hostile-count trigger evaluated
in town counts bystanders. Rung 8's armor recast is the one town-permitted
action (castable and harmless there, proven live in P2); the combat-module
delegation is out-of-town only (desecrate/revive are not castable in town,
R47.4).

Belt columns follow the PERMANENT layout the user declared at R53 — key 1
mana, key 2 rejuv, keys 3+4 healing. (The phase file's rung table still
carries R47.6's original key numbers; R53 superseded them, and the config
here is the R53 mapping.)

Cooldown and last-attempt bookkeeping is this module's job; P2's primitives
are dumb on purpose. It is DECIDED here and COMMITTED by the engine, once
the send has landed — see `ReflexDecision.commit`. Blood warp's own cooldown
is unknown-length, so it is
tracked by POSITION-VERIFY: an attempt is recorded with where the player
stood, a later evaluation that finds the player far from that spot counts it
as landed, and one that does not treats the warp as still on cooldown rather
than spamming casts (the trust-nothing pattern: a cast is a request, the
effect is the proof).
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.behavior.actions import (
    Action,
    CastAtPoint,
    CastSelf,
    DrinkPotion,
    MoveTo,
)
from pd2bot.items import CarriedItem, CarriedItems
from pd2bot.memory import GameSession
from pd2bot.snapshot import GameSnapshot
from pd2bot.units import player_unit, read_stats


@dataclass(frozen=True)
class ReflexConfig:
    """Every ladder number, user-approved at R49 and owned by the class TOML.

    Defaults here mirror config/necro.toml so a hand-built ladder in a test
    behaves like the shipped one; the TOML is the authoritative, commented
    copy the user tunes.
    """

    # Belt columns, zero-based (key = column + 1). The R53 permanent layout.
    mana_column: int = 0
    rejuv_column: int = 1
    heal_columns: tuple[int, ...] = (2, 3)  # primary first, then backup
    # Rung 3 — rejuv.
    rejuv_below_pct: float = 50.0
    escalate_hostiles: int = 2  # empty column + this many hostiles ...
    escalate_radius: int = 10  # ... within this range -> escalate to warp
    # Rung 4 — blood warp.
    warp_skill_id: int = offsets.SKILL_BLOOD_WARP
    warp_hostiles: int = 4
    warp_radius: int = 8
    warp_hp_pct: float = 60.0
    warp_loss_pct: float = 25.0  # of max hp ...
    warp_loss_window_s: float = 2.0  # ... lost within this window
    warp_min_mana: int = 10  # the cast costs 10 mana (R47.3)
    warp_cost_pct: float = 12.0  # hp cost: max(12% of max hp, 12) (R47.3)
    warp_cost_floor: int = 12
    warp_verify_move: int = 10  # moved this far since the attempt = it landed
    warp_retry_s: float = 2.0  # an unverified attempt blocks re-casts this long
    retreat_distance: int = 20  # subtiles from the hostile centroid
    # Rung 5 — healing potion.
    heal_below_pct: float = 100.0
    heal_cooldown_s: float = 10.0
    # Rung 6 — mana potion.
    mana_below_pct: float = 25.0
    mana_cooldown_s: float = 15.0  # 15 s, the R49 amendment (was 5)
    # Rung 6.5 — reposition (R176 Q3, numbers user-approved). Sustained
    # chip damage while standing still means "stand somewhere else", even
    # at low damage (user, watching the R173 run hold its ground in fire
    # until chicken). Ground fire has no unit for perception to see, so
    # the trigger is damage-source-agnostic: health falling while the feet
    # are not moving IS the signal.
    reposition_loss_pct: float = 2.0  # of max hp lost within the window ...
    reposition_window_s: float = 2.5  # ... this long ...
    reposition_still_subtiles: int = 3  # ... while moving less than this
    reposition_step: int = 10  # how far to step away
    reposition_cooldown_s: float = 2.0  # pacing between fires
    # Rung 7 — disengage.
    disengage_hp_pct: float = 70.0
    # Rung 8 — bone armor upkeep.
    armor_skill_id: int = offsets.SKILL_BONE_ARMOR
    armor_recast_below_pct: float = 75.0
    armor_retry_s: float = 2.0  # pace recast attempts; cooldown is unreadable
    armor_in_town: bool = True  # the one rung allowed in town


@dataclass(frozen=True)
class ReflexDecision:
    """One firing rung: which one, what to do, and why (for the log).

    `commit` is the rung's bookkeeping — starting a cooldown, recording a
    warp attempt — held back until the action has actually been SENT. The
    engine calls it after a successful execute and never after a refused
    one. Deciding is not acting: a heal whose click was refused (a panel
    open, focus elsewhere) used to start its 10 s cooldown anyway, so the
    ladder stopped offering the heal that the character still needed. The
    ladder's promise is that it re-decides from fresh state every tick, and
    committing at decision time broke that promise precisely when input was
    being refused — which correlates with things going wrong (review 002).

    `on_attempt` is the other half, and the difference between the two is
    worth stating because collapsing them cost a live run. A COOLDOWN says
    "the resource is spent" and must only start when the action actually
    happened — that is `commit`, and it is review 002's point. PACING says
    "do not spam this", and it has to record even when the send failed:
    otherwise an action that keeps failing is retried at tick rate forever.

    Stage B run 9 is what that looks like. The bone-armor switch would not
    take, the rung fired, the send failed, nothing was recorded, and the
    rung fired again on the very next tick — fifteen times in a row, every
    tick consumed, the run unable to take a single step. A crash had become
    a livelock.
    """

    rung: str
    action: Action
    reason: str
    commit: Callable[[], None] | None = None
    on_attempt: Callable[[], None] | None = None

    def commit_sent(self) -> None:
        """Called by the engine once the action left the building."""
        if self.commit is not None:
            self.commit()

    def commit_attempted(self) -> None:
        """Called whether or not the action landed — pacing only."""
        if self.on_attempt is not None:
            self.on_attempt()


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _within(
    positions: list[tuple[int, int]], origin: tuple[int, int], radius: int
) -> int:
    return sum(1 for p in positions if _chebyshev(p, origin) <= radius)


def _centroid(positions: list[tuple[int, int]]) -> tuple[float, float]:
    n = len(positions)
    return (sum(p[0] for p in positions) / n, sum(p[1] for p in positions) / n)


def retreat_point(
    origin: tuple[int, int],
    hostiles: list[tuple[int, int]],
    distance: int,
    is_walkable: Callable[[tuple[int, int]], bool],
    accept: Callable[[tuple[int, int]], bool] | None = None,
) -> tuple[int, int] | None:
    """A walkable spot ~`distance` subtiles from `origin`, away from the pack.

    Directly away from the hostile centroid first, then rotated fallbacks in
    widening steps (+-45, +-90, +-135, 180) — running toward the pack is the
    last resort, not the second choice. Returns None when nothing checks out
    walkable, which callers must treat as "this escape is not available",
    never as "go anyway": warping onto unwalkable ground would burn the cast,
    the mana, and the hp cost for a teleport the game refuses.

    `accept` is a second condition on the same ladder, for callers who want
    somewhere away from the pack but not ANYWHERE away from it. The combat
    module's idle drift uses it to refuse a step that would leave the fight
    (review 001) — and because it rides the existing rotation ladder rather
    than vetoing the one answer, a rejected straight-back step becomes a
    LATERAL one instead of standing still. That distinction is the user's,
    stated twice from watching live runs: standing still is the dangerous
    option, so "cannot go backwards" must mean "go sideways", not "stop".
    """
    if not hostiles:
        base_angle = 0.0
    else:
        cx, cy = _centroid(hostiles)
        dx, dy = origin[0] - cx, origin[1] - cy
        if dx == 0 and dy == 0:
            base_angle = 0.0
        else:
            base_angle = math.atan2(dy, dx)
    for offset_deg in (0, 45, -45, 90, -90, 135, -135, 180):
        angle = base_angle + math.radians(offset_deg)
        candidate = (
            round(origin[0] + distance * math.cos(angle)),
            round(origin[1] + distance * math.sin(angle)),
        )
        if is_walkable(candidate) and (accept is None or accept(candidate)):
            return candidate
    return None


def read_armor_ratio(session: GameSession) -> float | None:
    """Bone armor absorb remaining: 0.0-1.0, or None when nothing was read.

    Stats 132/133, fully live-verified by T46 — and the distinction between
    "the armor is down" and "I cannot tell" is the entire point of this
    function, because collapsing them meant the bot never cast bone armor
    at all.

    T46's three readings, on the live character:

        armor down   132 ABSENT, 133 ABSENT   (70 stats read)
        armor up     132 = 866, 133 = 866     (77 stats read)
        after a hit  132 = 807, 133 = 866     (78 stats read)

    So a healthy stat list simply omits both entries while the armor is
    down. The old code returned None for that, the ladder read None as
    "unreadable" and fell back to R47's recast-after-being-hit — and in
    town, where nothing hits us, that meant the armor was never cast. The
    strongest possible reason to cast was arriving as the value that means
    ignorance. (Same conflation as `units.read_socket_count`, same fix.)

    An EMPTY stat list still returns None, and that guard is what makes the
    change safe: absence only means "down" when the read plainly worked.
    """
    unit = player_unit(session)
    if unit is None:
        return None
    stats = read_stats(session, unit)
    if not stats:
        return None  # nothing read at all — genuinely unknown, use the fallback
    maximum = stats.get(offsets.STAT_BONE_ARMOR_MAX)
    if not maximum:
        return 0.0  # the list read fine and has no armor in it: it is DOWN
    return stats.get(offsets.STAT_BONE_ARMOR, 0) / maximum


class ReflexLadder:
    """Evaluates the ladder against one snapshot; owns all bookkeeping.

    Pure decision-making: nothing here sends input. The engine executes the
    returned decision through the injected executor, which is what keeps the
    whole ladder testable against scripted worlds.
    """

    def __init__(
        self,
        config: ReflexConfig | None = None,
        *,
        carried: Callable[[], CarriedItems],
        armor_ratio: Callable[[], float | None],
        is_walkable: Callable[[tuple[int, int]], bool],
        combat_upkeep: Callable[[GameSnapshot], Action | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config if config is not None else ReflexConfig()
        self._carried = carried
        self._armor_ratio = armor_ratio
        self._is_walkable = is_walkable
        self._combat_upkeep = combat_upkeep
        self._clock = clock
        # Bookkeeping. All of it lives here because P2's primitives are dumb
        # on purpose: the ladder owns the WHEN, skills.py owns the HOW.
        # (time, hp, position) — one history serves both windowed triggers
        # (warp's burst and reposition's chip-while-still); each computes
        # over ITS OWN window, because the deque is trimmed to the longer
        # of the two and warp's threshold must not quietly widen.
        self._hp_samples: deque[tuple[float, int, tuple[int, int]]] = deque()
        self._last_hp: int | None = None
        self._last_drink: dict[str, float] = {}
        self._warp_attempt: tuple[float, tuple[int, int]] | None = None
        self._armor_attempt: float | None = None
        self._reposition_attempt: float | None = None

    # -- shared bookkeeping ----------------------------------------------------

    def _record_vitals(
        self, now: float, hp: int, position: tuple[int, int]
    ) -> bool:
        """Track hp+position history for the windowed triggers. Returns
        'was hit'."""
        was_hit = self._last_hp is not None and hp < self._last_hp
        self._last_hp = hp
        self._hp_samples.append((now, hp, position))
        horizon = now - max(
            self.config.warp_loss_window_s, self.config.reposition_window_s
        )
        while self._hp_samples and self._hp_samples[0][0] < horizon:
            self._hp_samples.popleft()
        return was_hit

    def _hp_lost_in_window(self, hp: int) -> int:
        horizon = self._clock() - self.config.warp_loss_window_s
        losses = [
            sample_hp for when, sample_hp, _ in self._hp_samples
            if when >= horizon
        ]
        if not losses:
            return 0
        return max(losses) - hp

    def _bleeding_while_still(
        self, now: float, hp: int, max_hp: int, position: tuple[int, int]
    ) -> bool:
        """Rung 6.5's trigger: lost enough within the window without moving.

        Movement is judged as the furthest any in-window sample sits from
        where we stand NOW — a wiggle that returns to the same spot is
        still standing in the fire, and must not read as travel.
        """
        cfg = self.config
        horizon = now - cfg.reposition_window_s
        window = [s for s in self._hp_samples if s[0] >= horizon]
        if not window:
            return False
        lost = max(sample_hp for _, sample_hp, _ in window) - hp
        if lost < cfg.reposition_loss_pct / 100.0 * max_hp:
            return False
        moved = max(_chebyshev(position, at) for _, _, at in window)
        return moved < cfg.reposition_still_subtiles

    def _resolve_warp_attempt(self, position: tuple[int, int]) -> None:
        """Position-verify the outstanding warp attempt, if any.

        Moved far enough since the attempt: it landed, clear the record.
        Otherwise the record stands and blocks re-casts for `warp_retry_s` —
        a cast that did not move the player is treated as still-on-cooldown
        rather than proof we should click harder.
        """
        if self._warp_attempt is None:
            return
        _, origin = self._warp_attempt
        if _chebyshev(position, origin) >= self.config.warp_verify_move:
            self._warp_attempt = None

    def _column_potion(
        self, carried: CarriedItems, column: int, type_check: Callable[[CarriedItem], bool]
    ) -> bool:
        """Does this belt column hold a potion of the right type?

        Both halves matter: the column can be empty, and — because the belt
        routes by column — a column can in principle hold something other
        than what the layout says. Drinking key N swallows whatever sits at
        the bottom of column N, so the ladder checks what is actually there.
        """
        return any(
            i.belt_column == column and type_check(i) for i in carried.belt
        )

    # -- the rungs -------------------------------------------------------------

    def _try_warp(
        self,
        player_hp: int,
        player_max_hp: int,
        player_mana: int,
        position: tuple[int, int],
        hostiles: list[tuple[int, int]],
        now: float,
        reason: str,
    ) -> ReflexDecision | None:
        """Rung 4's action, guarded. None when the warp is not available —
        guards failing, an unverified attempt outstanding, or no walkable
        retreat ground — so the caller falls through to the rungs below."""
        cfg = self.config
        if player_mana < cfg.warp_min_mana:
            return None
        cost = max(cfg.warp_cost_pct / 100.0 * player_max_hp, cfg.warp_cost_floor)
        if player_hp <= 2 * cost:
            # R47.3's guardrail (never cast at <= 12 hp) is implied: hp must
            # clear twice the cost, and the cost is at least the floor.
            return None
        if (
            self._warp_attempt is not None
            and now - self._warp_attempt[0] < cfg.warp_retry_s
        ):
            return None  # an attempt is pending its position-verify
        target = retreat_point(
            position, hostiles, cfg.retreat_distance, self._is_walkable
        )
        if target is None:
            return None

        def commit() -> None:
            self._warp_attempt = (now, position)
            # Forget the damage history. Blood warp COSTS 12% of max hp, and
            # that self-inflicted drop otherwise reads as more incoming burst
            # damage on the next tick — so the escape re-triggers its own
            # trigger and the character pays twice (found in the P5 sim: two
            # warps back to back, 240 hp for one escape). The burst rung is
            # about damage being DONE to us, and after an escape the situation
            # has changed anyway, so the window starts fresh here.
            #
            # Both of these are deferred to the SEND for the same reason, and
            # this rung is where it matters most: a warp that was never cast
            # would otherwise block re-casts for `warp_retry_s` while the
            # character stands in the pack it was trying to escape, and would
            # throw away the burst history that justified the escape.
            self._hp_samples.clear()

        return ReflexDecision(
            rung="blood_warp",
            action=CastAtPoint(cfg.warp_skill_id, target),
            reason=reason,
            commit=commit,
        )

    def _armor_needs_recast(self, was_hit: bool) -> tuple[bool, str]:
        ratio = self._armor_ratio()
        if ratio is None:
            # The R47-approved fallback: the stat is unreadable, so recast
            # whenever the player was hit since the last look.
            return was_hit, "armor stat unreadable; player was hit"
        pct = ratio * 100.0
        if pct < self.config.armor_recast_below_pct:
            return True, f"armor absorb {pct:.0f}% < {self.config.armor_recast_below_pct:.0f}%"
        return False, ""

    def _armor_down_and_cooling(self, now: float) -> bool:
        """Rung 7's armor half: absorb reads zero AND a recent recast attempt
        has not restored it (i.e. the recast is presumed on cooldown)."""
        ratio = self._armor_ratio()
        if ratio is None or ratio > 0:
            return False
        return (
            self._armor_attempt is not None
            and now - self._armor_attempt < self.config.armor_retry_s
        )

    # -- the ladder ------------------------------------------------------------

    def evaluate(self, snap: GameSnapshot) -> ReflexDecision | None:
        """First firing rung, or None when offense may proceed this tick."""
        cfg = self.config
        player = snap.player
        if player is None or player.max_hp <= 0:
            return None
        now = self._clock()
        was_hit = self._record_vitals(now, player.hp, player.position)
        self._resolve_warp_attempt(player.position)
        hp_pct = 100.0 * player.hp / player.max_hp
        in_town = snap.in_town

        if not in_town:
            hostiles = [m.position for m in snap.live_monsters]
            carried = self._carried()

            # Rung 3 — rejuv. No cooldown: a rejuv fills instantly, so a
            # re-fire next tick means it genuinely did not help enough.
            if hp_pct < cfg.rejuv_below_pct:
                if self._column_potion(
                    carried, cfg.rejuv_column, lambda i: i.is_rejuv_potion
                ):
                    return ReflexDecision(
                        rung="rejuv",
                        action=DrinkPotion(cfg.rejuv_column, "rejuv"),
                        reason=f"hp {hp_pct:.0f}% < {cfg.rejuv_below_pct:.0f}%",
                    )
                if (
                    _within(hostiles, player.position, cfg.escalate_radius)
                    >= cfg.escalate_hostiles
                ):
                    # The R49 escalation: no rejuv left and surrounded. Warp
                    # on ITS guards but not its trigger.
                    warp = self._try_warp(
                        player.hp, player.max_hp, player.mana, player.position,
                        hostiles, now,
                        reason=(
                            f"hp {hp_pct:.0f}% with an empty rejuv column and "
                            f">={cfg.escalate_hostiles} hostiles within "
                            f"{cfg.escalate_radius} — escalated from rung 3"
                        ),
                    )
                    if warp is not None:
                        return warp

            # Rung 4 — blood warp on its own trigger.
            packed = (
                _within(hostiles, player.position, cfg.warp_radius)
                >= cfg.warp_hostiles
                and hp_pct < cfg.warp_hp_pct
            )
            lost = self._hp_lost_in_window(player.hp)
            bursted = lost > cfg.warp_loss_pct / 100.0 * player.max_hp
            if packed or bursted:
                warp = self._try_warp(
                    player.hp, player.max_hp, player.mana, player.position,
                    hostiles, now,
                    reason=(
                        f"packed: >={cfg.warp_hostiles} within {cfg.warp_radius}, "
                        f"hp {hp_pct:.0f}%"
                        if packed
                        else f"lost {lost} hp within {cfg.warp_loss_window_s:.0f}s"
                    ),
                )
                if warp is not None:
                    return warp

            # Rung 5 — healing potion, cooldown-gated, backup column when
            # the primary is empty (R53 layout: two healing columns).
            if hp_pct < cfg.heal_below_pct and (
                now - self._last_drink.get("healing", -math.inf)
                >= cfg.heal_cooldown_s
            ):
                for column in cfg.heal_columns:
                    if self._column_potion(
                        carried, column, lambda i: i.is_healing_potion
                    ):
                        return ReflexDecision(
                            rung="heal",
                            action=DrinkPotion(column, "healing"),
                            reason=f"hp {hp_pct:.0f}% < {cfg.heal_below_pct:.0f}%",
                            commit=lambda: self._last_drink.__setitem__(
                                "healing", now
                            ),
                        )

            # Rung 6 — mana potion, 15 s cooldown (the R49 amendment).
            if player.max_mana > 0:
                mana_pct = 100.0 * player.mana / player.max_mana
                if mana_pct < cfg.mana_below_pct and (
                    now - self._last_drink.get("mana", -math.inf)
                    >= cfg.mana_cooldown_s
                ):
                    if self._column_potion(
                        carried, cfg.mana_column, lambda i: i.is_mana_potion
                    ):
                        return ReflexDecision(
                            rung="mana",
                            action=DrinkPotion(cfg.mana_column, "mana"),
                            reason=f"mana {mana_pct:.0f}% < {cfg.mana_below_pct:.0f}%",
                            commit=lambda: self._last_drink.__setitem__("mana", now),
                        )

            # Rung 6.5 — reposition (R176 Q3): bleeding while standing
            # still. Below the potion and warp rungs on purpose — an
            # emergency gets an emergency's answer first — and paced
            # rather than cooled down: the timestamp records on ATTEMPT,
            # because a step that keeps failing to send must not re-fire
            # at tick rate (the stage B run 9 lesson).
            if (
                self._bleeding_while_still(
                    now, player.hp, player.max_hp, player.position
                )
                and (
                    self._reposition_attempt is None
                    or now - self._reposition_attempt
                    >= cfg.reposition_cooldown_s
                )
            ):
                target = retreat_point(
                    player.position, hostiles, cfg.reposition_step,
                    self._is_walkable,
                )
                if target is not None:
                    return ReflexDecision(
                        rung="reposition",
                        action=MoveTo(target),
                        reason=(
                            "losing health while standing still "
                            f"(>={cfg.reposition_loss_pct:.0f}% max hp in "
                            f"{cfg.reposition_window_s:.1f}s, moved "
                            f"<{cfg.reposition_still_subtiles}) — stand "
                            "somewhere else"
                        ),
                        on_attempt=lambda: setattr(
                            self, "_reposition_attempt", now
                        ),
                    )

            # Rung 7 — disengage: armor down, recast pending, hp sliding.
            if (
                hostiles
                and hp_pct < cfg.disengage_hp_pct
                and self._armor_down_and_cooling(now)
            ):
                target = retreat_point(
                    player.position, hostiles, cfg.retreat_distance,
                    self._is_walkable,
                )
                if target is not None:
                    return ReflexDecision(
                        rung="disengage",
                        action=MoveTo(target),
                        reason=(
                            f"bone armor down and cooling, hp {hp_pct:.0f}% < "
                            f"{cfg.disengage_hp_pct:.0f}%"
                        ),
                    )

        # Rung 8 — upkeep. The armor half runs in town too (castable there,
        # proven in P2's live drill; arriving armored is strictly better);
        # the combat-module half never does (desecrate/revive are not
        # castable in town, R47.4).
        needs, why = self._armor_needs_recast(was_hit)
        if (
            needs
            and (cfg.armor_in_town or not in_town)
            and (
                self._armor_attempt is None
                or now - self._armor_attempt >= cfg.armor_retry_s
            )
        ):
            return ReflexDecision(
                rung="upkeep",
                action=CastSelf(cfg.armor_skill_id),
                reason=why,
                # PACING, not a cooldown: recorded even when the send
                # fails, or a switch that never takes retries at tick rate
                # and starves the whole run (stage B run 9).
                on_attempt=lambda: setattr(self, "_armor_attempt", now),
            )
        if not in_town and self._combat_upkeep is not None:
            action = self._combat_upkeep(snap)
            if action is not None:
                return ReflexDecision(
                    rung="upkeep", action=action, reason="combat-module upkeep"
                )
        return None
