"""Buying potions from a vendor to fill the belt (R241 item 5).

The pure planning half lives here — given what the vendor stocks and
what the belt is short, produce the ordered list of cells to click —
so it is fully testable without the game. The clicking half is a
`_RestockMixin` method on the town layer that walks this plan against
the shop grid (calibrated in T85); its live behaviour is proven in the
standing-mandate batch, and only THEN do the potion pickup rules leave
config/pickit.toml (the plan's Q5 ordering — never a gap where the belt
has neither source).
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot.perception.items import VendorPotion


@dataclass(frozen=True)
class BuyClick:
    """One purchase: which stocked potion to click, and why."""

    potion: VendorPotion
    potion_type: str


def plan_purchases(
    stock: list[VendorPotion],
    shortfall: dict[str, int],
) -> list[BuyClick]:
    """The ordered clicks that would bring the belt up to its minimums.

    `shortfall` is the belt.py computation: potion type -> how many more
    are needed. For each type we emit that many BuyClicks, each naming a
    stocked potion of that type (vendors restock instantly on purchase,
    so the SAME cell can be clicked repeatedly — but we round-robin the
    available cells so a torn read of one cell does not sink the whole
    order). Types with no matching stock are skipped and reported by the
    caller; a type with zero shortfall contributes nothing.

    Pure: no game, no clicks. Determinism matters (a resume must replan
    identically), so ordering is healing, mana, rejuv, and within a type
    the stock's own order.
    """
    by_type: dict[str, list[VendorPotion]] = {}
    for potion in stock:
        by_type.setdefault(potion.potion_type, []).append(potion)

    plan: list[BuyClick] = []
    for potion_type in ("healing", "mana", "rejuv"):
        need = shortfall.get(potion_type, 0)
        available = by_type.get(potion_type, [])
        if need <= 0 or not available:
            continue
        for i in range(need):
            plan.append(
                BuyClick(potion=available[i % len(available)], potion_type=potion_type)
            )
    return plan


def unmet_types(
    stock: list[VendorPotion], shortfall: dict[str, int]
) -> list[str]:
    """Belt-short potion types the vendor does not stock — the caller
    warns on these (a healing shortfall Akara cannot fill is worth a
    notice, though never a halt: the inventory refill is still the
    fallback, and the belt-minimum halt still guards the floor)."""
    stocked = {p.potion_type for p in stock}
    return [
        t for t in ("healing", "mana", "rejuv")
        if shortfall.get(t, 0) > 0 and t not in stocked
    ]
