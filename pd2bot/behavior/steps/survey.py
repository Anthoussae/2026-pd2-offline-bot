"""SurveyStep: operator-steered room recording into the atlas.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pd2bot.behavior.actions import (
    MoveTo,
)
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.steps.pickup import _PickupMixin
from pd2bot.behavior.steps.util import (
    _chebyshev,
    _route_leg,
)
from pd2bot.perception.snapshot import GameSnapshot


@dataclass
class SurveyStep(_PickupMixin):
    """Walk an area until its reachable ground is all in the atlas.

    The map store remembers every room ever loaded and every walk records
    as a side effect (M3); route planning already refuses unknown ground.
    This step supplies the missing piece: it keeps walking to the nearest
    *frontier* — recorded walkable ground with unrecorded ground just
    beyond (`pd2bot/survey.py`) — until none remains inside the area's
    bounds. Single-player maps are fixed per character+difficulty, so a
    finished area is finished forever (R175: "permanently reusable").

    Not a clearance (R176 Q1): hostiles get fought only inside
    `survey_engage_radius`; everything further is somebody the survey
    walks politely around. The ladder and chicken stand above as always.

    The frontier list is recomputed by the wiring's closure as the atlas
    grows; written-off targets are remembered by exact position, which is
    stable because the closure caches per room-count — the list only
    changes when new ground was actually recorded, at which point stale
    write-offs mostly stop being frontier at all.
    """

    name: str = "survey"
    _done_targets: set[tuple[int, int]] = field(default_factory=set)
    _route_denied: dict[tuple[int, int], int] = field(default_factory=dict)
    _written_off: int = 0
    _legs: int = 0
    _current: tuple[int, int] | None = None
    _closest: int | None = None
    _attempts: int = 0
    # Monsters a failed walk proved unreachable, and where they stood —
    # the clearance's rule (expiry on movement) in miniature, so a walled
    # monster cannot pin the survey the way one pinned the clearance.
    _unreachable: dict[int, tuple[int, int]] = field(default_factory=dict)
    # Per-monster fight patience: (best distance, last hp, stale ticks).
    # The first Cold Plains survey (2026-08-02) livelocked without this:
    # a monster the bot could walk TOWARD but never reach — every dash
    # succeeded, none arrived — kept winning the tick for 14 minutes, and
    # only failed WALKS were being written off. Progress here is distance
    # closing OR the monster's hp falling: a poison fight legitimately
    # pauses (restrike cooldown, revives building) while the target dies,
    # and counting those pauses as stalling would abandon kills mid-way.
    _fight_progress: dict[int, tuple[int, int, int]] = field(
        default_factory=dict
    )

    def _fightable(self, m) -> bool:
        where = self._unreachable.get(m.unit_id)
        if where is None:
            return True
        if _chebyshev(m.position, where) <= self.services.unreachable_forget:
            return False
        del self._unreachable[m.unit_id]
        self._fight_progress.pop(m.unit_id, None)
        return True

    def _fight_stalled(self, m, origin: tuple[int, int]) -> bool:
        """Book one fighting tick against `m`; True when patience is spent.

        Called once per tick for the monster gating the survey. Distance
        closing or hp falling resets the count — only ticks in which the
        fight moved neither needle count toward giving up.
        """
        distance = _chebyshev(m.position, origin)
        best, last_hp, stale = self._fight_progress.get(
            m.unit_id, (distance + 1, m.hp + 1, 0)
        )
        if distance < best or m.hp < last_hp:
            self._fight_progress[m.unit_id] = (
                min(distance, best), min(m.hp, last_hp), 0
            )
            return False
        stale += 1
        self._fight_progress[m.unit_id] = (best, last_hp, stale)
        if stale < self.services.survey_fight_patience:
            return False
        self._unreachable[m.unit_id] = m.position
        self.services.log(
            f"survey: {stale} fighting ticks moved neither the distance to "
            f"monster {m.unit_id} nor its hp — writing it off at "
            f"{m.position} and surveying on (another look if it moves)"
        )
        return True

    def _finish(self) -> StepOutcome:
        cov = (
            self.services.survey_coverage()
            if self.services.survey_coverage is not None
            else "coverage unknown"
        )
        written = (
            f", {self._written_off} frontier point(s) written off unreachable"
            if self._written_off
            else ""
        )
        note = f"survey complete: {cov}{written}"
        self.services.log(note)
        return StepOutcome(done=True, acted=True, note=note)

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        if self.services.survey_targets is None:
            return StepOutcome(
                done=True,
                note="no survey service wired; nothing this step can do",
            )
        if self.maybe_cleanse(snap, ctx):
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        if snap.player is None:
            return StepOutcome(done=False, waiting=True)
        origin = snap.player.position

        # Fighting wins the tick, but only up close (R176 Q1) — and only
        # while the fight is going somewhere. The first Cold Plains survey
        # spent 14 minutes here on a monster every dash could walk toward
        # and never reach: each walk SUCCEEDED, so the failed-walk
        # write-off below never fired, and the survey starved.
        # `_fight_stalled` is the other half, the same split the clearance
        # learned (failed walks AND walks that succeed without arriving).
        near = [
            m for m in snap.live_monsters
            if _chebyshev(m.position, origin) <= self.services.survey_engage_radius
            and self._fightable(m)
        ]
        if near:
            gating = min(near, key=lambda m: _chebyshev(m.position, origin))
            if self._fight_stalled(gating, origin):
                pass  # written off: fall through and survey this tick
            else:
                action = self.services.combat.engage(snap, ctx)
                if action is not None:
                    if not self.send(ctx, action):
                        blamed = getattr(action, "toward", None)
                        target = next(
                            (m for m in near if m.unit_id == blamed), None
                        )
                        if target is not None:
                            self._unreachable[target.unit_id] = target.position
                            self.services.log(
                                f"survey: monster {target.unit_id} at "
                                f"{target.position} is unreachable; walking on "
                                "(it gets another look if it moves)"
                            )
                    return StepOutcome(done=False, acted=True, note="fighting")
                # engage had nothing offensive to do this tick (poison
                # settling, revives building): surveying on beats standing.

        if self._legs >= self.services.survey_max_legs:
            self.services.alert(
                f"survey stopped at the {self._legs}-leg budget. That is a "
                "bug signal, not a big area — a healthy survey finishes "
                "well under it."
            )
            return self._finish()

        targets = [
            t for t in self.services.survey_targets()
            if t not in self._done_targets
        ]
        if not targets:
            return self._finish()
        # STICKY target choice: keep walking to the one we chose until it
        # is reached, written off, or no longer frontier. Re-picking the
        # nearest every tick let two near-equidistant frontiers trade
        # "nearest" as the bot moved — each swap reset the progress
        # counter, so the ping-pong could neither finish nor give up
        # (the other half of the first Cold Plains survey's stall).
        if self._current is not None and self._current in targets:
            target = self._current
        else:
            target = min(targets, key=lambda t: _chebyshev(t, origin))
        distance = _chebyshev(target, origin)

        if distance <= self.services.patrol_reach:
            # Standing here has loaded the rooms beyond; the recorder has
            # them. The frontier list shrinks on its own recompute.
            self._done_targets.add(target)
            self._current = None
            self.services.log(f"survey: reached frontier {target}")
            return StepOutcome(
                done=False, acted=True, note=f"survey reached {target}"
            )

        if target != self._current:
            self._current, self._closest, self._attempts = target, None, 0
        if (
            self._closest is None
            or distance <= self._closest - self.services.patrol_progress_margin
        ):
            # The same margin rule as the patrol (R189 b): subtile wobble
            # is not progress.
            self._closest, self._attempts = distance, 0
        else:
            self._attempts += 1
        if self._attempts >= self.services.patrol_attempts:
            self.services.log(
                f"survey: giving up on frontier {target} after "
                f"{self._attempts} legs that got no closer (still "
                f"{distance} away)"
            )
            self._done_targets.add(target)
            self._written_off += 1
            self._current = None
            return StepOutcome(
                done=False, acted=True, note=f"survey gave up on {target}"
            )

        leg = _route_leg(self.services, origin, target)
        if leg is None:
            # No route on the map (R181) — confirmed by a second ask over
            # a fresh grid before it costs the point (T55 run 1's torn
            # grid read; the patrol carries the same two-strike rule).
            strikes = self._route_denied.get(target, 0) + 1
            self._route_denied[target] = strikes
            if strikes < 2:
                return StepOutcome(
                    done=False, acted=True,
                    note=f"no route to {target} — asking again",
                )
            self.services.log(f"survey: no route to frontier {target}")
            self._done_targets.add(target)
            self._written_off += 1
            self._current = None
            return StepOutcome(
                done=False, acted=True, note=f"survey wrote off {target} (no route)"
            )
        self._route_denied.pop(target, None)
        self._legs += 1
        if not self.send(ctx, MoveTo(leg)):
            # Unknown/blocked ground on the way: this frontier is not
            # approachable from here. Costs the point, never the run.
            self._done_targets.add(target)
            self._written_off += 1
            self._current = None
            return StepOutcome(
                done=False, acted=True, note=f"survey skipped {target}"
            )
        return StepOutcome(done=False, acted=True, note=f"survey leg to {leg}")


# -- the registry ---------------------------------------------------------------



