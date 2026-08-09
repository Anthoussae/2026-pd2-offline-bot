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

from dataclasses import dataclass, field

from pd2bot import offsets
from pd2bot.perception.items import (
    CarriedItem,
    CarriedItems,
    read_carried_items,
)
from pd2bot.perception.memory import GameSession
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
    # How long ONE approach may spend on capped legs before giving up.
    # `walk_to` returns every 2 s now whether or not it arrived, so a town
    # crossing is many calls rather than one; measured crossings are ~26 s,
    # so this is generous without being unbounded.
    approach_timeout_s: float = 60.0
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


