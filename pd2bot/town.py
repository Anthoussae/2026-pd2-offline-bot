"""The town layer: everything the bot does before leaving town, verified.

The preamble (R46 Q5, order fixed): heal at Akara -> stash deposit -> belt
refill -> conditional merc resurrect. Each step is a small, individually
drillable method that verifies its effect through perception — a click is
never trusted to have worked (M4's house rule). The preamble exists because
PD2 carries vitals between games (R45): without the heal, a hurt character
chickens out of every game it ever enters.

Design constraints carried in from planning:

- Belt refill is from INVENTORY ONLY (R48 option b): no vendor UI. Below
  the configured minimums after refilling, the layer halts loudly for a
  manual restock rather than improvising.
- **The same gesture means different things depending on what is open**
  (user-supplied, R63). With the stash OPEN, shift+right-click moves an
  item between inventory and stash — in either direction. With the stash
  CLOSED, shift+right-click sends a potion from the inventory to the
  belt. The panel state is therefore part of the instruction, not
  ambient context, which is why every step opens with `_begin_step()`
  rather than assuming: a refill attempted with the stash still up would
  quietly stash the potion instead of belting it. (Refill itself uses
  shift+LEFT-click, the vanilla move-to-belt gesture, proven live in
  T14; PD2's shift+right variant carries the identical precondition.)
- Kashya's menu is state-dependent (R56): the resurrect row exists only
  while the merc is dead, so the flow confirms the merc is dead before
  trusting the dead-state calibration, verifies merc-alive AND gold-spent
  afterwards, and halts loudly on any mismatch — no blind re-clicks into a
  menu whose layout may not match.
- Grid geometry (inventory cell -> pixel) and the resurrect row are
  hover-calibrated client-rect fractions (M4's Save-and-Exit precedent).
  Uncalibrated steps refuse before sending anything.

Two live findings about the stash that any future stash work must respect
(T15/T16, R72):

1. **The materials tab makes the ordinary stash read EMPTY.** Switching to
   it took the stash from 18 items to 0, and switching back restored them.
   So "the stash has no items" is ambiguous — it can mean an empty stash
   or the wrong tab — and no logic may infer fullness or emptiness from a
   bare count without knowing which tab is showing. Deposits here are
   safe regardless, because they verify by watching the INVENTORY shrink
   rather than the stash grow.
2. **Stash contents populate progressively.** Immediately after a tab
   switch the list was still filling — a read caught 10 of the 18 items
   mid-flight. Any future check that counts stash items must let the
   panel settle first, or it will occasionally act on a partial list.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot import offsets, uistate
from pd2bot.input import VK_I, GatedInput
from pd2bot.items import (
    CarriedItem,
    CarriedItems,
    read_carried_items,
    read_equipped_durability,
)
from pd2bot.memory import GameSession
from pd2bot.menuinput import MenuInput
from pd2bot.navigate import NavigationError
from pd2bot.panelinput import PanelInput
from pd2bot.player import Player, read_player
from pd2bot.snapshot import GameSnapshot


class TownError(RuntimeError):
    """A town step failed in a way retrying will not fix."""


class TownStopped(TownError):
    """An outside veto fired mid-step. Not a defect — someone said stop."""


class StashFull(TownError):
    """A deposit never left the inventory. A human must make stash space."""


class BeltBelowMinimum(TownError):
    """Refill exhausted the inventory and the belt is still short."""


class Uncalibrated(TownError):
    """A step needs a hover calibration that has not been run."""


def _default_alert(reason: str) -> None:  # pragma: no cover - exercised live
    print("\n" + "!" * 66)
    print(f"!!  TOWN LAYER HALTED: {reason}")
    print("!!  The bot is waiting; a human resolves this one.")
    print("!" * 66 + "\n", flush=True)
    try:
        import winsound

        for _ in range(3):
            winsound.Beep(660, 300)
            winsound.Beep(880, 300)
    except Exception:
        pass


@dataclass(frozen=True)
class TownConfig:
    # Belt minimums per potion type, checked after refill (columns per the
    # permanent layout, R53: key 1 mana, key 2 rejuv, keys 3+4 healing).
    # Rejuvs are unbuyable (R47.6) so their minimum is advisory-zero.
    min_healing: int = 4
    min_mana: int = 2
    min_rejuv: int = 0
    # Merc resurrect needs this much gold available. Checked against
    # carried PLUS stashed, because PD2 pays for services out of the
    # shared stash regardless of what is on the person (user, R76) — the
    # earlier carried-only reading would have skipped the step forever on
    # a character that banks everything and carries nothing (R52).
    #
    # Gold is otherwise a non-topic by user decision (R76): the stash
    # covers every foreseeable cost, so nothing here budgets, reserves, or
    # prices anything.
    resurrect_gold_floor: int = 49_999
    # Walking ONTO an NPC means clicking ON them, and a click on an NPC
    # opens their dialog — so the navigator's own final click interacts,
    # the dialog blocks all further world input, and the next walk dies as
    # a NavigationError. That is precisely what T12 did: it opened Kashya's
    # dialog with its *travel* clicks and looped (R66). So approach walks
    # stop short, and the interaction click is always made deliberately.
    # Stop FAR short of an NPC, for two reasons that pull the same way.
    #
    # Too close and the navigator's own travel clicks land inside D2's
    # click-selection radius and open the NPC's dialog instead of moving —
    # at a 5-subtile standoff the bot ended 2-8 subtiles out and spent its
    # walk retries opening and closing Kashya's chat (R78).
    #
    # And proximity buys nothing: clicking an NPC from across the screen
    # makes the character walk over and interact by itself. The only real
    # limit is that the click must project inside the safe region — the
    # isometric projection puts a target (dx+dy) subtiles away at
    # 10*(dx+dy) px below centre, and the HUD strip eats everything below
    # ~285 px, so a diagonal target beyond ~14 subtiles is unclickable.
    # 12 keeps a margin.
    npc_standoff: int = 10
    interact_range: int = 12  # already this close? then do not walk at all
    interact_timeout_s: float = 6.0
    # Clicking an NPC from across the screen makes the character walk over
    # before the dialog opens, so this wait covers a journey. Six seconds
    # was too short for it, and the retry then re-clicked mid-walk and
    # restarted the approach — the other half of the Kashya loop (R80).
    npc_walk_timeout_s: float = 15.0
    # A panel's flag goes up before the panel is ready to be clicked: D2
    # animates dialogs in, and T15 caught the stash still populating its
    # item list after the flag appeared. Clicking into that window is a
    # click into nothing — the likeliest reason T19's trade/repair row did
    # nothing (R80). Let it settle, then click, then retry if needed.
    panel_settle_s: float = 0.6
    panel_click_retries: int = 2
    interact_retries: int = 2
    transfer_attempts: int = 2  # shift-clicks per item before StashFull
    verify_timeout_s: float = 3.0
    poll_s: float = 0.2
    # Calibrated client-rect fractions. None = refuse rather than guess.
    #
    # The inventory pair is T11's snake-sweep fit (R61, 1536x864 window):
    # 78 click samples over all 40 usable cells, least-squares, worst
    # per-cell residual 11.5 px on a 41.1 x 39.8 px pitch — random scatter,
    # no row/column drift, so the grid is uniform. Preferred over T10's
    # four aimed hovers because it is denser and derived from real clicks.
    # (T10 agreed within 7 px of origin and 0.8 px/cell of pitch — both
    # fits put every predicted centre well inside its cell.) Re-run the
    # calibration after any window or resolution change — same standing
    # rule as M4's Save-and-Exit fractions (game-cycle.md).
    inventory_origin: tuple[float, float] | None = (0.5301, 0.4385)
    inventory_cell: tuple[float, float] | None = (0.0268, 0.0461)
    # Dead-merc state ONLY (R56): the row does not exist while the merc
    # lives. Captured by T20 (R80) during a real dead-merc window, which
    # is the only time it can be measured — so it is kept here rather than
    # re-captured, and T21 re-confirms the merc is dead before trusting it.
    resurrect_row: tuple[float, float] | None = (0.5716, 0.2569)
    # Where to stand to find each NPC when they are beyond perception range
    # (80 subtiles). T12 failed exactly here: the bot asked perception for
    # Akara while standing too far away and gave up rather than walking.
    # Single-player maps are fixed per character+difficulty (the atlas
    # premise, M3 ADR), so these are stable for this character; they are
    # approach targets, not exact spots, because NPCs pace around.
    # Measured by the T17 proximity drill (R68): the user stood beside each
    # NPC and the nearest ally was read, so these are where they actually
    # stand, not where they once happened to be seen.
    npc_positions: dict[int, tuple[int, int]] = field(
        default_factory=lambda: {
            offsets.NPC_AKARA: (5922, 5714),
            offsets.NPC_KASHYA: (5877, 5743),
            offsets.NPC_CHARSI: (5824, 5724),
        }
    )
    # Repair (user request, R70). Repair EVERY game rather than tuning a
    # threshold (user decision, R71): gear wears every run, and a number
    # that needs tuning is a number that will one day be wrong. 100% means
    # "any wear at all is enough reason to go".
    #
    # The one thing this does not do is skip the durability *read*: that is
    # not the trigger, it is the proof. Without it a repair-all click that
    # lands where the button used to be is indistinguishable from success,
    # and the first sign of trouble is gear breaking mid-run in Hell.
    repair_below_pct: float = 100.0
    # Hover-calibrated at Charsi (T18, R72, 1536x864 window). Re-run T18
    # after any window or resolution change, and note the R56 caveat: these
    # belong to the menu as it stood, and NPC rows move with NPC state.
    trade_repair_row: tuple[float, float] | None = (0.5879, 0.2072)
    repair_all_button: tuple[float, float] | None = (0.4707, 0.7523)
    walk_retries: int = 3  # travel clicks that open a dialog (see _walk_guarded)
    # Objects need the same treatment as NPCs, and for a stronger reason:
    # perception is capped at 80 subtiles, but the client only keeps NEARBY
    # ROOMS loaded at all, so a distant stash is not merely out of range —
    # it is absent from the unit table entirely. T13 failed here, standing
    # at Akara after the heal with the stash unloaded across town (R69).
    object_positions: dict[int, tuple[int, int]] = field(
        default_factory=lambda: {
            offsets.OBJ_STASH: (5856, 5734),
            offsets.OBJ_WAYPOINT_A1: (5884, 5709),
        }
    )
    # The stash's materials-tab toggle, hover-calibrated (T15, R72).
    # Nothing uses it yet — which items belong there is P5's pickit work —
    # but see the tab caveats in this module's docstring before anything
    # does.
    materials_tab_button: tuple[float, float] | None = (0.2188, 0.8426)


@dataclass
class PreambleReport:
    healed: bool = False
    repaired: int = 0
    deposited: int = 0
    refilled: int = 0
    merc_action: str = "not_needed"  # not_needed | skipped_gold | resurrected
    log: list[str] = field(default_factory=list)


class TownLayer:
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
        carried: Callable[[GameSession], CarriedItems] = read_carried_items,
        read_player_fn: Callable[[GameSession], Player | None] = read_player,
        alert: Callable[[str], None] = _default_alert,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.session = session
        self.gated = gated
        self.panel = panel
        self.menu = menu
        self.walk_to = walk_to
        self.snapshot = snapshot
        self.config = config if config is not None else TownConfig()
        self._carried = carried
        self._read_player = read_player_fn
        self._alert = alert
        self._clock = clock
        self._sleep = sleep
        # An outside veto, checked in every wait. A bot stuck in a retry
        # ladder was previously unstoppable: the drill harness could only
        # cancel its OWN waits, and a loop inside this layer ran to
        # exhaustion while a human watched it (R80). Optional so nothing
        # else has to care.
        self._should_stop = should_stop

    # -- small shared machinery ------------------------------------------------

    def _check_stop(self) -> None:
        if self._should_stop is not None and self._should_stop():
            raise TownStopped("stopped by request")

    def _await(self, condition: Callable[[], bool], timeout_s: float) -> bool:
        deadline = self._clock() + timeout_s
        while self._clock() < deadline:
            self._check_stop()
            if condition():
                return True
            self._sleep(self.config.poll_s)
        return False

    def _panel_open(self, panel_id: int) -> bool:
        state = uistate.read_ui_state(self.session, self.panel._ui_array)
        return state.is_open(panel_id)

    def _find_ally(self, kind: int) -> tuple[int, int] | None:
        snap = self.snapshot()
        for ally in snap.allies:
            if ally.kind == kind:
                return ally.position
        return None

    def _any_panel_open(self) -> bool:
        return any(
            self._panel_open(p)
            for p in (offsets.UI_NPCMENU, offsets.UI_STASH, offsets.UI_INVENTORY)
        )

    def _walk_guarded(self, destination: tuple[int, int]) -> None:
        """Walk, surviving travel clicks that land on a bystander.

        The navigator moves by clicking toward the destination, and a click
        that lands on an NPC opens their dialog instead of moving — so
        crossing a crowded town can interrupt itself on someone who has
        nothing to do with where we are going. That is what actually
        happened in T12: the bot was correctly aimed at Akara and got
        waylaid by Kashya *en route* (R66/R68). The dialog then blocks all
        world input, the navigator waits its ten seconds, and the walk dies.

        The recovery is exact rather than hopeful: only a NavigationError
        that comes with a panel open is treated as this case; the panel is
        closed and the walk resumed from wherever it stopped, so every
        attempt makes real progress. Any other NavigationError is a genuine
        pathing failure and propagates untouched.
        """
        for _ in range(1 + self.config.walk_retries):
            self._check_stop()
            try:
                self.walk_to(destination)
                return
            except NavigationError:
                if not self._any_panel_open():
                    raise  # a real pathing failure, not an accidental chat
                self._close_panels()
        raise TownError(
            f"could not reach {destination}: travel clicks kept opening "
            f"dialogs after {self.config.walk_retries} recoveries — the route "
            "may run straight through a crowd"
        )

    def _walk_near(self, target: tuple[int, int]) -> None:
        """Get within clicking distance of `target` WITHOUT walking onto it.

        A travel click that lands on an NPC opens their dialog instead of
        moving, and the dialog then blocks every later click (T12, R66). So
        stop `npc_standoff` subtiles short, on our own side of the target,
        and leave the interaction to a deliberate click. Already close
        enough? Then do not walk at all — the shortest walk is none.
        """
        player = self._read_player(self.session)
        if player is None:
            self._walk_guarded(target)
            return
        px, py = player.position
        dx, dy = px - target[0], py - target[1]
        distance = max(abs(dx), abs(dy))
        if distance <= self.config.interact_range:
            return
        scale = self.config.npc_standoff / distance
        self._walk_guarded(
            (round(target[0] + dx * scale), round(target[1] + dy * scale))
        )

    def _approach_ally(self, kind: int, name: str) -> tuple[int, int]:
        """Get within clicking range of an NPC, walking blind if we must.

        Perception only reaches 80 subtiles, and a town NPC is routinely
        further than that from where a game drops you — T12's first live
        run died on exactly this, asking perception for Akara from across
        the camp and giving up. So: if she is not visible, walk to the
        configured approach position first, then look again.
        """
        position = self._find_ally(kind)
        if position is None:
            known = self.config.npc_positions.get(kind)
            if known is None:
                raise TownError(
                    f"{name} is not in perception range and has no configured "
                    "approach position — cannot walk blind to an unknown spot"
                )
            self._walk_near(known)
            position = self._find_ally(kind)
            if position is None:
                raise TownError(
                    f"{name} still not visible after walking to {known} — the "
                    "configured approach position may be wrong for this map"
                )
        self._walk_near(position)
        # NPCs pace; re-read after the walk so the click targets where they
        # are now, not where they were when we set off.
        return self._find_ally(kind) or position

    def _approach_object(self, kind: int, name: str) -> tuple[int, int]:
        """Same walk-then-look as NPCs, for scenery we must click.

        Objects do not pace, but they do vanish: the client only keeps
        nearby rooms loaded, so a stash across town is not in the unit
        table at all until we are closer.
        """
        position = self._find_object(kind)
        if position is None:
            known = self.config.object_positions.get(kind)
            if known is None:
                raise TownError(
                    f"{name} is not in perception range and has no configured "
                    "position — cannot walk blind to an unknown spot"
                )
            self._walk_near(known)
            position = self._find_object(kind)
            if position is None:
                raise TownError(
                    f"{name} still not visible after walking to {known} — the "
                    "configured position may be wrong for this map"
                )
        self._walk_near(position)
        return position

    def _find_object(self, kind: int) -> tuple[int, int] | None:
        snap = self.snapshot()
        for obj in snap.objects:
            if obj.kind == kind:
                return obj.position
        return None

    def _grid_pixel(self, cell: tuple[int, int]) -> tuple[int, int]:
        """Inventory grid cell -> screen pixel, from calibrated fractions."""
        if self.config.inventory_origin is None or self.config.inventory_cell is None:
            raise Uncalibrated(
                "inventory grid geometry is not calibrated — run the P3 hover "
                "calibration before any grid click"
            )
        x, y = cell
        if not (0 <= x < offsets.INVENTORY_COLS and 0 <= y < offsets.INVENTORY_ROWS):
            # The calibration only describes the usable grid; a cell outside
            # it is charm space or nonsense, and clicking there is exactly
            # what R60 exists to prevent.
            raise TownError(
                f"cell {cell} is outside the usable inventory grid "
                f"({offsets.INVENTORY_COLS}x{offsets.INVENTORY_ROWS}) — "
                "refusing to compute a click position for it"
            )
        rect = self.panel.window.client_rect()
        fx = self.config.inventory_origin[0] + cell[0] * self.config.inventory_cell[0]
        fy = self.config.inventory_origin[1] + cell[1] * self.config.inventory_cell[1]
        return rect.left + round(fx * rect.width), rect.top + round(fy * rect.height)

    def _close_panels(self) -> None:
        """ESC closes whatever town panel is up; verify it actually closed."""
        for panel_id in (offsets.UI_STASH, offsets.UI_NPCMENU, offsets.UI_INVENTORY):
            if self._panel_open(panel_id):
                self.menu.press_escape()
                if not self._await(
                    lambda p=panel_id: not self._panel_open(p),
                    self.config.verify_timeout_s,
                ):
                    raise TownError(
                        f"{offsets.UI_NAMES.get(panel_id, panel_id)} did not close on ESC"
                    )

    def _begin_step(self) -> None:
        """Start from a state where walking is possible.

        Every step here walks, and `GatedInput` rightly refuses to click the
        world while a blocking panel is open — so a panel left up by the
        previous step (or by a human mid-setup) turns the first walk into a
        NavigationError ten seconds later. T13's first live run died exactly
        that way, with the stash still open. Closing up front is cheap and
        makes each step independent of what came before it.
        """
        self._close_panels()

    def click_in_panel_until(
        self,
        panel_id: int,
        fraction: tuple[float, float],
        condition: Callable[[], bool],
        *,
        what: str,
    ) -> None:
        """Click a calibrated spot inside a panel until it has its effect.

        The flag going up does not mean the panel is ready: D2 animates
        dialogs in, and clicks landing during that window are simply lost —
        which is what a single immediate click ran into (R80). So: settle,
        click, watch for the effect, retry a couple of times, and if it
        never lands say what WAS on screen rather than only what was not.
        """
        rect = self.panel.window.client_rect()
        sx = rect.left + round(fraction[0] * rect.width)
        sy = rect.top + round(fraction[1] * rect.height)
        for _ in range(1 + self.config.panel_click_retries):
            self._check_stop()
            self._sleep(self.config.panel_settle_s)
            if not self._panel_open(panel_id):
                break  # the panel we were told to click in has gone
            self.panel.click(panel_id, sx, sy)
            if self._await(condition, self.config.interact_timeout_s):
                return
        state = uistate.read_ui_state(self.session, self.panel._ui_array)
        raise TownError(
            f"{what}: clicked ({sx}, {sy}) in "
            f"{offsets.UI_NAMES.get(panel_id, panel_id)} "
            f"{1 + self.config.panel_click_retries} times with no effect; "
            f"panels now open: {', '.join(state.names) or 'none'} — the "
            "calibrated position may be wrong or the menu may have shifted "
            "(NPC menus are state-dependent, R56)"
        )

    def open_object_panel(self, kind: int, name: str, panel_id: int) -> tuple[int, int]:
        """Click a world object and wait for its panel. Same shape as
        `open_npc_dialog`, and for the same reasons.

        Clicking the stash from across the room makes the character walk to
        it before the panel opens, so this wait covers a journey too — and
        the single un-retried attempt it replaced was the exact pair of
        mistakes that broke the NPC path (R80). Fixed here before it could
        be discovered live a third time.
        """
        clicked = None
        for _ in range(1 + self.config.interact_retries):
            self._check_stop()
            if self._panel_open(panel_id):
                return clicked if clicked is not None else self._find_object(kind)
            clicked = self._approach_object(kind, name)
            self.gated.click_world(*clicked)
            if self._await(
                lambda: self._panel_open(panel_id), self.config.npc_walk_timeout_s
            ):
                return clicked
        player = self._read_player(self.session)
        raise TownError(
            f"{name} never opened its panel after "
            f"{1 + self.config.interact_retries} attempts — last click at "
            f"{clicked}, player at {player.position if player else 'unreadable'}"
        )

    def open_npc_dialog(self, kind: int, name: str) -> tuple[int, int]:
        """Approach an NPC and open their dialog, verified. Returns where
        they were clicked.

        One path for all three NPC steps. They used to each carry their own
        copy, and the copies drifted: heal retried a missed click three
        times, repair did not, and repair was the one that failed live
        (R78). Two steps doing the same thing should not differ in how
        robust they are.
        """
        clicked = None
        for _ in range(1 + self.config.interact_retries):
            self._check_stop()
            # If our previous click already opened it, STOP. Re-approaching
            # now is what produced the Kashya loop (R80): the walk cannot
            # run with a dialog open, so `_walk_guarded` closed it, walked,
            # and the next click reopened it — round and round, up to a
            # dozen times, looking exactly like the bot chatting to her
            # compulsively.
            if self._panel_open(offsets.UI_NPCMENU):
                return clicked if clicked is not None else self._find_ally(kind)
            clicked = self._approach_ally(kind, name)
            self.gated.click_world(*clicked)
            # Clicking an NPC from a distance makes the character WALK to
            # them first, so this wait covers a journey, not a frame.
            if self._await(
                lambda: self._panel_open(offsets.UI_NPCMENU),
                self.config.npc_walk_timeout_s,
            ):
                return clicked
        player = self._read_player(self.session)
        raise TownError(
            f"{name}'s dialog never opened after "
            f"{1 + self.config.interact_retries} attempts — last click at "
            f"{clicked}, player at {player.position if player else 'unreadable'}"
        )

    # -- step 1: heal ------------------------------------------------------------

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
        if player.hp == player.max_hp and player.mana == player.max_mana:
            report.healed = True
            report.log.append("heal: already at full vitals")
            return

        self._begin_step()
        talked_to = None
        # Approach and dialog failures propagate with their own diagnosis —
        # they say far more than anything this step could add. What is
        # retried here is the EFFECT: a dialog that opened but did not heal.
        for _ in range(1 + self.config.interact_retries):
            talked_to = self.open_npc_dialog(offsets.NPC_AKARA, "Akara")
            self._close_panels()

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
            report.log.append(f"repair: nothing worn ({len(worn)} items checked)")
            return
        if self.config.trade_repair_row is None or self.config.repair_all_button is None:
            raise Uncalibrated(
                "the repair UI is not calibrated (trade row / repair-all "
                "button) — run the T18 drill before repairing"
            )

        missing_before = sum(d.missing for d in worn)
        self._begin_step()
        # Bounded retries, exactly as the heal does. The first live run had
        # a single attempt and failed on it: NPCs pace, so one click can
        # miss a target that a second click catches. An asymmetry between
        # two steps doing the same thing is a bug waiting for a bad day.
        self.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
        try:
            self.click_in_panel_until(
                offsets.UI_NPCMENU,
                self.config.trade_repair_row,
                lambda: self._panel_open(offsets.UI_NPCSHOP),
                what="trade/repair row",
            )
        except TownError:
            self._close_panels()
            raise

        def _repaired() -> bool:
            return sum(d.missing for d in read_equipped_durability(self.session)) == 0

        try:
            self.click_in_panel_until(
                offsets.UI_NPCSHOP,
                self.config.repair_all_button,
                _repaired,
                what="repair-all button",
            )
        except TownError:
            still = sum(d.missing for d in read_equipped_durability(self.session))
            self._close_panels()
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
        candidates = [i for i in self._carried(self.session).main_inventory if keep(i)]
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
        self._close_panels()

    # -- step 3: belt refill ---------------------------------------------------------

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
                self.gated.press_key(VK_I)
                if not self._await(
                    lambda: self._panel_open(offsets.UI_INVENTORY),
                    self.config.verify_timeout_s,
                ):
                    raise TownError("the inventory never opened for the refill")

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
            self._close_panels()

        shortfall = self._belt_shortfall()
        if any(shortfall.values()):
            missing = ", ".join(f"{k} short {v}" for k, v in shortfall.items() if v)
            self._alert(f"belt below minimum after refill: {missing} — manual restock")
            raise BeltBelowMinimum(missing)
        report.log.append(f"belt: {report.refilled} moved, minimums hold")

    # -- step 4: conditional merc resurrect ---------------------------------------------

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
        if self.config.resurrect_row is None:
            self._alert(
                "merc is dead with enough gold, but the resurrect row is "
                "uncalibrated (it only exists in the dead-merc state, R56) — "
                "hover-calibrate now while it is on screen"
            )
            raise Uncalibrated("resurrect row fraction is None")

        self._begin_step()
        self.open_npc_dialog(offsets.NPC_KASHYA, "Kashya")
        # Re-confirm the state the calibration belongs to (R56): the row is
        # only where we measured it while the merc is dead.
        if self.snapshot().merc is not None:
            self._close_panels()
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
            self.click_in_panel_until(
                offsets.UI_NPCMENU,
                self.config.resurrect_row,
                _resurrected,
                what="resurrect row",
            )
        except TownError:
            self._close_panels()
            self._alert(
                "resurrect did not produce a live merc AND spent gold — see "
                "the error for what was on screen"
            )
            raise
        report.merc_action = "resurrected"
        report.log.append("merc: resurrected (verified alive + gold spent)")
        self._close_panels()

    # -- the preamble ----------------------------------------------------------------

    def run_preamble(
        self, keep: Callable[[CarriedItem], bool], report: PreambleReport | None = None
    ) -> PreambleReport:
        """heal -> repair -> stash -> refill -> merc. Raises on the first
        failed step; the caller (the cycle) owns what happens next.

        Order is R46 Q5's with repair inserted after the heal (R70): both
        are NPC visits, and repair is conditional, so a game that needs no
        repair walks no further than before.
        """
        report = report if report is not None else PreambleReport()
        self.heal_at_akara(report)
        self.repair_at_charsi(report)
        self.deposit_to_stash(keep, report)
        self.refill_belt(report)
        self.resurrect_merc_if_dead(report)
        return report
