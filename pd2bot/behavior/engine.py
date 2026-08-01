"""The ticked behavior engine: safety first, reflexes second, the run third.

One tick is one decision:

    snapshot -> SafetyMonitor.tick() -> reflex ladder -> current step

The monitor raises (`ChickenExit`/`DeathHalt`) straight through — the engine
neither catches nor wraps them, so the cycle's handling and the death
latch's permanence are exactly what M4 built and live-verified. A firing
reflex rung consumes the tick: offense and run progress simply do not happen
while survival has something to say. Only a quiet ladder lets the current
run step act.

The engine knows nothing about necromancers or Cold Plains: states come
from the run loader, class specifics from the class config, and every
side effect goes through the injected executor. All timing is injectable
(the M3/M4 pattern), so the whole loop runs against scripted fakes.

**The never-idle invariant** (R47.9, user danger assessment: any enemy can
kill an idle character). If, outside town, nothing has been sent and no
progress has been made for `idle_bail_s`, the engine raises `IdleBail` —
typed as a `ChickenExit` subclass so the existing cycle leaves the game
exactly as it does for a vitals chicken, with no change to cycle.py (whose
internals are out of P4's scope). The separate not-a-vitals-problem
counting lives in runner.py at the callback boundary.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pd2bot.behavior.actions import ActionExecutor
from pd2bot.behavior.reflex import ReflexLadder
from pd2bot.input import InputRefused
from pd2bot.safety import ChickenExit
from pd2bot.skills import SkillSwitchFailed
from pd2bot.snapshot import GameSnapshot

# Two different ways a send can fail to land, treated identically on
# purpose. `InputRefused` is the guard saying "not now"; `SkillSwitchFailed`
# is the client having dropped a hotkey press, which the user watched happen
# during an area-change stutter in stage B run 5. Both mean the same thing
# to the engine — nothing reached the game, so decide again next tick —
# and both must keep the SAFETY they encode: no cast on an unverified
# skill, and no bookkeeping for an action that never happened.
#
# Retrying inside the tick was the alternative and it is worse: the ladder
# is not consulted while a tick blocks, so a patient retry buys reliability
# with exactly the seconds the survival rungs need.
SEND_DID_NOT_LAND = (InputRefused, SkillSwitchFailed)


class BehaviorError(RuntimeError):
    """The engine cannot continue; the message says why."""


class InputRefusedHalt(BehaviorError):
    """Every send refused for `refusal_limit` ticks running.

    A single refusal is routine — the guards raise it by design, and M4's
    cycle already treats focus loss as recoverable — so the engine absorbs
    it and re-decides next tick. A LONG run of them is different: the
    character is standing in Hell while nothing the bot decides reaches the
    game, which is the same danger the never-idle invariant exists for, and
    it will not fix itself by ticking harder.
    """


class IdleBail(ChickenExit):
    """Outside town with nothing sent and no progress for too long.

    A `ChickenExit` subclass ON PURPOSE: the cycle's existing handler is
    what makes the bot leave the game, and leaving is the R47.9-mandated
    response to standing around. It is NOT a vitals problem though — an
    idle loop is a bug — so runner.py counts these separately and halts
    loudly on repetition rather than letting them hide among chickens.
    """


class _Monitor(Protocol):
    """SafetyMonitor's shape; tests substitute scripted ones."""

    def tick(self) -> None: ...


@dataclass(frozen=True)
class StepOutcome:
    """What one tick of a step reports back.

    `acted` feeds the never-idle bookkeeping: a step that sent input (or
    made verifiable progress) this tick says so, and a step that neither
    acts nor finishes for `idle_bail_s` outside town is exactly what the
    invariant exists to catch.

    `waiting` is the step saying "I am standing still ON PURPOSE" — the
    clearance settle timer, the restrike interval, the wait for revives to
    tank. It counts as progress for the watchdog. The invariant is about the
    bot being STUCK, not about it being still, and the two were previously
    indistinguishable: several deliberate waits are configured in different
    files by different owners (`clear_settle_s`, `restrike_s`,
    `wait_for_revives_s`) and the watchdog knew about none of them, so
    lengthening any one of them past `idle_bail_s` made runs abandon
    themselves with a message blaming an idle loop (review 003).
    """

    done: bool
    acted: bool = False
    note: str = ""
    waiting: bool = False


class StepState(Protocol):
    """One run step being executed. Small object, explicit lifecycle:
    `step` is called once per tick until it reports done."""

    name: str

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome: ...


@dataclass
class EngineContext:
    """What every step (and the combat module) gets besides the snapshot.

    `notes` is the run's shared blackboard: the waypoint step records the
    arrival position under "arrival", `clear_radius` reads it back — the
    declarative run's way of passing data forward without the steps knowing
    each other.

    `snapshot` re-reads the world mid-tick. Almost nothing should want it —
    the whole design is "decide from the tick's snapshot" — but a blocking
    step invalidates its own: the waypoint step's snapshot was taken in
    town, before a trip that moved the character to another act.
    """

    executor: ActionExecutor
    combat: object | None = None  # the class CombatModule, when one is wired
    notes: dict[str, object] = field(default_factory=dict)
    snapshot: Callable[[], GameSnapshot] | None = None


@dataclass(frozen=True)
class EngineConfig:
    tick_interval_s: float = 0.2  # ~5 decisions/s against a 25 fps sim
    idle_bail_s: float = 10.0  # R47.9 default
    # Consecutive all-refused ticks before the engine gives up on the game.
    # ~5 ticks/s, so 50 is about 10 s of the game refusing everything —
    # deliberately the same order as `idle_bail_s`, because it is the same
    # danger wearing a different hat.
    refusal_limit: int = 50


@dataclass
class EngineReport:
    ticks: int = 0
    reflex_fires: list[str] = field(default_factory=list)
    steps_completed: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    refusals: int = 0  # lifetime, for the post-run report

    def summary(self) -> str:
        return (
            f"ticks: {self.ticks}, reflex fires: {len(self.reflex_fires)}, "
            f"steps done: {', '.join(self.steps_completed) or 'none'}"
        )


class BehaviorEngine:
    """Drives one run inside one game. Built fresh per game by the runner."""

    def __init__(
        self,
        *,
        snapshot: Callable[[], GameSnapshot],
        monitor: _Monitor,
        states: Sequence[StepState],
        executor: ActionExecutor,
        ladder: ReflexLadder | None = None,
        combat: object | None = None,
        config: EngineConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not states:
            raise BehaviorError("a run with no steps cannot do anything")
        self._snapshot = snapshot
        self._monitor = monitor
        self._states = list(states)
        self._executor = executor
        self._ladder = ladder
        self.config = config if config is not None else EngineConfig()
        self._clock = clock
        self._sleep = sleep
        self.ctx = EngineContext(
            executor=executor, combat=combat, snapshot=snapshot
        )
        self.report = EngineReport()
        self._index = 0
        self._last_activity = self._clock()
        self._last_position: tuple[int, int] | None = None
        self._refusal_streak = 0

    @property
    def complete(self) -> bool:
        return self._index >= len(self._states)

    @property
    def step_names(self) -> list[str]:
        """The run this engine will execute, in order. For the operator."""
        return [state.name for state in self._states]

    # -- the tick ---------------------------------------------------------------

    def _mark_activity(self, now: float) -> None:
        self._last_activity = now

    def _check_idle(self, snap: GameSnapshot, now: float) -> None:
        if not snap.in_game or snap.in_town:
            # The invariant is an out-of-town rule (town is safe by
            # definition and town steps legitimately wait on walks); the
            # clock restarts at the town/field boundary.
            self._last_activity = now
            return
        idle_for = now - self._last_activity
        if idle_for > self.config.idle_bail_s:
            raise IdleBail(
                f"no action sent and no progress for {idle_for:.1f}s outside "
                f"town (limit {self.config.idle_bail_s:.0f}s) — leaving the "
                "game rather than standing in Hell doing nothing (R47.9)"
            )

    def tick(self) -> bool:
        """One decision. Returns True when the run is complete.

        Monitor exceptions (ChickenExit, DeathHalt) and IdleBail propagate
        to the caller untouched — the cycle owns what they mean.
        """
        snap = self._snapshot()
        self._monitor.tick()
        now = self._clock()
        self.report.ticks += 1

        # Movement counts as progress: a walk in flight sends nothing new
        # per tick, and bailing out mid-journey would make every long walk
        # an "idle loop".
        if snap.player is not None and snap.player.position != self._last_position:
            self._last_position = snap.player.position
            self._mark_activity(now)

        decision = self._ladder.evaluate(snap) if self._ladder is not None else None
        if decision is not None:
            # Survival owns the tick; the run step is skipped outright.
            self.report.reflex_fires.append(decision.rung)
            self.report.log.append(
                f"reflex {decision.rung}: {decision.reason}"
            )
            try:
                self._executor.execute(decision.action)
            except SEND_DID_NOT_LAND as exc:
                # Do NOT commit the rung's bookkeeping and do NOT mark
                # activity: nothing happened, so the next tick must be free
                # to decide the very same thing again.
                self._note_refusal(f"reflex {decision.rung}", exc)
                self._check_idle(snap, now)
                return self.complete
            decision.commit_sent()
            self._refusal_streak = 0
            self._mark_activity(self._clock())
            return self.complete

        if not self.complete:
            state = self._states[self._index]
            try:
                outcome = state.step(snap, self.ctx)
            except SEND_DID_NOT_LAND as exc:
                # Steps send through the same executor, so they refuse the
                # same way. A step is free to have done part of its work
                # before the refusal; it is written to be re-entered, which
                # is what makes swallowing this safe.
                self._note_refusal(f"step {state.name}", exc)
                self._check_idle(snap, now)
                return self.complete
            if outcome.acted:
                self._refusal_streak = 0
                self._mark_activity(self._clock())
            if outcome.waiting:
                # A declared wait is progress, not idleness (review 003).
                self._mark_activity(self._clock())
            if outcome.done:
                self._index += 1
                self.report.steps_completed.append(state.name)
                self.report.log.append(
                    f"step {state.name} done"
                    + (f": {outcome.note}" if outcome.note else "")
                )
                self._mark_activity(self._clock())

        self._check_idle(snap, now)
        return self.complete

    def _note_refusal(self, where: str, exc: Exception) -> None:
        """Absorb one refused send, and escalate only on a long streak."""
        self.report.refusals += 1
        self._refusal_streak += 1
        self.report.log.append(
            f"{where}: send did not land — {type(exc).__name__}: {exc}"
        )
        if self._refusal_streak >= self.config.refusal_limit:
            raise InputRefusedHalt(
                f"{self._refusal_streak} sends failed to land in a row "
                f"(last at {where}: {type(exc).__name__}: {exc}) — the "
                "bot is deciding but nothing is reaching the game"
            ) from exc

    def run(self) -> EngineReport:
        """Tick until the run completes. Raises are the caller's to route:
        ChickenExit/IdleBail mean leave, DeathHalt means stop forever."""
        while not self.tick():
            self._sleep(self.config.tick_interval_s)
        return self.report
