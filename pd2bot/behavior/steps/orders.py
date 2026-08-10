"""Mandatory pickup orders (R241 item 7): a wanted drop is pursued until
collected, provably gone, or out of budget — never silently forgotten.

Pure bookkeeping: the OrderBook holds one PickupOrder per sighted wanted
item and answers "what should be pursued next, and may we still?". The
driving (walking back, clicking, cleansing) is `_PickupMixin
.service_orders`; every transition here is mirrored into the run event
log by the caller, because the census must be able to say what happened
to EVERY order (`pickup.order_*` kinds).

Priorities, fixed by construction: combat and the reflex ladder outrank
orders (service_orders only runs on ticks combat declined), and orders
outrank onward traversal (the traverse consults them before walking to
its exit). The budget is ACTIVE time — ticks spent actually pursuing —
so a long fight nearby does not eat an order's allowance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Lifecycle states. OPEN orders may become ACTIVE when serviced; every
# order ends CLOSED with a reason the census reports.
OPEN = "open"
CLOSED_COLLECTED = "collected"
CLOSED_GONE = "gone"  # the unit left the world (T51 expiry, or scooped)
CLOSED_BUDGET = "budget"  # active time spent; written off loudly


@dataclass
class PickupOrder:
    unit_id: int
    kind: int
    position: tuple[int, int]
    created_at: float
    state: str = OPEN
    active_s: float = 0.0  # accumulated ACTIVE pursuit time
    _last_service: float | None = field(default=None, repr=False)

    @property
    def closed(self) -> bool:
        return self.state != OPEN


class OrderBook:
    """Every wanted drop's order, oldest-first service, budget-enforced."""

    def __init__(self, budget_s: float = 75.0) -> None:
        self.budget_s = budget_s
        self._orders: dict[int, PickupOrder] = {}

    # -- sighting and closing --------------------------------------------------

    def sight(
        self, unit_id: int, kind: int, position: tuple[int, int], now: float
    ) -> PickupOrder | None:
        """Book a wanted drop. Returns the NEW order, or None if it is
        already known (a re-sighting refreshes the position — items do
        not move, but a better read wins — and is not a new order)."""
        existing = self._orders.get(unit_id)
        if existing is not None:
            if not existing.closed:
                existing.position = position
            return None
        order = PickupOrder(unit_id, kind, position, created_at=now)
        self._orders[unit_id] = order
        return order

    def collected(self, unit_id: int) -> PickupOrder | None:
        return self._close(unit_id, CLOSED_COLLECTED)

    def gone(self, unit_id: int) -> PickupOrder | None:
        return self._close(unit_id, CLOSED_GONE)

    def _close(self, unit_id: int, state: str) -> PickupOrder | None:
        order = self._orders.get(unit_id)
        if order is None or order.closed:
            return None
        order.state = state
        order._last_service = None
        return order

    # -- service ---------------------------------------------------------------

    def next_order(self, now: float) -> PickupOrder | None:
        """The oldest open order with budget left. Orders whose budget is
        spent are closed HERE (state -> budget) so the caller sees each
        write-off exactly once, on the tick it happens."""
        for order in sorted(self._orders.values(), key=lambda o: o.created_at):
            if order.closed:
                continue
            if order.active_s >= self.budget_s:
                order.state = CLOSED_BUDGET
                order._last_service = None
                return order  # surfaced once, already closed; caller logs
            return order
        return None

    def service_tick(self, order: PickupOrder, now: float) -> None:
        """Book active pursuit time: call once per tick spent on `order`.
        Gaps (combat interruptions) cost nothing — only serviced ticks
        accumulate, measured between CONSECUTIVE service calls and capped
        so a stall between distant calls cannot bill the whole gap."""
        if order._last_service is not None:
            delta = now - order._last_service
            order.active_s += min(max(delta, 0.0), 2.0)
        order._last_service = now

    def interrupt(self, order: PickupOrder) -> None:
        """Mark a service gap starting (combat preempted): the next
        service tick starts a fresh delta instead of billing the fight."""
        order._last_service = None

    # -- reporting -------------------------------------------------------------

    def pending(self) -> list[PickupOrder]:
        return [
            o for o in sorted(self._orders.values(), key=lambda o: o.created_at)
            if not o.closed
        ]

    def all_orders(self) -> list[PickupOrder]:
        return sorted(self._orders.values(), key=lambda o: o.created_at)
