"""Town: the stash - item deposit, gold deposit, capacity pressure.

Split from town.py 2026-08-09; method bodies unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

from pd2bot import offsets
from pd2bot.behavior.town.config import (
    PreambleReport,
    StashFull,
    TownError,
    _potion_type,
)
from pd2bot.input.gated import VK_RETURN
from pd2bot.perception.items import (
    CarriedItem,
)


class _StashMixin:
    def deposit_to_stash(
        self, keep: Callable[[CarriedItem], bool], report: PreambleReport
    ) -> None:
        """Shift+right-click every `keep` item from inventory into the stash.

        Verification is list-shrink per item (P1: true grid occupancy needs
        item sizes we cannot read). An item that survives its transfer
        attempts means a full stash or a mis-calibrated grid — both human
        problems: halt loudly (R46 Q4)."""
        # main_inventory, never `inventory`: PD2's charm space shares the
        # container and is untouchable (R60). Depositing from it would fail
        # every transfer and halt over a stash that was never full.
        # The sockets reader: `keep` is a caller's predicate and may be
        # socket-conditioned, and this is a DECISION about each item. The
        # `_gone` verification below stays on the cheap one — it asks only
        # whether a unit id is still listed.
        candidates = [
            i for i in self._carried_sockets(self.session).main_inventory if keep(i)
        ]
        # Unmovable items are filtered HERE rather than left to the caller's
        # predicate: the Horadric Cube opens on right-click instead of
        # transferring, so a pickit that says "keep" would otherwise halt
        # the whole preamble on it every single game (R67).
        to_deposit = [i for i in candidates if i.is_movable]
        skipped = len(candidates) - len(to_deposit)
        if skipped:
            report.log.append(f"stash: skipped {skipped} unmovable (cube/quest)")
        if not to_deposit:
            report.log.append("stash: nothing to deposit")
            return

        self._begin_step()
        self.open_object_panel(offsets.OBJ_STASH, "the stash", offsets.UI_STASH)

        for item in to_deposit:
            for _ in range(self.config.transfer_attempts):
                pixel = self._grid_pixel(item.position)
                self.panel.click(offsets.UI_STASH, *pixel, button="right", shift=True)

                def _gone(uid: int = item.unit_id) -> bool:
                    return all(
                        i.unit_id != uid
                        for i in self._carried(self.session).main_inventory
                    )

                if self._await(_gone, self.config.verify_timeout_s):
                    report.deposited += 1
                    break
            else:
                self._alert(
                    f"item kind {item.kind} at {item.position} never left the "
                    "inventory — stash full or grid mis-calibrated"
                )
                raise StashFull(
                    f"deposit failed after {self.config.transfer_attempts} attempts"
                )
        report.log.append(f"stash: {report.deposited} deposited")
        self.close_panels()

    # -- step 3: belt refill ---------------------------------------------------------

    # -- the inventory-management loop (R75, user-designed) ---------------------

    # What the tab signal was, and why nothing reads it any more (T15/T36/T45).
    #
    # `len(carried.stash)` is not "how full is the stash", it is "how much of
    # the classic stash is ON SCREEN": the materials tab nulls that store's
    # item-chain head, so switching to it took 18 items to 0 and back. That
    # made it the tab signal — and T36 plus a direct probe (R110) established
    # it was the ONLY one, every other store being byte-identical across
    # tabs.
    #
    # T45 finished the story. The signal is absent exactly when a PD2
    # character keeps their items in the expanded stash (location 8): the
    # classic store is empty, reads 0 on both tabs, and the inference has
    # nothing to work with. That is not a missing offset, it is a real limit
    # — and the R134 design routes around it by never asking the question.
    # `_stash_held` counts what is OWNED instead, which needs no tab at all.

    def _click_tab_toggle(self) -> None:
        point = self.point("stash.materials_tab")
        self._check_stop()
        self.panel.click(offsets.UI_STASH, *self.point_pixel(point))

    # Gone with R134, and worth knowing why rather than just that they went:
    # `ensure_materials_tab`, `ensure_regular_tab`, `_probe_stash_tab` and
    # `_switch_tab_until` all existed to answer "which tab is displayed?"
    # before depositing. T45 established that the question has no reliable
    # answer (the regular stash lists nothing on either tab when it is empty,
    # and the materials tab is not enumerable at all) AND that it does not
    # need one, because materials self-route from the regular tab. A whole
    # mechanism whose only job was an unanswerable question is now one blind
    # toggle in `deposit_all`, taken only when something actually refuses.
    #
    # The R108 lesson they carried survives in `_attempt_deposit` and
    # `send_until`: a single click that goes missing must never be read as a
    # fact about the game.

    def _cursor_is_armed(self) -> bool:
        """Is something on the cursor that will eat the next click?

        Reads the drag slot (`Inventory.pCursorItem`, R52 drill C). It
        catches a half-completed pick-up; it does NOT catch a cursor
        armed by a USED item (the identify scroll), which is a mode
        rather than a held unit — hence `_clear_cursor` below, which
        does not depend on being able to see the problem.
        """
        try:
            return self._carried(self.session).cursor_item is not None
        except Exception:  # noqa: BLE001 - a failed read must not halt a step
            return False

    def _clear_cursor(self) -> None:
        """Blind recovery between failed transfer attempts (T70 run 2).

        A right-click that USED an item instead of moving it leaves the
        cursor armed — the identify scroll waiting for a target — and
        every subsequent click feeds that instead of the stash. The loop
        then sees "the item never left" over and over and reports a full
        stash, which is how one misclick came to look like a resource
        problem twice (R112/R113, then T70 run 2).

        ESC clears an armed cursor. It also closes the stash, so the
        panel is reopened afterwards — the retry costs a couple of
        seconds, and it is spent only when something already refused.
        Verified by its effect the way every other town send is: the
        stash is reopened through the same `open_object_panel` that
        proves the panel edge.
        """
        self.close_panels()
        self._sleep(self.config.panel_settle_s)
        self.open_object_panel(offsets.OBJ_STASH, "the stash", offsets.UI_STASH)

    def _attempt_deposit(self, item: CarriedItem, *, attempts: int, verify_s: float) -> bool:
        """Shift+right-click one item toward the stash. Did it leave?"""
        for attempt in range(attempts):
            self._check_stop()
            if attempt:
                # Every retry starts from a clean cursor. Unconditional
                # rather than gated on `_cursor_is_armed`, because the
                # state that matters most (an armed identify cursor) is
                # exactly the one that read cannot see — and a retry that
                # repeats the failed click unchanged is not a retry at
                # all, the rule this project keeps relearning (object
                # clicks R161, patrol points, pathing R162).
                self._clear_cursor()
            self.panel.click(
                offsets.UI_STASH, *self._grid_pixel(item.position),
                button="right", shift=True,
            )

            def _gone(uid: int = item.unit_id) -> bool:
                return all(
                    i.unit_id != uid
                    for i in self._carried(self.session).main_inventory
                )

            if self._await(_gone, verify_s):
                self.runlog.event(
                    "stash.deposit", unit_id=item.unit_id,
                    item_kind=item.kind, quality=item.quality,
                    sockets=item.sockets, cell=list(item.position),
                    attempts=attempt + 1,
                )
                return True
        self.runlog.event(
            "stash.refused", unit_id=item.unit_id, item_kind=item.kind,
            attempts=attempts,
            reason="the item would not leave the inventory",
        )
        return False

    def _deposit_items(
        self,
        items: list[CarriedItem] | None = None,
        *,
        attempts: int,
        verify_s: float,
    ) -> tuple[int, list[CarriedItem]]:
        """Try each item into whatever tab is showing. Returns (moved, refused).

        `items` defaults to everything movable in the main inventory; pass a
        list to retry a specific set (the second deposit pass does).

        Nothing here knows or cares which tab is displayed, which is the
        point of the R134 design — see `deposit_all`.
        """
        moved, refused = 0, []
        for item in (
            self._carried(self.session).main_inventory if items is None else items
        ):
            if not item.is_movable:
                continue  # the Cube opens on right-click instead of moving
            if _potion_type(item) is not None:
                # No potion is ever stashed (R118 Q2). The exclusion must be
                # explicit here because the materials tab would happily
                # ACCEPT a rejuv — it is a material to the game, just not to
                # us any more.
                continue
            if self._attempt_deposit(item, attempts=attempts, verify_s=verify_s):
                moved += 1
            else:
                refused.append(item)
        return moved, refused

    def deposit_all(self, report: PreambleReport) -> list[CarriedItem]:
        """Empty the inventory into the stash. Returns whatever would not go.

        **Toggle on REFUSAL, not on inference (R134).** The old design
        identified the displayed tab up front, by toggling and counting what
        the regular stash listed. That count is not always a signal: on a
        character whose regular stash is empty it reads zero on both tabs,
        the identification refuses, and the whole preamble dies — which is
        exactly how stage B's first attempt ended, on a character with 350
        items in PD2's expanded stash and none in the classic one.

        Two live findings (T45) removed the need to identify it at all:

        1. **A material self-routes.** Shift+right-click a rune or gem with
           the REGULAR tab displayed and it goes to materials anyway (the
           user's observation at the R134 gate, confirmed: the gem left the
           inventory while the regular stash stayed at zero).
        2. **The materials tab is not readable.** That gem landed somewhere
           the player's inventory chain does not enumerate — its kind never
           appeared in the expanded container either. So there was never a
           count to identify the materials tab BY, which retro-explains
           T15/T36 finding no store for it.

        So: deposit onto whatever tab happens to be up, and let the game
        classify (still R75's good idea — no item taxonomy to go stale).
        Verification is per item and tab-independent: the item leaves the
        inventory. Only if something refuses does the tab become a question
        at all, and then the answer is a BLIND toggle and one retry, because
        the effect settles it either way. Still refused after that means the
        stash is genuinely full.

        The two passes are tuned in opposite directions on purpose. Pass one
        fails fast — a refusal there is cheap, pass two fixes it. Pass two is
        patient, because a refusal there is terminal.
        """
        moved, refused = self._deposit_items(
            attempts=self.config.first_pass_attempts,
            verify_s=self.config.first_pass_verify_s,
        )
        report.log.append(f"stash: {moved} deposited on the displayed tab")
        if refused:
            # The blind toggle. No condition to verify it by — that is the
            # whole problem — so this is the one send in the town layer that
            # is not effect-verified in itself. What IS verified is the
            # retry: if the items go now, the toggle worked, and if they do
            # not, they were never going anywhere.
            self._sleep(self.config.panel_settle_s)
            self._click_tab_toggle()
            self._sleep(self.config.tab_settle_s)
            retried, refused = self._deposit_items(
                refused,
                attempts=self.config.transfer_attempts,
                verify_s=self.config.verify_timeout_s,
            )
            moved += retried
            report.log.append(
                f"stash: {retried} more after switching tab "
                f"({len(refused)} still refused)"
            )
        report.deposited = moved
        return refused

    def deposit_gold(self, report: PreambleReport) -> int:
        """Bank the carried gold. Returns the amount moved.

        Click the gold button, press Enter, and check the balance — because
        the balance is all there is to check. **The amount dialog raises no
        panel flag** (T37), so unlike every other panel in this layer its
        presence cannot be verified before acting, and the usual
        settle-then-confirm-the-flag pattern has nothing to confirm.

        That makes a missed click genuinely hazardous rather than merely
        useless: with no dialog open, the Enter is the key that opens the
        CHAT CONSOLE (R89's mechanism, from the other side), leaving a
        blocking panel behind. So a failed attempt clears any console before
        retrying, and the proof of success is carried gold actually falling.
        """
        player = self._read_player(self.session)
        if player is None:
            raise TownError("player unreadable at gold-deposit time")
        carried = player.gold
        if carried == 0:
            report.log.append("gold: none carried")
            return 0
        # Keep a working reserve on the character so the Akara restock has
        # money to spend (R241): the deposit dialog banks ALL carried gold,
        # so depositing whenever any is carried left the bot broke every
        # run and the restock could never buy — found live 2026-08-10.
        # Below the reserve, skip the deposit entirely; a level-92 necro is
        # nowhere near the carry cap, so gold on hand is harmless.
        if carried <= self.config.gold_reserve:
            report.log.append(
                f"gold: {carried} carried, kept as restock reserve "
                f"(<= {self.config.gold_reserve})"
            )
            return 0
        point = self.point("stash.gold_button")

        def carried_now() -> int:
            now = self._read_player(self.session)
            return now.gold if now else carried

        for attempt in range(1 + self.config.panel_click_retries):
            self._check_stop()
            if attempt:
                self._dismiss_chat_console()
            self._sleep(self.config.panel_settle_s)
            if not self._panel_open(offsets.UI_STASH):
                break
            self.panel.click(offsets.UI_STASH, *self.point_pixel(point))
            # Nothing to wait FOR — the dialog is invisible to us — so this
            # is a settle, not a verification.
            self._sleep(self.config.panel_settle_s)
            self.panel.press_key(offsets.UI_STASH, VK_RETURN)
            if self._await(
                lambda: carried_now() < carried, self.config.verify_timeout_s
            ):
                moved = carried - carried_now()
                report.log.append(f"gold: {moved} deposited")
                self.runlog.event(
                    "stash.gold", amount=moved, before=carried,
                    after=carried_now(),
                )
                return moved
        self._dismiss_chat_console()
        raise TownError(
            f"gold deposit had no effect: still carrying {carried_now()} after "
            f"{1 + self.config.panel_click_retries} attempts — the gold button "
            "may have moved, and note the dialog is invisible to perception "
            "so a miss cannot be distinguished from a refusal (T37)"
        )

    def _stash_held(self) -> int:
        """Every stashed item the inventory chain can see, both containers.

        The classic stash (`STORAGE_STASH`) and PD2's expanded one
        (`STORAGE_EXPANDED_STASH`) are counted together because a human
        thinks of them as one place with tabs, and because counting only the
        classic one measures nothing on a character who uses the other:
        location 7 read ZERO while location 8 held 350 items (T45's probe),
        which is the shape that broke stage B.

        Materials are NOT counted, because they cannot be — T45 put a gem in
        there and it left the readable world entirely. That is a real limit,
        stated here rather than hidden behind a number that looks complete.
        """
        return sum(
            1
            for i in self._carried(self.session).items
            if i.game_location
            in (offsets.STORAGE_STASH, offsets.STORAGE_EXPANDED_STASH)
        )

    def warn_on_stash_pressure(self, report: PreambleReport) -> None:
        """Say the stash is filling up, while there is still time to act.

        Deliberately a warning and never a halt. The count is a lower bound
        on occupancy — a 2x4 armour and a rune both count as one item, and
        the sizes that would turn this into real arithmetic are not readable
        (P1) — so acting on it would mean stopping runs over a number that
        can be wrong in the direction that matters. The alert is the whole
        feature: `StashFull` is a hard stop with no workaround (the bot
        cannot make room), and arriving at it with no notice is the part
        worth fixing (R132).

        Unlike the old tab inference this does not care which tab is
        displayed: it counts what the character OWNS, not what is on screen.
        """
        held = self._stash_held()
        report.log.append(f"stash: {held} items stashed")
        if held < self.config.stash_pressure_at or self._pressure_warned:
            # Once per session, not once per run. A warning that repeats
            # every game is noise, and noise is how people learn to ignore
            # alerts — which would cost us the one that matters.
            return
        self._pressure_warned = True
        self._notice(
            f"stash pressure: {held} items stashed (warning at "
            f"{self.config.stash_pressure_at}). Item sizes are unreadable and "
            "the materials tab cannot be counted at all, so this is a floor, "
            "not an occupancy — clear space before a deposit refuses and "
            "halts the session. The run continues."
        )

