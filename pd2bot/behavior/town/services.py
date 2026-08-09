"""Town: NPC services - heal at Akara, repair at Charsi, merc resurrect.

Split from town.py 2026-08-09; method bodies unchanged.
"""

from __future__ import annotations

from pd2bot import offsets
from pd2bot.behavior.town.config import (
    PreambleReport,
    TownError,
    Uncalibrated,
)
from pd2bot.perception.items import (
    read_equipped_durability,
)


class _ServiceMixin:
    def heal_at_akara(self, report: PreambleReport) -> None:
        """Interact with Akara until vitals read full. The heal applies on
        opening her dialog; the NPC-menu flag going up is the interaction
        proof, full hp/mana is the effect proof — we require the effect.

        The effect proof is load-bearing, not belt-and-braces: the NPC kind
        table is inference, not observation (see offsets.NPC_KINDS), and
        T12's first run proved it wrong by opening a dialog with Kashya. So
        a dialog that opens but does not heal must accuse the *identity*,
        which is why the failure names the kind and position it clicked.
        """
        player = self._read_player(self.session)
        if player is None:
            raise TownError("player unreadable at heal time")
        hp_pct = 100.0 * player.hp / player.max_hp if player.max_hp else 0.0
        mana_pct = (
            100.0 * player.mana / player.max_mana if player.max_mana else 100.0
        )
        merc = self.snapshot().merc
        merc_ok = merc is None or merc.life_pct >= self.config.heal_skip_merc_pct
        if (
            hp_pct >= self.config.heal_skip_hp_pct
            and mana_pct >= self.config.heal_skip_mana_pct
            and merc_ok
        ):
            # Effectively full (T1, R186): the cross-town walk buys a
            # sliver the first potion covers. A hurting merc still earns
            # the trip — Akara heals it for free.
            report.healed = True
            report.log.append(
                f"heal: skipped (hp {hp_pct:.0f}%, mana {mana_pct:.0f}%"
                + (f", merc {merc.life_pct:.0f}%" if merc is not None else "")
                + ")"
            )
            return

        self._begin_step()
        talked_to = None
        # Approach and dialog failures propagate with their own diagnosis —
        # they say far more than anything this step could add. What is
        # retried here is the EFFECT: a dialog that opened but did not heal.
        for _ in range(1 + self.config.interact_retries):
            talked_to = self.open_npc_dialog(offsets.NPC_AKARA, "Akara")
            self.close_panels()

            def _full() -> bool:
                now = self._read_player(self.session)
                return now is not None and now.hp == now.max_hp and now.mana == now.max_mana

            if self._await(_full, self.config.verify_timeout_s):
                report.healed = True
                report.log.append("heal: vitals read full")
                return

        raise TownError(
            f"opened a dialog with kind {offsets.NPC_AKARA} at {talked_to} "
            "but vitals did not fill — that NPC does not heal, so the kind "
            "table is wrong (run the T17 proximity drill), not the clicking"
        )

    # -- step 1b: repair -------------------------------------------------------------

    def repair_at_charsi(self, report: PreambleReport) -> None:
        """Repair worn gear at the smith, when anything is actually worn.

        Two clicks deep into NPC UI (dialog row, then the shop's repair
        button), so both positions are hover-calibrated fractions and an
        uncalibrated build refuses rather than guessing. The proof is the
        effect: durability read back off the worn items must stop being
        short. Menu rows can shift with NPC state (the R56 lesson from
        Kashya), and verifying by effect is what makes that survivable —
        a mis-aimed row click leaves the gear worn and says so.
        """
        worn = read_equipped_durability(self.session)
        # Pristine gear is the one case worth skipping: the walk would buy
        # nothing and the trip could not be verified either way.
        damaged = [
            d
            for d in worn
            if d.missing and d.fraction * 100 <= self.config.repair_below_pct
        ]
        if not damaged:
            # "nothing worn" was the old wording and it contradicted its own
            # parenthesis — the second clean stage-B run reported "nothing
            # worn (8 items checked)" about a fully equipped character. The
            # facts were right; the sentence was not.
            report.log.append(
                f"repair: nothing damaged ({len(worn)} worn item(s) checked)"
            )
            return
        # Both points are looked up BEFORE the walk: an uncalibrated one
        # can only fail, and failing after crossing town is a worse way to
        # learn that than failing here.
        trade_row = self.point("charsi.trade_repair")
        repair_all = self.point("charsi.repair_all")

        missing_before = sum(d.missing for d in worn)
        self._begin_step()
        # Bounded retries, exactly as the heal does. The first live run had
        # a single attempt and failed on it: NPCs pace, so one click can
        # miss a target that a second click catches. An asymmetry between
        # two steps doing the same thing is a bug waiting for a bad day.
        self.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
        try:
            self.click_point(trade_row)  # proof: the shop screen opens
        except TownError:
            self.close_panels()
            raise

        def _repaired() -> bool:
            return sum(d.missing for d in read_equipped_durability(self.session)) == 0

        try:
            # Proof is durability, not a flag: a click that lands where the
            # button used to be must not read as a successful repair.
            self.click_point(repair_all, _repaired)
        except TownError:
            still = sum(d.missing for d in read_equipped_durability(self.session))
            self.close_panels()
            self._alert(
                f"repair did not restore durability ({missing_before} -> "
                f"{still} missing) — see the error for what was on screen"
            )
            raise
        report.repaired = len(damaged)
        report.log.append(
            f"repair: {len(damaged)} item(s) restored, {missing_before} durability"
        )

    # -- step 2: stash deposit -----------------------------------------------------

    def resurrect_merc_if_dead(self, report: PreambleReport) -> None:
        snap = self.snapshot()
        if snap.merc is not None:
            report.log.append("merc: alive")
            return
        player = self._read_player(self.session)
        available = (player.gold + player.gold_stash) if player else 0
        if player is None or available <= self.config.resurrect_gold_floor:
            report.merc_action = "skipped_gold"
            report.log.append(
                f"merc: dead but only {available} gold available "
                f"(carried + stashed) <= {self.config.resurrect_gold_floor} — skipped"
            )
            return
        try:
            resurrect = self.point("kashya.resurrect")
        except Uncalibrated:
            self._alert(
                "merc is dead with enough gold, but the resurrect row is "
                "uncalibrated (it only exists in the dead-merc state, R56) — "
                "calibrate now, while it is on screen and measurable"
            )
            raise

        self._begin_step()
        self.open_npc_dialog(offsets.NPC_KASHYA, "Kashya")
        # Re-confirm the state the calibration belongs to (R56): the row is
        # only where we measured it while the merc is dead.
        if self.snapshot().merc is not None:
            self.close_panels()
            raise TownError(
                "merc reads alive with Kashya's menu open — resurrect row "
                "position is not trustworthy in this state; aborting"
            )
        gold_before = player.gold + player.gold_stash

        def _resurrected() -> bool:
            now = self._read_player(self.session)
            return (
                self.snapshot().merc is not None
                and now is not None
                and (now.gold + now.gold_stash) < gold_before
            )

        try:
            # Proof is both halves: a live merc AND gold actually spent.
            self.click_point(resurrect, _resurrected)
        except TownError:
            self.close_panels()
            self._alert(
                "resurrect did not produce a live merc AND spent gold — see "
                "the error for what was on screen"
            )
            raise
        report.merc_action = "resurrected"
        report.log.append("merc: resurrected (verified alive + gold spent)")
        self.close_panels()

    # -- the preamble ----------------------------------------------------------------

