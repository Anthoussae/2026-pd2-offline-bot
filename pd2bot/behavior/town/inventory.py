"""Town: the inventory - drop, protect, cleanse, manage.

Split from town.py 2026-08-09; method bodies unchanged.
"""

from __future__ import annotations

from pd2bot import offsets
from pd2bot.behavior.town.config import (
    PreambleReport,
    StashFull,
    TownError,
)
from pd2bot.input.gated import VK_I
from pd2bot.perception.items import (
    CarriedItem,
)


class _InventoryMixin:
    def drop_item(self, item: CarriedItem) -> bool:
        """Ctrl+right-click one inventory item onto the ground. Did it leave?

        MUST run with the stash CLOSED: gesture meaning depends on what is
        open (the R64 lesson — the same shift-click stashes or belts an item
        depending on the stash), and ctrl-clicks are quick-move gestures in
        several mods when a container is up. With only the inventory open
        there is nowhere for the item to go but the floor, so "gone from the
        inventory" is proof of the drop.

        The ctrl is settled on both sides of the click by PanelInput (the
        R113 modifier race): an UNMODIFIED right-click here would drink a
        potion or use a tome — the exact incident that bought the settle.
        """
        if self._panel_open(offsets.UI_STASH):
            raise TownError(
                "refusing to drop an item with the stash open — gesture "
                "meaning depends on open panels (R64), and this one must "
                "mean 'to the floor'"
            )
        for _ in range(self.config.transfer_attempts):
            self._check_stop()
            self.panel.click(
                offsets.UI_INVENTORY, *self._grid_pixel(item.position),
                button="right", ctrl=True,
            )

            def _gone(uid: int = item.unit_id) -> bool:
                return all(
                    i.unit_id != uid
                    for i in self._carried(self.session).main_inventory
                )

            if self._await(_gone, self.config.verify_timeout_s):
                return True
        return False

    def _protected(self) -> set[int]:
        """Unit ids the cleanse may not drop.

        **The default protects everything, not nothing.** A caller that
        supplies a whitelist but forgets the baseline would otherwise get
        the most destructive configuration available by doing half the
        wiring — and the audit in T43 showed what that costs: 4 of 12
        carried items would have gone on the floor, including a magic
        grand charm the keep list never mentions.

        So with no baseline supplied, one is captured the first time the
        cleanse runs. Everything present then predates the bot's own
        accidents by definition, which is exactly the set this feature
        must not touch. A session-wide baseline is still better and the
        wiring should pass one; this is the floor, not the goal.
        """
        if self._protected_ids is not None:
            return self._protected_ids()
        if self._implicit_baseline is None:
            self._implicit_baseline = {
                i.unit_id for i in self._carried(self.session).main_inventory
            }
        return self._implicit_baseline

    def cleanse_inventory(self, report: PreambleReport) -> int:
        """Drop accidental-pickup junk on the ground (R117).

        Junk = movable, not a potion, and not recognised by the whitelist.
        With no whitelist wired (None), this does nothing at all — the
        fail-safe default, active while the pickit vocabulary still has
        unverified ids, because a whitelist that cannot recognise a quest
        item must never be allowed to throw one away (pickit.cleanse_keep).

        A stuck item is alerted and LEFT (it falls through to the stash
        phases): failing to drop junk costs stash space, not correctness,
        and halting the whole preamble over garbage would invert the
        priorities.

        **It reports on every path, including the ones where it does
        nothing** (user request, 2026-08-01). It used to log only when it
        actually dropped something, so the two silent returns below — no
        whitelist wired at all, and nothing judged junk — were
        indistinguishable from each other AND from the cleanse never
        having run. A run where junk reached the stash could not be told
        apart from one where the cleanse looked and found nothing, which
        made the feature unfalsifiable: there was no observation that
        could show it was broken. The user's rule is that only
        whitelisted items and the Horadric Cube stay, so the report names
        every kept item and WHY it was kept — that rule is checkable
        against this log, and was checkable against nothing before.

        **The baseline policy is CONFIRMED as designed (user, R172):**
        items that predate the current bot session are protected — for
        the whole session, indefinitely if the user never clears them by
        hand, and that is the intended outcome, not a leak. Within a
        session the cleanse is ruthless. The Horadric Cube is always
        protected regardless of any of this (offsets.UNMOVABLE_KINDS —
        policy as well as mechanics). Do not "fix" pre-session survivors
        by re-baselining per game without a fresh user decision.
        """
        if self._keep_item is None:
            report.log.append(
                "cleanse: DISABLED and nothing was examined — no whitelist is "
                "wired, because the pickit vocabulary still has unverified "
                "item ids (pickit.cleanse_keep returns None). A whitelist "
                "that cannot recognise a quest item must not be allowed to "
                "throw one away."
            )
            return 0
        protected = self._protected()
        # The one place sockets are needed: `_keep_item` is the pickit's
        # whitelist and several of its rules are socket-conditioned, so an
        # item read without them has `sockets=None` — which reads as "keep"
        # and would silently turn the cleanse into a no-op for exactly the
        # bases it exists to protect (R132).
        carried = self._carried_sockets(self.session).main_inventory
        junk: list = []
        kept: list[tuple[object, str]] = []
        for item in carried:
            if not item.is_movable:
                # Name the actual member: the unmovable set now holds the
                # Cube, the tomes, the SCROLLS and dungeon MAPS (the item-
                # exception registry, P5), so "unmovable (the Cube)" printed
                # against a tome reads like a bug in the report (T70 run 3
                # did exactly that, three times in one preamble). The reason
                # comes from the registry, so each names itself.
                kept.append(
                    (item, f"unmovable ({offsets.unmovable_reason(item.kind)})")
                )
            elif item.kind in offsets.RIGHT_CLICK_HAZARD_KINDS:
                # Only POTIONS reach here now: everything else with a
                # harmful right-click is also unmovable and caught above.
                kept.append((item, "right-click hazard (potion)"))
            elif item.unit_id in protected:
                # The likeliest reason junk survives, and it was invisible.
                # The baseline is captured the first time the cleanse runs
                # and protects everything present THEN, so anything already
                # in the inventory when the bot started is protected for the
                # whole session — including junk the user wanted gone.
                kept.append((item, "protected: predates this bot session"))
            elif self._keep_item(item):
                kept.append((item, "whitelisted by the pickit"))
            else:
                junk.append(item)

        summary = (
            f"cleanse: {len(carried)} item(s) in the inventory, "
            f"{len(junk)} judged junk, {len(kept)} kept"
        )
        for item, why in kept:
            report.log.append(
                f"cleanse: KEEP kind {item.kind} quality {item.quality} "
                f"sockets {item.sockets} at {item.position} — {why}"
            )
        if not junk:
            report.log.append(f"{summary}; nothing to drop")
            return 0
        self._begin_step()
        self.press_inventory_open()
        dropped = 0
        for item in junk:
            if self.drop_item(item):
                dropped += 1
                continue
            # STOP, rather than move on to the next item. A drop that did
            # not land means the gesture did not do what we asked, and the
            # most likely reason is the ctrl modifier not registering — in
            # which case every further attempt is an unmodified right-click
            # on an inventory item, which USES it. Stage B run 4 opened a
            # town portal that way. One surprise is recoverable; carrying on
            # through the rest of the inventory turns it into a sequence.
            self._alert(
                f"junk item kind {item.kind} at {item.position} would not "
                "drop — abandoning the cleanse for this game rather than "
                "aiming the same gesture at more items. The rest falls "
                "through to the stash phases."
            )
            break
        self.close_panels()
        # Name what went on the floor, not just how many. "3 dropped" is
        # not something the user can check the keep-rule against; a kind
        # and a quality is.
        for item in junk[:dropped]:
            report.log.append(
                f"cleanse: DROP kind {item.kind} quality {item.quality} "
                f"sockets {item.sockets} at {item.position}"
            )
        report.log.append(
            f"{summary}; {dropped} dropped"
            + (
                f", {len(junk) - dropped} left behind (a drop did not land)"
                if dropped < len(junk)
                else ""
            )
        )
        return dropped

    def manage_inventory(self, report: PreambleReport) -> None:
        """The inventory loop: belt, drink, cleanse, materials, regular.

        The R75 design amended by R117/R118: belt filled first, the
        inventory keeps a reserve of `potion_reserve` per potion type, ALL
        excess is drunk (rejuvs included), **no potion is ever stashed**,
        and accidental-pickup junk is dropped before the stash phases.

        The good idea underneath is still the user's: **the game does the
        classification**. Attempting every non-potion into the materials
        tab and keeping whatever it accepts means the bot needs no item
        taxonomy — precisely the kind of knowledge that goes stale every
        patch. Potions are the one category it must recognise, and it
        already does.

        Panel state is part of the instruction, not ambient context (R64):
        shift-click means inventory->belt with the stash CLOSED and
        inventory<->stash with it OPEN. So the belt and drinking phases run
        with the stash shut, and only then is the stash opened.

        Replaces `deposit_to_stash` + `refill_belt` as a pair; both remain
        for the drills that test them in isolation.
        """
        self._begin_step()
        if self._carried(self.session).main_inventory:
            # Stash CLOSED for all of these: gesture meaning depends on what
            # is open (R64) — shift-click belts a potion only while it is
            # shut, and the drop gesture must have nowhere to send an item
            # but the floor. Fill the belt BEFORE drinking, so that what
            # gets drunk is genuinely surplus rather than potions the belt
            # had room for; drink down to the reserve (R118: 2 per type
            # stay); then drop whatever the whitelist disowns (R117).
            self.press_inventory_open()
            self.fill_belt(report)
            self.drink_excess_potions(report)
            self.close_panels()
            self.cleanse_inventory(report)
        self.assert_belt_minimums(report)

        carried = self._carried(self.session).main_inventory
        remaining = [i for i in carried if i.is_movable]
        unmovable = len(carried) - len(remaining)
        if not remaining:
            # Say what is being left behind even on the do-nothing path: an
            # inventory holding only the Cube looks identical to an empty one
            # in the report otherwise, and the difference matters when a
            # later run halts on a full inventory.
            report.log.append(
                "stash: nothing left to deposit"
                + (f"; skipped {unmovable} unmovable (cube/quest)" if unmovable else "")
            )
            return

        self._begin_step()
        self.open_object_panel(offsets.OBJ_STASH, "the stash", offsets.UI_STASH)
        self._sleep(self.config.tab_settle_s)  # the list arrives progressively

        refused = self.deposit_all(report)

        self.warn_on_stash_pressure(report)

        skipped = [
            i for i in self._carried(self.session).main_inventory if not i.is_movable
        ]
        if skipped:
            report.log.append(f"stash: skipped {len(skipped)} unmovable (cube/quest)")
        # Gold last, while the stash is still open (R75). Deliberately after
        # the items: it is the only step that cannot verify what it is
        # talking to, so it runs when nothing else depends on what follows.
        self.deposit_gold(report)
        self.close_panels()

        if refused:
            # Survived both tabs — but "refused" is NOT "the stash is
            # full", and asserting that cost two live sessions (R112 and
            # T70 run 2, both a misclicked tome). The evidence is right
            # here and was never consulted: if other items deposited in
            # this same visit, the stash plainly had room, so the item is
            # the problem, not the container. This is the belt-full
            # lesson (T56/T57) applied to the stash, fifteen days late —
            # there, "would not come up after 3 clicks" was diagnosed as
            # a full belt until it was evidence-checked against live
            # counts, and the same shape sat here untouched.
            kinds = sorted({i.kind for i in refused})
            detail = (
                f"{len(refused)} item(s) left in the inventory after both "
                f"deposit passes (kinds {kinds})"
            )
            if report.deposited:
                # Not a full stash: things went in. Notice and continue —
                # the run is not worth ending over one stubborn item, the
                # policy the user set for the belt-short case (R208).
                self._alert(
                    f"{len(refused)} item(s) (kinds {kinds}) would not "
                    f"stash, but {report.deposited} other item(s) did — so "
                    "the stash has room and these items are the problem "
                    "(a right-click side effect, or a grid mis-read). "
                    "Leaving them in the inventory and carrying on."
                )
                report.log.append(f"stash: {detail} — carried on")
                return
            self._alert(
                f"{detail}, and NOTHING deposited this visit — a stash is "
                "full (the materials tab cannot be measured, so it may be "
                "that one), or the grid calibration is wrong"
            )
            raise StashFull(detail)

    def press_inventory_open(self) -> None:
        """Open the inventory panel, verified, retried like every other send."""
        if self._panel_open(offsets.UI_INVENTORY):
            return
        self.send_until(
            lambda: self.gated.press_key(VK_I),
            lambda: self._panel_open(offsets.UI_INVENTORY),
            what="opening the inventory",
        )

    # -- step 4: conditional merc resurrect ---------------------------------------------

