"""The step handlers behind the run vocabulary: what each TOML step does.

P4 declared the step NAMES and validated `runs/cold-plains.toml` against
them; this is where each name gets a ticking implementation. Steps are
supplied their collaborators through `RunServices` at registry-build time,
so a run file never mentions a town layer or a combat module — it says
`town_preamble` and the wiring decides what that means.

Two shapes of step live here, and the difference matters:

**Blocking steps** (`town_preamble`, `waypoint`) do their whole job inside
one tick, because the layers beneath them are already written that way —
`run_preamble` walks across town and back, `take` polls until the area id
changes. That is safe precisely where they run: town is the one place the
survival ladder has nothing to say, and the waypoint trip is a loading
screen. The reflex ladder is not consulted during them, which would be
unacceptable anywhere else.

**Ticked steps** (`clear_radius`, `pickup`) do one small thing per tick and
return, so the ladder gets a look between every decision. Everything that
happens in Hell is one of these — that is the whole reason the engine is a
loop rather than a script.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot import mapframe, offsets
from pd2bot.behavior.actions import (
    PICKUP_AIM_POINTS,
    InteractObject,
    MoveTo,
    PickUpItem,
)
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.run import ParamSpec, StepRegistry, StepSpec
from pd2bot.items import CarriedItems
from pd2bot.narrate import noop as narrate_noop
from pd2bot.navigate import NavigationError
from pd2bot.pickit import Pickit, belt_count, potion_type_of
from pd2bot.runlog import NullRunLog
from pd2bot.snapshot import GameSnapshot
from pd2bot.uistate import blocking_panels
from pd2bot.units import GroundItem


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _hop(
    origin: tuple[int, int], destination: tuple[int, int], step: int
) -> tuple[int, int]:
    """One short leg toward `destination`, capped at `step` subtiles.

    `walk_to` BLOCKS until arrival (navigate.py), so a leg is time the
    reflex ladder is not being consulted — the same discipline, and the
    same reason, as `NecroCombat._dash_target`. A patrol built out of one
    `walk_to` per point would cross a Hell field with survival switched
    off for the whole crossing.
    """
    dx, dy = destination[0] - origin[0], destination[1] - origin[1]
    span = max(abs(dx), abs(dy))
    if span <= step:
        return destination
    scale = step / span
    return (round(origin[0] + dx * scale), round(origin[1] + dy * scale))


# How close counts as "at" a route waypoint. The navigator's own
# ARRIVAL_RADIUS, restated here because the steps follow routes without
# owning the walking.
_ROUTE_WAYPOINT_REACH = 3

# How far inside its own area's bounds a patrol ring point must sit
# (R189 c): a point ON the seam has the T55 run 2 problem — reaching it
# crosses the border, and the crossing flips which area's grid plans
# the next walk.
_SEAM_INSET = 4


def _next_route_waypoint(
    route: list[tuple[int, int]], origin: tuple[int, int]
) -> tuple[int, int] | None:
    """The first waypoint of `route` not already underfoot, or None when
    the whole route is within reach (i.e. we are effectively there)."""
    for waypoint in route:
        if _chebyshev(waypoint, origin) > _ROUTE_WAYPOINT_REACH:
            return waypoint
    return None


def _route_leg(
    services: RunServices,
    origin: tuple[int, int],
    target: tuple[int, int],
) -> tuple[int, int] | None:
    """The next short leg toward `target`, following the MAP's answer.

    R181, watched live twice: the atlas answered every navigator question
    and no step ever asked it. Legs were straight-line bearings, so a
    far-corner target had each hop plan locally, clamp at the fence, and
    burn the no-progress budget while the bot visibly shuffled at dead
    edges — and a bearing hop happily leads through a zone exit the
    target is not behind (T53 run 2 wandered into Stony Field that way).

    With a route service wired, the leg aims at the route's next waypoint
    — a route planned on the area's grid never crosses an exit — capped
    at `patrol_step`, because the reflex ladder must get its look between
    legs (the whole reason hops exist). None means the map says NO ROUTE
    EXISTS, and the caller writes the target off on the spot: the honest
    fast-fail the R174 closure wrongly claimed already happened. Without
    a service (open-ground sims, drills), the bearing hop stands.
    """
    if services.route_to is None:
        return _hop(origin, target, services.patrol_step)
    route = services.route_to(target)
    if route is None:
        return None
    waypoint = _next_route_waypoint(route, origin)
    if waypoint is None:
        return _hop(origin, target, services.patrol_step)
    return _hop(origin, waypoint, services.patrol_step)


def _point_away(
    origin: tuple[int, int], repel: tuple[int, int], distance: int
) -> tuple[int, int]:
    """A point `distance` from `repel`, on the far side of `origin`.

    The cleanse hygiene's direction chooser: walk directly away from the
    thing the junk must not land near. Standing exactly ON the repel point
    has no away direction, so any fixed one serves — the distance is what
    matters, not the bearing.
    """
    dx, dy = origin[0] - repel[0], origin[1] - repel[1]
    span = max(abs(dx), abs(dy))
    if span == 0:
        dx, dy, span = 1, 1, 1
    scale = distance / span
    return (round(repel[0] + dx * scale), round(repel[1] + dy * scale))


def _default_alert(reason: str) -> None:  # pragma: no cover - exercised live
    print(f"\n!!  {reason}\n", flush=True)


def _default_log(line: str) -> None:  # pragma: no cover - exercised live
    print(f"  {line}", flush=True)


def _note_unsurveyed(services: RunServices, exc: Exception) -> None:
    """R176 Q2: a give-up caused by UNKNOWN ground gets said loudly, once.

    The navigator's error message already distinguishes "solidly blocked"
    from "never been seen"; only the second has a permanent fix the user
    can order (a survey run), so only the second earns an alert. No
    auto-survey here by decision: a clearance that detours into a survey
    stops being a clearance.
    """
    if services.unsurveyed_alerted or "never been seen" not in str(exc):
        return
    services.unsurveyed_alerted = True
    services.alert(
        "a target sits on UNSURVEYED ground — this run walks around the "
        "gap, but a survey run (runs/survey-*.toml) would map it once and "
        "fix this permanently."
    )


@dataclass
class RunServices:
    """Everything the steps need, bound once when the registry is built."""

    run_preamble: Callable[[], object]
    travel_to: Callable[[int], object]
    combat: object  # a CombatModule
    pickit: Pickit
    carried: Callable[[], CarriedItems]
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    # The loaded posture names (M6 P3), for BUILD-time validation of a
    # step's `posture` parameter. Empty = no postures in this environment
    # (sims, drills), and naming one is then a loud build error rather
    # than a runtime surprise.
    postures: frozenset[str] = frozenset()
    # Tuning that belongs to the steps rather than to a class.
    clear_settle_s: float = 5.0
    pickup_radius: int = 30  # opportunistic pickups during clearance
    pickup_reach: int = 4  # close enough to click an item and have it land
    pickup_attempts: int = 3  # WALKS toward an item before calling it stuck
    # CLICKS per item before calling it stuck — one per T63 sprite-offset,
    # so the budget and the aim schedule are the same length by design:
    # every write-off means every measured aim point was actually tried.
    pickup_click_attempts: int = 8
    pickup_retry_s: float = 1.5  # between attempts on the same item
    alert: Callable[[str], None] = _default_alert
    # Where per-decision detail goes. Separate from `alert`, which is for
    # things a human must act on; this is the run's record.
    log: Callable[[str], None] = _default_log
    # The NARRATIVE channel (R179): one line per broad act, wall-clock
    # stamped by the Narrator behind it. Deliberately coarser than `log`
    # — the contract lives in pd2bot/narrate.py, and every call site here
    # is an editorial decision. Defaults to a no-op so sims and drills
    # stay silent unless they opt in.
    narrate: Callable[[str], None] = narrate_noop
    # Pickup bookkeeping, shared by every step that collects loot.
    #
    # It lives HERE rather than on a step because it must outlast the step
    # that recorded it. Clearance and the sweep both pick things up, and
    # when each kept its own memory the sweep re-attempted an item
    # clearance had already given up on — six clicks on an unpickable
    # unique instead of three (found in the P5 sim). Two steps doing the
    # same thing must not differ in what they remember: that is the same
    # asymmetry that cost three live runs in P3, where the heal retried a
    # missed click and the repair did not.
    inventory_full: bool = False
    attempts: dict[int, int] = field(default_factory=dict)
    last_try: dict[int, float] = field(default_factory=dict)
    stuck: set[int] = field(default_factory=set)
    # The inventory cleanse (R117). `cleanse` is the procedure itself
    # (TownLayer.cleanse_inventory behind a closure at wiring time; the
    # sim scripts its own); None means unavailable — which it IS while the
    # pickit vocabulary has unverified ids (pickit.cleanse_keep returns
    # None, and the wiring passes that straight through). A failed pickup
    # queues one; it runs at the next safe moment, defined as no live
    # hostile within `cleanse_safe_radius` — the cleanse stands still with
    # panels open, which is precisely what must never happen in a fight.
    cleanse: Callable[[], int] | None = None
    cleanse_queued: bool = False
    # Close whatever blocking panel is up (TownLayer.close_panels behind a
    # closure at wiring time). None means unavailable, and the steps treat
    # it as "nothing I can do" rather than as "nothing to do".
    #
    # The field needs this because a panel outside town is not recoverable
    # by waiting: `GatedInput` refuses every send while one is open, so the
    # bot decides correctly and reaches the game with none of it. Stage B's
    # tenth attempt opened the waypoint menu with a mis-placed cast and
    # spent its remaining 10 s being refused, then chickened out with the
    # area untouched. The town layer has closed stray panels since R85; the
    # field simply had no way to ask.
    clear_panels: Callable[[], None] | None = None
    # -- the patrol (2026-08-01) ------------------------------------------
    #
    # `clear_radius` decides the area is clear when no live monster is
    # within `radius` of the centre — and it can decide that from a
    # STANDSTILL only while the radius fits inside perception. T51
    # measured perception on 2026-08-01: items vanish at 46-67 subtiles,
    # room-quantised, NOT the 80 `units.PERCEPTION_RADIUS` claims (that
    # constant never binds; the client's loaded-room horizon does).
    # `runs/cold-plains.toml` asks for 150, so it has always been
    # declaring clear a circle it can see under a third of.
    #
    # The patrol walks the circle instead. Numbers live here rather than
    # in the run file because they are judgement calls nobody should have
    # to restate per run; the run file carries the one number the user
    # actually tunes, which is the radius.
    patrol_points: int = 8  # sample points evenly spaced around the ring
    # The ring's radius as a FRACTION of the clearance radius. A fraction
    # on purpose (user request: "make the radius value easy to alter"):
    # an absolute ring would stay put while the circle grew around it, so
    # changing the one number would silently stop covering the edge.
    patrol_ring: float = 0.66
    # Subtiles per leg. `walk_to` BLOCKS until arrival (navigate.py), so a
    # leg is time the reflex ladder is not being consulted — the same
    # reason `NecroCombat._dash_target` caps a dash at 8. A little longer
    # than a dash because nothing is being fought yet.
    patrol_step: int = 12
    patrol_reach: int = 6  # close enough to call a point visited
    # Legs WITHOUT GETTING CLOSER before giving up on a point, so a point
    # we can walk toward but never reach cannot hold the run open forever.
    #
    # Counted as lack of progress rather than as a number of legs, which
    # was the first cut and was wrong: consecutive ring points are ~48
    # subtiles apart, so three 12-subtile legs always fell one short and
    # the sim abandoned SEVEN OF EIGHT points while reporting green.
    # A budget that has to be re-derived whenever the ring or the leg
    # length changes is not a budget, it is a coincidence.
    patrol_attempts: int = 3
    # -- writing off a monster we cannot get to ---------------------------
    #
    # The same idea as `stuck` for items and as `patrol_attempts` for ring
    # points, arriving late because `clear_radius` only recently stopped
    # ending the run over it. `send` absorbs `NavigationError` so one
    # unreachable target cannot fail the cycle — correct, and incomplete on
    # its own: nothing then wrote the monster off, so the step re-decided
    # the identical approach every tick and the clearance could never
    # finish. The user watched it "hesitate at great length when an enemy
    # was behind a wall".
    #
    # Ticks of closing on one monster WITHOUT GETTING CLOSER before giving
    # up on it. Progress rather than effort, the same correction the patrol
    # needed: a budget counted in attempts has to be re-derived whenever
    # anything about the geometry changes, and is a coincidence rather than
    # a budget.
    monster_attempts: int = 3
    # How far a written-off monster must MOVE to earn another try.
    #
    # Monsters differ from ring points and from items in the one way that
    # matters here: they walk. The write-off says "unreachable from where it
    # was standing", and a monster that has since left that spot has
    # invalidated the only evidence behind it — which is this codebase's own
    # rule that a retry which cannot differ from the attempt it retries is
    # not a retry. Without this, a monster that gives up on its own wall and
    # walks into the open would be ignored for the rest of the game.
    unreachable_forget: int = 10
    # How far to step off a waypoint after arriving on one (user request).
    # The character lands ON the waypoint with the cursor still over it,
    # which makes the next few clicks — and any ground-targeted cast — a
    # coin flip on opening its menu. Moving off first is cheaper than
    # avoiding it from on top of it.
    waypoint_step_off: int = 10
    # Potion types the belt has refused this game. Kept apart from
    # `inventory_full` because they are different facts with different
    # remedies: the cleanse can free inventory grid space, and nothing
    # the bot does in the field can empty a full belt column.
    #
    # Since T56 (2026-08-02) the set is EVIDENCE-CHECKED both ways rather
    # than sticky: a type only enters it while the live belt count really
    # is at capacity (a click that fails with room in the belt is a MISS,
    # and misses write off the item, not the type), and it leaves the set
    # the moment drinking makes room again — "nothing the bot does in the
    # field can empty a full belt column" forgot that the ladder empties
    # them all game long, and a game that starts with one transiently full
    # column must not end it ignoring the potions it is starving for.
    belt_full: set[str] = field(default_factory=set)
    # Items we have clicked and not yet seen leave the ground: unit_id ->
    # (kind, potion type, position, clicked-at). Pure telemetry — the
    # confirmation narrates the arrival with a belt census, which is what
    # makes the narrative log answer "did the potions actually arrive?"
    # (T56's log showed the same coordinates "picked" twice and the belt
    # still short, and nobody could say what really happened).
    pending_pickup: dict[int, tuple] = field(default_factory=dict)
    # What the most recent pickup click was aimed at: (unit_id, position,
    # when). Telemetry for the "clicked A, got B" case — T71 run 4 had 9
    # of its 13 misses sitting within 2 subtiles of an item that DID come
    # up, so the click was landing on the neighbour. Knowing that turns a
    # one-off forensic finding into a standing measurement.
    last_click: tuple[int, tuple[int, int], float] | None = None
    cleanse_safe_radius: int = 40
    # -- cleanse drop hygiene (R175, user-diagnosed live) ------------------
    #
    # The R173 run found the loop: the cleanse drops junk AT THE FEET,
    # right where the failed pickup is about to click again, and the click
    # scoops the junk straight back. Dropped items appear at the pointer
    # (user observation, watching it happen). So: never drop within this
    # distance of an item we intend to click, and after dropping, get at
    # least this far from the pile before clicking anything. 8 is
    # comfortably past the sprite-overlap zone (a click hits items within
    # a subtile or two) without costing real walking time.
    cleanse_standoff: int = 8
    # Where the last cleanse dropped its junk; None = no pile to avoid.
    # Shared service state, not step state, for the usual reason: both the
    # clearance and the sweep cleanse, and the pile does not care which
    # step made it.
    cleanse_dropped_at: tuple[int, int] | None = None
    # Items that already got their one post-cleanse retry. The cleanse
    # frees space and the bot steps clear of the pile, so the retry
    # genuinely differs from the attempt that failed — once. A second
    # failure of the same item cannot be explained by junk-at-the-feet
    # again, so it is final for this game: re-queueing another cleanse for
    # it is the retry-that-cannot-differ this codebase keeps refusing.
    cleanse_retried: set[int] = field(default_factory=set)
    # Hygiene-walk patience (review 2026-08-02, issue 001). The walk-away
    # and step-off walks are the "acted but achieved nothing" shape the
    # survey's fight gate had: a walk clamped at a wall ARRIVES (honest
    # arrival) without gaining an inch, and an unbounded retry of it pins
    # the bot with every watchdog blind — each tick sends real input.
    # Progress = distance from the repel point growing; `patrol_attempts`
    # progress-free walks spend the patience and the hygiene yields
    # (drop anyway / accept the pile risk), which is the R173 trade again:
    # one risky cleanse beats a pinned character.
    hygiene_walk_best: int | None = None
    hygiene_walk_attempts: int = 0
    # Collect-walk patience (R189, T55 run 2's border livelock): per item,
    # the closest a collect walk has gotten and how many walks have gained
    # nothing since. The walk to the seam item ARRIVED 5 subtiles short of
    # pickup reach every time, clicked nothing, and therefore spent
    # nothing — collect's only budget counted CLICKS. Walks that get no
    # closer now pay the same budget every other mover pays
    # (`pickup_attempts`), and the item is written off as stuck.
    collect_closest: dict[int, int] = field(default_factory=dict)
    collect_stalls: dict[int, int] = field(default_factory=dict)
    # Progress must beat the best distance by this margin to reset a
    # no-progress budget (R189): T55 run 2's ping-pong occasionally
    # landed a single subtile closer, and that hair of "progress" kept
    # the patrol budget resetting forever. Slow-but-real closing still
    # survives — two subtiles over a few legs re-earns the budget.
    patrol_progress_margin: int = 2
    # The sightings memo (T3, R186 — the user's per-run scratch-note
    # idea, verbatim): every wanted item the CLEARANCE saw, by unit id,
    # at the position it was seen. Entries are reaped once the spot is
    # back in view and the item is gone (collected or despawned), and
    # `stuck` items do not count as pending. The sweep re-walks the ring
    # ONLY while this holds something unaccounted for — the full re-walk
    # of ground the clearance just patrolled was ~60-120 s of the run,
    # spent mostly confirming emptiness. Dies with the run, like every
    # RunServices field: a memo, not a memory.
    #
    # Value = (position, kind, potion type or None). Kind and type exist
    # so `pending_sightings` can re-ask WANTEDNESS at sweep time (review
    # 002, potions-live-validation): an item recorded as wanted can stop
    # being wanted — a mana potion sighted early, then belt_full["mana"]
    # set — and a memo that cannot re-check kept the sweep walking the
    # ring for a bottle nobody would pick up on arrival.
    wanted_seen: dict[int, tuple[tuple[int, int], int, str | None]] = field(
        default_factory=dict
    )
    # -- the survey step (R175/R176) ---------------------------------------
    #
    # Both closures are wired closures over the map store (wiring.py) so
    # the step never learns what a MapStore is — the same treatment
    # `cleanse` gets. None = no survey service in this environment, and
    # the step finishes immediately rather than guessing.
    survey_targets: Callable[[], list[tuple[int, int]]] | None = None
    survey_coverage: Callable[[], str] | None = None
    # -- the traverse step (M6 P2) -----------------------------------------
    #
    # Wired closures over the exit reader and the exit memory, so the
    # step never learns what a GameSession or an ExitMemory is (the
    # survey-closure treatment). None = unavailable in this environment;
    # the step waits on the reader and treats missing memory as cold.
    level_exits: Callable[[], object | None] | None = None  # -> ExitScan
    exit_recall: Callable[[int, int], tuple[int, int] | None] | None = None
    exit_remember: (
        Callable[[int, int, tuple[int, int]], None] | None
    ) = None
    # -- the route service (R181) ------------------------------------------
    #
    # `route_to(target)` plans A* over the navigator's grid (atlas + live
    # overlay) and returns the simplified waypoint list, or None when NO
    # PATH EXISTS. Read-only — no clicks, no walking — and cached briefly
    # by the wiring, because re-planning every tick is the tick-rate waste
    # this repo keeps refusing. None (the field, not the answer) means no
    # service is wired: open-ground sims and drills fall back to the old
    # straight-line hops via `_route_leg`.
    route_to: Callable[
        [tuple[int, int]], list[tuple[int, int]] | None
    ] | None = None
    # Fight only what comes this close while surveying (R176 Q1): a
    # survey is not a clearance, and the reflex ladder plus chicken stay
    # on above this either way.
    survey_engage_radius: int = 30
    # Hard cap on survey walking, as legs. A backstop against convergence
    # bugs, not a tuning knob — but sized for a big Hell area with
    # give-up retries included (~13 subtiles a leg, so this is several
    # kilometres of walking). The first Cold Plains attempt showed the
    # real risk is a LOOP that never sends survey legs at all, which this
    # cannot catch; `survey_fight_patience` is what catches that.
    survey_max_legs: int = 500
    # Consecutive fighting ticks in which neither the distance to the
    # gating monster nor its hp improves before the survey writes it off
    # and walks on. ~10 s at the engine's tick rate: far longer than any
    # deliberate combat pause (restrike 1 s, revives ~2 s), far shorter
    # than the 14 minutes the first Cold Plains survey burned on a
    # monster it could approach forever and reach never.
    survey_fight_patience: int = 20
    # Whether this game has already alerted about a target on unsurveyed
    # ground (R176 Q2: no auto-survey mid-run — say it loudly, once, and
    # recommend the survey run instead). Once, because the same run will
    # often give up on several such targets and each repeat of the alert
    # buys nothing.
    unsurveyed_alerted: bool = False
    # -- the run event log (P6/P7) ----------------------------------------
    #
    # The steps' own events: area transitions, wanted drops, collections,
    # accidental pickups, the cleanse. Defaults to the null sink so the
    # sim and unit tests stay silent; `wiring.py` passes the real log.
    runlog: object = field(default_factory=NullRunLog)
    frame: Callable[[], object] | None = None
    # Wanted items already announced this run, by unit id — `item.dropped`
    # fires on the TRANSITION into the wanted set, so a rune lying on the
    # floor for thirty ticks is one event, not thirty.
    seen_drops: set[int] = field(default_factory=set)
    # -- the countess endgame (M6 P4) --------------------------------------
    #
    # Judgement calls that belong to the step, not the run file — the run
    # file carries what the user tunes (the chamber anchor, the radii).
    #
    # How far screen-north of the chamber anchor the staging point sits.
    # Screen-north is the world (-1,-1) diagonal (the projection is
    # sx=(wx-wy), sy=(wx+wy): decreasing both is "up"). 25 is outside
    # the aggressive posture's engagement bubble but inside one or two
    # advance legs — staged, not camped.
    staging_distance: int = 25
    # The chamber sweep's whole budget (R212 Q7: "<15 s"). One short
    # in-and-out pass so a blind corner cannot hide her; spent across
    # every entry into the sweep, not per entry, so a countess who blinks
    # in and out of perception cannot stretch it forever.
    sweep_budget_s: float = 15.0
    # Ticks the advance will hold for the revive wall without the wall
    # GROWING before it advances anyway, loudly. The brake is the user's
    # tactic (revives tank the approach); the bound exists because a
    # fresh cellar with nothing dead nearby can never raise a wall, and
    # a brake that cannot release is a hang, not a tactic (~10 s at tick
    # rate — the survey's fight-patience shape).
    advance_revive_patience: int = 20


# -- blocking steps ------------------------------------------------------------


@dataclass
class TownPreambleStep:
    """Run P3's verified preamble: heal, repair, the R75 inventory loop, merc."""

    services: RunServices
    name: str = "town_preamble"

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        report = self.services.run_preamble()
        note = "; ".join(getattr(report, "log", []) or []) or "preamble complete"
        return StepOutcome(done=True, acted=True, note=note)


@dataclass
class WaypointStep:
    """Take the waypoint to `dest`, then record where we landed.

    The arrival position goes on the shared blackboard under "arrival",
    which is how `clear_radius` learns where its centre is without either
    step knowing the other exists.
    """

    services: RunServices
    dest: int
    name: str = "waypoint"
    # The post-arrival settle. Small numbers on purpose: this runs once
    # per area change, and its whole job is to outlast a load stutter.
    settle_timeout_s: float = 8.0
    settle_poll_s: float = 0.2
    stable_reads: int = 3

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        self.services.travel_to(self.dest)
        settled = self.settle(ctx)
        # Read the position AFTER travelling: the snapshot handed to this
        # tick was taken in town, before the trip.
        arrival = None
        fresh = None
        if ctx.snapshot is not None:
            fresh = ctx.snapshot()
            arrival = fresh.player.position if fresh.player is not None else None
        if arrival is None and snap.player is not None:
            arrival = snap.player.position
        if arrival is not None:
            ctx.notes["arrival"] = arrival
        stepped = self.step_off(arrival, fresh if fresh is not None else snap, ctx)
        return StepOutcome(
            done=True, acted=True,
            note=f"arrived at {arrival}"
            + ("" if settled else " (never settled)")
            + (f", stepped off to {stepped}" if stepped else ""),
        )

    def step_off(
        self,
        arrival: tuple[int, int] | None,
        snap: GameSnapshot,
        ctx: EngineContext,
    ) -> tuple[int, int] | None:
        """Walk a few subtiles off the waypoint we just arrived on.

        The user's request, from watching the tenth stage-B attempt lock
        itself out: *when travelling through a waypoint it will be right
        under the mouse pointer*, so the arrival point is the one square of
        ground where an ordinary click is likeliest to open a menu instead
        of doing what it meant. Standing there while the combat module
        starts placing casts is asking for it.

        Conditioned on a clickable object ACTUALLY being within stepping
        distance rather than done unconditionally after every trip. That is
        the user's reasoning stated precisely — the hazard is the thing
        under the cursor, not the travelling — and it means a run that
        arrives somewhere harmless pays nothing and behaves exactly as
        before.

        The arrival note is recorded BEFORE this runs, so `clear_radius`
        still centres on the waypoint — the run's landmark does not move
        just because the character does.

        Best effort, and deliberately so: a failed walk here is a nicety
        not delivered, and turning it into a raise would let a cosmetic
        step end a run that was otherwise fine. The panel clear runs first
        for the case where the trip itself left something open.
        """
        if self.services.clear_panels is not None:
            try:
                self.services.clear_panels()
            except Exception as exc:  # noqa: BLE001 - never fatal here
                self.services.log(f"waypoint: could not clear panels ({exc})")
        if arrival is None:
            return None
        offset = self.services.waypoint_step_off
        underfoot = [
            o.position
            for o in snap.objects
            if o.kind in offsets.INTERACTIVE_OBJECT_KINDS
            and _chebyshev(o.position, arrival) <= offset
        ]
        if not underfoot:
            return None
        candidates = [
            (arrival[0] + dx * offset, arrival[1] + dy * offset)
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (0, 1))
        ]
        # Furthest from what we are standing on, first: the direction is the
        # whole point, and a step that ended up beside the waypoint instead
        # of on it would have solved nothing.
        candidates.sort(
            key=lambda t: min(_chebyshev(t, o) for o in underfoot), reverse=True
        )
        for target in candidates:
            try:
                ctx.executor.execute(MoveTo(target))
            except Exception as exc:  # noqa: BLE001 - try the next direction
                self.services.log(f"waypoint: step off to {target} failed ({exc})")
                continue
            return target
        return None

    def settle(self, ctx: EngineContext) -> bool:
        """Wait for the new area to finish arriving before anything is sent.

        `travel_to` returns when the area ID changes, which is the START of
        the new area loading, not the end. The user watched run 5 stutter
        right there — "common when changing areas" — and the bot's next act
        was a hotkey press that the loading client simply dropped. Three
        presses inside 1.8 s all landed in that window, the switch never
        verified, and the run died on an unverified skill.

        So: poll until the world reads back consistently — a player, in one
        area, unchanged across `stable_reads` consecutive looks. Cheap
        insurance measured in a second or two, once per area change, in the
        one place where the client is guaranteed to be busy.

        Returns whether it settled; a timeout is reported, not raised. The
        engine is a loop and the ladder is about to get its look either way,
        which is a better answer than refusing to continue.
        """
        if ctx.snapshot is None:
            return False
        deadline = self.services.clock() + self.settle_timeout_s
        # Bounded by COUNT as well as by time: an injected clock that
        # does not advance (a sim, a test) would never reach a deadline,
        # and a wait that can hang forever is worse than one that gives
        # up early — the caller treats a timeout as reportable, not fatal.
        budget = int(self.settle_timeout_s / max(self.settle_poll_s, 1e-6)) + 1
        stable = 0
        last: tuple[int, object] | None = None
        while self.services.clock() < deadline and budget > 0:
            budget -= 1
            snap = ctx.snapshot()
            here = (
                (snap.area.level_no, snap.player.position)
                if snap.area is not None and snap.player is not None
                else None
            )
            if here is not None and here == last:
                stable += 1
                if stable >= self.stable_reads:
                    return True
            else:
                stable = 0
            last = here
            self.services.sleep(self.settle_poll_s)
        return False


@dataclass
class DoneStep:
    """The run is over. The cycle leaves the game; nothing to do here."""

    services: RunServices
    name: str = "done"

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        return StepOutcome(done=True, note="run complete")


# -- ticked steps ---------------------------------------------------------------


@dataclass
class _PickupMixin:
    """Shared pickup machinery: both clearance and the sweep collect loot.

    Kept in one place on purpose. Two steps doing the same thing and
    differing in how robust they are is the exact shape that cost P3 three
    live runs (the heal retried a missed click, the repair did not — and
    repair was the one that failed).
    """

    services: RunServices

    def _belt_has_room(self, potion: str, carried: CarriedItems | None = None) -> bool:
        if carried is None:
            carried = self.services.carried()
        capacity = self.services.pickit.belt_capacity.get(potion, 0)
        return belt_count(carried, potion) < capacity

    def log_wanted_drops(
        self, snap: GameSnapshot, carried: CarriedItems | None = None
    ) -> None:
        """One `item.dropped` for every whitelisted item, wherever it lies.

        Deliberately independent of the caller's circle and of every
        situational filter. `decide` returning anything but "skip" IS the
        whitelist verdict; a belt that happens to be full, an inventory
        that happens to be full, and a walk that already gave up are
        facts about US, not about whether the item dropped. The operator
        asked for the drop itself to be on the record either way
        (2026-08-06), and the run that prompted it is the argument: 13
        wanted items were clicked and never came up, and reconstructing
        that needed unit-id correlation because the event stream could
        not answer it.

        Called from `wanted_items`, which is the ONE enumerator every
        collecting step shares — including `TraverseStep`, whose absence
        from the old call path is exactly why T71 run 4 logged four
        drops on one floor and none on the four floors it descended
        through. Putting it anywhere else would re-open that hole the
        next time a step learns to collect.

        Costs nothing when the log is off (sims, unit tests): the guard
        is checked before any pickit work.
        """
        log = getattr(self.services, "runlog", None)
        if log is None or not getattr(log, "enabled", False):
            return
        seen = self.services.seen_drops
        for item in snap.ground_items:
            if item.unit_id in seen:
                continue
            if carried is None:
                carried = self.services.carried()
            action, rule = self.services.pickit.decide(item, carried)
            if action == "skip":
                continue
            self._log_drop(item, rule)

    def wanted_items(
        self, snap: GameSnapshot, centre: tuple[int, int], radius: int
    ) -> list[GroundItem]:
        carried = self.services.carried()
        # Record BEFORE filtering: what dropped is not the same question
        # as what this step is in a position to collect right now.
        self.log_wanted_drops(snap, carried)
        found = []
        for item in snap.ground_items:
            if item.unit_id in self.services.stuck:
                continue
            if _chebyshev(item.position, centre) > radius:
                continue
            action, _ = self.services.pickit.decide(item, carried)
            if action == "skip":
                continue
            if action == "belt":
                # Belt-bound potions are unaffected by a full inventory —
                # they route to the belt — but a belt that is still at
                # capacity for this type will refuse it again, and
                # re-attempting it every tick is how run 4 spent its time.
                # The write-off expires the moment drinking makes room:
                # the belt drains all game, and a belt-full mark that
                # outlived the fullness is how T56 game 2 starved.
                potion = potion_type_of(item)
                if potion in self.services.belt_full:
                    if self._belt_has_room(potion, carried):
                        self.services.belt_full.discard(potion)
                        self.services.log(
                            f"pickup: the belt has room for {potion} again "
                            f"— {potion} potions are wanted again"
                        )
                    else:
                        continue
            elif self.services.inventory_full:
                continue
            found.append(item)
        return found

    def confirm_pickups(self, snap: GameSnapshot) -> None:
        """Narrate clicked items that actually left the ground.

        Verification stays where it always was — the wanted list re-derives
        from the ground every tick — but until now nothing SAID an item
        came up, so the narrative showed decisions with no outcomes and the
        belt census had to be reconstructed by hand. One line per arrival,
        with the belt state for potions, closes that. An item still lying
        there after its clicks is simply forgotten once stale (the per-item
        attempts budget is the real bookkeeping; this is telemetry).
        """
        if not self.services.pending_pickup:
            return
        on_ground = {g.unit_id for g in snap.ground_items}
        now = self.services.clock()
        census: str | None = None
        for unit_id, (kind, potion, position, clicked) in list(
            self.services.pending_pickup.items()
        ):
            if unit_id in on_ground:
                if now - clicked > 10.0:
                    del self.services.pending_pickup[unit_id]
                continue
            del self.services.pending_pickup[unit_id]
            frame = self.services.frame() if self.services.frame else None
            self.services.runlog.event(
                "item.collected",
                unit_id=unit_id,
                item=self._logged_name(kind),
                item_kind=kind,
                potion=potion,
                position=mapframe.describe(position, frame=frame),
                took_s=round(now - clicked, 2),
                accidental=False,
                **self._attribution(unit_id, position, now),
            )
            if potion is not None:
                if census is None:
                    carried = self.services.carried()
                    capacity = self.services.pickit.belt_capacity
                    census = ", ".join(
                        f"{t} {belt_count(carried, t)}/{capacity.get(t, 0)}"
                        for t in ("healing", "mana", "rejuv")
                    )
                self.services.narrate(
                    f"pickup: kind {kind} at {position} came up — belt {census}"
                )
            else:
                self.services.narrate(f"pickup: kind {kind} at {position} came up")

    def _attribution(
        self, unit_id: int, position: tuple[int, int], now: float
    ) -> dict:
        """Which click actually produced this pickup, when it was not this
        item's own — the "clicked A, got B" measurement.

        T71 run 4: nine of thirteen misses lay within 1-2 subtiles of an
        item that DID come up, the sharpest case being a Nef rune missed
        at (12544, 11084) while a Hel rune one subtile away came up. The
        bot recorded a clean success for the neighbour and kept spending
        clicks on the target, learning nothing from the strongest signal
        in the run.

        Deliberately conservative — it only speaks when the most recent
        click was aimed at a DIFFERENT unit, was recent enough to still
        be resolving, and was close enough that the sprites could
        plausibly overlap. Anything else returns nothing rather than a
        guess: an attribution that fires loosely would poison the very
        measurement it exists to produce.
        """
        aimed = self.services.last_click
        if aimed is None:
            return {}
        target_id, target_at, when = aimed
        if target_id == unit_id:
            return {}  # its own click; nothing to attribute
        if now - when > self.services.pickup_retry_s * 2:
            return {}  # too stale to blame
        if _chebyshev(target_at, position) > 2:
            return {}  # too far apart for one click to have hit both
        return {"attributed_to": target_id, "attributed_aim": list(target_at)}

    def _log_drop(self, item: GroundItem, rule: str | None = None) -> None:
        """One `item.dropped` per wanted item, ever (P7).

        Keyed on the unit id and fired on the TRANSITION into the wanted
        set, so a rune lying on the floor for thirty ticks is one event
        rather than thirty. The T70 Thul was invisible to behaviour while
        perception listed it the whole time; this is the line that would
        have made that obvious.

        `rule` is passed by callers that have already asked the pickit,
        so the common path decides once rather than twice.
        """
        if item.unit_id in self.services.seen_drops:
            return
        self.services.seen_drops.add(item.unit_id)
        if rule is None:
            _, rule = self.services.pickit.decide(item, self.services.carried())
        frame = self.services.frame() if self.services.frame else None
        self.services.runlog.event(
            "item.dropped",
            unit_id=item.unit_id,
            item=self._logged_name(item.kind),
            item_kind=item.kind,
            quality=item.quality,
            sockets=item.sockets,
            rule=rule,
            position=mapframe.describe(item.position, frame=frame),
        )

    def _log_click_write_off(
        self,
        snap: GameSnapshot,
        item: GroundItem,
        attempts: int,
        potion: str | None,
    ) -> None:
        """Say why the click budget was spent without the item coming up.

        The reason MIRRORS the decision the caller is about to make —
        this reports, it does not decide (P1's constraint: the
        belt-full/inventory-full reasoning is load-bearing and was paid
        for by T56's starvation loop).

        `neighbours` rides along because the density correlation is the
        leading hypothesis for why these clicks miss (T71 run 4: misses
        averaged 1.6 items within 2 subtiles against 0.9 for successes,
        and 9 of 13 had a COLLECTED neighbour that close). Carrying the
        number means the next investigation reads it instead of
        re-deriving it.
        """
        log = getattr(self.services, "runlog", None)
        if log is None or not getattr(log, "enabled", False):
            return
        if potion is not None:
            reason = (
                "clicks did not land"
                if self._belt_has_room(potion)
                else f"belt full for {potion}"
            )
        else:
            # What the caller concludes, stated as the inference it is —
            # item sizes are unreadable, so persistence is the only
            # signal available and it cannot tell a full grid from a
            # missed click. P4 of the pickup plan splits these.
            reason = "inventory full (inferred from persistence)"
        near = 0
        for other in snap.ground_items:
            if other.unit_id == item.unit_id:
                continue
            if _chebyshev(other.position, item.position) <= 2:
                near += 1
        frame = self.services.frame() if self.services.frame else None
        log.event(
            "item.abandoned",
            unit_id=item.unit_id,
            item=self._logged_name(item.kind),
            item_kind=item.kind,
            reason=reason,
            clicks=attempts,
            aim_points=[list(p) for p in PICKUP_AIM_POINTS[:attempts]],
            neighbours=near,
            position=mapframe.describe(item.position, frame=frame),
        )

    def _logged_name(self, kind: int) -> str:
        """Code-anchored name or an honest `kind <n>` (R144)."""
        table = getattr(self.services.pickit, "item_table", None)
        if table is not None:
            try:
                name = table.name_for(kind)
            except Exception:  # noqa: BLE001
                name = None
            if name:
                return name
        return f"kind {kind}"

    def note_wanted_sightings(
        self, snap: GameSnapshot, centre: tuple[int, int], radius: int
    ) -> None:
        """Book wanted items into the sightings memo, and reap the dead.

        Two halves of one bookkeeping (T3, R186). RECORD: every wanted
        item currently visible inside the circle. REAP: a remembered spot
        that is comfortably back inside perception with no such item on
        the ground means collected (or despawned) — either way, no longer
        pending. What remains when the clearance finishes is the sweep's
        entire justification for re-walking the ring.
        """
        services = self.services
        # `wanted_items` logs the drops now (for every step, not just the
        # ones that keep a sightings memo), so this loop is back to being
        # about the memo alone.
        for item in self.wanted_items(snap, centre, radius):
            services.wanted_seen[item.unit_id] = (
                item.position,
                item.kind,
                potion_type_of(item),
            )
        player = snap.player
        if player is None:
            return
        on_ground = {g.unit_id for g in snap.ground_items}
        for unit_id, (position, _, _) in list(services.wanted_seen.items()):
            if unit_id in on_ground:
                continue
            if _chebyshev(position, player.position) <= 40:
                # Well inside the loaded-room horizon (46-67, T51): the
                # spot is in view and the item is not on it.
                del services.wanted_seen[unit_id]

    def pending_sightings(self) -> list[tuple[int, tuple[int, int]]]:
        """Memo entries still worth walking for: seen, not collected, not
        written off as stuck — and still WANTED (review 002,
        potions-live-validation).

        Wantedness is re-asked at read time because it changes after the
        sighting: a mana potion recorded early stops being worth a walk
        once `belt_full` gains "mana", and a non-potion stops once the
        inventory fills. The memo used to be unable to ask (it kept only
        positions), so the sweep walked the ring for bottles it would
        refuse on arrival — one avoidable ~60 s ring walk per run where
        a belt type filled mid-clearance (T55 run 1's shape). The same
        checks `wanted_items` applies, minus the expiry bookkeeping —
        deciding whether to WALK must not mutate the belt-full marks.
        """
        pending = []
        carried = None
        for unit_id, (position, _, potion) in self.services.wanted_seen.items():
            if unit_id in self.services.stuck:
                continue
            if potion is not None:
                if potion in self.services.belt_full:
                    if carried is None:
                        carried = self.services.carried()
                    if not self._belt_has_room(potion, carried):
                        continue
            elif self.services.inventory_full:
                continue
            pending.append((unit_id, position))
        return pending

    def collect(
        self, snap: GameSnapshot, ctx: EngineContext, item: GroundItem
    ) -> bool:
        """One tick of collecting `item`. Returns whether anything was sent.

        Verification is the item leaving the ground, checked on the NEXT
        tick's snapshot rather than by waiting here — that is what keeps the
        ladder in the loop while looting a floor full of drops.
        """
        now = self.services.clock()
        player = snap.player
        if player is None:
            return False
        distance = _chebyshev(item.position, player.position)
        if distance > self.services.pickup_reach:
            # The R189 budget: a walk that SUCCEEDS without getting closer
            # is not progress (T55 run 2: the seam item's walk arrived 5
            # subtiles short of reach 4 forever, and clicked nothing, so
            # the per-click budget below never spent a cent).
            best = self.services.collect_closest.get(item.unit_id)
            if best is None or distance < best:
                self.services.collect_closest[item.unit_id] = distance
                self.services.collect_stalls[item.unit_id] = 0
            else:
                stalls = self.services.collect_stalls.get(item.unit_id, 0) + 1
                self.services.collect_stalls[item.unit_id] = stalls
                if stalls >= self.services.pickup_attempts:
                    self.services.stuck.add(item.unit_id)
                    self.services.log(
                        f"pickup: item {item.unit_id} at {item.position} "
                        f"written off — {stalls} walks got no closer than "
                        f"{best} (reach is {self.services.pickup_reach})"
                    )
                    self.services.narrate(
                        f"pickup: gave up on the item at {item.position} "
                        "(walks keep arriving short)"
                    )
                    self.services.runlog.event(
                        "item.abandoned", unit_id=item.unit_id,
                        item=self._logged_name(item.kind),
                        reason="walks kept arriving short", walks=stalls,
                    )
                    return True
            if not self.send(ctx, MoveTo(item.position)):
                # Unreachable ground: give up on this item rather than the
                # game, the same way the patrol gives up on a point.
                self.services.stuck.add(item.unit_id)
            return True
        if (
            now - self.services.last_try.get(item.unit_id, -1e9)
            < self.services.pickup_retry_s
        ):
            return False  # the last click is still resolving
        attempts = self.services.attempts.get(item.unit_id, 0)
        if attempts >= self.services.pickup_click_attempts:
            self.services.stuck.add(item.unit_id)
            potion = potion_type_of(item)
            # The click budget is spent. Whatever the diagnosis below
            # concludes, SAY SO — until 2026-08-06 every branch here
            # returned silently, and T71 run 4's eleven click-budget
            # write-offs (a Nef rune and a flawless emerald among them)
            # left no event at all. "Which wanted items did we fail to
            # get" then needed unit-id correlation in a throwaway script.
            self._log_click_write_off(snap, item, attempts, potion)
            if potion is not None:
                # A potion routes to the BELT, so a potion that will not come
                # up says the belt is full for its type — NOT that the
                # inventory grid is. Stage B run 4 conflated the two and
                # reported "INVENTORY FULL" four times for three potions,
                # while the inventory had room the whole time. Worse, it
                # looped: marking full queued a cleanse, the cleanse cleared
                # `inventory_full` and `stuck`, the same potion was retried,
                # and it failed again for the same unchanged reason.
                #
                # But "would not come up" only MEANS belt-full while the
                # belt count agrees (T56: three click misses in a dense
                # pile were diagnosed as "belt full for healing" on a belt
                # that was SHORT, and the type-level write-off then refused
                # every later healing potion in a game that chickened on
                # exactly that starvation). With room in the belt the
                # failure is the CLICK's — the item is written off (the
                # `stuck` add above), the type stays wanted.
                #
                # Recorded per TYPE, because that is the granularity the belt
                # refuses at — same reasoning as `fill_belt`'s own `full` set.
                if self._belt_has_room(potion):
                    self.services.alert(
                        f"pickup: a {potion} potion at {item.position} "
                        f"would not come up after "
                        f"{self.services.pickup_click_attempts} attempts even "
                        f"though the belt has room — click misses "
                        f"suspected. Leaving that one; {potion} potions "
                        "stay wanted."
                    )
                elif potion not in self.services.belt_full:
                    self.services.belt_full.add(potion)
                    self.services.alert(
                        f"belt full for {potion}: a {potion} potion at "
                        f"{item.position} would not come up after "
                        f"{self.services.pickup_click_attempts} attempts. Leaving "
                        f"{potion} potions until drinking makes room; the "
                        "inventory has nothing to do with it."
                    )
                return False
            # A non-potion that will not come up IS the inventory-full tell.
            # The only observable cause we can distinguish is "the inventory
            # has no room" — item sizes are unreadable (P1), so free-cell
            # arithmetic is not available and persistence IS the signal.
            self._mark_inventory_full(item)
            # A failed pickup is the tell for accidental-pickup junk taking
            # up room (R117): ask for a cleanse at the next safe moment —
            # unless this item already failed AFTER a cleanse-and-step-off
            # retry. That retry differed in everything a cleanse can change
            # (space freed, pile avoided), so another cleanse cannot help
            # it, and re-queueing one is how the R173 loop span forever.
            if item.unit_id not in self.services.cleanse_retried:
                self.services.cleanse_queued = True
            return False
        if attempts == 0:
            # Log the DECISION, not just the click (R144). "The bot picked up
            # a wire fleece" took a lost item and an id audit to explain; the
            # rule name plus what was actually read makes the next surprise
            # answer itself, and means nothing has to be kept as evidence.
            action, rule = self.services.pickit.decide(item, self.services.carried())
            self.services.log(
                f"pickup: kind {item.kind} quality {item.quality} "
                f"sockets {item.sockets} at {item.position} -> {action} "
                f"({rule})"
            )
            self.services.narrate(
                f"pickup: kind {item.kind} at {item.position} ({rule})"
            )
        self.services.attempts[item.unit_id] = attempts + 1
        self.services.last_try[item.unit_id] = now
        self.services.pending_pickup[item.unit_id] = (
            item.kind, potion_type_of(item), item.position, now,
        )
        # What this click was AIMED at, so a pickup that lands on the
        # neighbour can say so (`confirm_pickups`). Pure telemetry.
        self.services.last_click = (item.unit_id, item.position, now)
        ctx.executor.execute(
            PickUpItem(
                item.unit_id, item.position, attempt=attempts, kind=item.kind
            )
        )
        return True

    def send(self, ctx: EngineContext, action) -> bool:
        """Execute one action, absorbing a walk that could not be made.

        `NavigationError` means the navigator tried and failed — unknown
        ground, a corner it cannot round, a target it cannot reach. That
        is information about ONE target, not a reason to end the game,
        and it ends the game today: it is not in the engine's
        `SEND_DID_NOT_LAND` pair (rightly — something DID happen), so it
        escapes the step and the runner books a failed run.

        Live, 2026-08-01: the first run that fought since the review
        fixes — four kills, a full revive wall, the circle walked —
        ended on *"gave up after 5 plan cycles without progress; last
        position (5226, 5658), target (5219, 5658)"*. Seven subtiles.
        The patrol already treats an unreachable point this way and
        picks another; the fight and the sweep had no equivalent.

        Deliberately narrow: `InputRefused` and `SkillSwitchFailed` still
        propagate to the engine, which absorbs them and re-decides.
        """
        started = self.services.clock()
        try:
            ctx.executor.execute(action)
        except NavigationError as exc:
            self.services.log(f"could not walk: {exc}")
            # A swallowed walk failure used to leave NOTHING in the run
            # log. T71 run 4's endgame spent four ticks of 25-35 s each
            # this way — visible only as tick durations with nothing
            # inside them, which is precisely the vacuum the event log
            # exists to fill. The absorb behaviour is unchanged; this
            # only says it happened.
            self._log_nav_failure(action, exc, self.services.clock() - started)
            _note_unsurveyed(self.services, exc)
            return False
        return True

    def _log_nav_failure(self, action, exc: Exception, elapsed: float) -> None:
        """Record one absorbed `NavigationError`. Never raises."""
        log = getattr(self.services, "runlog", None)
        if log is None or not getattr(log, "enabled", False):
            return
        target = getattr(action, "target", None) or getattr(
            action, "position", None
        )
        frame = self.services.frame() if self.services.frame else None
        log.event(
            "nav.failed",
            where=getattr(self, "name", type(self).__name__),
            action=type(action).__name__,
            target=(
                mapframe.describe(target, frame=frame)
                if target is not None
                else None
            ),
            toward=getattr(action, "toward", None),
            elapsed_s=round(elapsed, 2),
            detail=str(exc),
        )

    def recover_panels(self, snap: GameSnapshot) -> bool:
        """Close a blocking panel that opened outside town. Returns whether.

        Nothing in the field opens a panel on purpose, so one being up means
        a click went somewhere it did not mean to — a cast beside a waypoint
        (stage B's tenth attempt), a stray travel click on the stash. It is
        not a state that resolves by waiting: `GatedInput` refuses every send
        while a blocking panel is open, so the bot keeps deciding correctly
        and keeps reaching the game with none of it, until something else
        gives up. That run spent its last 10 s that way and chickened out
        with the area untouched.

        Checked before anything else a step does, because until it is true
        nothing else a step does can land.

        THE CHAT CONSOLE IS EXEMPT. Nothing in the field opens it but a
        human — and the human opening it mid-run is most likely typing
        `abort` (T54 run 4: this method ESC'd the console over and over
        while the user typed, wiping the half-typed abort each time, so
        the abort never reached chat at all). Left open it costs refused
        sends for a few seconds; the engine keeps polling the stop
        channel, and the submitted line lands within a tick. A console
        that stays open past the refusal limit still ends the game
        safely — which is also an acceptable outcome of someone trying
        to stop the bot.
        """
        if snap.ui is None or not snap.ui.blocks_input or snap.in_town:
            return False
        blocking_open = snap.ui.open_panels & frozenset(blocking_panels())
        if blocking_open == {offsets.UI_CHAT_CONSOLE}:
            return False
        if self.services.clear_panels is None:
            return False
        names = ", ".join(snap.ui.names) or "an unnamed panel"
        self.services.log(f"clearing {names}: nothing in the field opens one on purpose")
        self.services.clear_panels()
        return True

    def _desired_nearby(
        self, snap: GameSnapshot, origin: tuple[int, int], radius: int
    ) -> list[GroundItem]:
        """Ground items the pickit wants within `radius`, IGNORING the
        stuck/full suppressions. The cleanse hygiene needs this exact list:
        the item whose failed pickup queued the cleanse is in `stuck` right
        now, and it is precisely the item the retry will click next — a
        filter that hides it would put the drop pile back at its feet."""
        carried = self.services.carried()
        return [
            item for item in snap.ground_items
            if _chebyshev(item.position, origin) <= radius
            and self.services.pickit.decide(item, carried)[0] != "skip"
        ]

    def maybe_cleanse(self, snap: GameSnapshot, ctx: EngineContext) -> bool:
        """Run a queued inventory cleanse if this is a safe moment — with
        drop hygiene (R175, after the R173 loop the user diagnosed live).

        Safe = no live hostile within `cleanse_safe_radius`. The cleanse is
        a blocking stretch with the inventory open — the character stands
        still and the ladder is not consulted — so it gets the same
        treatment as the town steps: only where nothing can punish it.
        Never in town (the town preamble has its own cleanse pass).

        Hygiene, in tick order:
        1. If the last cleanse left a pile we are still standing on, one
           walk away from it wins the tick — nothing gets clicked near the
           pile. Only once clear does the post-cleanse retry get re-armed,
           because only then does the retry actually differ.
        2. A queued cleanse with a wanted item in click range walks AWAY
           from that item first, and drops only when clear — the junk must
           never land where the next deliberate click is aimed.
        """
        services = self.services
        if snap.player is None or snap.in_town:
            return False
        origin = snap.player.position

        def walk_progressing(repel: tuple[int, int]) -> bool:
            """Book one hygiene-walk tick; False when patience is spent.

            A clamped walk ARRIVES without gaining ground, so 'the send
            succeeded' cannot be the loop condition — distance from the
            repel point growing is (review 2026-08-02, issue 001).
            """
            distance = _chebyshev(origin, repel)
            if services.hygiene_walk_best is None or distance > services.hygiene_walk_best:
                services.hygiene_walk_best = distance
                services.hygiene_walk_attempts = 0
                return True
            services.hygiene_walk_attempts += 1
            if services.hygiene_walk_attempts < services.patrol_attempts:
                return True
            self.services.log(
                f"cleanse hygiene: {services.hygiene_walk_attempts} walks "
                f"gained no distance from {repel}; accepting the risk "
                "rather than looping"
            )
            return False

        def walk_done() -> None:
            services.hygiene_walk_best = None
            services.hygiene_walk_attempts = 0

        # 1 — step off the drop pile before anything near it gets clicked.
        if services.cleanse_dropped_at is not None:
            if _chebyshev(origin, services.cleanse_dropped_at) < services.cleanse_standoff:
                away = _point_away(
                    origin, services.cleanse_dropped_at,
                    services.cleanse_standoff + 4,
                )
                if walk_progressing(services.cleanse_dropped_at) and self.send(
                    ctx, MoveTo(away)
                ):
                    self.services.log(
                        f"cleanse hygiene: stepping off the drop pile at "
                        f"{services.cleanse_dropped_at} toward {away}"
                    )
                    return True
                # Boxed in (walk failed or patience spent): clear the
                # marker rather than loop. One risky retry beats a hang.
                self.services.log(
                    "cleanse hygiene: could not step off the drop pile; "
                    "accepting the risk rather than looping"
                )
            walk_done()
            services.cleanse_dropped_at = None
            # Clear of the pile (or accepting we cannot get clear): NOW the
            # retry differs — space was freed and the junk is out of the
            # click path — so the written-off items get their one re-try.
            # Once each: an id already in `cleanse_retried` failed AFTER a
            # differing retry, and stays written off for the game.
            for unit_id in list(services.stuck):
                if unit_id not in services.cleanse_retried:
                    services.cleanse_retried.add(unit_id)
                    services.stuck.discard(unit_id)
                    services.attempts.pop(unit_id, None)
            services.inventory_full = False
            return False

        if not services.cleanse_queued or services.cleanse is None:
            return False
        if any(
            _chebyshev(m.position, origin) <= services.cleanse_safe_radius
            for m in snap.live_monsters
        ):
            return False

        # 2 — never drop junk beside something we intend to click.
        desired = self._desired_nearby(snap, origin, services.cleanse_standoff)
        if desired:
            nearest = min(
                desired, key=lambda i: _chebyshev(i.position, origin)
            )
            away = _point_away(
                origin, nearest.position, services.cleanse_standoff + 4
            )
            if walk_progressing(nearest.position) and self.send(
                ctx, MoveTo(away)
            ):
                self.services.log(
                    f"cleanse hygiene: walking clear of wanted item at "
                    f"{nearest.position} before dropping junk"
                )
                return True
            self.services.log(
                "cleanse hygiene: could not walk clear of the wanted item; "
                "dropping here rather than looping"
            )

        walk_done()
        services.cleanse_queued = False
        dropped = services.cleanse()
        frame = self.services.frame() if self.services.frame else None
        self.services.runlog.event(
            "inventory.cleanse", dropped=dropped,
            position=mapframe.describe(origin, frame=frame),
        )
        if dropped:
            self.services.narrate(
                f"cleanse: dropped {dropped} junk item(s) at {origin}"
            )
            # The pile exists where we stand. The re-arm of stuck items
            # deliberately does NOT happen here — it happens in branch 1,
            # after the step-off, when the retry can actually differ.
            services.cleanse_dropped_at = origin
        return True

    def _mark_inventory_full(self, item: GroundItem) -> None:
        """Stop trying non-potion pickups for the rest of the game, loudly.

        A within-game suppression, not a halt: the durable fix is the next
        game's town preamble, which empties the inventory into the stash.
        Suppressing rather than halting is the right severity — a full
        inventory costs loot, it does not endanger the character.
        """
        if self.services.inventory_full:
            return
        self.services.inventory_full = True
        self.services.alert(
            f"INVENTORY FULL: item kind {item.kind} at {item.position} would "
            f"not come up after {self.services.pickup_click_attempts} attempts. "
            "Skipping further non-potion pickups this game; the town preamble "
            "empties the inventory next game."
        )


@dataclass
class _PatrolMixin:
    """Walking a ring, so that a standstill reading means something.

    Shared by the clearance and the sweep because they have the identical
    problem and it would be the identical code twice. That is not a style
    preference here: `_PickupMixin` exists for the same reason and its
    docstring records what the alternative cost — two steps doing the same
    thing and differing in how robust they are is the shape that cost P3
    three live runs, where the heal retried a missed click and the repair
    did not.

    **The premise, measured.** A step that decides something about a circle
    of `radius` from a standstill is only sound while perception reaches
    that far, and T51 (2026-08-01) measured what it actually reaches: 12
    potions dropped along a walk, seven of them watched vanishing, at
    **46, 46, 54, 55, 61, 63 and 67 subtiles**. Every one far inside the
    `PERCEPTION_RADIUS` of 80 we had been quoting, and five of the seven
    lost at the same distance whether the radius filter was applied or
    lifted entirely — so the bound is the CLIENT's loaded-room horizon, not
    a constant we can raise. The spread rather than a crisp circle is what
    room-quantised loading predicts.

    Worst case ~46 subtiles. Anything above that has to be walked.
    """

    _points: list[tuple[int, int]] | None = None
    _visited: set[int] = field(default_factory=set)
    _index: int = 0
    _attempts: int = 0  # legs since we last got closer to the current point
    _closest: int | None = None
    # No-route strikes per target (T55 run 1): a torn live-collision read
    # walled the origin in for ~a second and FIVE reachable ring points
    # were written off on single "no route" answers. One answer is a
    # reading; two consecutive answers over fresh grids is a fact — the
    # same distinction the warp's position-verify draws. Genuine
    # no-routes still die in two ticks with zero legs spent.
    _route_denied: dict[tuple[int, int], int] = field(default_factory=dict)

    def patrol_points(
        self, centre: tuple[int, int], area=None
    ) -> list[tuple[int, int]]:
        """The ring, computed once from the centre and the radius.

        Sized as a fraction of `radius` so that changing the radius — the
        one number the user tunes — moves the whole pattern with it. At
        radius 96 the ring sits at ~63: adjacent points are ~49 apart and
        the furthest edge of the circle is ~33 from the nearest point,
        which is inside even T51's worst-case 46.

        Points outside the AREA's own bounds (with a small seam inset)
        are dropped at birth (R189 c): "clear Cold Plains" must never
        chase ground that belongs to Blood Moor — the seam is where T55
        run 2 livelocked, with each border crossing flipping which
        area's grid planned the next walk.
        """
        if self._points is None:
            if area is None:
                # A mid-transition read (review 003, potions-live-
                # validation): without the area's bounds the seam filter
                # cannot run, and CACHING an unfiltered ring would re-open
                # the T55 run 2 border surface for the whole step. Plan
                # nothing this tick; the next tick with the area readable
                # computes and caches the filtered ring.
                return []
            ring = max(1, round(self.radius * self.services.patrol_ring))
            count = max(1, self.services.patrol_points)
            points = [
                (
                    centre[0] + round(ring * math.cos(2 * math.pi * i / count)),
                    centre[1] + round(ring * math.sin(2 * math.pi * i / count)),
                )
                for i in range(count)
            ]
            inset = _SEAM_INSET
            left, top, right, bottom = area.bounds_subtiles
            kept = [
                (x, y)
                for x, y in points
                if left + inset <= x < right - inset
                and top + inset <= y < bottom - inset
            ]
            if len(kept) < len(points):
                self.services.log(
                    f"patrol: dropped {len(points) - len(kept)} ring "
                    "point(s) outside the area's bounds"
                )
            self._points = kept
        return self._points

    @property
    def patrol_complete(self) -> bool:
        if not self.patrol:
            return True
        if self._points is None:
            return False  # not even planned yet, let alone walked
        return len(self._visited) >= len(self._points)

    def _advance(self) -> None:
        """Done with the current point, for whatever reason. Next."""
        self._visited.add(self._index)
        self._attempts = 0
        self._closest = None
        points = self._points or []
        for _ in range(len(points)):
            self._index = (self._index + 1) % max(1, len(points))
            if self._index not in self._visited:
                return

    def walk_the_circle(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        """One leg of the patrol. Only called with nothing else to do.

        Every exit from here reports `acted`, because every one of them
        either sent a walk or made a decision that moved the patrol on —
        which is what keeps both watchdogs fed without either of them
        needing to know a patrol exists.
        """
        points = self.patrol_points(self._centre, snap.area)  # type: ignore[arg-type]
        if not points:
            return StepOutcome(
                done=False, acted=True,
                note="patrol ring empty (every point outside the area)",
            )
        target = points[self._index]
        here = snap.player.position  # type: ignore[union-attr]

        distance = _chebyshev(here, target)
        if distance <= self.services.patrol_reach:
            self.services.log(f"patrol: reached {target}")
            self._advance()
            return StepOutcome(done=False, acted=True, note=f"patrol reached {target}")

        # Progress, not effort — and progress must beat the best by a
        # MARGIN (R189 b): T55 run 2's ping-pong landed a subtile closer
        # now and then, and that hair kept this budget resetting forever.
        if (
            self._closest is None
            or distance <= self._closest - self.services.patrol_progress_margin
        ):
            self._closest = distance
            self._attempts = 0
        else:
            self._attempts += 1

        if self._attempts >= self.services.patrol_attempts:
            # Walkable in principle, unreachable in practice. Visited
            # means "dealt with", not "stood on" — otherwise one awkward
            # corner holds the whole step open.
            self.services.log(
                f"patrol: giving up on {target} after {self._attempts} legs "
                f"that got no closer (still {distance} away)"
            )
            self._advance()
            return StepOutcome(done=False, acted=True, note=f"patrol gave up on {target}")

        leg = _route_leg(self.services, here, target)
        if leg is None:
            # The map says no route exists (R181) — believed only when a
            # SECOND ask over a fresh grid agrees (T55 run 1: a torn
            # grid read produced five spurious no-routes in one second).
            strikes = self._route_denied.get(target, 0) + 1
            self._route_denied[target] = strikes
            if strikes < 2:
                return StepOutcome(
                    done=False, acted=True,
                    note=f"no route to {target} — asking again",
                )
            self.services.log(f"patrol: no route to {target} — written off")
            self.services.narrate(f"patrol: no route to ring point {target}")
            self._advance()
            return StepOutcome(
                done=False, acted=True, note=f"patrol wrote off {target} (no route)"
            )
        self._route_denied.pop(target, None)
        try:
            ctx.executor.execute(MoveTo(leg))
        except NavigationError as exc:
            # Unknown ground is impassable BY DESIGN (navigate.py: "that
            # ground has never been seen — survey it first"), and a ring
            # several screens out will often name ground nobody has read.
            # Left uncaught this fails the whole cycle. Deliberately NOT
            # `except Exception`: InputRefused and SkillSwitchFailed must
            # keep reaching the engine, which absorbs them and re-decides
            # — swallowing those would mark a point visited that we never
            # actually tried to walk to.
            self.services.log(f"patrol: skipping {target} ({exc})")
            self.services.narrate(f"patrol: gave up ring point {target}")
            _note_unsurveyed(self.services, exc)
            self._advance()
            return StepOutcome(done=False, acted=True, note=f"patrol skipped {target}")
        return StepOutcome(done=False, acted=True, note=f"patrol leg to {leg}")


@dataclass
class ClearRadiusStep(_PatrolMixin, _PickupMixin):
    """Kill everything within `radius` of the centre, then settle.

    Termination is deliberately not "no monsters right now": a pack can be
    mid-spawn, a poisoned monster is still alive for a few seconds, and a
    revive can drag something into range. So the step requires the radius to
    read EMPTY continuously for `clear_settle_s` before it calls the job
    done — the same "wait for it to stay true" discipline the town layer's
    verifications use.

    **With `patrol` on, it walks the circle before believing it.** The
    standstill version is only sound while the radius fits inside
    perception, and T51 measured perception at **46-67 subtiles** — not
    the 80 the constant claims. Past that, "no monster within `radius`"
    means "no monster within ~50", and the rest of the circle is being
    declared clear unobserved. `runs/cold-plains.toml` has asked for 150
    since it was written. Both 2026-08-01 runs also completed without
    ever fighting, because nothing happened to be inside stage B's 50 —
    a trial run that can pass without doing the thing it tests.

    The patrol is deliberately unclever (user: *we don't need this to
    become enormously onerous*): a fixed ring of sample points, a visited
    set, one short leg per tick. Fighting always wins the tick; the
    patrol is only what happens when there is nothing to clear.
    """

    radius: int = 150
    centre_note: str = "arrival"
    patrol: bool = False
    # The combat posture this step fights in (M6 P3, R212 Q5). None =
    # leave the module as it is (pre-M6 runs change nothing). Validated
    # against the loaded posture names at registry-build time, so an
    # unknown name never reaches a game.
    posture: str | None = None
    name: str = "clear_radius"
    _empty_since: float | None = None
    _posture_applied: bool = False
    _centre: tuple[int, int] | None = None
    # Monsters inside the radius that we have given up reaching, and where
    # each was standing when we did. The position is what allows the
    # write-off to expire (see `_reachable`); a bare set could not.
    _unreachable: dict[int, tuple[int, int]] = field(default_factory=dict)
    # Per monster: the closest we have got, and how many closing ticks have
    # achieved nothing since. Same shape as the patrol's own two fields.
    _closest_to: dict[int, int] = field(default_factory=dict)
    _no_progress: dict[int, int] = field(default_factory=dict)
    # No-route strikes per monster (T55 run 1's torn grid read): one
    # answer is a reading, two consecutive answers is a fact.
    _no_route: dict[int, int] = field(default_factory=dict)

    # -- monsters we cannot get to -------------------------------------------

    def _reachable(self, monster) -> bool:
        """Does this monster still count toward the clearance?

        False once it has been written off — and the write-off EXPIRES the
        moment the monster leaves the spot it was written off at, because
        the only evidence behind it was "we could not get there from here"
        and it is no longer where "there" was.
        """
        where = self._unreachable.get(monster.unit_id)
        if where is None:
            return True
        if _chebyshev(monster.position, where) <= self.services.unreachable_forget:
            return False
        self._unreachable.pop(monster.unit_id, None)
        self._closest_to.pop(monster.unit_id, None)
        self._no_progress.pop(monster.unit_id, None)
        self.services.log(
            f"clearance: monster {monster.unit_id} moved from {where} to "
            f"{monster.position}, so it gets another try"
        )
        return True

    def _write_off(self, unit_id: int, position: tuple[int, int], why: str) -> None:
        if unit_id in self._unreachable:
            return
        self._unreachable[unit_id] = position
        self.services.log(
            f"clearance: writing off monster {unit_id} at {position} — {why}. "
            "It stops counting toward the radius unless it moves."
        )
        self.services.narrate(
            f"clearance: wrote off monster {unit_id} at {position} ({why})"
        )

    def _closing_progress(self, monster, origin: tuple[int, int]) -> None:
        """Book one closing tick against `monster`, and write it off at budget.

        Only called on the ticks where the STEP decided to close on it, never
        during a fight `engage` is running: the module's deliberate pauses —
        a restrike cooldown, holding off for the revives — are not failures
        to reach anything, and counting them here would write off the monster
        we are in the middle of killing.
        """
        unit_id = monster.unit_id
        distance = _chebyshev(monster.position, origin)
        best = self._closest_to.get(unit_id)
        if best is None or distance < best:
            self._closest_to[unit_id] = distance
            self._no_progress[unit_id] = 0
            return
        count = self._no_progress.get(unit_id, 0) + 1
        self._no_progress[unit_id] = count
        if count >= self.services.monster_attempts:
            self._write_off(
                unit_id,
                monster.position,
                f"{count} closing ticks got no closer than {best} subtiles",
            )

    def centre(self, snap: GameSnapshot, ctx: EngineContext) -> tuple[int, int] | None:
        if self._centre is None:
            noted = ctx.notes.get(self.centre_note)
            if isinstance(noted, tuple):
                self._centre = noted
            elif snap.player is not None:
                # No note (a run that starts mid-area): here is as good a
                # centre as any, and saying so beats refusing to run.
                self._centre = snap.player.position
            if self._centre is not None:
                # Publish the circle for whoever sweeps it afterwards.
                #
                # The sweep has to cover the same ground this step cleared,
                # and the alternative — restating the radius in the run file
                # under `pickup` — is two numbers that mean one thing and can
                # drift apart silently. It would also quietly break the
                # `--radius` override, which only rewrites `clear_radius`
                # (the user's request was to make the radius easy to alter,
                # and "alter it in two places" is not that).
                ctx.notes["cleared"] = {
                    "centre": self._centre,
                    "radius": self.radius,
                    "patrol": self.patrol,
                }
        return self._centre

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.posture is not None and not self._posture_applied:
            # First tick: fight this step in its declared posture. The
            # module keeps all its bookkeeping across the swap — a
            # posture is a manner, not a new fight — and modules without
            # postures (fakes, sims) are simply left alone.
            set_posture = getattr(self.services.combat, "set_posture", None)
            if set_posture is not None:
                set_posture(self.posture)
                self.services.narrate(f"combat posture: {self.posture}")
            self._posture_applied = True
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        centre = self.centre(snap, ctx)
        if centre is None or snap.player is None:
            return StepOutcome(done=False)
        now = self.services.clock()
        self.confirm_pickups(snap)
        # The sightings memo (T3): whatever the pickit wants and this
        # step does not collect is the sweep's work order — and its only
        # reason to re-walk the ring.
        self.note_wanted_sightings(snap, centre, self.radius)

        in_radius = [
            m for m in snap.live_monsters
            if _chebyshev(m.position, centre) <= self.radius and self._reachable(m)
        ]
        if in_radius:
            self._empty_since = None
            # A fight is not a failed patrol leg. The character walks
            # TOWARD the monster, which is away from wherever the patrol
            # was heading, so a `_closest` recorded before the fight makes
            # every leg after it look like no progress — and three such
            # ticks abandon a point that was never unreachable. Live,
            # 2026-08-01: two points given up on from 20 subtiles, which
            # is walking distance, not a wall. The budget measures one
            # attempt, so an interruption ends the attempt.
            self._closest = None
            self._attempts = 0
            action = self.services.combat.engage(snap, ctx)
            if action is not None:
                if not self.send(ctx, action):
                    # The walk failed. `MoveTo.toward` names the monster the
                    # module was dashing at, which is the only honest way to
                    # know — `_select_target` prefers never-struck over
                    # nearest, so the step cannot recover it by guessing, and
                    # blaming the wrong monster would write off a reachable
                    # one. Nothing is blamed for a retreat or a drift, which
                    # carry no `toward` because they aim at open ground.
                    blamed = getattr(action, "toward", None)
                    target = next(
                        (m for m in in_radius if m.unit_id == blamed), None
                    )
                    if target is not None:
                        # Straight to a write-off rather than onto the
                        # no-progress budget: `walk_to` has already spent
                        # five plan cycles and a shake-loose before raising,
                        # so this is not one hopeful attempt, and the
                        # expiry-on-movement rule is what keeps it honest.
                        self._write_off(
                            target.unit_id, target.position, "the walk to it failed"
                        )
                return StepOutcome(done=False, acted=True)
            # Nothing to do offensively this tick (everything freshly
            # poisoned, or waiting for the revives): pick up loot instead of
            # standing still. Potions especially — the belt is the supply.
            items = self.wanted_items(snap, snap.player.position, self.services.pickup_radius)
            if items and self.collect(snap, ctx, items[0]):
                return StepOutcome(done=False, acted=True)
            if self.maybe_cleanse(snap, ctx):
                return StepOutcome(done=False, acted=True, note="inventory cleansed")
            # Before calling this patience, check it IS patience. This step
            # measures from the arrival point and the combat module measures
            # from the player, so a monster can be inside the clearance and
            # outside the fight — and then the module has nothing to say
            # while the step still wants that monster dead. Waiting there is
            # waiting for a kill nobody is going to make (review 001), so
            # ask the module to close the distance. It refuses whenever a
            # fight is actually in progress, which is what keeps this from
            # overriding a deliberate pause.
            nearest = min(
                in_radius,
                key=lambda m: _chebyshev(m.position, snap.player.position),
            )
            # Route-aware closing (R181): ask the map first. No route =
            # an instant write-off (expiry-on-movement keeps it honest),
            # and otherwise the route's next waypoint steers the hop —
            # the module stays grid-ignorant, it just dashes where told.
            via = None
            if self.services.route_to is not None:
                route = self.services.route_to(nearest.position)
                if route is None:
                    # Two-strike like the patrol's (T55 run 1): one torn
                    # grid read must not write off a reachable monster.
                    strikes = self._no_route.get(nearest.unit_id, 0) + 1
                    self._no_route[nearest.unit_id] = strikes
                    if strikes < 2:
                        return StepOutcome(
                            done=False, acted=True,
                            note=f"no route to monster {nearest.unit_id} — asking again",
                        )
                    self._write_off(
                        nearest.unit_id, nearest.position, "no route exists"
                    )
                    return StepOutcome(
                        done=False, acted=True,
                        note=f"no route to monster {nearest.unit_id}",
                    )
                self._no_route.pop(nearest.unit_id, None)
                via = _next_route_waypoint(route, snap.player.position)
            closing = self.services.combat.approach(
                snap, nearest.position, via=via
            )
            if closing is not None:
                if self.send(ctx, closing):
                    # Walked. Whether it ACHIEVED anything is the question,
                    # and the silent version of the hang is the one where
                    # every leg succeeds and none of them gets closer.
                    self._closing_progress(nearest, snap.player.position)
                else:
                    self._write_off(
                        nearest.unit_id, nearest.position, "the walk to it failed"
                    )
                return StepOutcome(
                    done=False, acted=True,
                    note=f"closing on monster {nearest.unit_id} at {nearest.position}",
                )
            # Nothing to send, nothing to pick up, hostiles still standing:
            # this is the skirmish pattern deliberately holding off —
            # `restrike_s` since the last dagger, or `wait_for_revives_s` for
            # the revives to take the front. Poison is doing the killing and
            # the ladder still gets its look every tick. Declared as a wait
            # so the never-idle watchdog does not read patience as a hang
            # (review 003); the worst realistic case is a 6 s restrike
            # against a 10 s limit, which was margin nobody had declared.
            return StepOutcome(done=False, waiting=True)

        # The radius reads clear — but "clear" is only a claim about what
        # we can SEE, and the settle timer must not start while there is
        # still circle we have never looked at. Starting it here was the
        # whole bug: the step would finish on an 80-subtile look at a
        # 150-subtile promise.
        if not self.patrol_complete:
            self._empty_since = None
            return self.walk_the_circle(snap, ctx)

        if self._empty_since is None:
            self._empty_since = now
            return StepOutcome(done=False, acted=True, note="radius reads clear")
        if now - self._empty_since >= self.services.clear_settle_s:
            # Say when "clear" means "clear except for the ones we gave up
            # on". A step that finishes with monsters still standing is the
            # right outcome — finishing beats hanging — but it is not the
            # same outcome as an empty field, and a note that reported both
            # identically would hide the write-off working too hard.
            written_off = (
                f", {len(self._unreachable)} monster(s) written off as "
                "unreachable"
                if self._unreachable
                else ""
            )
            return StepOutcome(
                done=True, acted=True,
                note=f"clear for {self.services.clear_settle_s:.0f}s{written_off}",
            )
        # Sweep loot while the settle timer runs; it is free time — and so
        # is a queued cleanse, with nothing alive to punish standing still.
        items = self.wanted_items(snap, centre, self.radius)
        if items and self.collect(snap, ctx, items[0]):
            return StepOutcome(done=False, acted=True)
        if self.maybe_cleanse(snap, ctx):
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        # The settle timer itself: the radius reads clear and the step is
        # waiting to be sure. `clear_settle_s` is a knob that LOOKS
        # independent of `idle_bail_s`, so raising it used to make the run
        # abandon itself mid-settle (review 003).
        return StepOutcome(done=False, waiting=True)


@dataclass
class PickupStep(_PatrolMixin, _PickupMixin):
    """Sweep the cleared ground for anything the pickit wants.

    **It walks the same circle the clearance did.** Standing where the
    clearance happened to finish and collecting what is visible was the
    bug: visible means the client's loaded-room horizon, which T51 measured
    at 46-67 subtiles (2026-08-01, seven dropped potions watched vanishing)
    — so against a 96-radius circle the far side was not merely dim, it was
    never in the bot's world at all. The user watched a whitelisted Tir
    rune left behind on ground the sweep had no way to see. The pickit
    rules were right the whole time; nothing ever asked them about that
    rune.

    This is the identical flaw the clearance had before it got a patrol,
    and it gets the identical fix from the identical code (`_PatrolMixin`).

    The circle comes from the clearance over the shared blackboard rather
    than from this step's own parameters, so the radius stays ONE number
    (user request) and the `--radius` override reaches the sweep too. A run
    with no clearance falls back to the defaults below and does not patrol,
    because there is no circle to walk.
    """

    radius: int = 150
    centre_note: str = "arrival"
    patrol: bool = False
    name: str = "pickup"
    _centre: tuple[int, int] | None = None
    _resolved: bool = False

    def resolve(self, snap: GameSnapshot, ctx: EngineContext) -> None:
        """Adopt the clearance's circle, or fall back to our own."""
        if self._resolved:
            return
        cleared = ctx.notes.get("cleared")
        if isinstance(cleared, dict):
            centre = cleared.get("centre")
            if isinstance(centre, tuple):
                self._centre = centre
            self.radius = int(cleared.get("radius", self.radius))
            self.patrol = bool(cleared.get("patrol", self.patrol))
            self.services.log(
                f"sweep: covering the cleared circle — centre {self._centre}, "
                f"radius {self.radius}, patrol {'on' if self.patrol else 'off'}"
            )
        if self._centre is None:
            noted = ctx.notes.get(self.centre_note)
            self._centre = (
                noted if isinstance(noted, tuple)
                else (snap.player.position if snap.player else None)
            )
        self._resolved = self._centre is not None

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        self.resolve(snap, ctx)
        if self._centre is None:
            return StepOutcome(done=True, note="nowhere to sweep")
        self.confirm_pickups(snap)
        if self.maybe_cleanse(snap, ctx):
            # Space first, sweep second: a written-off item may be liftable
            # once the junk is gone.
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        items = self.wanted_items(snap, self._centre, self.radius)
        if items:
            if snap.player is not None:
                items.sort(key=lambda i: _chebyshev(i.position, snap.player.position))
            acted = self.collect(snap, ctx, items[0])
            return StepOutcome(done=False, acted=acted)
        # Nothing WE CAN SEE is wanted — which is not the same as nothing
        # left, and treating the two as one is what left the rune behind.
        # But the ring walk now needs EVIDENCE (T3, R186): the clearance
        # already patrolled this circle recording every wanted sighting,
        # so the sweep re-walks only while the memo holds something
        # unaccounted for. No sightings pending = the rune-class item
        # provably does not exist this run, and the old unconditional
        # re-walk spent 60-120 s confirming emptiness.
        if not self.patrol_complete and snap.player is not None:
            self.note_wanted_sightings(snap, self._centre, self.radius)
            pending = self.pending_sightings()
            if not pending:
                return StepOutcome(
                    done=True, acted=True,
                    note="nothing left to pick — every sighting accounted "
                    "for, ring walk skipped",
                )
            return self.walk_the_circle(snap, ctx)
        return StepOutcome(
            done=True, acted=True,
            note="nothing left to pick"
            + (f" (circle walked, {len(self._visited)} points)" if self.patrol else ""),
        )


@dataclass
class SurveyStep(_PickupMixin):
    """Walk an area until its reachable ground is all in the atlas.

    The map store remembers every room ever loaded and every walk records
    as a side effect (M3); route planning already refuses unknown ground.
    This step supplies the missing piece: it keeps walking to the nearest
    *frontier* — recorded walkable ground with unrecorded ground just
    beyond (`pd2bot/survey.py`) — until none remains inside the area's
    bounds. Single-player maps are fixed per character+difficulty, so a
    finished area is finished forever (R175: "permanently reusable").

    Not a clearance (R176 Q1): hostiles get fought only inside
    `survey_engage_radius`; everything further is somebody the survey
    walks politely around. The ladder and chicken stand above as always.

    The frontier list is recomputed by the wiring's closure as the atlas
    grows; written-off targets are remembered by exact position, which is
    stable because the closure caches per room-count — the list only
    changes when new ground was actually recorded, at which point stale
    write-offs mostly stop being frontier at all.
    """

    name: str = "survey"
    _done_targets: set[tuple[int, int]] = field(default_factory=set)
    _route_denied: dict[tuple[int, int], int] = field(default_factory=dict)
    _written_off: int = 0
    _legs: int = 0
    _current: tuple[int, int] | None = None
    _closest: int | None = None
    _attempts: int = 0
    # Monsters a failed walk proved unreachable, and where they stood —
    # the clearance's rule (expiry on movement) in miniature, so a walled
    # monster cannot pin the survey the way one pinned the clearance.
    _unreachable: dict[int, tuple[int, int]] = field(default_factory=dict)
    # Per-monster fight patience: (best distance, last hp, stale ticks).
    # The first Cold Plains survey (2026-08-02) livelocked without this:
    # a monster the bot could walk TOWARD but never reach — every dash
    # succeeded, none arrived — kept winning the tick for 14 minutes, and
    # only failed WALKS were being written off. Progress here is distance
    # closing OR the monster's hp falling: a poison fight legitimately
    # pauses (restrike cooldown, revives building) while the target dies,
    # and counting those pauses as stalling would abandon kills mid-way.
    _fight_progress: dict[int, tuple[int, int, int]] = field(
        default_factory=dict
    )

    def _fightable(self, m) -> bool:
        where = self._unreachable.get(m.unit_id)
        if where is None:
            return True
        if _chebyshev(m.position, where) <= self.services.unreachable_forget:
            return False
        del self._unreachable[m.unit_id]
        self._fight_progress.pop(m.unit_id, None)
        return True

    def _fight_stalled(self, m, origin: tuple[int, int]) -> bool:
        """Book one fighting tick against `m`; True when patience is spent.

        Called once per tick for the monster gating the survey. Distance
        closing or hp falling resets the count — only ticks in which the
        fight moved neither needle count toward giving up.
        """
        distance = _chebyshev(m.position, origin)
        best, last_hp, stale = self._fight_progress.get(
            m.unit_id, (distance + 1, m.hp + 1, 0)
        )
        if distance < best or m.hp < last_hp:
            self._fight_progress[m.unit_id] = (
                min(distance, best), min(m.hp, last_hp), 0
            )
            return False
        stale += 1
        self._fight_progress[m.unit_id] = (best, last_hp, stale)
        if stale < self.services.survey_fight_patience:
            return False
        self._unreachable[m.unit_id] = m.position
        self.services.log(
            f"survey: {stale} fighting ticks moved neither the distance to "
            f"monster {m.unit_id} nor its hp — writing it off at "
            f"{m.position} and surveying on (another look if it moves)"
        )
        return True

    def _finish(self) -> StepOutcome:
        cov = (
            self.services.survey_coverage()
            if self.services.survey_coverage is not None
            else "coverage unknown"
        )
        written = (
            f", {self._written_off} frontier point(s) written off unreachable"
            if self._written_off
            else ""
        )
        note = f"survey complete: {cov}{written}"
        self.services.log(note)
        return StepOutcome(done=True, acted=True, note=note)

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        if self.services.survey_targets is None:
            return StepOutcome(
                done=True,
                note="no survey service wired; nothing this step can do",
            )
        if self.maybe_cleanse(snap, ctx):
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        if snap.player is None:
            return StepOutcome(done=False, waiting=True)
        origin = snap.player.position

        # Fighting wins the tick, but only up close (R176 Q1) — and only
        # while the fight is going somewhere. The first Cold Plains survey
        # spent 14 minutes here on a monster every dash could walk toward
        # and never reach: each walk SUCCEEDED, so the failed-walk
        # write-off below never fired, and the survey starved.
        # `_fight_stalled` is the other half, the same split the clearance
        # learned (failed walks AND walks that succeed without arriving).
        near = [
            m for m in snap.live_monsters
            if _chebyshev(m.position, origin) <= self.services.survey_engage_radius
            and self._fightable(m)
        ]
        if near:
            gating = min(near, key=lambda m: _chebyshev(m.position, origin))
            if self._fight_stalled(gating, origin):
                pass  # written off: fall through and survey this tick
            else:
                action = self.services.combat.engage(snap, ctx)
                if action is not None:
                    if not self.send(ctx, action):
                        blamed = getattr(action, "toward", None)
                        target = next(
                            (m for m in near if m.unit_id == blamed), None
                        )
                        if target is not None:
                            self._unreachable[target.unit_id] = target.position
                            self.services.log(
                                f"survey: monster {target.unit_id} at "
                                f"{target.position} is unreachable; walking on "
                                "(it gets another look if it moves)"
                            )
                    return StepOutcome(done=False, acted=True, note="fighting")
                # engage had nothing offensive to do this tick (poison
                # settling, revives building): surveying on beats standing.

        if self._legs >= self.services.survey_max_legs:
            self.services.alert(
                f"survey stopped at the {self._legs}-leg budget. That is a "
                "bug signal, not a big area — a healthy survey finishes "
                "well under it."
            )
            return self._finish()

        targets = [
            t for t in self.services.survey_targets()
            if t not in self._done_targets
        ]
        if not targets:
            return self._finish()
        # STICKY target choice: keep walking to the one we chose until it
        # is reached, written off, or no longer frontier. Re-picking the
        # nearest every tick let two near-equidistant frontiers trade
        # "nearest" as the bot moved — each swap reset the progress
        # counter, so the ping-pong could neither finish nor give up
        # (the other half of the first Cold Plains survey's stall).
        if self._current is not None and self._current in targets:
            target = self._current
        else:
            target = min(targets, key=lambda t: _chebyshev(t, origin))
        distance = _chebyshev(target, origin)

        if distance <= self.services.patrol_reach:
            # Standing here has loaded the rooms beyond; the recorder has
            # them. The frontier list shrinks on its own recompute.
            self._done_targets.add(target)
            self._current = None
            self.services.log(f"survey: reached frontier {target}")
            return StepOutcome(
                done=False, acted=True, note=f"survey reached {target}"
            )

        if target != self._current:
            self._current, self._closest, self._attempts = target, None, 0
        if (
            self._closest is None
            or distance <= self._closest - self.services.patrol_progress_margin
        ):
            # The same margin rule as the patrol (R189 b): subtile wobble
            # is not progress.
            self._closest, self._attempts = distance, 0
        else:
            self._attempts += 1
        if self._attempts >= self.services.patrol_attempts:
            self.services.log(
                f"survey: giving up on frontier {target} after "
                f"{self._attempts} legs that got no closer (still "
                f"{distance} away)"
            )
            self._done_targets.add(target)
            self._written_off += 1
            self._current = None
            return StepOutcome(
                done=False, acted=True, note=f"survey gave up on {target}"
            )

        leg = _route_leg(self.services, origin, target)
        if leg is None:
            # No route on the map (R181) — confirmed by a second ask over
            # a fresh grid before it costs the point (T55 run 1's torn
            # grid read; the patrol carries the same two-strike rule).
            strikes = self._route_denied.get(target, 0) + 1
            self._route_denied[target] = strikes
            if strikes < 2:
                return StepOutcome(
                    done=False, acted=True,
                    note=f"no route to {target} — asking again",
                )
            self.services.log(f"survey: no route to frontier {target}")
            self._done_targets.add(target)
            self._written_off += 1
            self._current = None
            return StepOutcome(
                done=False, acted=True, note=f"survey wrote off {target} (no route)"
            )
        self._route_denied.pop(target, None)
        self._legs += 1
        if not self.send(ctx, MoveTo(leg)):
            # Unknown/blocked ground on the way: this frontier is not
            # approachable from here. Costs the point, never the run.
            self._done_targets.add(target)
            self._written_off += 1
            self._current = None
            return StepOutcome(
                done=False, acted=True, note=f"survey skipped {target}"
            )
        return StepOutcome(done=False, acted=True, note=f"survey leg to {leg}")


# -- the registry ---------------------------------------------------------------


@dataclass
class TraverseStep(_PickupMixin):
    """Walk out of the current area into `dest` through its staircase.

    The M6 traversal gesture (R212 Q3): every connection on the Countess
    route — Black Marsh into the Forgotten Tower, each cellar into the
    next — is a single-click warp. The step routes to the exit via the
    atlas in capped legs (the ladder gets its look between them), clicks
    the staircase, and then trusts NOTHING about the click: arrival is
    proven by the area id reading `dest`, the waypoint.py discipline.

    The exit position comes from memory first (`ExitMemory`, recorded on
    first discovery), refined by the live RoomTile read when it answers
    (`exits.read_level_exits`). This is kolbot's `moveToExit` shape —
    look the exit's coordinates up, path to them, use it — with one
    honest difference: kolbot's in-process engine is HANDED the full
    exit list (its host adds room data before reading presets, the same
    privilege d2mapapi uses), while an out-of-process read only sees
    exits in rooms the client has loaded around the player (T70
    descent, live). So on the one run where neither memory nor the scan
    knows the way, the step SEEKS: it routes over the atlas to the
    nearest room centre it has not yet been near — room positions are
    static and readable level-wide — and re-scans as the client loads
    each room's data. Bounded by the level's room count, every leg on
    known walkable ground, and the answer is remembered per map seed:
    the search happens once per level, ever, and every later run is
    kolbot-shaped from the first tick. Only a search that has walked
    EVERY room and still found nothing raises `NavigationError` — at
    that point "this map has no such transition" finally has evidence.

    Combat en route belongs to the posture (M6 P3): the module's
    `engage` owns any tick it wants — brisk makes that "only what
    obstructs the corridor" — and this step simply does not advance on
    those ticks (the approach-refusal pattern).
    """

    services: RunServices = None  # type: ignore[assignment]
    dest: int = 0
    posture: str | None = None
    name: str = "traverse"
    # Close enough to click the staircase: safely on screen (T50: the
    # nearest screen edge is 19-38 subtiles out) and inside the
    # loaded-room horizon, so the click projects and resolves.
    click_range: int = 18
    # A click whose walk has STALLED for this long earns a re-click.
    # Progress-aware since T70 (the user watched the pause): the first
    # click is a walk order the client honours over several seconds, and
    # a timer that ignored the closing distance re-issued the same order
    # mid-walk — ~10 s of a 16 s traverse was that pacing. While the
    # character keeps getting closer to the stairs, the click is doing
    # its job and the clock keeps resetting (the patrol's own
    # progress-vs-time distinction, R189 b).
    exit_retry_s: float = 3.0
    # Re-clicks are BOUNDED: past this, the staircase is not taking us
    # anywhere and the run must say so loudly rather than click forever.
    click_budget: int = 5
    # Seeking: a room counts as visited (its data loaded, its presets
    # scanned) once the character has been within this many subtiles.
    # Comfortably inside the measured loaded-room horizon (46-67, T51).
    seek_reach: int = 25
    _posture_applied: bool = False
    _exit: tuple[int, int] | None = None
    _from_memory: bool = False
    _clicked_at: float | None = None
    _click_closest: int | None = None
    _clicks: int = 0
    _announced: bool = False
    _seek_rooms: list[tuple[int, int]] | None = None
    _seek_announced: bool = False
    # The decision trace (T71): consecutive identical decisions collapse
    # into one line with a tick count and a duration.
    _trace_last: str | None = None
    _trace_ticks: int = 0
    _trace_since: float | None = None
    # Where this traverse started, so the transition event can name BOTH
    # ends (the operator asked for the departing area as well as the
    # target — "arrived in X" alone does not say what you left).
    _departed_from: int | None = None
    _transition_logged: bool = False

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        """One tick, with its decision RECORDED (T71, live).

        The wrapper exists because of what T71 could not answer. The bot
        spent 144 s in the Forgotten Tower — a 19x19-subtile room it had
        fully mapped, 11 subtiles from the staircase — and left five log
        lines behind: the five clicks. Every other tick returned through
        a path that said nothing, so ~165 decisions were made and thrown
        away, and the question "what was it doing?" had no answer in the
        artifact. A step that acts without recording what it did is a
        step that cannot be debugged, and this one was the last in the
        file that did so.

        Consecutive identical decisions are collapsed into one line with
        a tick count and a duration, so a normal healthy traverse still
        costs a handful of lines while a stuck one prints exactly the
        shape of its stall.
        """
        outcome = self._decide(snap, ctx)
        self._record_decision(snap, outcome)
        if outcome.done:
            self._flush_decision()
        return outcome

    def _record_decision(self, snap: GameSnapshot, outcome: StepOutcome) -> None:
        where = snap.player.position if snap.player is not None else None
        label = outcome.note or (
            "acted (unnamed)" if outcome.acted
            else "waiting (unnamed)" if outcome.waiting
            else "nothing to do"
        )
        if self._exit is not None and where is not None:
            label += f" [at {where}, {_chebyshev(where, self._exit)} from the stairs]"
        elif where is not None:
            label += f" [at {where}]"
        if label == self._trace_last:
            self._trace_ticks += 1
            return
        self._flush_decision()
        self._trace_last = label
        self._trace_ticks = 1
        self._trace_since = self.services.clock()

    def _flush_decision(self) -> None:
        if self._trace_last is None:
            return
        span = self.services.clock() - (self._trace_since or 0.0)
        ticks = self._trace_ticks
        self.services.log(
            f"traverse[{self.dest}]: {self._trace_last} "
            f"— {ticks} tick(s) over {span:.1f}s"
        )
        self._trace_last = None
        self._trace_ticks = 0

    def _decide(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.posture is not None and not self._posture_applied:
            set_posture = getattr(self.services.combat, "set_posture", None)
            if set_posture is not None:
                set_posture(self.posture)
                self.services.narrate(f"combat posture: {self.posture}")
            self._posture_applied = True

        # Arrival first: the only exit condition, proven by the area id.
        if snap.area is not None and snap.area.level_no == self.dest:
            arrival = snap.player.position if snap.player is not None else None
            if arrival is not None:
                ctx.notes["arrival"] = arrival
            name = offsets.AREA_NAMES.get(self.dest, f"area {self.dest}")
            if not self._transition_logged:
                self._transition_logged = True
                frame = self.services.frame() if self.services.frame else None
                self.services.runlog.event(
                    "area.transition",
                    from_area=self._departed_from,
                    from_name=mapframe.area_name(self._departed_from),
                    to_area=self.dest,
                    to_name=name,
                    via="staircase",
                    exit_position=(
                        mapframe.describe(self._exit, frame=frame)
                        if self._exit else None
                    ),
                    arrival=mapframe.describe(arrival, frame=frame),
                    clicks=self._clicks,
                )
            return StepOutcome(
                done=True, acted=True, note=f"arrived in {name} at {arrival}"
            )
        if snap.player is None or snap.area is None:
            # Mid-load — very likely OUR transition resolving. A declared
            # wait: deliberate, and still bounded by wait_bail_s.
            return StepOutcome(
                done=False, waiting=True, note="mid-load (no player/area read)"
            )
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")

        here = snap.area.level_no
        if self._departed_from is None:
            self._departed_from = here
        # The fight owns any tick it claims; the posture decides how much
        # fighting that is (brisk: only what obstructs the corridor).
        action = self.services.combat.engage(snap, ctx)
        if action is not None:
            landed = self.send(ctx, action)
            # Named, because this was the biggest of the silent paths and
            # "the fight owned the tick" was the story T71 could neither
            # confirm nor refute (6 reflex fires across the whole run).
            return StepOutcome(
                done=False, acted=True,
                note=f"fighting: {type(action).__name__}"
                + ("" if landed else " (send did not land)"),
            )

        origin = snap.player.position
        # Opportunistic collection en route (M6 P4, the T70 run 5 Thul).
        # The descent walked past a wanted rune on Cellar 4's floor
        # because traversal floors had NO pickup logic at all — a wanted
        # item was invisible to behavior even while perception listed it,
        # and runes are the entire point of the Countess route. The
        # machinery is the shared mixin the clearance and the sweep
        # already use (same budgets, same write-offs, same memory), so a
        # traversal differing from them in robustness — the shape that
        # cost P3 three live runs — cannot recur here. Bounded by
        # `pickup_radius`, and only on ticks combat declined: with the
        # brisk posture that means no hostile owns the tick, and the
        # ladder still gets its look between every click.
        self.confirm_pickups(snap)
        items = self.wanted_items(snap, origin, self.services.pickup_radius)
        if items:
            items.sort(key=lambda i: _chebyshev(i.position, origin))
            if self.collect(snap, ctx, items[0]):
                return StepOutcome(
                    done=False, acted=True,
                    note=f"collecting item {items[0].unit_id} at {items[0].position}",
                )
            # Claimed but still resolving (the retry pacing): hold the
            # walk rather than march away from a click in flight.
            return StepOutcome(done=False, waiting=True, note="pickup resolving")
        scan = self._locate_exit(here, origin)
        if self._exit is None:
            if scan is None:
                # The live read has not answered yet (mid-load): wait the
                # tick out rather than walk anywhere blind.
                return StepOutcome(
                    done=False, waiting=True,
                    note="the exit read has not answered yet",
                )
            # The scan answered and the exit is NOT VISIBLE from here —
            # which is not "does not exist" (T70 descent: preset data
            # only loads around the player). Seek: route to the nearest
            # room centre we have not been near, so the client loads its
            # data and the next scan can see further.
            return self._seek(ctx, origin, here, scan)
        if not self._announced:
            self.services.narrate(
                f"traverse: exit toward "
                f"{offsets.AREA_NAMES.get(self.dest, self.dest)} at "
                f"{self._exit}"
                + (" (remembered)" if self._from_memory else "")
            )
            self._announced = True

        now = self.services.clock()
        distance = _chebyshev(origin, self._exit)
        if distance <= self.click_range:
            if self._clicked_at is not None:
                # Progress-aware pacing (the T70 pause): a click whose
                # walk is still CLOSING on the stairs is working — the
                # clock restarts on every subtile of progress and only a
                # genuine stall earns the re-click.
                if self._click_closest is None or distance < self._click_closest:
                    self._click_closest = distance
                    self._clicked_at = now
                if now - self._clicked_at < self.exit_retry_s:
                    # No elapsed-seconds in the label, deliberately: the
                    # trace collapses consecutive IDENTICAL decisions and
                    # reports the duration itself, so a per-tick clock in
                    # the text would defeat the collapsing and bury the
                    # reader in one line per tick (found demoing this).
                    return StepOutcome(
                        done=False, waiting=True,
                        note=f"waiting out the last click ({distance} away)",
                    )
            # The contested-staircase rule that briefly lived here was
            # REVERTED (R220 Q10, 2026-08-05). It held a click while a
            # hostile stood on the stairs, on the theory that T71's
            # failure was monsters eating the clicks. The user then
            # supplied the fact that killed it: the Forgotten Tower
            # never contains monsters, and never has. The rule was
            # unmotivated code carrying a 10 s hold, built on a
            # hypothesis inferred from silence — see
            # docs/adr/2026-08-05-run-event-log.md for why that silence
            # is the real defect being fixed.
            if self._clicks >= self.click_budget:
                self._flush_decision()  # the stall's shape, before the raise
                raise NavigationError(
                    f"clicked the staircase at {self._exit} {self._clicks} "
                    f"times without the area changing from {here} — the "
                    "transition is not taking; giving the run up loudly"
                )
            self._clicks += 1
            self._clicked_at = now
            self._click_closest = distance
            self.send(ctx, InteractObject(self._exit))
            return StepOutcome(
                done=False, acted=True,
                note=f"clicked the staircase (attempt {self._clicks})",
            )

        leg = _route_leg(self.services, origin, self._exit)
        if leg is None:
            self._flush_decision()
            raise NavigationError(
                f"no route from {origin} to the exit at {self._exit} in "
                f"area {here} — the atlas has no path (survey the area, "
                "or the exit read misfired)"
            )
        landed = self.send(ctx, MoveTo(leg))
        return StepOutcome(
            done=False, acted=True,
            note=f"walking to the exit via {leg}"
            + ("" if landed else " (walk refused)"),
        )

    def _locate_exit(self, here: int, origin: tuple[int, int]):
        """Fill `_exit`: memory immediately, the live read when it answers.

        Returns the scan (or None) so the caller can seek off it. The
        live read REPLACES a remembered position when they disagree (the
        memory is a cache of this very read), and EVERY exit a scan sees
        is written back — not just the sought one — so each discovery
        run warms the map for every future traversal through this level
        (the up-staircase learned on the way down is the down-staircase
        of the return trip).
        """
        if self._exit is None and self.services.exit_recall is not None:
            remembered = self.services.exit_recall(here, self.dest)
            if remembered is not None:
                self._exit = remembered
                self._from_memory = True
        scan = None
        if self._exit is None or self._from_memory:
            reader = self.services.level_exits
            scan = reader() if reader is not None else None
            if scan is not None and getattr(scan, "area", None) == here:
                if self.services.exit_remember is not None:
                    for one in scan.exits:
                        self.services.exit_remember(
                            here, one.dest_area, one.position
                        )
                found = scan.toward(self.dest)
                if found:
                    # Nearest first, kolbot's own tiebreak for paired
                    # staircases.
                    best = min(
                        found,
                        key=lambda e: _chebyshev(e.position, origin),
                    )
                    self._exit = best.position
                    self._from_memory = False
            elif scan is not None:
                scan = None  # a stale-area scan is no answer at all
        return scan

    def _seek(
        self, ctx: EngineContext, origin: tuple[int, int], here: int, scan
    ) -> StepOutcome:
        """One leg of the discovery walk (T70 descent, the fix).

        Room centres come from the scan (static data, level-wide); the
        route comes from the atlas. Rooms the character has been near
        are done — their data loaded and their presets were in the very
        scan that still lacked the exit — so the walk visits each
        remaining room nearest-first until the exit turns up, which ends
        seeking via `_locate_exit` next tick. All rooms exhausted with
        no exit is the one situation that now has EVIDENCE behind "this
        map has no such transition".
        """
        if self._seek_rooms is None:
            self._seek_rooms = sorted(
                scan.rooms, key=lambda c: _chebyshev(c, origin), reverse=True
            )
            self.services.narrate(
                f"traverse: exit toward "
                f"{offsets.AREA_NAMES.get(self.dest, self.dest)} not in "
                f"sight — searching the level's {len(self._seek_rooms)} "
                "room(s) (first visit; the answer is remembered)"
            )
        while self._seek_rooms:
            target = self._seek_rooms[-1]
            if _chebyshev(target, origin) <= self.seek_reach:
                self._seek_rooms.pop()  # been here: its data is loaded
                continue
            leg = _route_leg(self.services, origin, target)
            if leg is None:
                # No route over the atlas: the centre sits in a wall or
                # unwalkable void. Costs the candidate, not the search.
                self._seek_rooms.pop()
                continue
            self.send(ctx, MoveTo(leg))
            return StepOutcome(
                done=False, acted=True,
                note=f"seeking the exit — walking to room {target} "
                f"({len(self._seek_rooms)} room(s) left)",
            )
        self._flush_decision()
        raise NavigationError(
            f"area {here} has no exit toward area {self.dest}: every one "
            f"of its {scan.rooms_walked} room(s) was visited and scanned "
            f"({len(scan.exits)} exit(s) found: "
            f"{[(e.dest_area, e.position) for e in scan.exits]}) — the run "
            "file asks for a transition this map does not have"
        )


def _screen_north_point(
    anchor: tuple[int, int],
    distance: int,
    is_walkable: Callable[[tuple[int, int]], bool] | None = None,
) -> tuple[int, int]:
    """The most-northerly stageable ground within `distance` of `anchor`.

    Delegates to `mapframe.screen_north`, which owns the convention:
    screen-north is the world (-1,-1) diagonal, and the pure -x/-y axes
    are screen NW and NE. ONE definition in the codebase — the log's
    bearings and the endgame's staging must agree, and two copies of an
    isometric convention are two chances to get it backwards.

    Cellar 5's chamber is cut into solid rock, so strictly-north-outside
    ground may simply not exist; the search degrades to the NW/NE
    shoulders and then closer in, which is why the derived staging point
    sits on the chamber's own north-west band.
    """
    return mapframe.screen_north(anchor, distance, is_walkable)


@dataclass
class ClearCountessStep(_PickupMixin):
    """The Cellar 5 endgame: the user's tactics for the Countess, encoded.

    Four beats, in order (R212 Q4 exception, Q7):

    1. **Clear the neighborhood** — a bounded clearance around the
       arrival point so the encounter has no gaggle at our backs. A
       composed `ClearRadiusStep` (modest radius, no patrol): the same
       machinery, the same budgets, not a re-implementation.
    2. **Stage north** — route to a point screen-north of the chamber
       anchor, derived from the atlas at run time and recorded on the
       blackboard (`notes["countess"]`) for the drill and the gate to
       display. Best-effort: staging is a tactic, and a staging point
       the map refuses is logged and skipped, never a hang.
    3. **Advance slowly** — short legs through the module's own
       `approach` (its gates decide what "in a fight" means), held by
       the revive brake: no advancing while the wall is shorter than
       `approach_with_revives`, until the patience bound releases it
       loudly. The on-contact wait-for-revives beat is `engage`'s own.
    4. **Kill and prove it** — the fight itself belongs to `engage`
       (aggressive posture). The step owns the EVIDENCE: her pinned
       identity (kind 734 / unique_no 6, T68+R216) seen with a dead
       mode, or provably absent after the budgeted chamber sweep — one
       short in-and-out pass so a blind corner cannot hide her, run in
       BOTH outcomes (after a seen kill it doubles as drop
       reconnaissance, priming the sightings memo the sweep-after
       relies on). Alive and unreachable is a loud stop-and-report,
       never a silent give-up: this step IS the run's objective.

    On confirmation the chamber region goes on the blackboard as the
    `cleared` circle (`pickup` adopts it unchanged — one region format,
    the M5 handoff), centred on her corpse when one was seen.
    """

    services: RunServices = None  # type: ignore[assignment]
    chamber: tuple[int, int] = (0, 0)
    neighborhood_radius: int = 30
    chamber_radius: int = 25
    posture: str | None = None
    name: str = "clear_countess"
    _phase: str = "clear"
    _posture_applied: bool = False
    _neighborhood: ClearRadiusStep | None = None
    _anchor: tuple[int, int] | None = None
    _anchor_live: bool = False
    _seen_alive: bool = False
    _corpse_at: tuple[int, int] | None = None
    _staging: tuple[int, int] | None = None
    _closest: int | None = None
    _attempts: int = 0
    _walk_fails: int = 0
    _revive_waited: int = 0
    _revives_seen: int = 0
    _brake_logged: bool = False
    _sweep_points: list[tuple[int, int]] | None = None
    _sweep_deadline: float | None = None
    _sweep_narrated: bool = False
    _sweep_skipped: int = 0

    def __post_init__(self) -> None:
        self._anchor = self.chamber
        # The neighborhood clearance, composed. No patrol: the arrival
        # pocket is small and the chamber must not be wandered into as a
        # "ring point". No posture: this step already set the run's.
        self._neighborhood = ClearRadiusStep(
            self.services,
            radius=self.neighborhood_radius,
            centre_note="arrival",
            patrol=False,
        )

    # -- identity ------------------------------------------------------------

    @staticmethod
    def _is_countess(unit) -> bool:
        """The pinned identity (T68 + R216). kind is the monstats row —
        hers alone — and unique_no confirms when readable; a corpse read
        that lost the boss flag (unique_no None) must not un-kill her."""
        return unit.kind == offsets.COUNTESS_KIND and (
            unit.unique_no is None
            or unit.unique_no == offsets.COUNTESS_UNIQUE_NO
        )

    def _scan(self, snap: GameSnapshot) -> object | None:
        """One look for her, live or dead. Returns the live unit if any.

        The live position REPLACES the run file's anchor whenever she is
        in perception — the memory-first, live-read-as-authority rule
        the traverse step already follows for exits.
        """
        for unit in snap.corpses:
            if self._is_countess(unit):
                if self._corpse_at is None:
                    self._corpse_at = unit.position
                    self.services.narrate(
                        f"countess: DOWN — her corpse reads at {unit.position}"
                    )
                return None
        alive = None
        for unit in snap.monsters:
            if not self._is_countess(unit):
                continue
            if unit.is_corpse:
                if self._corpse_at is None:
                    self._corpse_at = unit.position
                    self.services.narrate(
                        f"countess: DOWN — her corpse reads at {unit.position}"
                    )
                return None
            alive = unit
            break
        if alive is not None:
            self._seen_alive = True
            if not self._anchor_live:
                self._anchor_live = True
                self.services.log(
                    f"countess: sighted live at {alive.position} — the "
                    f"anchor {self._anchor} yields to the read"
                )
            self._anchor = alive.position
        return alive

    def _loud_stop(self, why: str) -> None:
        """The run's objective cannot be met and silence is forbidden."""
        self.services.alert(f"COUNTESS UNRESOLVED: {why}")
        raise NavigationError(f"clear_countess: {why}")

    def _confirmed(self, ctx: EngineContext) -> StepOutcome:
        centre = self._corpse_at or self._anchor or self.chamber
        # The M5 region handoff: `pickup` adopts this circle verbatim.
        ctx.notes["cleared"] = {
            "centre": centre,
            "radius": self.chamber_radius,
            "patrol": True,
        }
        if self._corpse_at is not None:
            note = f"the countess is down; drop zone {centre} r{self.chamber_radius}"
        else:
            note = (
                "the countess is provably absent (chamber swept clean); "
                f"drop zone {centre} r{self.chamber_radius}"
            )
        self.services.narrate(f"countess: {note}")
        return StepOutcome(done=True, acted=True, note=note)

    # -- movement bookkeeping ------------------------------------------------

    def _progressing(self, distance: int) -> bool:
        """The patrol's margin rule (R189 b), for whichever walk owns the
        phase. Reset via `_retarget` on every phase or target change."""
        if (
            self._closest is None
            or distance <= self._closest - self.services.patrol_progress_margin
        ):
            self._closest = distance
            self._attempts = 0
            return True
        self._attempts += 1
        return self._attempts < self.services.patrol_attempts

    def _retarget(self) -> None:
        self._closest = None
        self._attempts = 0
        self._walk_fails = 0

    def _leg_toward(
        self, ctx: EngineContext, origin: tuple[int, int], target: tuple[int, int]
    ) -> bool:
        """One capped leg via the map. False = this target is not happening
        (no route twice would be cleaner, but the two-strike rule guards
        WRITE-OFFS of many candidates; here every no-route already falls
        through to the next phase, which re-decides from fresh reads)."""
        leg = _route_leg(self.services, origin, target)
        if leg is None:
            return False
        if not self.send(ctx, MoveTo(leg)):
            self._walk_fails += 1
            return self._walk_fails < 2
        return True

    # -- the tick ------------------------------------------------------------

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.posture is not None and not self._posture_applied:
            set_posture = getattr(self.services.combat, "set_posture", None)
            if set_posture is not None:
                set_posture(self.posture)
                self.services.narrate(f"combat posture: {self.posture}")
            self._posture_applied = True
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        if snap.player is None or snap.area is None:
            return StepOutcome(done=False, waiting=True)
        origin = snap.player.position

        self.confirm_pickups(snap)
        alive = self._scan(snap)
        # Everything the chamber region drops feeds the sightings memo,
        # so the pickup step's ring walk starts with evidence in hand.
        if self._anchor is not None:
            self.note_wanted_sightings(snap, self._anchor, self.chamber_radius)

        # 1 — the neighborhood clearance owns the tick until it is done.
        # It fights, collects and cleanses through its own machinery;
        # running this step's engage beside it would decide twice.
        if self._phase == "clear":
            outcome = self._neighborhood.step(snap, ctx)
            if not outcome.done:
                return outcome
            self._phase = "stage"
            self._retarget()
            self.services.narrate(
                f"countess: neighborhood clear ({outcome.note}) — staging north"
            )
            return StepOutcome(done=False, acted=True, note="neighborhood clear")

        # Her corpse settles the question in any later phase: sweep for
        # the sanity pass (and the drop reconnaissance), then confirm.
        if self._corpse_at is not None and self._phase != "sweep":
            self._enter_sweep()

        # The fight owns any tick it claims — aggressive posture: she and
        # her court are exactly what this step came to fight.
        action = self.services.combat.engage(snap, ctx)
        if action is not None:
            if not self.send(ctx, action):
                blamed = getattr(action, "toward", None)
                if alive is not None and blamed == alive.unit_id:
                    self._walk_fails += 1
                    if self._walk_fails >= 2:
                        self._loud_stop(
                            f"she is alive at {alive.position} and the walk "
                            "to her keeps failing — alive and unreachable"
                        )
            return StepOutcome(done=False, acted=True)

        if self._phase == "stage":
            return self._stage_tick(snap, ctx, origin)
        if self._phase == "advance":
            return self._advance_tick(snap, ctx, origin, alive)
        return self._sweep_tick(snap, ctx, origin, alive)

    # -- 2: staging ----------------------------------------------------------

    def _stage_tick(
        self, snap: GameSnapshot, ctx: EngineContext, origin: tuple[int, int]
    ) -> StepOutcome:
        if self._staging is None:
            self._staging = _screen_north_point(
                self._anchor or self.chamber,
                self.services.staging_distance,
                getattr(self.services.combat, "is_walkable", None),
            )
            # The blackboard record the drill displays and the gate reviews.
            ctx.notes["countess"] = {
                "anchor": self._anchor,
                "staging": self._staging,
                "radius": self.chamber_radius,
            }
            self.services.narrate(
                f"countess: staging north of the chamber at {self._staging} "
                f"(anchor {self._anchor})"
            )
        distance = _chebyshev(origin, self._staging)
        if distance <= self.services.patrol_reach:
            self._to_advance("staged")
            return StepOutcome(done=False, acted=True, note="staged north")
        if not self._progressing(distance) or not self._leg_toward(
            ctx, origin, self._staging
        ):
            # Best-effort by design: the staging point is a tactic, not
            # the objective, and a map that refuses it must not hang the
            # run that came to kill her.
            self.services.log(
                f"countess: staging at {self._staging} not reachable "
                f"(closest {self._closest}); advancing from here"
            )
            self._to_advance("staging written off")
        return StepOutcome(done=False, acted=True, note="staging north")

    def _to_advance(self, why: str) -> None:
        self._phase = "advance"
        self._retarget()
        self.services.narrate(f"countess: advancing on the chamber ({why})")

    # -- 3: the advance ------------------------------------------------------

    def _advance_tick(
        self, snap: GameSnapshot, ctx: EngineContext, origin: tuple[int, int], alive
    ) -> StepOutcome:
        # The revive brake (the user's tactic): no advancing while the
        # wall is short. Released by the wall reaching the module's own
        # `approach_with_revives`, by the wall GROWING resetting the
        # patience, or by the patience bound — loudly, because a cellar
        # with nothing dead nearby can never raise a wall at all.
        needed = getattr(
            getattr(self.services.combat, "config", None),
            "approach_with_revives",
            0,
        )
        standing = len(snap.revives)
        if standing > self._revives_seen:
            self._revive_waited = 0
        self._revives_seen = standing
        if standing < needed:
            self._revive_waited += 1
            if self._revive_waited <= self.services.advance_revive_patience:
                if not self._brake_logged:
                    self._brake_logged = True
                    self.services.log(
                        f"countess: holding the advance for the revive wall "
                        f"({standing}/{needed} up)"
                    )
                return StepOutcome(done=False, waiting=True, note="revive brake")
            if self._brake_logged:
                self._brake_logged = False
                self.services.log(
                    f"countess: the wall never grew past {standing}/{needed} "
                    f"— advancing without it"
                )

        target = self._anchor or self.chamber
        distance = _chebyshev(origin, target)
        if distance <= self.services.patrol_reach:
            if alive is None:
                self._enter_sweep()
                return StepOutcome(done=False, acted=True, note="at the chamber")
            # At her anchor with her alive in sight: `engage`'s fight now;
            # its deliberate pauses (restrike, revives) are not stalls.
            return StepOutcome(done=False, waiting=True)

        via = None
        if self.services.route_to is not None:
            route = self.services.route_to(target)
            if route is not None:
                via = _next_route_waypoint(route, origin)
        closing = self.services.combat.approach(snap, target, via=via)
        if closing is not None:
            if not self.send(ctx, closing):
                self._walk_fails += 1
                if self._walk_fails >= 2:
                    if alive is not None:
                        self._loud_stop(
                            f"she is alive at {alive.position} and every "
                            "approach fails — alive and unreachable"
                        )
                    self.services.log(
                        "countess: the anchor is not approachable — sweeping"
                    )
                    self._enter_sweep()
                return StepOutcome(done=False, acted=True)
            if not self._progressing(distance):
                if alive is not None:
                    self._loud_stop(
                        f"she is alive at {alive.position} and "
                        f"{self._attempts} advance legs got no closer than "
                        f"{self._closest} — alive and unreachable"
                    )
                self.services.log(
                    f"countess: the advance stalled {self._attempts} legs "
                    f"short of the anchor — sweeping from here"
                )
                self._enter_sweep()
            return StepOutcome(done=False, acted=True, note="advancing")
        # approach refused. With her alive in sight that is a deliberate
        # combat beat (wait-for-revives on contact, a restrike window) —
        # engage's next look. With NO live countess it means the module
        # considers the anchor in reach and has nothing to fight there:
        # the chamber is as approached as it gets, and waiting on an
        # empty anchor was this step's own hang (found by the blinded
        # sim scenario, exactly the sweep's case).
        if alive is None:
            self._enter_sweep()
            return StepOutcome(done=False, acted=True, note="at the chamber")
        return StepOutcome(done=False, waiting=True)

    # -- 4: the chamber sweep ------------------------------------------------

    def _enter_sweep(self) -> None:
        if self._phase != "sweep":
            self._phase = "sweep"
            self._retarget()
        if self._sweep_deadline is None:
            # One budget across every entry: a countess blinking in and
            # out of perception must not stretch it.
            self._sweep_deadline = self.services.clock() + self.services.sweep_budget_s
        if self._sweep_points is None:
            anchor = self._anchor or self.chamber
            r = self.chamber_radius
            walkable = getattr(self.services.combat, "is_walkable", None)
            south = (anchor[0] + r, anchor[1] + r)
            if walkable is not None:
                for d in range(r, 7, -4):
                    candidate = (anchor[0] + d, anchor[1] + d)
                    try:
                        if walkable(candidate):
                            south = candidate
                            break
                    except Exception:  # noqa: BLE001 - torn read
                        continue
            # In-and-out: the heart of the chamber, its far (south) side,
            # and back to the heart — a pass, not a patrol.
            self._sweep_points = [anchor, south, anchor]
        if not self._sweep_narrated:
            self._sweep_narrated = True
            self.services.narrate(
                f"countess: sweeping the chamber ({self.services.sweep_budget_s:.0f}s "
                f"budget) — {self._sweep_points}"
            )

    def _sweep_tick(
        self, snap: GameSnapshot, ctx: EngineContext, origin: tuple[int, int], alive
    ) -> StepOutcome:
        self._enter_sweep()  # idempotent: fills points/deadline if entered abruptly
        if alive is not None and self._corpse_at is None:
            # The sweep fed the scan and the scan answered: she lives.
            # Back to the approach — the budget clock keeps running.
            self._to_advance("she is in sight")
            return StepOutcome(done=False, acted=True, note="sighted her")
        if self.services.clock() > self._sweep_deadline:
            if self._corpse_at is not None:
                return self._confirmed(ctx)
            self._loud_stop(
                f"the {self.services.sweep_budget_s:.0f}s chamber sweep "
                "budget is spent with the kill unproven — she is neither "
                "dead on the ground nor provably absent"
            )
        while self._sweep_points:
            point = self._sweep_points[0]
            distance = _chebyshev(origin, point)
            if distance <= self.services.patrol_reach:
                self._sweep_points.pop(0)
                self._retarget()
                continue
            if not self._progressing(distance) or not self._leg_toward(
                ctx, origin, point
            ):
                self.services.log(
                    f"countess: sweep point {point} not reachable — skipped"
                )
                self._sweep_points.pop(0)
                self._sweep_skipped += 1
                self._retarget()
                continue
            return StepOutcome(done=False, acted=True, note=f"sweeping via {point}")
        # The pass is complete. A corpse settles it regardless — the sweep
        # was only drop reconnaissance then. But ABSENCE is only proven by
        # ground actually walked: a pass whose points were skipped as
        # unreachable saw nothing, and calling that "provably absent"
        # would hand the flagship drill a PASS on a partial run — the
        # review-001 shape, one layer down.
        if self._corpse_at is None and self._sweep_skipped:
            self._loud_stop(
                f"the chamber sweep skipped {self._sweep_skipped} of its "
                "points as unreachable — she was never seen and absence "
                "is unproven"
            )
        return self._confirmed(ctx)


def _checked_posture(services: RunServices, name: str | None) -> str | None:
    """Validate a step's posture name at BUILD time (M6 P3).

    Reaching a game with an unknown posture would fail mid-run in Hell;
    this fails while the bot is still standing at the menus, the same
    place every other run-file mistake fails.
    """
    if name is None:
        return None
    if name not in services.postures:
        from pd2bot.behavior.run import RunError

        loaded = ", ".join(sorted(services.postures))
        raise RunError(
            f"unknown posture {name!r} (loaded: "
            f"{loaded or 'none — this environment has no postures'})"
        )
    return name


def build_registry(services: RunServices) -> StepRegistry:
    """The M5 step vocabulary, with handlers wired to `services`.

    Same names and parameter schemas as P4's `default_registry` — that one
    stays as the validate-without-a-game path (drills and the run linter),
    this one is what actually runs.
    """
    registry = StepRegistry()
    registry.register(
        StepSpec("town_preamble", factory=lambda p: TownPreambleStep(services))
    )
    registry.register(
        StepSpec(
            "waypoint",
            params=(ParamSpec("dest", int),),
            factory=lambda p: WaypointStep(services, dest=p["dest"]),
        )
    )
    registry.register(
        StepSpec(
            "clear_radius",
            params=(
                ParamSpec("center", str, required=False, default="arrival"),
                ParamSpec("radius", int),
                # Off by default so every run written before the patrol
                # existed keeps behaving exactly as it did.
                ParamSpec("patrol", bool, required=False, default=False),
                # M6 P3: which combat posture to fight this step in.
                # Absent = leave the module alone (cautious in practice).
                ParamSpec("posture", str, required=False, default=None),
            ),
            factory=lambda p: ClearRadiusStep(
                services,
                radius=p["radius"],
                centre_note=p["center"],
                patrol=p["patrol"],
                posture=_checked_posture(services, p["posture"]),
            ),
        )
    )
    registry.register(
        StepSpec(
            "traverse",
            params=(
                ParamSpec("dest", int),
                ParamSpec("posture", str, required=False, default=None),
            ),
            factory=lambda p: TraverseStep(
                services,
                dest=p["dest"],
                posture=_checked_posture(services, p["posture"]),
            ),
        )
    )
    registry.register(
        StepSpec(
            "clear_countess",
            params=(
                # The chamber anchor: her T68-measured position for this
                # seed, upgraded to the live boss read the moment she is
                # in perception. Two ints because run-file params are
                # scalars — the run file comments their provenance.
                ParamSpec("chamber_x", int),
                ParamSpec("chamber_y", int),
                ParamSpec("neighborhood_radius", int, required=False, default=30),
                ParamSpec("chamber_radius", int, required=False, default=25),
                ParamSpec("posture", str, required=False, default=None),
            ),
            factory=lambda p: ClearCountessStep(
                services,
                chamber=(p["chamber_x"], p["chamber_y"]),
                neighborhood_radius=p["neighborhood_radius"],
                chamber_radius=p["chamber_radius"],
                posture=_checked_posture(services, p["posture"]),
            ),
        )
    )
    registry.register(
        StepSpec(
            "pickup",
            factory=lambda p: PickupStep(services),
        )
    )
    registry.register(
        StepSpec("survey", factory=lambda p: SurveyStep(services))
    )
    registry.register(StepSpec("done", factory=lambda p: DoneStep(services)))
    return registry
