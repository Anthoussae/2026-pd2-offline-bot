"""Reproduce the live pilot gap: a whitelisted drop during CLEARANCE
must book a mandatory order. Live, 8 (then 2) whitelisted items dropped
and zero orders opened, though item.dropped logged them — so booking
via the clearance path is what to pin here, not just the traverse path.
"""

from pd2bot.behavior.steps.orders import OrderBook
from pd2bot.perception.units import GroundItem
from tests.behavior.test_behavior_steps import (
    Clock,
    context,
    make_step,
    monster,
    services,
    snap,
)
from tests.behavior.test_traverse_leash import EventLog

RARE = 6


def rare(uid, pos):
    return GroundItem(unit_id=uid, kind=999, position=pos, quality=RARE)


def test_clearance_books_an_order_for_a_whitelisted_drop():
    clock = Clock()
    log = EventLog()
    svc = services(clock, runlog=log)
    svc.order_book = OrderBook(budget_s=75.0)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    ctx = context()
    # A wanted rare on the cleared ground, no monsters left.
    step.step(snap(pos=(1000, 1000), items=[rare(50, (1010, 1000))]), ctx)
    opened = [f for k, f in log.events if k == "pickup.order_open"]
    assert opened, "the clearance booked no order for a whitelisted drop"
    assert svc.order_book.pending()


def test_clearance_books_even_mid_fight():
    clock = Clock()
    log = EventLog()
    svc = services(clock, runlog=log)
    svc.order_book = OrderBook(budget_s=75.0)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    ctx = context()
    # A hostile present AND a wanted drop: booking must not wait for the
    # field to clear (the item could despawn during the fight).
    step.step(
        snap(pos=(1000, 1000), monsters=[monster(9, (1005, 1000))],
             items=[rare(50, (1010, 1000))]),
        ctx,
    )
    assert [f for k, f in log.events if k == "pickup.order_open"]


def test_an_unreachable_order_closes_instead_of_pacing_forever():
    """The Countess ruby deadlock (R264, log 20260814-034442): a
    flawless ruby's order opened mid-fight, the walk to it failed the
    stall ladder, collect's send-fail branch marked it stuck SILENTLY,
    and the open order declared "pickup pacing" waits until the
    engine's 30 s wait-cap killed the whole run 10 subtiles away.
    A failed walk must be said out loud, and an order on unreachable
    ground must CLOSE - try hard, concede honestly, never wait forever."""
    from pd2bot.behavior.actions import MoveTo
    from pd2bot.nav.navigate import NavigationError

    class WallExecutor:
        def execute(self, action):
            if isinstance(action, MoveTo):
                raise NavigationError("gave up after 5 capped attempts")

    clock = Clock()
    log = EventLog()
    svc = services(clock, runlog=log)
    svc.order_book = OrderBook(budget_s=75.0)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    ctx = context(WallExecutor())
    ruby = rare(50, (1025, 1000))  # beyond pickup_reach: collect must walk

    for _ in range(12):
        step.step(snap(pos=(1000, 1000), items=[ruby]), ctx)
        clock.advance(1.0)
        if svc.order_book is not None and not svc.order_book.pending():
            break

    assert not svc.order_book.pending(), (
        "the order never closed - the ruby deadlock"
    )
    walk_writeoffs = [
        f for k, f in log.events
        if k == "item.abandoned" and f.get("reason") == "the walk to it failed"
    ]
    assert walk_writeoffs, "the send-fail write-off is still silent"
    closed = [
        f for k, f in log.events
        if k == "pickup.order_abandoned"
        and f.get("reason") == "the walk to it failed"
    ]
    assert closed, "the order did not close with the honest reason"
