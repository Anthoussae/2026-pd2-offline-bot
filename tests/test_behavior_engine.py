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
    StepOutcome,
)
from pd2bot.behavior.reflex import ReflexDecision
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
