"""Town: the belt - fill, minimums, excess potions, refill.

Split from town.py 2026-08-09; method bodies unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

from pd2bot import offsets
from pd2bot.behavior.town.config import (
    BeltBelowMinimum,
    PreambleReport,
    _potion_type,
)
from pd2bot.perception.items import (
    CarriedItem,
    CarriedItems,
)


class _BeltMixin:
    def fill_belt(self, report: PreambleReport) -> int:
        """Move every potion the belt will take — not merely enough to reach
        the minimums.

        The distinction matters inside the R75 loop and is where it differs
        from the older `refill_belt` step (R48). Topping up to minimums and
        then drinking the rest throws away potions the belt had room for; the
        loop's "drink the excess" only means anything if the belt is FULL
        first, so that what remains is genuinely excess (user, R107).

        A column that will not take another potion is how the belt reports
        itself full — shift-click routes by type, so a refusal is per type,
        not global, and the other types keep going.
        """
        moved = 0
        full: set[str] = set()
        while True:
            self._check_stop()
            carried = self._carried(self.session)
            pool = [
                i
                for i in carried.main_inventory
                if _potion_type(i) is not None and _potion_type(i) not in full
            ]
            if not pool:
                break
            potion = pool[0]
            before = len(carried.belt)
            self.panel.click(
                offsets.UI_INVENTORY, *self._grid_pixel(potion.position), shift=True
            )
            if self._await(
                lambda b=before: len(self._carried(self.session).belt) > b,
                self.config.verify_timeout_s,
            ):
                moved += 1
            else:
                # By TYPE, not by kind: the belt routes by column, so a full
                # healing column is full for every healing kind. Keying this
                # on `potion_name` (which is per-kind, "healing_606") would
                # retry the same full column for each variant.
                full.add(_potion_type(potion))
        report.refilled += moved
        report.log.append(
            f"belt: {moved} moved"
            + (f"; full for {', '.join(sorted(full))}" if full else "")
        )
        return moved

    def assert_belt_minimums(self, report: PreambleReport) -> None:
        """Halt ONLY for a real failure; merely missing potions is normal.

        The old contract halted on any unmet minimum, and R178 showed what
        that costs: a mana potion squatting in a healing column left the
        count short, the preamble halted a healthy run at 2 AM, and the
        user had to restock a belt that nothing was wrong with. The user's
        rule (R179) is the new contract: minimums are met WHEN STOCK
        ALLOWS, emptiness is normal, and the halt-for-a-human fires only
        when the refill mechanically failed — a type is short while the
        inventory holds that type AND the belt has a column that would
        take it, which means the clicks themselves are not landing.
        """
        shortfall = self._belt_shortfall()
        if not any(shortfall.values()):
            report.log.append("belt: minimums hold")
            return
        carried = self._carried(self.session)
        stock: dict[str, int] = {"healing": 0, "mana": 0, "rejuv": 0}
        for item in carried.main_inventory:
            potion_type = _potion_type(item)
            if potion_type is not None:
                stock[potion_type] += 1
        mechanical = [
            potion_type
            for potion_type, short in shortfall.items()
            if short and stock[potion_type] and self._belt_accepts(carried, potion_type)
        ]
        missing = ", ".join(f"{k} short {v}" for k, v in shortfall.items() if v)
        if mechanical:
            self._alert(
                f"belt refill is mechanically failing: {missing}, with "
                f"{', '.join(mechanical)} stock in the inventory and belt room "
                "to take it — the clicks are not landing; a human should look"
            )
            raise BeltBelowMinimum(missing)
        self._notice(
            f"belt short ({missing}) with no loadable stock — continuing; "
            "restock when convenient"
        )
        report.log.append(f"belt: short ({missing}), no loadable stock — continuing")

    def _belt_accepts(self, carried: CarriedItems, potion_type: str) -> bool:
        """Would a shift-click of this type land somewhere in the belt?

        The game routes a belted potion to a column of its own type with
        room, or to an empty column. A column holding ANY other type is
        not a home for this one — that is how a misplaced potion "counts
        where it sits" (R179): it spends a slot of whatever column it
        squats in, and the capacity sums honestly around it. A mixed
        column is conservatively counted as accepting nothing; the cost
        of underestimating room here is a quieter run, never a halt.
        """
        for column in range(offsets.BELT_COLUMNS):
            occupants = [i for i in carried.belt if i.belt_column == column]
            if len(occupants) >= offsets.BELT_ROWS:
                continue
            if not occupants or all(
                _potion_type(i) == potion_type for i in occupants
            ):
                return True
        return False

    def _dismiss_chat_console(self) -> None:
        """Close a chat console opened by an Enter that missed its dialog.

        Cheap insurance in exactly one place: gold is the only step that
        sends Enter without being able to confirm what will receive it.
        """
        if self._panel_open(offsets.UI_CHAT_CONSOLE):
            self.send_until(
                self.menu.press_escape,
                lambda: not self._panel_open(offsets.UI_CHAT_CONSOLE),
                what="closing a chat console left by a stray Enter",
            )

    def _excess_potions(self) -> list[CarriedItem]:
        """Inventory potions beyond the per-type reserve (R118 Q1).

        The first `potion_reserve` of each type are the keepers; everything
        past them is excess. Which particular bottles stay is deliberately
        not interesting — they are interchangeable within a type.
        """
        seen: dict[str, int] = {}
        excess = []
        for item in self._carried(self.session).main_inventory:
            potion_type = _potion_type(item)
            if potion_type is None:
                continue
            seen[potion_type] = seen.get(potion_type, 0) + 1
            if seen[potion_type] > self.config.potion_reserve:
                excess.append(item)
        return excess

    def drink_excess_potions(self, report: PreambleReport) -> int:
        """Drink inventory potions down to the per-type reserve.

        Runs after the belt is filled, so what is left is genuinely excess.
        ALL types are drunk, rejuvenations included — the R118 Q2 decision
        ("easy and clean"), superseding R75's rejuvs-to-materials — and no
        potion is ever stashed, so drinking is the only outlet.

        Drinking always works, even at full health (R75), so a potion that
        does not disappear was not clicked — worth reporting, not worth a
        fallback.
        """
        drunk = 0
        while True:
            self._check_stop()
            excess = self._excess_potions()
            if not excess:
                break
            potion = excess[0]
            self.panel.click(
                offsets.UI_INVENTORY, *self._grid_pixel(potion.position),
                button="right",
            )

            def _gone(uid: int = potion.unit_id) -> bool:
                return all(
                    i.unit_id != uid
                    for i in self._carried(self.session).main_inventory
                )

            if not self._await(_gone, self.config.verify_timeout_s):
                report.log.append(
                    f"drink: potion {potion.kind} at {potion.position} would "
                    "not drink — stopping rather than clicking in a loop"
                )
                break
            drunk += 1
        if drunk:
            report.log.append(f"drink: {drunk} excess potion(s)")
        return drunk

    def _belt_shortfall(self) -> dict[str, int]:
        carried = self._carried(self.session)
        healing = sum(1 for i in carried.belt if i.is_healing_potion)
        mana = sum(1 for i in carried.belt if i.is_mana_potion)
        rejuv = carried.belt_rejuv_count
        return {
            "healing": max(0, self.config.min_healing - healing),
            "mana": max(0, self.config.min_mana - mana),
            "rejuv": max(0, self.config.min_rejuv - rejuv),
        }

    def refill_belt(self, report: PreambleReport) -> None:
        """Shift-click inventory potions into the belt until minimums hold.

        Runs with ONLY the inventory open: the same click with the stash up
        would route the potion to the stash instead (see module docstring).
        """
        shortfall = self._belt_shortfall()
        if any(shortfall.values()):
            # Only the inventory may be up: with the stash also open, the
            # same shift-click sends the potion to the stash instead.
            self._begin_step()
            if not self._panel_open(offsets.UI_INVENTORY):
                # Retried like every other send: this one follows the ESC
                # that `_begin_step` just issued, which is precisely the
                # frame where a keypress is most likely to be eaten (R94).
                self.send_until(
                    lambda: self.gated.press_key(self.bindings.inventory),
                    lambda: self._panel_open(offsets.UI_INVENTORY),
                    what="opening the inventory for the refill",
                )

            selectors: dict[str, Callable[[CarriedItem], bool]] = {
                "healing": lambda i: i.is_healing_potion,
                "mana": lambda i: i.is_mana_potion,
                "rejuv": lambda i: i.is_rejuv_potion,
            }
            for kind_name, needed in shortfall.items():
                matches = selectors[kind_name]
                for _ in range(needed):
                    pool = [
                        i
                        for i in self._carried(self.session).main_inventory
                        if matches(i)
                    ]
                    if not pool:
                        break  # inventory exhausted; the minimum check decides
                    potion = pool[0]
                    before = len(self._carried(self.session).belt)
                    pixel = self._grid_pixel(potion.position)
                    self.panel.click(offsets.UI_INVENTORY, *pixel, shift=True)
                    if self._await(
                        lambda b=before: len(self._carried(self.session).belt) > b,
                        self.config.verify_timeout_s,
                    ):
                        report.refilled += 1
            self.close_panels()

        report.log.append(f"belt: {report.refilled} moved")
        self.assert_belt_minimums(report)

