"""The engine: tick order, propagation, short-circuiting, and never-idle.

The engine is the traffic cop, so the tests script every participant — a
monitor that raises on cue, a ladder that fires on cue, states that finish
on cue — and assert on who was consulted, in what order, and who was
skipped.
"""

import pytest

from pd2bot.behavior.actions import CastSelf, DrinkPotion
from pd2bot.behavior.engine import (
    BehaviorEngine,
    BehaviorError,
    EngineConfig,
    IdleBail,
    InputRefusedHalt,
    StepOutcome,
)
from pd2bot.behavior.reflex import ReflexDecision
from pd2bot.input import InputRefused
from pd2bot.player import Player
from pd2bot.safety import ChickenExit, DeathHalt
from pd2bot.snapshot import GameSnapshot
from pd2bot.world import Area

TOWN, FIELD = 1, 3


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def player(pos=(100, 100)):
    return Player(
        name="N", level=91, act=1, position=pos, mode=1,
        hp=1000, max_hp=1000, mana=200, max_mana=400,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


def snap(area=FIELD, pos=(100, 100)):
    return GameSnapshot(
        in_game=True, taken_at=0.0, player=player(pos),
        area=Area(level_no=area, position=(0, 0), size=(500, 500)),
    )


class ScriptedMonitor:
    """tick() raises whatever is queued next, else passes quietly."""

    def __init__(self, raises=()):
        self.raises = list(raises)
        self.ticks = 0
        self.order: list[str] | None = None

    def tick(self):
        self.ticks += 1
        if self.order is not None:
            self.order.append("monitor")
        if self.raises:
            exc = self.raises.pop(0)
            if exc is not None:
                raise exc


class ScriptedLadder:
    """evaluate() pops the next scripted decision (None = quiet tick)."""

    def __init__(self, decisions=()):
        self.decisions = list(decisions)
        self.calls = 0
        self.order: list[str] | None = None

    def evaluate(self, snap):
        self.calls += 1
        if self.order is not None:
            self.order.append("ladder")
        return self.decisions.pop(0) if self.decisions else None


class RecordingExecutor:
    def __init__(self):
        self.executed = []

    def execute(self, action):
        self.executed.append(action)


class FakeStep:
    """Reports done after `ticks_to_done` calls; `acted` per call."""

    def __init__(self, name, ticks_to_done=1, acted=False):
        self.name = name
        self.remaining = ticks_to_done
        self.acted = acted
        self.calls = 0
        self.order: list[str] | None = None

    def step(self, snap, ctx):
        self.calls += 1
        if self.order is not None:
            self.order.append(f"step:{self.name}")
        self.remaining -= 1
        return StepOutcome(done=self.remaining <= 0, acted=self.acted)


def engine(
    *, states=None, monitor=None, ladder=None, executor=None,
    snaps=None, config=None, clock=None,
):
    clock = clock or Clock()
    snaps = snaps if snaps is not None else [snap()]

    def snapshot():
        return snaps.pop(0) if len(snaps) > 1 else snaps[0]

    return (
        BehaviorEngine(
            snapshot=snapshot,
            monitor=monitor or ScriptedMonitor(),
            states=states if states is not None else [FakeStep("only")],
            executor=executor or RecordingExecutor(),
            ladder=ladder,
            config=config or EngineConfig(),
            clock=clock,
            sleep=lambda s: clock.advance(s),
        ),
        clock,
    )


DECISION = ReflexDecision(
    rung="heal", action=DrinkPotion(2, "healing"), reason="test"
)


def test_engine_refuses_an_empty_run():
    with pytest.raises(BehaviorError):
        engine(states=[])


def test_tick_order_is_monitor_ladder_step():
    order = []
    monitor = ScriptedMonitor()
    monitor.order = order
    ladder = ScriptedLadder()
    ladder.order = order
    step = FakeStep("s", ticks_to_done=2)
    step.order = order
    eng, _ = engine(states=[step], monitor=monitor, ladder=ladder)
    eng.tick()
    assert order == ["monitor", "ladder", "step:s"]


def test_monitor_exceptions_propagate_untouched():
    for exc_type in (ChickenExit, DeathHalt):
        step = FakeStep("s")
        eng, _ = engine(
            states=[step], monitor=ScriptedMonitor([exc_type("now")])
        )
        with pytest.raises(exc_type):
            eng.tick()
        assert step.calls == 0  # nothing ran past the monitor


def test_reflex_fire_consumes_the_tick():
    step = FakeStep("s", ticks_to_done=2)
    executor = RecordingExecutor()
    eng, _ = engine(
        states=[step],
        ladder=ScriptedLadder([DECISION]),
        executor=executor,
    )
    eng.tick()
    assert executor.executed == [DECISION.action]
    assert step.calls == 0  # offense skipped while survival spoke
    assert eng.report.reflex_fires == ["heal"]
    eng.tick()  # quiet ladder: the step gets its turn back
    assert step.calls == 1


def test_states_advance_in_order_and_run_completes():
    steps = [FakeStep("a", 2), FakeStep("b", 1)]
    eng, _ = engine(states=steps)
    report = eng.run()
    assert report.steps_completed == ["a", "b"]
    assert report.ticks == 3
    assert eng.complete


def test_step_completion_is_progress():
    # Slow but advancing steps must never idle-bail: each completion (and
    # each acted tick) resets the clock.
    config = EngineConfig(tick_interval_s=6.0, idle_bail_s=10.0)
    steps = [FakeStep(f"s{i}", 1) for i in range(5)]
    eng, _ = engine(states=steps, config=config)
    assert eng.run().steps_completed == [f"s{i}" for i in range(5)]


def test_idle_bail_fires_out_of_town():
    step = FakeStep("stuck", ticks_to_done=99, acted=False)
    eng, clock = engine(states=[step], config=EngineConfig(idle_bail_s=10.0))
    eng.tick()
    clock.advance(11.0)
    with pytest.raises(IdleBail):
        eng.tick()


def test_idle_bail_is_a_chicken_exit():
    # The typed contract the runner and cycle boundary rely on.
    assert issubclass(IdleBail, ChickenExit)


def test_no_idle_bail_in_town():
    step = FakeStep("waiting", ticks_to_done=99)
    eng, clock = engine(
        states=[step], snaps=[snap(area=TOWN)],
        config=EngineConfig(idle_bail_s=10.0),
    )
    eng.tick()
    clock.advance(60.0)
    eng.tick()  # a minute of town idling is somebody shopping, not a bug


def test_movement_counts_as_progress():
    step = FakeStep("walking", ticks_to_done=99)
    positions = [snap(pos=(100, 100 + i)) for i in range(6)]
    eng, clock = engine(
        states=[step], snaps=positions, config=EngineConfig(idle_bail_s=10.0)
    )
    for _ in range(5):
        eng.tick()
        clock.advance(8.0)  # under the limit only because movement resets it


def test_reflex_fire_counts_as_activity():
    step = FakeStep("stuck", ticks_to_done=99)
    eng, clock = engine(
        states=[step],
        ladder=ScriptedLadder([DECISION] * 5),
        config=EngineConfig(idle_bail_s=10.0),
    )
    for _ in range(5):
        eng.tick()
        clock.advance(8.0)


def test_acted_step_counts_as_activity():
    step = FakeStep("fighting", ticks_to_done=99, acted=True)
    eng, clock = engine(states=[step], config=EngineConfig(idle_bail_s=10.0))
    for _ in range(5):
        eng.tick()
        clock.advance(8.0)


def test_town_resets_the_idle_clock():
    step = FakeStep("stuck", ticks_to_done=99)
    eng, clock = engine(
        states=[step],
        snaps=[snap(area=TOWN), snap(area=TOWN), snap(area=FIELD), snap(area=FIELD)],
        config=EngineConfig(idle_bail_s=10.0),
    )
    eng.tick()  # in town: the idle clock is pinned ...
    clock.advance(60.0)
    eng.tick()  # ... however long town takes
    clock.advance(5.0)
    eng.tick()  # first field tick: only 5 s since the last town tick — fine
    clock.advance(11.0)
    with pytest.raises(IdleBail):
        eng.tick()  # 16 s since the town/field boundary


def test_report_log_records_fires_and_steps():
    eng, _ = engine(
        states=[FakeStep("a", 1)], ladder=ScriptedLadder([DECISION])
    )
    eng.tick()
    eng.tick()
    assert any("reflex heal" in line for line in eng.report.log)
    assert any("step a done" in line for line in eng.report.log)


def test_context_blackboard_is_shared_between_steps():
    class Writer:
        name = "writer"

        def step(self, snap, ctx):
            ctx.notes["arrival"] = (5, 6)
            return StepOutcome(done=True)

    class Reader:
        name = "reader"

        def __init__(self):
            self.saw = None

        def step(self, snap, ctx):
            self.saw = ctx.notes.get("arrival")
            return StepOutcome(done=True)

    reader = Reader()
    eng, _ = engine(states=[Writer(), reader])
    eng.run()
    assert reader.saw == (5, 6)


def test_ladder_consulted_every_tick_until_done():
    ladder = ScriptedLadder()
    eng, _ = engine(states=[FakeStep("a", 3)], ladder=ladder)
    eng.run()
    assert ladder.calls == 3


def test_upkeep_reflex_can_use_cast_self():
    # An upkeep decision travels the same path as any other rung.
    decision = ReflexDecision(rung="upkeep", action=CastSelf(68), reason="t")
    executor = RecordingExecutor()
    eng, _ = engine(
        states=[FakeStep("a", 2)],
        ladder=ScriptedLadder([decision]),
        executor=executor,
    )
    eng.tick()
    assert executor.executed == [CastSelf(68)]


# -- review 002: a refused send must not end the run ------------------------------


class RefusingExecutor:
    """Raises InputRefused for the first `refusals` sends, then records."""

    def __init__(self, refusals=1):
        self.remaining = refusals
        self.executed = []
        self.attempts = 0

    def execute(self, action):
        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise InputRefused("the window is not in the foreground")
        self.executed.append(action)


class CommittingLadder:
    """A ladder whose decisions record whether the engine committed them."""

    def __init__(self, count):
        self.committed = 0
        self.count = count

    def evaluate(self, snap):
        if self.count <= 0:
            return None
        self.count -= 1
        return ReflexDecision(
            rung="heal", action=DrinkPotion(2, "healing"), reason="test",
            commit=self._commit,
        )

    def _commit(self):
        self.committed += 1


def test_a_refused_reflex_send_does_not_escape_the_engine():
    """The guards raise InputRefused by design and M4 treats focus loss as
    routine; the behaviour layer used to have no equivalent, so an ordinary
    refusal ended the whole session with a traceback."""
    executor = RefusingExecutor(refusals=1)
    eng, _ = engine(
        states=[FakeStep("s", ticks_to_done=2)],
        ladder=ScriptedLadder([DECISION, None, None]),
        executor=executor,
    )
    eng.tick()  # refused — and survived
    assert eng.report.refusals == 1
    assert eng.run().steps_completed == ["s"]


def test_a_refused_send_is_not_committed_and_not_activity():
    ladder = CommittingLadder(count=2)
    executor = RefusingExecutor(refusals=1)
    eng, clock = engine(
        states=[FakeStep("s", ticks_to_done=99)],
        ladder=ladder, executor=executor,
        config=EngineConfig(idle_bail_s=10.0),
    )
    eng.tick()
    assert ladder.committed == 0  # decided, refused, NOT booked
    eng.tick()
    assert ladder.committed == 1  # the retry landed, and only then booked
    # And the refused tick did not count as activity: the idle clock never
    # restarted for it, so the watchdog is still watching.
    clock.advance(11.0)
    with pytest.raises(IdleBail):
        eng.tick()


def test_a_refused_step_send_does_not_escape_either():
    """Steps send through the same executor, so they refuse the same way."""

    class SendingStep:
        name = "sends"

        def __init__(self):
            self.calls = 0

        def step(self, snap, ctx):
            self.calls += 1
            ctx.executor.execute(CastSelf(68))
            return StepOutcome(done=self.calls >= 2, acted=True)

    step = SendingStep()
    eng, _ = engine(states=[step], executor=RefusingExecutor(refusals=1))
    eng.tick()  # refused inside the step
    assert eng.report.refusals == 1
    assert eng.run().steps_completed == ["sends"]


def test_an_unbroken_refusal_streak_eventually_halts():
    """One refusal is routine; a hundred means nothing is reaching the game
    while the character stands in Hell — the never-idle danger in a hat."""
    eng, _ = engine(
        states=[FakeStep("s", ticks_to_done=999)],
        ladder=ScriptedLadder([DECISION] * 10),
        executor=RefusingExecutor(refusals=99),
        config=EngineConfig(refusal_limit=5, idle_bail_s=1000.0),
    )
    with pytest.raises(InputRefusedHalt):
        for _ in range(6):
            eng.tick()


def test_the_refusal_streak_resets_on_a_send_that_lands():
    executor = RefusingExecutor(refusals=1)
    eng, _ = engine(
        states=[FakeStep("s", ticks_to_done=999)],
        ladder=ScriptedLadder([DECISION] * 6),
        executor=executor,
        config=EngineConfig(refusal_limit=2, idle_bail_s=1000.0),
    )
    for _ in range(4):
        eng.tick()  # refuse, land, land, land — never two in a row
    assert eng.report.refusals == 1


# -- review 003: a declared wait is not idleness ----------------------------------


class WaitingStep:
    """Stands still on purpose, and says so."""

    name = "settling"

    def __init__(self, waiting=True):
        self.waiting = waiting
        self.calls = 0

    def step(self, snap, ctx):
        self.calls += 1
        return StepOutcome(done=False, acted=False, waiting=self.waiting)


def test_a_declared_wait_is_not_idleness():
    """Review 003's probe: a settle longer than `idle_bail_s` must survive.

    `clear_settle_s`, `restrike_s` and `wait_for_revives_s` live in
    different files under different configs, and the watchdog knew about
    none of them — so raising any one past the limit made runs abandon
    themselves and blame an idle loop.
    """
    eng, clock = engine(
        states=[WaitingStep()], config=EngineConfig(idle_bail_s=10.0)
    )
    for _ in range(4):
        eng.tick()
        clock.advance(8.0)  # 32 s of deliberate waiting, no bail


def test_an_undeclared_wait_still_bails():
    # The watchdog is not disarmed — it now catches waits nobody asked for,
    # which is what it was always for.
    eng, clock = engine(
        states=[WaitingStep(waiting=False)],
        config=EngineConfig(idle_bail_s=10.0),
    )
    eng.tick()
    clock.advance(11.0)
    with pytest.raises(IdleBail):
        eng.tick()


# -- the area-change stutter (stage B run 5, user-diagnosed) ---------------------


def test_a_dropped_hotkey_press_is_absorbed_like_a_refusal():
    """The user watched run 5 stutter on the area change and then stand
    still. `SkillSwitchFailed` means the client dropped the keypress —
    nothing reached the game — which is exactly what InputRefused means, so
    it gets exactly the same handling: absorb, do not commit, decide again
    next tick. It used to end the session."""
    from pd2bot.skills import SkillSwitchFailed

    class DroppingExecutor:
        def __init__(self):
            self.attempts = 0

        def execute(self, action):
            self.attempts += 1
            if self.attempts == 1:
                raise SkillSwitchFailed("right skill reads 83 after 3 presses")

    ladder = CommittingLadder(count=2)
    eng, _ = engine(
        states=[FakeStep("s", ticks_to_done=99)],
        ladder=ladder, executor=DroppingExecutor(),
    )
    eng.tick()
    assert ladder.committed == 0  # the cast never happened; do not book it
    eng.tick()
    assert ladder.committed == 1
    assert eng.report.refusals == 1
