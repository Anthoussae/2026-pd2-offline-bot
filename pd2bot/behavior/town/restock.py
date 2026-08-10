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
from pd2bot.perception.items import VendorPotion, read_carried_items

# restock.py is REPO/pd2bot/behavior/town/restock.py, so the repo root
# is parents[3] — NOT parents[2] (that is pd2bot/, which has no config/;
# the first live run skipped every buy because of the off-by-one).
CALIBRATION_PATH = Path(__file__).resolve().parents[3] / "config" / "shop_calibration.json"
# Buying is bounded per type so a mis-verify cannot drain gold forever.
MAX_BUYS_PER_TYPE = 12
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
        calib = load_calibration()
        if calib is None:
            report.log.append(
                "restock: no shop calibration (run T85c) — skipped, "
                "inventory refill still applies"
            )
            return

        player = self._read_player(self.session)
        # The user confirms vendor purchases can draw STASH gold, not just
        # carried (2026-08-10); affordability is the sum. If a buy does not
        # register, the belt-count verify in _buy_until is the backstop —
        # bounded attempts, no runaway spend.
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

        rect = self.panel.window.client_rect()
        bought: dict[str, int] = {}
        for potion_type in ("healing", "mana"):
            need = shortfall.get(potion_type, 0)
            spot = calib.get(potion_type)
            if need <= 0 or spot is None:
                continue
            fx, fy = spot["fraction"]
            px, py = round(fx * rect.width), round(fy * rect.height)
            bought[potion_type] = self._buy_until(potion_type, need, px, py)

        self.close_panels()
        summary = ", ".join(f"{n} {t}" for t, n in bought.items() if n) or "nothing"
        report.log.append(f"restock: bought {summary}")
        # A residual shortfall after buying hands off to the existing
        # belt-minimum guard downstream (BeltBelowMinimum), unchanged.

    def _buy_until(self, potion_type: str, need: int, px: int, py: int) -> int:
        """Right-click the calibrated spot until `need` more of this type
        sit in the belt (or the bounded attempts run out). Every buy is
        verified by the belt count rising; a click that does not move it
        is not counted, and the gold floor stops the spend."""
        start = self._belt_type_count(potion_type)
        bought = 0
        for _ in range(need + MAX_BUYS_PER_TYPE):
            self._check_stop()
            if bought >= need:
                break
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
                continue
            if self._await(
                lambda w=want: self._belt_type_count(potion_type) >= w,
                self.config.verify_timeout_s,
            ):
                bought += 1
            else:
                self._sleep(self.config.panel_settle_s)
        return bought

    def _belt_type_count(self, potion_type: str) -> int:
        carried = read_carried_items(self.session, with_sockets=False)
        return sum(
            1 for i in carried.belt
            if (i.is_healing_potion and potion_type == "healing")
            or (i.is_mana_potion and potion_type == "mana")
        )
