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

A step may declare a wait (`StepOutcome.waiting`) and the watchdog believes
it — but only up to `wait_bail_s`. That bound is the policy review 001
asked for: a declared wait is a claim that something will EXPIRE, and one
that outlives every timer in the bot is a hang with the alarm switched off.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pd2bot import offsets
from pd2bot.behavior.actions import ActionExecutor
from pd2bot.behavior.reflex import ReflexLadder
from pd2bot.input import InputRefused
from pd2bot.narrate import noop as narrate_noop
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

    `is_vitals = False` completes that separation (R115): until it, the
    cycle's vitals backstop counted these too, so one real chicken
    followed by one idle bail halted with a message telling the operator
    to heal a character whose actual problem was a hang.
    """

    is_vitals = False


class StopRequested(ChickenExit):
    """An OUTSIDE stop order: the user typed abort, or a drill's cancel
    file appeared. Checked at the very top of every tick, before the
    monitor and the ladder — an abort is a command, not a condition.

    Rides `ChickenExit` the way `IdleBail` does, so the unmodified M4
    cycle already does the right thing: stop sending, leave the game
    cleanly, hand the character back. It exists because T54 run 3 had no
    field-side stop at all — `should_stop` reached only the town layer's
    waits, so the user's in-chat abort went unheard until 50 refused
    sends piled into an `InputRefusedHalt` (user feedback, 2026-08-02:
    abort must take effect immediately, wherever the run is).
    """

    is_vitals = False


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

    It is a claim with a deadline, not a blanket exemption: the engine
    holds an unbroken run of declared waits to `wait_bail_s`, because the
    one thing a wait must not be able to say is "forever" (review 001).
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
    idle_bail_s: float = 10.0  # R47.9 default: with something hunting us
    # The same watchdog, with nothing nearby to punish standing still.
    #
    # The invariant's stated reason is danger — "any enemy can kill an
    # idle character" — and with no enemy in sight that reason does not
    # apply. The user's own read (R115): *technically, idle bailing is
    # only necessary if there are enemies nearby; however, there is
    # something to be said for always idle bailing regardless, as we
    # don't want the bot to get stuck for any reason.*
    #
    # Both, then, which is why this is a longer deadline and not an
    # exemption. An idle character in an empty field is not in danger,
    # but it is still a bot that has stopped working, and a stuck bot
    # must always surface. The message says which case fired, so the
    # difference reaches whoever reads the log.
    idle_bail_quiet_s: float = 30.0
    # What counts as "something nearby". Deliberately the same order as
    # the necro's `engage_radius` (40): the engine cannot see a class
    # config, and a monster further away than we would fight is not the
    # danger this invariant is about. Perception caps it at 80 regardless.
    idle_danger_radius: int = 40
    # Consecutive all-refused ticks before the engine gives up on the game.
    # ~5 ticks/s, so 50 is about 10 s of the game refusing everything —
    # deliberately the same order as `idle_bail_s`, because it is the same
    # danger wearing a different hat.
    refusal_limit: int = 50
    # The longest a step may keep saying "I am waiting on purpose".
    #
    # `waiting` suppresses the idle watchdog, and it was right to add it
    # (review 003: the watchdog fired during deliberate settles nobody had
    # told it about). What it also did was remove the alarm from the one
    # path that later grew a genuine hang — a clearance whose monsters had
    # drifted out of the combat module's reach reported a wait FOREVER,
    # and nothing was left to notice (review 001).
    #
    # So the policy, stated: a declared wait is a claim that something will
    # expire. This is the deadline that claim is held to — 6x the longest
    # wait configured anywhere (`clear_settle_s`, 5 s) and 3x `idle_bail_s`,
    # so it can only be reached by a wait that is not a wait at all. Past
    # it, the step is hung and gets treated as an idle loop, which is what
    # it is.
    wait_bail_s: float = 30.0
    # The Enter/ESC kill switch's correlation window (R189): an esc menu
    # appearing within this long of the BOT's own ESC send is the bot's
    # (the one real race — an ESC landing just after a panel closed opens
    # the menu instead); beyond it, the menu is the operator's.
    operator_escape_grace_s: float = 1.5


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
        narrate: Callable[[str], None] = narrate_noop,
        should_stop: Callable[[], bool] | None = None,
        bot_escape_at: Callable[[], float | None] | None = None,
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
        # The outside stop order (drill abort, operator request), polled
        # every tick. None = no channel wired.
        self._should_stop = should_stop
        # When the bot itself last sent an ESC (the wiring's tracked
        # clear_panels closure) — the kill switch's correlation input.
        # None = no kill switch in this environment (sims, drills that
        # build the engine bare).
        self._bot_escape_at = bot_escape_at
        # The narrative channel (R179): step transitions with durations —
        # the engine is the only thing that knows when a step began.
        self._narrate = narrate
        self._step_started = self._clock()
        # Per-rung fire counts, narrated at every 25th fire (R185 C): run
        # 4's clearance spent ~10 silent minutes on combat-module upkeep,
        # and a wait that big must explain itself. Per-fire lines would
        # break the coarseness contract; every 25th keeps the story short
        # and still surfaces any churn within ~a minute of it starting.
        self._rung_fires: dict[str, int] = {}
        self._last_activity = self._clock()
        self._last_position: tuple[int, int] | None = None
        self._refusal_streak = 0
        # When the CURRENT unbroken run of declared waits began. Cleared by
        # progress (a send that landed, a step that acted or finished), not
        # by movement: a character being shoved around by monsters while a
        # step waits forever is the hang, not the cure.
        self._waiting_since: float | None = None

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

    def _note_wait(self, snap: GameSnapshot, now: float, where: str) -> None:
        """One tick of a step standing still on purpose — and the deadline.

        The wait is believed (it keeps the idle watchdog quiet) right up to
        `wait_bail_s`, and then it is not. Town is exempt for the same
        reason the idle check exempts it: town steps block on walks, and
        town is safe by definition.
        """
        if not snap.in_game or snap.in_town:
            self._waiting_since = None
            return
        if self._waiting_since is None:
            self._waiting_since = now
            return
        waited = now - self._waiting_since
        if waited > self.config.wait_bail_s:
            raise IdleBail(
                f"step {where!r} has declared a deliberate wait for "
                f"{waited:.1f}s (limit {self.config.wait_bail_s:.0f}s) — a "
                "declared wait is supposed to be a timer that expires, so "
                "one this long is a hang wearing a wait's clothes; leaving "
                "the game rather than standing in Hell (R47.9, review 001)"
                f"\n{self._context(snap)}"
            )

    def _operator_took_the_controls(self, snap: GameSnapshot) -> bool:
        """The Enter/ESC kill switch (R189, the user's rule): out of
        town, the esc menu and the chat console can only be opened by a
        HUMAN — no world misclick opens either (misclicks open NPC and
        waypoint dialogs, different panels, still auto-recovered) — with
        one exception: the bot's own field-side ESC (`clear_panels`)
        landing just after a panel closed opens the menu instead. That
        race is correlated away by timestamp; past the grace window, the
        panel is the operator's, and operator input means the operator
        wants the character. Chat sent by the agent's other processes
        (Partyline) cannot collide: the elevated bridge runs one command
        at a time, so its chat waits until the run's command exits. Town
        is excluded — the chores legitimately press both keys constantly.
        """
        if snap.ui is None or not snap.in_game or snap.in_town:
            return False
        if not (
            snap.ui.is_open(offsets.UI_ESCMENU_MAIN)
            or snap.ui.is_open(offsets.UI_CHAT_CONSOLE)
        ):
            return False
        if self._bot_escape_at is not None:
            stamp = self._bot_escape_at()
            if (
                stamp is not None
                and self._clock() - stamp < self.config.operator_escape_grace_s
            ):
                return False
        return True

    def _check_idle(self, snap: GameSnapshot, now: float) -> None:
        if not snap.in_game or snap.in_town:
            # The invariant is an out-of-town rule (town is safe by
            # definition and town steps legitimately wait on walks); the
            # clock restarts at the town/field boundary.
            self._last_activity = now
            return
        idle_for = now - self._last_activity
        hostiles = self._hostiles_near(snap)
        limit = (
            self.config.idle_bail_s if hostiles
            else self.config.idle_bail_quiet_s
        )
        if idle_for > limit:
            why = (
                f"{len(hostiles)} hostile(s) within "
                f"{self.config.idle_danger_radius} — this is the danger the "
                "invariant is about (R47.9)"
                if hostiles
                else "nothing hostile nearby, so this is not danger — but a "
                "bot that has stopped working is still stuck, and being "
                "stuck must always surface (R115)"
            )
            raise IdleBail(
                f"no action sent and no progress for {idle_for:.1f}s outside "
                f"town (limit {limit:.0f}s): {why}\n{self._context(snap)}"
            )

    def _hostiles_near(self, snap: GameSnapshot) -> list:
        if snap.player is None:
            return []
        here = snap.player.position
        return [
            m
            for m in snap.live_monsters
            if max(abs(m.position[0] - here[0]), abs(m.position[1] - here[1]))
            <= self.config.idle_danger_radius
        ]

    def _context(self, snap: GameSnapshot) -> str:
        """Everything worth knowing at the moment the engine gives up.

        The user's request (R115): *take a careful log of everything
        before idle bailing.* An idle bail is by definition a case nobody
        predicted — if it had been predicted it would have been fixed —
        so the one chance to understand it is the state it happened in.
        The same discipline as `skills._failure_context`, and for the same
        reason: three live runs were spent re-reaching a failure that
        could have explained itself the first time.

        Every read is defended. Explaining a failure must not raise one.
        """
        lines = []
        try:
            step = (
                self._states[self._index].name
                if self._index < len(self._states)
                else "none (run complete)"
            )
            lines.append(
                f"    step {step} ({self._index + 1} of {len(self._states)}), "
                f"tick {self.report.ticks}"
            )
        except Exception as exc:  # noqa: BLE001 - diagnosis must not raise
            lines.append(f"    step unreadable: {type(exc).__name__}")
        try:
            player = snap.player
            lines.append(
                f"    at {player.position}, hp {player.hp}/{player.max_hp}, "
                f"mana {player.mana}/{player.max_mana}, mode {player.mode}"
                if player is not None
                else "    player UNREADABLE"
            )
            lines.append(
                f"    area {snap.area.level_no if snap.area else '?'}, "
                f"ui {', '.join(snap.ui.names) if snap.ui else '?'}"
                + ("  (BLOCKING)" if snap.ui is not None and snap.ui.blocks_input else "")
            )
            near = self._hostiles_near(snap)
            nearest = (
                min(
                    max(
                        abs(m.position[0] - snap.player.position[0]),
                        abs(m.position[1] - snap.player.position[1]),
                    )
                    for m in snap.live_monsters
                )
                if snap.live_monsters and snap.player is not None
                else None
            )
            lines.append(
                f"    {len(near)} hostile(s) within "
                f"{self.config.idle_danger_radius}, "
                f"{len(snap.live_monsters)} in perception"
                + (f", nearest at {nearest}" if nearest is not None else "")
                + f", {len(snap.allies)} ally/allies, {len(snap.corpses)} corpse(s)"
                + f", {len(snap.ground_items)} item(s) on the ground"
            )
        except Exception as exc:  # noqa: BLE001
            lines.append(f"    world unreadable: {type(exc).__name__}: {exc}")
        try:
            lines.append(
                f"    {self.report.refusals} refused send(s) this run, "
                f"streak {self._refusal_streak}"
                + (
                    f", declared wait running {self._clock() - self._waiting_since:.1f}s"
                    if self._waiting_since is not None
                    else ""
                )
            )
            trace = getattr(self._executor, "trace", None)
            if trace:
                recent = ", ".join(
                    type(entry.action).__name__ for entry in trace[-5:]
                )
                lines.append(f"    last sent: {recent}")
            else:
                lines.append("    last sent: NOTHING this run")
            if self.report.log:
                lines.append(f"    last log line: {self.report.log[-1]}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"    engine state unreadable: {type(exc).__name__}")
        return "\n".join(lines)

    def tick(self) -> bool:
        """One decision. Returns True when the run is complete.

        Monitor exceptions (ChickenExit, DeathHalt) and IdleBail propagate
        to the caller untouched — the cycle owns what they mean.
        """
        snap = self._snapshot()
        # The death latch outranks EVERY stop (review 2026-08-02, issue
        # 001): a StopRequested rides ChickenExit into the cycle's
        # leave-game path, which SENDS INPUT — and if the stop preempted
        # the monitor on the very tick a death occurred, the latch would
        # never set and the leave would type at a dead character. The
        # monitor ticks first; DeathHalt and ChickenExit win the race by
        # construction, and an abort is still heard within this same
        # tick, one line lower.
        self._monitor.tick()
        if self._should_stop is not None and self._should_stop():
            self._narrate("run aborted by request")
            raise StopRequested("stopped by outside request (abort)")
        if self._operator_took_the_controls(snap):
            self._narrate("operator input (ESC/Enter) — standing down")
            raise StopRequested(
                "the operator pressed ESC or opened chat — standing down"
            )
        now = self._clock()
        self.report.ticks += 1
        if self.report.ticks == 1:
            # On the first TICK, not at construction: `describe` builds a
            # throwaway engine pre-flight, and an inert engine must leave
            # no narrative file behind.
            self._narrate(f"run: {' -> '.join(self.step_names)}")
            self._step_started = now

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
                # Do NOT commit the rung's cooldown and do NOT mark
                # activity: nothing happened, so the next tick must be free
                # to decide the very same thing again. PACING is different
                # and is recorded either way — see `ReflexDecision`.
                decision.commit_attempted()
                self._note_refusal(f"reflex {decision.rung}", exc)
                self._check_idle(snap, now)
                return self.complete
            decision.commit_attempted()
            decision.commit_sent()
            self._refusal_streak = 0
            self._waiting_since = None  # something happened: not a wait
            fires = self._rung_fires.get(decision.rung, 0) + 1
            self._rung_fires[decision.rung] = fires
            if fires % 25 == 0:
                self._narrate(
                    f"reflex {decision.rung} has fired {fires}x this run "
                    f"— the run step is being outbid for these ticks"
                )
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
                self._waiting_since = None
                self._mark_activity(self._clock())
            if outcome.waiting:
                # A declared wait is progress, not idleness (review 003) —
                # but only for as long as it is still a wait (review 001).
                self._note_wait(snap, now, state.name)
                self._mark_activity(self._clock())
            if outcome.note and not outcome.done:
                # A step's note on a tick it did NOT finish is the only
                # record of WHY it did something, and until now the log
                # kept refusals and completions and threw these away. The
                # second clean stage-B run finished with five MoveTos in
                # its trace and nothing anywhere saying whether they were
                # the clearance closing on a hostile, the skirmish drift,
                # or a walk to an item — an unanswerable question about the
                # one artifact stage B exists to produce. Steps set notes
                # sparingly (closing on a monster, a cleanse, a stray panel
                # closed), so this stays a record rather than a stream.
                self.report.log.append(f"step {state.name}: {outcome.note}")
            if outcome.done:
                self._index += 1
                self._waiting_since = None
                self.report.steps_completed.append(state.name)
                self.report.log.append(
                    f"step {state.name} done"
                    + (f": {outcome.note}" if outcome.note else "")
                )
                elapsed = self._clock() - self._step_started
                self._narrate(
                    f"{state.name}: done after {elapsed:.0f}s"
                    + (f" — {outcome.note}" if outcome.note else "")
                )
                self._step_started = self._clock()
                if self.complete:
                    self._narrate(f"run complete ({self.report.summary()})")
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
