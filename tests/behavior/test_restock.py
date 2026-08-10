"""The potion-restock PLANNING half (R241 item 5): given vendor stock
and a belt shortfall, which cells to click. Pure logic — the clicking
is proven live (T85 + the restock drill), the arithmetic here.
"""

from pd2bot.behavior.town.restock import plan_purchases, unmet_types
from pd2bot.perception.items import VendorPotion


def pot(uid, ptype, cell):
    kind = {"healing": 617, "mana": 622, "rejuv": 627}[ptype]
    return VendorPotion(unit_id=uid, kind=kind, potion_type=ptype, cell=cell)


HEAL_STOCK = [pot(1, "healing", (0, 0)), pot(2, "healing", (1, 0))]
FULL_STOCK = HEAL_STOCK + [pot(3, "mana", (2, 0)), pot(4, "rejuv", (3, 0))]


def test_no_shortfall_buys_nothing():
    assert plan_purchases(FULL_STOCK, {"healing": 0, "mana": 0, "rejuv": 0}) == []


def test_it_buys_exactly_the_shortfall():
    plan = plan_purchases(FULL_STOCK, {"healing": 3, "mana": 1, "rejuv": 0})
    types = [b.potion_type for b in plan]
    assert types == ["healing", "healing", "healing", "mana"]


def test_it_round_robins_the_available_cells():
    # Three healing needed, two cells stocked: cells cycle 0,1,0 so a torn
    # read of one cell does not sink the whole order.
    plan = plan_purchases(HEAL_STOCK, {"healing": 3})
    cells = [b.potion.cell for b in plan]
    assert cells == [(0, 0), (1, 0), (0, 0)]


def test_a_type_with_no_stock_is_skipped_not_faked():
    plan = plan_purchases(HEAL_STOCK, {"healing": 1, "mana": 2})
    assert [b.potion_type for b in plan] == ["healing"]


def test_ordering_is_deterministic_healing_then_mana_then_rejuv():
    plan = plan_purchases(FULL_STOCK, {"healing": 1, "mana": 1, "rejuv": 1})
    assert [b.potion_type for b in plan] == ["healing", "mana", "rejuv"]


def test_unmet_types_reports_belt_short_types_the_vendor_lacks():
    assert unmet_types(HEAL_STOCK, {"healing": 1, "mana": 2, "rejuv": 0}) == ["mana"]
    assert unmet_types(FULL_STOCK, {"healing": 1, "mana": 1, "rejuv": 1}) == []


def test_cells_come_from_the_stock_read_not_assumed():
    # The Q4 property: a vendor whose potions sit at DIFFERENT cells than
    # last time is followed, because the plan only ever names cells that
    # came from THIS stock read.
    moved = [pot(9, "healing", (2, 1)), pot(8, "mana", (0, 3))]
    plan = plan_purchases(moved, {"healing": 1, "mana": 1})
    assert {b.potion.cell for b in plan} == {(2, 1), (0, 3)}
