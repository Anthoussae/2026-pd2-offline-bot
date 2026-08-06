"""P4: every tick and every decision recorded, with where the time went.

The phase that closes the T71 hole. That run made ~150 decisions in an
empty room and recorded five, because the engine only logged a tick whose
outcome carried a note. These tests assert the opposite property.
"""

import pytest

from pd2bot.behavior.actions import MoveTo
from pd2bot.behavior.engine import BehaviorEngine, EngineConfig, StepOutcome
from pd2bot.behavior.execute import RecordingExecutor
from pd2bot.mapframe import MapFrame
from pd2bot.player import Player
from pd2bot.runlog import RunLog, load, render
from pd2bot.snapshot import GameSnapshot
from pd2bot.units import GroundItem, Monster
from pd2bot.world import Area

TOWER = Area(level_no=20, position=(2000, 1600), size=(8, 8))
ARRIVAL = (10006, 8002)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


class Monitor:
    def tick(self):
        return None


def player(pos=ARRIVAL, hp=1737):
    return Player(
        name="N", level=91, act=1, position=pos, mode=1,
        hp=hp, max_hp=2000, mana=402, max_mana=500,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


def snap(monsters=(), items=()):
    return GameSnapshot(
        in_game=True, taken_at=0.0, player=player(), area=TOWER,
        monsters=tuple(monsters), ground_items=tuple(items),
    )


class ScriptedStep:
    """A step returning a scripted sequence of outcomes."""

    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)

    def step(self, snapshot, ctx):
        return self.outcomes.pop(0) if self.outcomes else StepOutcome(done=True)


def build(tmp_path, step, *, monsters=(), items=(), clock=None):
    clock = clock or Clock()
    log = RunLog("t", root=tmp_path, clock=clock, wall=lambda: 1786000000.0)
    engine = BehaviorEngine(
        snapshot=lambda: snap(monsters, items),
        monitor=Monitor(),
        states=[step],
        executor=RecordingExecutor(clock=clock),
        # The watchdogs are not what these tests are about; a declared
        # wait long enough to exercise the collapsing would otherwise
        # trip wait_bail at 30s.
        config=EngineConfig(tick_interval_s=0.2, idle_bail_s=1e9, wait_bail_s=1e9),
        clock=clock,
        runlog=log,
        frame=lambda: MapFrame.from_area(TOWER),
    )
    return engine, log, clock


def kinds(events, kind):
    return [e for e in events if e["kind"] == kind]


# -- the T71 property: no silent ticks ------------------------------------------


def test_a_silent_decision_is_still_recorded(tmp_path):
    # THE regression for T71: a step returning `waiting` with no note
    # used to leave nothing behind. Five of ~150 decisions were recorded
    # and the analysis that followed was invention.
    step = ScriptedStep("traverse", [StepOutcome(done=False, waiting=True)] * 12)
    engine, log, clock = build(tmp_path, step)
    for _ in range(12):
        engine.tick()
        clock.advance(0.85)
    events = load(log.directory)
    assert len(kinds(events, "tick")) == 12
    assert len(kinds(events, "step.decision")) == 12
    assert all(e["outcome"] == "waiting" for e in kinds(events, "step.decision"))


def test_every_tick_records_where_its_time_went(tmp_path):
    # The measurement T71 lacked: 1.05s per tick against a 0.2s interval,
    # and nothing could say which part was slow.
    step = ScriptedStep("traverse", [StepOutcome(done=False, acted=True)] * 3)
    engine, log, clock = build(tmp_path, step)
    for _ in range(3):
        engine.tick()
        clock.advance(0.85)
    for event in kinds(load(log.directory), "tick"):
        assert set(event["timing"]) >= {"snapshot", "ladder", "step"}
        assert event["dur_s"] >= 0


def test_a_tick_records_the_world_it_decided_against(tmp_path):
    # Counts, not lists. In the Forgotten Tower these both read zero on
    # every tick, which kills the "it was fighting" story on sight.
    monster = Monster(
        unit_id=1, kind=50, position=(10010, 8010), hp=100, max_hp=100,
        is_champion=False, is_boss=False, is_minion=False,
    )
    item = GroundItem(unit_id=880, kind=702, position=(10004, 8004), quality=2)
    step = ScriptedStep("traverse", [StepOutcome(done=False, waiting=True)])
    engine, log, clock = build(tmp_path, step, monsters=[monster], items=[item])
    engine.tick()
    event = kinds(load(log.directory), "tick")[0]
    assert event["hostiles"] == 1
    assert event["ground_items"] == 1
    assert event["hp"] == 1737 and event["mana"] == 402
    assert event["player"]["local"] == [6, 2]  # readable, not five digits


def test_the_tick_names_the_step_that_owned_it(tmp_path):
    step = ScriptedStep("traverse", [StepOutcome(done=False, acted=True)])
    engine, log, clock = build(tmp_path, step)
    engine.tick()
    assert kinds(load(log.directory), "tick")[0]["step"] == "traverse"


def test_a_tick_that_ends_by_raising_is_still_recorded(tmp_path):
    # The ticks most worth reading are the ones that failed.
    class Exploding:
        name = "traverse"

        def step(self, snapshot, ctx):
            raise RuntimeError("gave the run up loudly")

    engine, log, clock = build(tmp_path, Exploding())
    with pytest.raises(RuntimeError):
        engine.tick()
    assert len(kinds(load(log.directory), "tick")) == 1


# -- refusals are not sends -------------------------------------------------------


def test_a_refused_send_is_its_own_event(tmp_path):
    from pd2bot.input import InputRefused

    class Refusing:
        name = "traverse"

        def step(self, snapshot, ctx):
            raise InputRefused("a cast is still resolving")

    engine, log, clock = build(tmp_path, Refusing())
    engine.tick()
    refusals = kinds(load(log.directory), "refusal")
    assert len(refusals) == 1
    assert refusals[0]["error"] == "InputRefused"
    assert refusals[0]["streak"] == 1


# -- readability at volume ---------------------------------------------------------


def test_the_renderer_collapses_a_long_stall_into_one_line(tmp_path):
    # T71's shape: 40 identical waits. The file keeps every tick (counts
    # stay exact); the RENDERER folds them so a human can read it.
    step = ScriptedStep(
        "traverse",
        [StepOutcome(done=False, waiting=True, note="waiting out the last click")] * 40,
    )
    engine, log, clock = build(tmp_path, step)
    for _ in range(40):
        engine.tick()
        clock.advance(0.85)
    events = kinds(load(log.directory), "step.decision")
    assert len(events) == 40           # nothing lost on disk
    assert len(render(events)) == 1    # one line to read


def test_the_engine_without_a_log_still_ticks(tmp_path):
    # The null default must not be a special case anybody has to remember.
    step = ScriptedStep("traverse", [StepOutcome(done=True)])
    engine = BehaviorEngine(
        snapshot=lambda: snap(),
        monitor=Monitor(),
        states=[step],
        executor=RecordingExecutor(),
        config=EngineConfig(idle_bail_s=1e9),
    )
    assert engine.tick() is True


def test_actions_and_decisions_interleave_in_order(tmp_path):
    # A reader should see the decision and the action it produced next to
    # each other, in the order they happened.
    class Walking:
        name = "traverse"

        def step(self, snapshot, ctx):
            ctx.executor.execute(MoveTo((10002, 8013)))
            return StepOutcome(done=False, acted=True, note="walking to the exit")

    clock = Clock()
    log = RunLog("t", root=tmp_path, clock=clock, wall=lambda: 1786000000.0)
    executor = RecordingExecutor(
        clock=clock, runlog=log, frame=lambda: MapFrame.from_area(TOWER),
        player_position=lambda: ARRIVAL,
    )
    engine = BehaviorEngine(
        snapshot=lambda: snap(), monitor=Monitor(), states=[Walking()],
        executor=executor, config=EngineConfig(idle_bail_s=1e9),
        clock=clock, runlog=log, frame=lambda: MapFrame.from_area(TOWER),
    )
    engine.tick()
    order = [e["kind"] for e in load(log.directory)]
    assert order == ["action.move", "step.decision", "tick"]
