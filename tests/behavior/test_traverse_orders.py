"""Mandatory orders through the traverse step (R241 item 7): a wanted
drop pulls the step back before it walks on; gone items close orders;
the pilot flag gates all of it.
"""

from pd2bot.behavior.actions import MoveTo
from pd2bot.behavior.steps.orders import OrderBook
from pd2bot.perception.units import GroundItem
from tests.behavior.test_behavior_steps import Clock, traversing
from tests.behavior.test_traverse_leash import EventLog


def rare(uid, pos):
    return GroundItem(unit_id=uid, kind=999, position=pos, quality=6)  # rare


def ordered_world(clock):
    log = EventLog()
    step, world, remembered, executor, ctx, _ = traversing(clock, runlog=log)
    step.services.order_book = OrderBook(budget_s=75.0)
    return step, world, executor, log, ctx


def events(log, kind):
    return [f for k, f in log.events if k == kind]


def tick(step, ctx, world, items=()):
    from tests.behavior.test_behavior_steps import snap

    return step.step(
        snap(pos=world["pos"], area=world["area"], items=items), ctx
    )


def test_a_sighting_books_an_order_and_walking_away_pulls_back():
    clock = Clock()
    step, world, executor, log, ctx = ordered_world(clock)
    drop = rare(50, (1005, 1000))
    tick(step, ctx, world, items=[drop])  # sighted; collect claims the tick
    assert events(log, "pickup.order_open"), "the sighting was not booked"
    # The item vanishes from perception (say the step got dragged 40 east
    # by other logic) but the ORDER persists: with nothing else to do the
    # step walks back toward it instead of on toward the exit.
    world["pos"] = (1100, 1000)  # past the exit at (1060, 1000)
    clock.advance(1.0)
    outcome = tick(step, ctx, world, items=[])
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert moves and moves[-1].target[0] < 1100, outcome.note
    assert "order 50" in outcome.note


def test_near_and_absent_closes_the_order_as_gone():
    clock = Clock()
    step, world, executor, log, ctx = ordered_world(clock)
    tick(step, ctx, world, items=[rare(50, (1005, 1000))])
    clock.advance(1.0)
    # Standing right where it was, floor empty, never collected: expiry.
    tick(step, ctx, world, items=[])
    assert events(log, "pickup.order_gone")
    assert step.services.order_book.pending() == []


def test_no_flag_no_orders():
    clock = Clock()
    log = EventLog()
    step, world, remembered, executor, ctx, _ = traversing(clock, runlog=log)
    assert step.services.order_book is None
    tick(step, ctx, world, items=[rare(50, (1005, 1000))])
    assert events(log, "pickup.order_open") == []


def test_a_potion_never_becomes_an_order():
    clock = Clock()
    step, world, executor, log, ctx = ordered_world(clock)
    from pd2bot import offsets

    hp_kind = next(iter(offsets.HEALING_POTION_KINDS))
    potion = GroundItem(unit_id=51, kind=hp_kind, position=(1005, 1000), quality=2)
    tick(step, ctx, world, items=[potion])
    assert events(log, "pickup.order_open") == []
