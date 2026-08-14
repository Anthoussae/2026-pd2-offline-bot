"""Town: TownLayer itself - construction and the preamble orchestration.

The mixins each own one concern; this file composes them and runs the
preamble in its fixed, verified order.

Split from town.py 2026-08-09; method bodies unchanged.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pd2bot.behavior.town.belt import _BeltMixin
from pd2bot.behavior.town.config import (
    PreambleReport,
    TownConfig,
    TownError,
    _carried_for_polling,
    _default_alert,
    _default_notice,
)
from pd2bot.behavior.town.inventory import _InventoryMixin
from pd2bot.behavior.town.panels import _PanelMixin
from pd2bot.behavior.town.restock import _RestockMixin
from pd2bot.behavior.town.services import _ServiceMixin
from pd2bot.behavior.town.stash import _StashMixin
from pd2bot.behavior.town.walk import _WalkMixin
from pd2bot.input.gated import GatedInput
from pd2bot.input.menu import MenuInput
from pd2bot.input.panel import PanelInput
from pd2bot.perception.items import (
    CarriedItem,
    CarriedItems,
    read_carried_items,
)
from pd2bot.perception.memory import GameSession
from pd2bot.perception.player import Player, read_player
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.runlog import NullRunLog


class TownLayer(
    _WalkMixin,
    _PanelMixin,
    _ServiceMixin,
    _RestockMixin,
    _StashMixin,
    _BeltMixin,
    _InventoryMixin,
):
    """The preamble steps. All effects verified; all timing injectable."""

    def __init__(
        self,
        session: GameSession,
        gated: GatedInput,
        panel: PanelInput,
        menu: MenuInput,
        walk_to: Callable[[tuple[int, int]], object],
        snapshot: Callable[[], GameSnapshot],
        config: TownConfig | None = None,
        *,
        carried: Callable[[GameSession], CarriedItems] | None = None,
        carried_with_sockets: Callable[[GameSession], CarriedItems] | None = None,
        read_player_fn: Callable[[GameSession], Player | None] = read_player,
        alert: Callable[[str], None] = _default_alert,
        notice: Callable[[str], None] | None = None,
        narrate: Callable[[str], None] | None = None,
        runlog: object | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        should_stop: Callable[[], bool] | None = None,
        keep_item: Callable[[CarriedItem], bool] | None = None,
        protected_ids: Callable[[], set[int]] | None = None,
    ) -> None:
        self.session = session
        self.gated = gated
        self.panel = panel
        self.menu = menu
        self.walk_to = walk_to
        self.snapshot = snapshot
        self.config = config if config is not None else TownConfig()
        # TWO readers, because this layer asks the inventory two different
        # questions (review 003). Most of them are "has that item left yet?"
        # — asked inside `_await`, at `poll_s`, up to `verify_timeout_s`
        # long. Exactly one is "what IS this item?", which the cleanse's
        # socket-conditioned whitelist needs and which costs a stat read per
        # main-inventory item, up to 40.
        #
        # Sharing one reader meant every belt transfer paid ~1200 stat reads
        # to answer a question about the BELT, which never needs sockets at
        # all. And the response to the user's report that the bot "dithers"
        # was to halve `poll_s` — doubling that cost rather than removing
        # it. Deciding is allowed to be expensive; verifying is not.
        self._carried = carried if carried is not None else _carried_for_polling
        self._carried_sockets = (
            carried_with_sockets
            if carried_with_sockets is not None
            # A caller who injected one reader gets it for both: a fake has
            # no cheap/expensive distinction, and reaching for the real
            # reader behind its back would be worse than useless.
            else (carried if carried is not None else read_carried_items)
        )
        self._read_player = read_player_fn
        self._alert = alert
        # A notice is not an alert: it reports something worth knowing on a
        # run that CONTINUES. Defaulting it to `alert` would be the tidy
        # choice and the wrong one — the halt banner would come back, saying
        # the bot is waiting when it is not. Tests that inject an alert and
        # want to see notices too can pass the same callable deliberately.
        self._notice = notice if notice is not None else _default_notice
        # The narrative channel (R179): one line per preamble station,
        # with its duration — the "dawdle at Akara" is heal verification
        # polling plus settle timers, and this is where it says so. No-op
        # by default so drills and tests stay silent.
        self._narrate = narrate if narrate is not None else (lambda text: None)
        # The run event log (P6). Taken the same way `narrate` is — a
        # holder rather than a construction argument — because the town
        # layer is SESSION-scoped and outlives any one run, so the wiring
        # repoints it per run.
        self.runlog = runlog if runlog is not None else NullRunLog()
        # The character's real key layout (R247), a holder like `runlog`:
        # the layer is session-scoped, so the wiring re-points this per
        # run after re-reading the keyfile. Defaults = the historical
        # hardcoded assumptions, so tests and drills change nothing.
        from pd2bot.input.keys import default_bindings

        self.bindings = default_bindings()
        self._pressure_warned = False
        self._clock = clock
        self._sleep = sleep
        # The cleanse whitelist (R117): an item this returns False for is
        # accidental-pickup junk, dropped on the ground rather than stashed.
        # None means cleansing is DISABLED — the safe default, and what the
        # wiring passes while the pickit's vocabulary still has unverified
        # ids (pickit.cleanse_keep) — in which case everything is stashed
        # exactly as before.
        self._keep_item = keep_item
        # Unit ids the cleanse must NEVER drop, whatever the whitelist
        # thinks (R128). The bot is cleaning up its own accidents, so
        # anything already carried when the bot started is off limits: the
        # user pointed out that several keep-list items can only be
        # CRAFTED, never dropped, which means the whitelist can never learn
        # their ids from a live pickup — and one sitting in the inventory
        # would look exactly like junk. Protecting the startup baseline
        # closes that hole without needing those ids at all.
        self._protected_ids = protected_ids
        # Where a lazily-captured baseline lands when the caller supplied
        # none. See `_protected` for why the default is not "protect
        # nothing".
        self._implicit_baseline: set[int] | None = None
        # An outside veto, checked in every wait. A bot stuck in a retry
        # ladder was previously unstoppable: the drill harness could only
        # cancel its OWN waits, and a loop inside this layer ran to
        # exhaustion while a human watched it (R80). Optional so nothing
        # else has to care.
        self._should_stop = should_stop

    # -- small shared machinery ------------------------------------------------

    def run_preamble(self, report: PreambleReport | None = None) -> PreambleReport:
        """heal -> repair -> inventory loop -> merc. Raises on the first
        failed step; the caller (the cycle) owns what happens next.

        Order is R46 Q5's with repair inserted after the heal (R70): both
        are NPC visits, and repair is conditional, so a game that needs no
        repair walks no further than before.

        The middle used to be `deposit_to_stash(keep)` then `refill_belt`,
        with the caller supplying a predicate saying which items belonged in
        the stash. `manage_inventory` replaces both and takes no predicate,
        which is the point of R75's design: **the game classifies the items,
        not us.** Everything is offered to the materials tab, whatever it
        accepts stays there, and the rest goes to the regular stash — so
        there is no taxonomy to keep current as PD2 patches.

        Both old steps remain for the drills that exercise them alone
        (T13, T14).
        """
        report = report if report is not None else PreambleReport()
        # A truncated item read means every "absent" below is a potential
        # lie — the 2026-08-13 over-buy ran the WHOLE preamble against
        # one: repair saw 0 worn items on a geared character, the restock
        # saw an empty belt over 2 visible mana potions and bought ~30
        # potions into the inventory. No station may trust that read, so
        # none of them runs. This should never fire at the raised cap;
        # if it does, the stash has genuinely outgrown the reader and a
        # human must prune or the cap must rise again.
        carried = self._carried(self.session)
        if getattr(carried, "truncated", False):
            self._alert(
                f"the item read is TRUNCATED at the walk cap with "
                f"{len(carried.items)} items — the belt, worn gear and "
                "inventory cannot be trusted, so the preamble refuses to "
                "run. The stash has likely outgrown the reader; prune it "
                "or raise MAX_CARRIED_ITEMS."
            )
            raise TownError("item read truncated — preamble refused")
        # Each station narrates ONE completion line: what its own report
        # lines said, plus how long it took. The duration is the answer to
        # "what was it doing while it dawdled at Akara?" (R179) — the
        # station was polling its verification and sitting out settle
        # timers, and now it says so instead of standing there mutely. A
        # station that raises narrates too, via the failure line: the
        # dawdle a human asks about is usually the one that ended badly.
        stations: tuple[tuple[str, Callable[[PreambleReport], None]], ...] = (
            ("heal", self.heal_at_akara),
            ("repair", self.repair_at_charsi),
            ("restock", self.restock_at_akara),
            ("inventory", self.manage_inventory),
            ("merc", self.resurrect_merc_if_dead),
        )
        for label, station in stations:
            started = self._clock()
            before = len(report.log)
            try:
                station(report)
            except Exception as exc:
                self._narrate(
                    f"{label}: FAILED after {self._clock() - started:.1f}s "
                    f"({type(exc).__name__})"
                )
                raise
            elapsed = self._clock() - started
            # T4 (R186): the per-item cleanse KEEP lines belong to the
            # micro-log; in the narrative they buried the station summary
            # under a paragraph of item ids. The cleanse's own summary
            # line ("N judged junk, M kept") survives the filter.
            outcome = "; ".join(
                line
                for line in report.log[before:]
                if not line.startswith("cleanse: KEEP")
            ) or "nothing to do"
            self._narrate(f"{outcome} ({elapsed:.1f}s)")
        return report
