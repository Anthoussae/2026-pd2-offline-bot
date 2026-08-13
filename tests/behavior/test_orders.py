"""The mandatory-pickup OrderBook (R241 item 7): lifecycle, budget,
and the anti-livelock guarantees. Pure logic — the driving is proven
through the traverse harness and the live pilot.
"""

from pd2bot.behavior.steps.orders import (
    CLOSED_BUDGET,
    CLOSED_COLLECTED,
    CLOSED_GONE,
    OrderBook,
)


def book(budget=75.0):
    return OrderBook(budget_s=budget)


def test_a_sighting_opens_exactly_one_order():
    b = book()
    assert b.sight(1, 700, (10, 10), now=0.0) is not None
    assert b.sight(1, 700, (10, 10), now=1.0) is None  # re-sighting
    assert len(b.pending()) == 1


def test_a_resighting_refreshes_position_not_identity():
    b = book()
    b.sight(1, 700, (10, 10), now=0.0)
    b.sight(1, 700, (12, 10), now=1.0)
    assert b.pending()[0].position == (12, 10)


def test_orders_serve_oldest_first():
    b = book()
    b.sight(2, 700, (0, 0), now=5.0)
    b.sight(1, 700, (9, 9), now=1.0)
    assert b.next_order(now=6.0).unit_id == 1


def test_collected_and_gone_close_and_stay_closed():
    b = book()
    b.sight(1, 700, (0, 0), now=0.0)
    assert b.collected(1).state == CLOSED_COLLECTED
    assert b.collected(1) is None  # double-close reports nothing
    assert b.next_order(now=1.0) is None
    b.sight(2, 700, (0, 0), now=2.0)
    assert b.gone(2).state == CLOSED_GONE
    assert b.pending() == []


def test_a_closed_order_never_reopens_on_resighting():
    # The convergence rule: an order judged done must not resurrect just
    # because the item (or its ghost in a torn read) shows up again.
    b = book()
    b.sight(1, 700, (0, 0), now=0.0)
    b.gone(1)
    assert b.sight(1, 700, (0, 0), now=5.0) is None
    assert b.pending() == []


def test_active_time_accumulates_only_across_serviced_ticks():
    b = book(budget=10.0)
    b.sight(1, 700, (0, 0), now=0.0)
    order = b.next_order(now=0.0)
    b.service_tick(order, now=0.0)
    b.service_tick(order, now=1.0)  # +1
    b.interrupt(order)  # combat takes over
    b.service_tick(order, now=50.0)  # gap costs nothing (fresh delta)
    b.service_tick(order, now=51.0)  # +1
    assert order.active_s == 2.0


def test_a_stalled_clock_gap_is_capped_not_billed():
    b = book(budget=10.0)
    b.sight(1, 700, (0, 0), now=0.0)
    order = b.next_order(now=0.0)
    b.service_tick(order, now=0.0)
    b.service_tick(order, now=9.0)  # a 9 s stall bills at most 2 s
    assert order.active_s == 2.0


def test_the_budget_closes_the_order_loudly_once():
    b = book(budget=3.0)
    b.sight(1, 700, (0, 0), now=0.0)
    order = b.next_order(now=0.0)
    for t in range(5):
        b.service_tick(order, now=float(t))
    over = b.next_order(now=6.0)
    assert over is order and over.state == CLOSED_BUDGET
    # Surfaced exactly once; afterwards the book moves on.
    assert b.next_order(now=7.0) is None


def test_id_churn_rebinds_an_open_order_instead_of_duplicating():
    """2026-08-10 pilots: one amethyst on one subtile carried unit ids
    604, 661 and 764 across a run — the client re-registers a ground
    item when its room unloads and reloads. Without the rebind that was
    three orders, stale 'gone' closes, and a budget that reset on every
    reload."""
    b = book(budget=10.0)
    b.sight(604, 685, (5232, 5663), now=0.0)
    order = b.next_order(now=0.0)
    b.service_tick(order, now=0.0)
    b.service_tick(order, now=2.0)

    assert b.sight(661, 685, (5232, 5663), now=3.0) is None  # not a new order
    assert len(b.all_orders()) == 1
    survivor = b.pending()[0]
    assert survivor.unit_id == 661, "the order follows the item's new id"
    assert survivor.active_s == 2.0, "the budget survived the churn"


def test_id_churn_cannot_reopen_a_closed_order():
    # The convergence rule extends across ids: a spent budget must not
    # refill just because the room reloaded and the item re-registered.
    b = book(budget=2.0)
    b.sight(604, 685, (5232, 5663), now=0.0)
    order = b.next_order(now=0.0)
    for t in range(4):
        b.service_tick(order, now=float(t))
    assert b.next_order(now=5.0).state == CLOSED_BUDGET

    assert b.sight(661, 685, (5232, 5663), now=6.0) is None
    assert b.pending() == []


def test_a_write_off_closes_like_a_spent_budget_and_only_once():
    b = book()
    b.sight(1, 700, (0, 0), now=0.0)
    assert b.write_off(1).state == CLOSED_BUDGET
    assert b.write_off(1) is None  # double-close reports nothing
    assert b.pending() == []


def test_the_next_order_gets_its_turn_after_a_write_off():
    b = book(budget=2.0)
    b.sight(1, 700, (0, 0), now=0.0)
    b.sight(2, 701, (5, 5), now=1.0)
    first = b.next_order(now=1.0)
    b.service_tick(first, now=1.0)
    b.service_tick(first, now=3.0)
    b.service_tick(first, now=5.0)
    assert b.next_order(now=5.0).state == CLOSED_BUDGET  # first, written off
    assert b.next_order(now=5.0).unit_id == 2  # the chain advances
