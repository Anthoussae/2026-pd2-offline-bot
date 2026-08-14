"""The route leash on the traverse step (R241).

Reuses the traverse harness: a scripted world whose position the test
moves by hand to stray off a recorded line, then watches which way the
next leg walks and what the event log says. Geometry is chosen so
"walking back to the line" and "walking on toward the exit" pull in
OPPOSITE x directions — the assertion cannot pass by accident.
"""

from pd2bot.behavior.actions import MoveTo
from pd2bot.nav.navigate import NavigationError
from pd2bot.nav.routeline import RouteLine
from pd2bot.runlog import NullRunLog
from tests.behavior.test_behavior_steps import (
    Clock,
    monster,
    traversing,
)

# The scripted area is 20; HOME is (1000, 1000); the exit sits EAST at
# (1060, 1000). The line runs WEST from home, so a character standing
# strayed north of the line's west arm walks WEST-ish to return and
# EAST-ish to continue — unambiguous.
LINE = RouteLine(0xBEEF, 1, 20, [(1000, 1000), (900, 1000)])
STRAY_POS = (940, 1040)  # 40 subtiles north of the line


class EventLog(NullRunLog):
    def __init__(self):
        self.events = []

    def event(self, kind, /, **fields):
        # Tripwire (2026-08-10): the REAL log's record merge means a field
        # named after an envelope key would clobber it on disk. This fake
        # kept (kind, fields) apart, so seven order tests passed while
        # every live order event was written with an item-kind NUMBER as
        # its event kind. Fail the test the real log cannot fail.
        assert not {"seq", "at", "t", "kind"} & fields.keys(), (
            f"event field collides with the envelope: {sorted(fields)} — "
            "name it item_kind/npc_kind/monster_kind instead"
        )
        self.events.append((kind, fields))


def leashed(clock, *, line=LINE, monsters=(), posture=None, require=False):
    log = EventLog()
    step, world, remembered, executor, ctx, tick = traversing(
        clock, runlog=log
    )
    svc = step.services
    svc.route_line_for = (lambda a: line) if line is not None else (lambda a: None)
    if require:
        step.require_line = True
    if posture is not None:
        step.posture = posture
    world["pos"] = STRAY_POS
    original_tick = tick

    def tick_with(monster_list=monsters):
        from tests.behavior.test_behavior_steps import snap

        return step.step(
            snap(pos=world["pos"], area=world["area"], monsters=monster_list),
            ctx,
        )

    return step, world, executor, log, tick_with, original_tick


def strays(log):
    return [f for k, f in log.events if k == "route.stray"]


def test_strayed_walks_back_to_the_line_when_clear():
    clock = Clock()
    step, world, executor, log, tick, _ = leashed(clock)
    tick()
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert moves, "no leg was walked"
    # Returning: the leg heads toward (940, 1000) — x stays put or goes
    # west, y decreases. Continuing to the exit would push x EAST past
    # the stray x.
    tx, ty = moves[-1].target
    assert tx <= STRAY_POS[0] + 2
    assert ty < STRAY_POS[1]
    assert strays(log) and strays(log)[0]["returning"] is True


def test_stray_events_are_paced_not_per_tick():
    clock = Clock()
    step, world, executor, log, tick, _ = leashed(clock)
    # Deeper than the shared STRAY_POS: at 20-subtile legs (R257 P3) a
    # 40-subtile stray is back on the line in two ticks, and the test
    # needs the character still OUT when the ~5 s heartbeat comes due.
    world["pos"] = (940, 1060)
    tick()
    clock.advance(0.5)
    tick()
    assert len(strays(log)) == 1  # the crossing, not every tick
    clock.advance(6.0)
    tick()
    assert len(strays(log)) == 2  # the ~5 s heartbeat while still out


def test_default_posture_waits_for_a_clear_neighbourhood():
    clock = Clock()
    hostile = monster(7, (945, 1035))  # within the 12-subtile radius
    step, world, executor, log, tick, _ = leashed(clock)
    tick([hostile])
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    if moves:  # combat declined the tick; the leg must head EXITWARD
        assert moves[-1].target[0] > STRAY_POS[0]
    assert strays(log) and strays(log)[0]["returning"] is False


def test_brisk_returns_through_trouble():
    clock = Clock()
    hostile = monster(7, (945, 1035))
    step, world, executor, log, tick, _ = leashed(clock, posture="brisk")
    tick([hostile])
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert moves and moves[-1].target[1] < STRAY_POS[1]
    assert strays(log)[0]["returning"] is True


def test_inside_the_threshold_is_silent_and_exitward():
    clock = Clock()
    step, world, executor, log, tick, _ = leashed(clock)
    world["pos"] = (1000, 1004)  # 4 subtiles off: inside the 12 default
    tick()
    assert strays(log) == []
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert moves and moves[-1].target[0] > 1000  # on toward the exit


def test_require_line_with_none_recorded_stops_loudly():
    clock = Clock()
    step, world, executor, log, tick, _ = leashed(clock, line=None, require=True)
    try:
        tick()
    except NavigationError as exc:
        assert "t84_record_line" in str(exc)
    else:
        raise AssertionError("a required, missing line did not stop the run")


def test_a_goal_off_the_line_is_not_leashed_away_from():
    # The oscillation guard: the exit at (1060, 1000)... with a line that
    # ends far from it, walking to the exit necessarily strays — the
    # leash must yield to the goal instead of yanking back forever.
    clock = Clock()
    offline_goal = RouteLine(0xBEEF, 1, 20, [(900, 1200), (940, 1200)])
    step, world, executor, log, tick, _ = leashed(clock, line=offline_goal)
    world["pos"] = (1000, 1050)  # 150 off the line; the exit is further
    tick()
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    # The leg heads EXITWARD (east/up), not to the line (west/south).
    assert moves and moves[-1].target[0] > 1000
