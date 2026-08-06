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
from pd2bot.input import VK_DOWN, VK_I, VK_RETURN, GatedInput
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
from pd2bot.screen import projection_for
from pd2bot.snapshot import GameSnapshot
from pd2bot.uipoints import UIPoint, default_points


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


def _potion_type(item: CarriedItem) -> str | None:
    """"healing" / "mana" / "rejuv", or None for anything else.

    Coarser than `potion_name`, which is per-kind ("healing_606"), because
    the belt fills by COLUMN: whether a potion fits depends on its type, not
    on which tier of that type it happens to be (R53).
    """
    return item.potion_type


def _carried_for_polling(session: GameSession) -> CarriedItems:
    """The cheap inventory read: no per-item socket stat reads.

    The default for everything this layer does in a loop. `read_carried_items`
    defaults to WITH sockets, and rightly so — a caller who forgets them gets
    `sockets=None`, which a permissive whitelist reads as "keep" — but that
    default belongs to the decision path, not to a 10 Hz verification. See
    `TownLayer.__init__` for the split.
    """
    return read_carried_items(session, with_sockets=False)


def _default_notice(reason: str) -> None:  # pragma: no cover - exercised live
    """Something a human should know, on a run that is still going.

    Deliberately quieter than `_default_alert` and deliberately NOT saying
    "halted". T27's first run after the R132 stash-pressure warning printed
    the halt banner for a warning that halts nothing — the drill sailed past
    it and passed, while the operator's console said the bot was waiting for
    them. An alert that lies about severity is worse than no alert.
    """
    print(f"\n--  NOTICE: {reason}\n", flush=True)


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
    # ...but not THIS close. Clicking the tile under your own feet does
    # nothing, so an object approach that ends on top of the object can
    # never open it (stage B, live). Objects only: an NPC is a unit you
    # cannot stand inside.
    min_interact_range: int = 4
    # Where to aim, per attempt, relative to the object's own tile.
    #
    # A D2 object's POSITION is its tile; its sprite is drawn around and
    # behind that, so the tile centre is not reliably inside the clickable
    # body — and whether it is depends on the angle you approach from.
    # 2026-08-01, live: the stash at (5856, 5734) clicked from 7 subtiles
    # east, three times, at the same pixel each time. The character did
    # not move and the panel never opened — a click that hit neither the
    # sprite nor walkable ground. Aiming a subtile behind the tile (away
    # from the camera, which is up-left) puts the point further into the
    # sprite body.
    #
    # Exists because a retry that cannot differ from the attempt it
    # retries is not a retry. The first entry MUST be (0, 0): the tile
    # itself is right far more often than not, and this is a fallback
    # ladder, not a correction.
    object_aim_offsets: tuple[tuple[int, int], ...] = (
        (0, 0), (-1, -1), (1, 1), (-2, -2),
    )
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
    # Warn once per session when this many items are stashed across both
    # READABLE containers (classic + expanded; materials cannot be counted).
    #
    # An openly arbitrary number, and it has to be: item sizes are
    # unreadable (P1) and PD2's expanded stash has no capacity we can read,
    # so there is no denominator to be a percentage of. The first value
    # tried, 120, came from treating the classic 10x15 grid as the whole
    # story — and fired immediately on a live character holding 360, which
    # is how a warning becomes noise. Set above where a healthy character
    # sits, and treat it as "notably more than usual", not "nearly full".
    stash_pressure_at: int = 800
    # Between arrow presses when walking an NPC dialog by keyboard
    # (R104). The menu highlights per key, and D2 samples input per
    # frame at 25 fps, so this is comfortably more than one frame.
    key_step_s: float = 0.15
    # How often a wait re-checks. Halved from 0.2 after the user watched
    # the bot 'dither' on arriving somewhere: the panel or dialog was
    # already up and this was the lag before noticing. Cheap — these are
    # memory reads — and it tightens every wait in the layer at once.
    poll_s: float = 0.1
    # The stash's contents populate progressively after a tab switch — T15
    # caught a read with 10 of 18 items still in flight — so a tab toggle
    # must settle before its effect is read.
    tab_settle_s: float = 1.0
    # The two deposit passes, tuned in opposite directions (R134). Pass one
    # runs on whatever tab is displayed and fails FAST, because a refusal
    # there is cheap — pass two retries it after a blind toggle. Pass two
    # uses `transfer_attempts` x `verify_timeout_s` instead, because a
    # refusal there is terminal and worth being patient about.
    #
    # (These numbers were tuned for the old materials phase, which attempted
    # every item and expected most to bounce. The rationale carried over
    # unchanged — cheap where recoverable — so the values did too.)
    first_pass_attempts: int = 1
    first_pass_verify_s: float = 0.6
    # How many potions of EACH type stay in the inventory as reserve after
    # the belt is filled (R118 Q1: belt first, then up to this many). The
    # rest are drunk — all types, rejuvs included (R118 Q2, superseding
    # R75's rejuvs-to-materials) — and no potion is ever stashed.
    potion_reserve: int = 2
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
    # Every calibrated click target inside a panel, by name (R87). One
    # registry rather than a field per control: the per-field version grew
    # a consumer per field, and the consumers drifted — the same failure
    # the three NPC steps had before `open_npc_dialog` merged them. See
    # uipoints.py for what a point is and how each was measured.
    ui_points: dict[str, UIPoint] = field(default_factory=default_points)
    # Where to stand to find each NPC when they are beyond perception range
    # (46-67 subtiles, measured by T51 — the 80 in `PERCEPTION_RADIUS` is a
    # ceiling that never binds). T12 failed exactly here: the bot asked
    # perception for
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
    # Repair (user request, R70). R71 originally said repair EVERY game
    # ("any wear at all is enough reason to go"); R186 superseded it with
    # run-4 pricing in hand — a single missing point bought a 33 s Charsi
    # trip every game. 70 means: go when any worn item is at or below 70%
    # of its maximum; above that the trip buys nothing a later run will
    # not buy cheaper.
    #
    # The one thing this does not do is skip the durability *read*: that is
    # not the trigger, it is the proof. Without it a repair-all click that
    # lands where the button used to be is indistinguishable from success,
    # and the first sign of trouble is gear breaking mid-run in Hell.
    repair_below_pct: float = 70.0
    # T1 (R186): skip the Akara trip when vitals are effectively full.
    # Exactly-full was the old bar, and a character 1 hp short paid a
    # 26 s cross-town walk for a sliver (T54 run 4). Akara also heals the
    # merc, so the merc gets its own bar (its hp reads on the 0-128
    # client scale; `Monster.life_pct`) — and a DEAD merc does not block
    # the skip, because Kashya's resurrect step owns that case.
    heal_skip_hp_pct: float = 95.0
    heal_skip_mana_pct: float = 90.0
    heal_skip_merc_pct: float = 60.0
    walk_retries: int = 3  # travel clicks that open a dialog (see _walk_guarded)
    # How far to step aside when a route keeps clicking the same object
    # (R111). Far enough to change the angle, short enough that the
    # sidestep itself is unlikely to cross anything interactive.
    sidestep: int = 7
    # How far to the SIDE of a known obstacle to route, when one keeps
    # being clicked. Bigger than `sidestep` because it is measured from
    # the obstacle rather than from us, and has to clear it properly.
    detour: int = 14
    # Objects need the same treatment as NPCs, and for a stronger reason:
    # perception is capped at 80 subtiles, but the client only keeps NEARBY
    # ROOMS loaded at all, so a distant stash is not merely out of range —
    # it is absent from the unit table entirely. T13 failed here, standing
    # at Akara after the heal with the stash unloaded across town (R69).
    #
    # T51 later MEASURED that room horizon rather than inferring it, and
    # this comment turned out to be the whole story: dropped items vanish
    # from the unit table at 46-67 subtiles regardless of what radius we
    # ask for, so the 80 cap never binds anywhere in this codebase. The
    # knowledge was here since T13 and simply never reached the places
    # that were still quoting 80 as if it were the reach.
    object_positions: dict[int, tuple[int, int]] = field(
        default_factory=lambda: {
            offsets.OBJ_STASH: (5856, 5734),
            offsets.OBJ_WAYPOINT_A1: (5884, 5709),
        }
    )


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
        carried: Callable[[GameSession], CarriedItems] | None = None,
        carried_with_sockets: Callable[[GameSession], CarriedItems] | None = None,
        read_player_fn: Callable[[GameSession], Player | None] = read_player,
        alert: Callable[[str], None] = _default_alert,
        notice: Callable[[str], None] | None = None,
        narrate: Callable[[str], None] | None = None,
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

    def _blocking_panels_open(self) -> list[int]:
        """Which panels are currently making world input illegal.

        Asked of `uistate` rather than a list kept here, because the two
        lists disagreeing is a silent bug: a panel that blocks input but is
        absent from this side is one the layer can neither recognise nor
        close, so the walk it broke surfaces as a bare NavigationError with
        no diagnosis and no recovery. That is exactly what happened when a
        travel click landed on the WAYPOINT during T19 (R85) — the waypoint
        panel has been in the blocking set since P2, but town.py only knew
        about the NPC menu, the stash, and the inventory.
        """
        return [p for p in uistate.blocking_panels() if self._panel_open(p)]

    def _any_panel_open(self) -> bool:
        return bool(self._blocking_panels_open())

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
        interrupted_by: list[str] = []
        for attempt in range(1 + self.config.walk_retries):
            self._check_stop()
            try:
                self.walk_to(destination)
                return
            except NavigationError:
                blocking = self._blocking_panels_open()
                if not blocking:
                    raise  # a real pathing failure, not an accidental chat
                interrupted_by += [
                    offsets.UI_NAMES.get(p, f"ui_{p:#x}") for p in blocking
                ]
                self.close_panels()
                if attempt:
                    # It has happened before, so the same route will do it
                    # again: closing the panel and re-walking repeats the
                    # identical trajectory and the identical misclick. The
                    # waypoint sits almost in front of Akara, so every
                    # travel click toward her rakes across it (R111, live in
                    # T27). Move sideways first and the ray changes.
                    self._sidestep(destination, blocking)
        raise TownError(
            f"could not reach {destination}: travel clicks kept opening "
            f"panels after {self.config.walk_retries} recoveries "
            f"({', '.join(interrupted_by)}) — the route may run straight "
            "through a crowd, or past something clickable"
        )

    # Which world object raises which panel, for routing around the thing
    # that keeps being clicked. Only objects we know the position of are
    # useful here, which is exactly the set that has a configured position.
    _PANEL_OBSTACLE = {
        offsets.UI_WPMENU: offsets.OBJ_WAYPOINT_A1,
        offsets.UI_STASH: offsets.OBJ_STASH,
    }

    def _sidestep(
        self, destination: tuple[int, int], blocking: list[int] | None = None
    ) -> None:
        """Break a repeating misclick by changing where we walk FROM.

        The navigator moves by clicking TOWARD the destination, so anything
        interactive on that line gets clicked instead of walked past — and
        retrying from the same spot aims down the same line at the same
        object, forever.

        Stepping a few subtiles sideways is not enough when the obstacle is
        close: after the first misclick the character is standing right
        beside it, and a small step barely moves the angle. T27 hit exactly
        that — the waypoint sits at the same y as Akara's approach point, so
        it is squarely on the route (R111). So when the offending panel
        identifies a known object, this walks around THAT, to a point well
        to its side, and the final approach then comes in from a new angle.
        Both sides are tried before giving up.

        Best-effort by design: a failed detour must not replace the error the
        caller actually cares about. Preferred to clicking somewhere "empty"
        to dismiss the panel, which trades a known misclick for an unknown
        one — in town, "empty" ground is frequently an NPC.
        """
        player = self._read_player(self.session)
        if player is None:
            return
        px, py = player.position
        dx, dy = destination[0] - px, destination[1] - py
        span = max(abs(dx), abs(dy))
        if not span:
            return
        perp = (-dy / span, dx / span)

        obstacle = None
        for panel_id in blocking or []:
            kind = self._PANEL_OBSTACLE.get(panel_id)
            if kind is not None:
                obstacle = self._find_object(kind) or self.config.object_positions.get(
                    kind
                )
                if obstacle:
                    break

        if obstacle is None:
            self._try_walk((round(px + perp[0] * self.config.sidestep),
                            round(py + perp[1] * self.config.sidestep)))
            return
        # Round the obstacle, not ourselves: the far side is what changes the
        # approach angle enough to matter.
        for sign in (1, -1):
            target = (
                round(obstacle[0] + perp[0] * sign * self.config.detour),
                round(obstacle[1] + perp[1] * sign * self.config.detour),
            )
            if self._try_walk(target):
                return

    def _try_walk(self, target: tuple[int, int]) -> bool:
        """Walk somewhere, tolerating failure. Returns whether it arrived."""
        try:
            self.walk_to(target)
            return True
        except NavigationError:
            return False
        finally:
            if self._any_panel_open():
                self.close_panels()

    def _clear_stray_ui(self, keep: int | None = None) -> str:
        """ESC anything open that we did not ask for. Returns what it found.

        The user's rule, from watching two runs lock themselves out
        (2026-08-01): *check for unexpected dialogs/screens, close them
        immediately if they are not the current expected target, move the
        mouse pointer a little, and click elsewhere.*

        Deliberately wider than `close_panels`, which walks the known
        BLOCKING list. Two reasons. A dialog box is smaller than a panel
        and need not be in that list at all — Warriv's travel prompt is
        the one that cost a run — and `blocks_input` is a claim about
        clicks landing on the panel, which is not the same question as
        "is something in the way of what I meant to do". Anything open
        that is not our target is in the way by definition.

        Best effort on purpose: it reports rather than raises, because it
        runs on the recovery path and a recovery that can fail loudly is
        just a second way to lose the run.
        """
        found: list[str] = []
        for _ in range(1 + self.config.panel_click_retries):
            state = uistate.read_ui_state(self.session, self.panel._ui_array)
            stray = {
                panel
                for panel in state.open_panels
                # The automap is open scenery, not an obstacle: it takes no
                # clicks and the human may well have left it on. Closing
                # everything that is merely OPEN would fight them for it
                # every retry.
                if panel != keep and panel != offsets.UI_AUTOMAP
            }
            if not stray:
                break
            found.append(
                ", ".join(
                    sorted(
                        offsets.UI_NAMES.get(panel, f"ui_{panel:#x}")
                        for panel in stray
                    )
                )
            )
            try:
                self.menu.press_escape()
            except Exception:  # noqa: BLE001 - recovery must not raise
                break
            self._sleep(self.config.panel_settle_s)
        return "; ".join(found)

    def _walk_near(
        self, target: tuple[int, int], minimum: int = 0, turn: int = 0
    ) -> None:
        """Get within clicking distance of `target` WITHOUT walking onto it.

        A travel click that lands on an NPC opens their dialog instead of
        moving, and the dialog then blocks every later click (T12, R66). So
        stop `npc_standoff` subtiles short, on our own side of the target,
        and leave the interaction to a deliberate click. Already close
        enough? Then do not walk at all — the shortest walk is none.

        `minimum` is the other end of that range, and it exists because
        TOO CLOSE is its own failure: a click on the tile you are
        standing on does nothing in D2. Stage B ended with the character
        at (5885, 5710) clicking the waypoint at (5884, 5709) — distance
        1 — three times, because clicking a distant object makes the
        character WALK ONTO it, and every retry then found itself
        already 'close enough' and re-clicked from the same hopeless
        spot. A one-sided range cannot express 'step back'.

        **The walk is a request; the position is the proof.** This used to
        ask for a step-back and assume it happened, and assuming is what
        cost the run on 2026-08-01: the deliberate click that follows lands
        on a DISTANT object, which makes the character walk onto it, so
        every retry begins standing on the thing it means to click. The
        step-back was being issued and then quietly undone, three times,
        from a position `minimum` was written to prevent. So each attempt
        is verified, and a walk that did not achieve the standoff is tried
        again from wherever it actually ended up — the same trust-nothing
        discipline as the skill switch and the deposit.
        """
        for _ in range(1 + self.config.interact_retries):
            player = self._read_player(self.session)
            if player is None:
                self._walk_guarded(target)
                return
            px, py = player.position
            dx, dy = px - target[0], py - target[1]
            distance = max(abs(dx), abs(dy))
            if turn == 0 and minimum <= distance <= self.config.interact_range:
                return
            if distance == 0:
                dx, dy, distance = 1, 1, 1  # standing dead centre: any way out
            scale = self.config.npc_standoff / distance
            for _ in range(turn % 4):
                # A quarter turn around the target. `turn` is for a retry
                # that must not repeat itself: if the last click hit a
                # BYSTANDER standing between us and the thing we meant to
                # click, then re-approaching the same side puts them right
                # back in the way. Changing where we stand changes what is
                # in front of us, which is the only thing that can help.
                dx, dy = -dy, dx
            self._walk_guarded(
                (round(target[0] + dx * scale), round(target[1] + dy * scale))
            )
            if turn or minimum <= 0:
                return  # a deliberate reposition is one walk, by definition

    def _approach_ally(self, kind: int, name: str) -> tuple[int, int]:
        """Get within clicking range of an NPC, walking blind if we must.

        Perception only reaches 46-67 subtiles (T51), and a town NPC is
        routinely further than that from where a game drops you — T12's first live
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

    def _approach_object(
        self, kind: int, name: str, turn: int = 0
    ) -> tuple[int, int]:
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
            self._walk_near(known, minimum=self.config.min_interact_range)
            position = self._find_object(kind)
            if position is None:
                raise TownError(
                    f"{name} still not visible after walking to {known} — the "
                    "configured position may be wrong for this map"
                )
        self._walk_near(
            position, minimum=self.config.min_interact_range, turn=turn
        )
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

    def send_until(
        self,
        send: Callable[[], None],
        condition: Callable[[], bool],
        *,
        what: str,
    ) -> int:
        """Send something until its effect is observed. Returns sends made.

        One place for the lesson this codebase has now paid for four times:
        **a send that arrives while the UI is animating is simply lost**, so
        anything sent once and verified once will eventually fail on a bad
        frame. It was lost clicks on a dialog row (R80), then a lost click on
        the stash, then a lost ESC that killed T27 at its first step (R94).
        Clicks, keys and ESC are all the same problem, so they get the same
        answer rather than three similar ones that drift apart.

        The first send is immediate — the common case pays nothing — and only
        a send that did not take pays the settle before the next try.
        """
        attempts = 1 + self.config.panel_click_retries
        sent = 0
        for attempt in range(attempts):
            if attempt:
                self._sleep(self.config.panel_settle_s)
                if condition():  # the earlier send landed late
                    return sent
            self._check_stop()
            send()
            sent += 1
            if self._await(condition, self.config.verify_timeout_s):
                return sent
        state = uistate.read_ui_state(self.session, self.panel._ui_array)
        raise TownError(
            f"{what}: no effect after {sent} attempt(s); panels open: "
            f"{', '.join(state.names) or 'none'}"
        )

    def close_panels(self) -> None:
        """ESC closes whatever panel is up; verify each one actually closed.

        Every panel that blocks input, not the three the town steps happen
        to open themselves: the point of this call is to make the NEXT walk
        legal, so the list has to match what `GatedInput` refuses on. A
        stray travel click can open a panel no town step ever opens — the
        waypoint, during T19 (R85) — and a panel absent from this list can
        neither be closed nor named.

        Some ESC presses close two panels at once (the shop and the dialog
        behind it), which is why each is re-checked rather than pressed for
        blindly.

        **The ESC is retried**, because a key sent while a panel is still
        animating in is swallowed exactly like a click is (R80) — and this
        was the last place still sending one hopeful press. T27 died on it
        at the first step: the heal opens Akara's dialog and closes it
        immediately, so the ESC arrived while the dialog was still opening,
        and a 3-second wait then declared the panel unclosable (R94). The
        first press stays immediate, so the common case costs nothing; only
        a press that failed pays the settle.
        """
        for panel_id in uistate.blocking_panels():
            if not self._panel_open(panel_id):
                continue
            name = offsets.UI_NAMES.get(panel_id, str(panel_id))
            self.send_until(
                self.menu.press_escape,
                lambda p=panel_id: not self._panel_open(p),
                what=f"closing {name} with ESC",
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
        self.close_panels()

    def point(self, name: str) -> UIPoint:
        """Look up a calibrated point, refusing an unknown or unmeasured one.

        Refusing here rather than at click time is deliberate: a step that
        cannot possibly succeed should not first walk across town.
        """
        found = self.config.ui_points.get(name)
        if found is None:
            known = ", ".join(sorted(self.config.ui_points)) or "none"
            raise Uncalibrated(f"no UI point named {name!r} (known: {known})")
        if not found.calibrated:
            raise Uncalibrated(
                f"{name} is not calibrated — run the T25 calibration battery. "
                f"{found.note}"
            )
        return found

    def point_pixel(self, point: UIPoint) -> tuple[int, int]:
        """Where to click for `point`, resolved NOW.

        Screen-anchored points come straight off the client rect. NPC-anchored
        ones must be projected from where the NPC is *at this moment* (R97):
        the dialog is drawn relative to them, they wander, and the camera
        follows the player — so a position computed a second ago is already
        the wrong answer. Both readings are taken fresh here for that reason.
        """
        rect = self.panel.window.client_rect()
        if not point.npc_anchored:
            return point.pixel(rect)
        player = self._read_player(self.session)
        if player is None:
            raise TownError(f"{point.name}: player unreadable, cannot project")
        npc_world = self._find_ally(point.anchor_npc)
        if npc_world is None:
            raise TownError(
                f"{point.name}: the anchoring NPC (kind {point.anchor_npc}) is "
                "not in perception range, so the row cannot be located — a "
                "dialog row is positioned relative to its NPC, not the screen"
            )
        npc_screen = projection_for(player.position, rect).world_to_screen(*npc_world)
        return point.pixel_from_npc(npc_screen)

    def click_point(
        self,
        point: UIPoint,
        condition: Callable[[], bool] | None = None,
    ) -> None:
        """Click a named point until its effect is observed.

        `condition` defaults to the point's own `opens` panel, so a caller
        with a better proof (durability restored, a live merc) passes it and
        a caller without one still never trusts the click itself.
        """
        if condition is None:
            if point.opens is None:
                raise Uncalibrated(
                    f"{point.name} has no expected panel and no condition was "
                    "given — there would be no way to tell the click worked"
                )
            opens = point.opens
            condition = lambda: self._panel_open(opens)  # noqa: E731
        if point.by_keyboard:
            self.select_dialog_row(point, condition)
            return
        # `point_pixel` is passed, not called: every retry re-locates the
        # target. For an NPC-anchored row that matters — the NPC can take a
        # step between attempts, and re-clicking where they used to be is
        # how a retry becomes a click on a different row (R97).
        self.click_in_panel_until(
            point.panel,
            lambda: self.point_pixel(point),
            condition,
            what=point.name,
        )

    def select_dialog_row(
        self, point: UIPoint, condition: Callable[[], bool]
    ) -> None:
        """Choose an NPC dialog row by ordinal: N-1 Downs, then Enter.

        The highlight opens on row 1, Down advances it, and it wraps at the
        end (T34). Nothing on screen is located, which is the whole point:
        the row's PIXELS move when the NPC paces, its INDEX does not. Every
        positional approach this replaces failed for that one reason.

        A retry REOPENS the dialog rather than pressing more keys. The count
        only means anything from a freshly opened menu, where the highlight
        is known to be on row 1; after a failed attempt it could be anywhere,
        and pressing on from an unknown position is how you select something
        you did not intend — which at Kashya costs 50,000 gold.
        """
        if point.keyboard_row is None or point.keyboard_row < 1:
            raise Uncalibrated(f"{point.name} has no keyboard row")
        npc_name = offsets.NPC_KINDS.get(point.anchor_npc or -1, "the NPC")
        for attempt in range(1 + self.config.panel_click_retries):
            self._check_stop()
            if attempt:
                self.close_panels()
                if point.anchor_npc is None:
                    break  # nothing to reopen; the caller owns this dialog
                self.open_npc_dialog(point.anchor_npc, npc_name)
            self._sleep(self.config.panel_settle_s)
            if not self._panel_open(point.panel):
                break
            for _ in range(point.keyboard_row - 1):
                self.panel.press_key(point.panel, VK_DOWN)
                self._sleep(self.config.key_step_s)
            self.panel.press_key(point.panel, VK_RETURN)
            if self._await(condition, self.config.interact_timeout_s):
                return
        state = uistate.read_ui_state(self.session, self.panel._ui_array)
        raise TownError(
            f"{point.name}: row {point.keyboard_row}"
            + (f" of {point.row_count}" if point.row_count else "")
            + " selected by keyboard had no effect; panels now open: "
            f"{', '.join(state.names) or 'none'} — this menu may have a "
            "different number of rows in this state (R56)"
        )

    def click_in_panel_until(
        self,
        panel_id: int,
        locate: Callable[[], tuple[int, int]],
        condition: Callable[[], bool],
        *,
        what: str,
    ) -> None:
        """Click a spot inside a panel until it has its effect.

        `locate` is a callable, not a point, because the answer can change
        between attempts: an NPC dialog row is positioned relative to the
        NPC, and the NPC can take a step (R97). Re-clicking where the row
        used to be is how a retry lands on a different option.

        The flag going up does not mean the panel is ready either: D2
        animates dialogs in, and clicks landing during that window are
        simply lost — which is what a single immediate click ran into (R80).
        So: settle, locate, click, watch for the effect, retry a couple of
        times, and if it never lands say what WAS on screen rather than only
        what was not.
        """
        clicks = 0
        tried: list[tuple[int, int]] = []
        for _ in range(1 + self.config.panel_click_retries):
            self._check_stop()
            self._sleep(self.config.panel_settle_s)
            if not self._panel_open(panel_id):
                break  # the panel we were told to click in has gone
            sx, sy = locate()
            tried.append((sx, sy))
            self.panel.click(panel_id, sx, sy)
            clicks += 1
            if self._await(condition, self.config.interact_timeout_s):
                return
        state = uistate.read_ui_state(self.session, self.panel._ui_array)
        # Report the clicks actually SENT and where, not the budget: the
        # loop stops early when the panel vanishes, and "clicked 3 times"
        # hid whether T19's menu closed on the first click or survived to
        # the third (R85). The positions matter too now that they can differ
        # between attempts.
        raise TownError(
            f"{what}: clicked {tried or 'nowhere'} in "
            f"{offsets.UI_NAMES.get(panel_id, panel_id)} "
            f"{clicks} time(s) with no effect; "
            f"panels now open: {', '.join(state.names) or 'none'}"
        )

    def open_object_panel(self, kind: int, name: str, panel_id: int) -> tuple[int, int]:
        """Click a world object and wait for its panel. Same shape as
        `open_npc_dialog`, and for the same reasons.

        Clicking the stash from across the room makes the character walk to
        it before the panel opens, so this wait covers a journey too — and
        the single un-retried attempt it replaced was the exact pair of
        mistakes that broke the NPC path (R80). Fixed here before it could
        be discovered live a third time.

        The approach can also END with somebody's dialog open: a travel click
        that lands on a bystander opens it, and if that happens on the last
        click of the walk the walk still succeeds. `_walk_guarded` only
        recovers when the navigator actually failed, so the panel survives to
        the deliberate click — which `GatedInput` then refuses outright,
        killing the step (R106, live in T35). The NPC path has always handled
        this shape; the object path never did. Clear the way each attempt.
        """
        clicked = None
        # Per-attempt trail, for the failure message. Two live runs on
        # 2026-08-01 died here identically and the message could only say
        # where the character finished — which fitted three different
        # explanations, two of which were wrong before this was written.
        # T49 then proved the same clicks work in isolation (approach from
        # 24, standoff 11, panel open first try), so whatever this is only
        # happens in context, and the context is what has to be recorded.
        trail: list[str] = []
        aims = self.config.object_aim_offsets or ((0, 0),)
        for attempt in range(1 + self.config.interact_retries):
            self._check_stop()
            if self._panel_open(panel_id):
                return clicked if clicked is not None else self._find_object(kind)
            self._clear_stray_ui(keep=panel_id)
            # `turn` rotates where we stand, `aim` moves where we point.
            # Both are zero on the first attempt — the plain approach is
            # right almost always — and both change on every retry after
            # it, because the failure this exists for repeats forever
            # otherwise (2026-08-01: the same pixel, three times).
            clicked = self._approach_object(kind, name, turn=attempt)
            if self._any_panel_open():
                # The approach itself opened something; a world click now
                # would be refused rather than land.
                self.close_panels()
            before = self._read_player(self.session)
            distance = (
                max(
                    abs(before.position[0] - clicked[0]),
                    abs(before.position[1] - clicked[1]),
                )
                if before is not None
                else None
            )
            state = uistate.read_ui_state(self.session, self.panel._ui_array)
            offset = aims[attempt % len(aims)]
            aim = (clicked[0] + offset[0], clicked[1] + offset[1])
            screen = self.gated.click_world(*aim)
            landed = self._await(
                lambda: self._panel_open(panel_id), self.config.npc_walk_timeout_s
            )
            after = self._read_player(self.session)
            # What did we open, if not what we asked for? A panel that is
            # not our target means the click hit SOMETHING ELSE — a
            # bystander's dialog, a waypoint menu — and the user's rule
            # applies: close it immediately, move, and click elsewhere.
            # Naming it here is what turns "no panel" into a diagnosis.
            stray = ""
            if not landed:
                intruder = self._clear_stray_ui(keep=panel_id)
                if intruder:
                    stray = f", MISCLICK opened {intruder} (closed)"
            trail.append(
                f"#{attempt + 1} from "
                f"{before.position if before else '?'} d={distance} "
                f"(want {self.config.min_interact_range}-"
                f"{self.config.interact_range}), "
                f"panels {', '.join(state.names) or 'none'}, "
                f"turn {attempt} aim {offset} -> clicked {aim}->{screen}, "
                f"{'OPENED' if landed else 'no panel'}{stray}, "
                f"ended {after.position if after else '?'}"
            )
            if landed:
                return clicked
        raise TownError(
            f"{name} never opened its panel after "
            f"{1 + self.config.interact_retries} attempts — "
            + " | ".join(trail)
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
                return True
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
                return moved
        self._dismiss_chat_console()
        raise TownError(
            f"gold deposit had no effect: still carrying {carried_now()} after "
            f"{1 + self.config.panel_click_retries} attempts — the gold button "
            "may have moved, and note the dialog is invisible to perception "
            "so a miss cannot be distinguished from a refusal (T37)"
        )

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
                    lambda: self.gated.press_key(VK_I),
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
                # Name the actual member: the set holds the Cube AND the
                # tomes now, and "unmovable (the Cube)" printed against a
                # tome reads like a bug in the report (T70 run 3 did
                # exactly that, three times in one preamble).
                kept.append(
                    (item, f"unmovable ({offsets.unmovable_reason(item.kind)})")
                )
            elif item.kind in offsets.RIGHT_CLICK_HAZARD_KINDS:
                kept.append((item, "right-click hazard (potion/tome)"))
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
