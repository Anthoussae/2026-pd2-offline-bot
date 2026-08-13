"""Buying potions from Akara to fill the belt (R241 item 5).

Two halves: the pure planning (plan_purchases below, unit-tested) and
the `_RestockMixin` station that drives it live — approach Akara, open
her Trade screen (the akara.trade uipoint: Talk/Trade/Cancel, row 2,
the shared dialog-row discipline), then right-click the calibrated
potion spot until the belt reaches its minimum, verifying every
purchase by the belt count rising. The click
geometry is calibrated in T85c (config/shop_calibration.json); WHICH
potion sits at a cell is read fresh each visit (the Q4 principle).

Selling stays out of scope (ADR 2026-08-09-vendor-buying). The potion
pickup rules leave config/pickit.toml only once this station is
live-proven (R241 Q5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pd2bot import offsets
from pd2bot.behavior.town.config import TownError
from pd2bot.perception.items import VendorPotion

# restock.py is REPO/pd2bot/behavior/town/restock.py, so the repo root
# is parents[3] — NOT parents[2] (that is pd2bot/, which has no config/;
# the first live run skipped every buy because of the off-by-one).
CALIBRATION_PATH = Path(__file__).resolve().parents[3] / "config" / "shop_calibration.json"
# Clicks that produced NEITHER a belt potion NOR an inventory one — true
# mis-aims — before the type is abandoned. This replaces the old
# MAX_BUYS_PER_TYPE=12, which bounded CLICKS while believing an
# unverified click was a non-event. It is not: a vendor right-click is a
# PURCHASE wherever the potion lands, and on 2026-08-13 a belt with no
# room for the type turned that belief into ~30 potions bought straight
# into the inventory (verify never fired, the gold floor never bit —
# potions are cheap — and the client's can't-carry popup ended the run).
MAX_DEAD_CLICKS = 3
RESTOCK_GOLD_FLOOR = 5000


@dataclass(frozen=True)
class BuyClick:
    potion: VendorPotion
    potion_type: str


def plan_purchases(
    stock: list[VendorPotion], shortfall: dict[str, int]
) -> list[BuyClick]:
    """Ordered clicks to bring the belt to its minimums (pure). Healing,
    then mana, then rejuv; a type with no stock or no shortfall is
    skipped; cells round-robin so a torn read of one does not sink it."""
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
            plan.append(BuyClick(available[i % len(available)], potion_type))
    return plan


def unmet_types(stock: list[VendorPotion], shortfall: dict[str, int]) -> list[str]:
    stocked = {p.potion_type for p in stock}
    return [
        t for t in ("healing", "mana", "rejuv")
        if shortfall.get(t, 0) > 0 and t not in stocked
    ]


def load_calibration(path: Path = CALIBRATION_PATH) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


class _RestockMixin:
    """The Akara buy station. Composed into TownLayer; uses the shared
    town toolkit (open_npc_dialog, panel, config, _await, _narrate)."""


    def restock_at_akara(self, report) -> None:
        """Fill the belt from Akara if it is short and she stocks it.

        Skips silently when nothing is short. A shortfall Akara cannot
        cover (or an absent calibration) is a NOTICE, not a halt — the
        inventory refill and the belt-minimum floor still guard the run.
        """
        shortfall = self._belt_shortfall()
        if not any(v > 0 for v in shortfall.values()):
            report.log.append("restock: belt at minimums, skipped")
            return
        # A shortfall the belt cannot TAKE is not a reason to buy: the
        # game routes a bought potion to a column of its own type with
        # room (or an empty column), and otherwise into the INVENTORY.
        # `_belt_shortfall` counts bottles against minimums and knows
        # nothing about columns, so a belt whose columns are occupied by
        # other types reads "short" forever while every purchase lands
        # in the grid — the 2026-08-13 over-buy. `_belt_accepts` is the
        # routing question, asked before any gold moves.
        carried = self._carried(self.session)
        no_room = [
            t for t in ("healing", "mana")
            if shortfall.get(t, 0) > 0 and not self._belt_accepts(carried, t)
        ]
        for potion_type in no_room:
            shortfall[potion_type] = 0
        if no_room:
            self._notice(
                f"restock: {', '.join(no_room)} short but the belt has no "
                "column to take them — not buying (a bought potion would "
                "land in the inventory)"
            )
        if not any(shortfall.get(t, 0) > 0 for t in ("healing", "mana")):
            self.runlog.event(
                "town.restock", bought={}, no_room=no_room, overflowed=[],
            )
            report.log.append(
                "restock: nothing buyable (belt has no room), skipped"
            )
            return
        calib = load_calibration()
        if calib is None:
            report.log.append(
                "restock: no shop calibration (run T85c) — skipped, "
                "inventory refill still applies"
            )
            return

        player = self._read_player(self.session)
        # The user confirms vendor purchases can draw STASH gold, not just
        # carried (2026-08-10); affordability is the sum. _buy_until owns
        # the per-purchase guards: belt-verify, the inventory-landed stop,
        # the dead-click bound, and the gold floor.
        gold = (player.gold + player.gold_stash) if player is not None else 0
        if gold <= RESTOCK_GOLD_FLOOR:
            report.log.append(f"restock: gold {gold} at/under floor, skipped")
            return

        self._begin_step()
        self.open_npc_dialog(offsets.NPC_AKARA, "Akara")
        # Akara's Talk/Trade/Cancel menu, selected by the shared dialog-row
        # discipline (the charsi.trade_repair pattern): row 2, verified by
        # the shop panel opening. No hardcoding in the caller — the point
        # carries the row, select_dialog_row does the keys.
        try:
            self.select_dialog_row(
                self.point("akara.trade"),
                lambda: self._panel_open(offsets.UI_NPCSHOP),
            )
        except TownError:
            self.close_panels()
            report.log.append("restock: could not open Akara's Trade — skipped")
            return

        player = self._read_player(self.session)
        gold_before = (player.gold + player.gold_stash) if player is not None else 0
        rect = self.panel.window.client_rect()
        bought: dict[str, int] = {}
        overflowed: list[str] = []
        for potion_type in ("healing", "mana"):
            need = shortfall.get(potion_type, 0)
            spot = calib.get(potion_type)
            if need <= 0 or spot is None:
                continue
            fx, fy = spot["fraction"]
            px, py = round(fx * rect.width), round(fy * rect.height)
            got, overflow = self._buy_until(potion_type, need, px, py)
            bought[potion_type] = got
            if overflow:
                overflowed.append(potion_type)

        self.close_panels()
        player = self._read_player(self.session)
        gold_after = (player.gold + player.gold_stash) if player is not None else 0
        self.runlog.event(
            "town.restock",
            bought=bought,
            no_room=no_room,
            overflowed=overflowed,
            gold_before=gold_before,
            gold_after=gold_after,
        )
        summary = ", ".join(f"{n} {t}" for t, n in bought.items() if n) or "nothing"
        if overflowed:
            summary += (
                f" — stopped {', '.join(overflowed)} after a purchase "
                "landed in the inventory (belt out of room)"
            )
        report.log.append(f"restock: bought {summary}")
        # A residual shortfall after buying hands off to the existing
        # belt-minimum guard downstream (BeltBelowMinimum), unchanged.

    def _buy_until(
        self, potion_type: str, need: int, px: int, py: int
    ) -> tuple[int, bool]:
        """Right-click the calibrated spot until `need` more of this type
        sit in the belt. Returns (belt-verified buys, overflowed).

        Every click is a PURCHASE wherever the potion lands, so the exit
        conditions are about where the potions went, not about clicks:
        the belt count rising is a verified buy; the INVENTORY count
        rising instead means the belt has no room — the purchase still
        happened, and clicking again would buy straight into the grid
        (2026-08-13: ~30 potions that way, ended by the client's
        can't-carry popup), so the type stops immediately. Only a click
        that moved NEITHER count is a mis-aim, and those are bounded by
        `MAX_DEAD_CLICKS`. The gold floor still guards the spend.
        """
        start = self._belt_type_count(potion_type)
        inventory_start = self._inventory_type_count(potion_type)
        bought = 0
        dead_clicks = 0
        while bought < need and dead_clicks < MAX_DEAD_CLICKS:
            self._check_stop()
            player = self._read_player(self.session)
            spendable = (player.gold + player.gold_stash) if player is not None else 0
            if spendable <= RESTOCK_GOLD_FLOOR:
                self._narrate(f"restock: gold floor reached buying {potion_type}")
                break
            want = start + bought + 1
            try:
                self.panel.click(offsets.UI_NPCSHOP, px, py, button="right")
            except Exception:  # noqa: BLE001
                self._sleep(self.config.panel_settle_s)
                dead_clicks += 1
                continue
            if self._await(
                lambda w=want: self._belt_type_count(potion_type) >= w,
                self.config.verify_timeout_s,
            ):
                bought += 1
                continue
            if self._inventory_type_count(potion_type) > inventory_start:
                self._notice(
                    f"restock: a bought {potion_type} potion landed in the "
                    f"INVENTORY — the belt has no room; stopping {potion_type} "
                    f"after {bought} belt-verified buy(s)"
                )
                return bought, True
            self._sleep(self.config.panel_settle_s)
            dead_clicks += 1
        return bought, False

    def _belt_type_count(self, potion_type: str) -> int:
        # The injected polling reader, NOT read_carried_items directly:
        # verification polls at _await frequency, and the layer carries a
        # cheap reader for exactly that (see TownLayer.__init__).
        carried = self._carried(self.session)
        return sum(
            1 for i in carried.belt
            if (i.is_healing_potion and potion_type == "healing")
            or (i.is_mana_potion and potion_type == "mana")
        )

    def _inventory_type_count(self, potion_type: str) -> int:
        """How many of this type sit in the main inventory — the tell for
        a purchase the belt did not take."""
        carried = self._carried(self.session)
        return sum(
            1 for i in carried.main_inventory
            if (i.is_healing_potion and potion_type == "healing")
            or (i.is_mana_potion and potion_type == "mana")
        )
