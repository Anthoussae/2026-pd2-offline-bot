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

from pd2bot import offsets
from pd2bot.behavior.actions import MoveTo, PickUpItem
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.run import ParamSpec, StepRegistry, StepSpec
from pd2bot.items import CarriedItems
from pd2bot.navigate import NavigationError
from pd2bot.pickit import Pickit, potion_type_of
from pd2bot.snapshot import GameSnapshot
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
    # Tuning that belongs to the steps rather than to a class.
    clear_settle_s: float = 5.0
    pickup_radius: int = 30  # opportunistic pickups during clearance
    pickup_reach: int = 4  # close enough to click an item and have it land
    pickup_attempts: int = 3  # clicks per item before calling it stuck
    pickup_retry_s: float = 1.5  # between attempts on the same item
    alert: Callable[[str], None] = _default_alert
    # Where per-decision detail goes. Separate from `alert`, which is for
    # things a human must act on; this is the run's record.
    log: Callable[[str], None] = _default_log
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
    belt_full: set[str] = field(default_factory=set)
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
    # -- the survey step (R175/R176) ---------------------------------------
    #
    # Both closures are wired closures over the map store (wiring.py) so
    # the step never learns what a MapStore is — the same treatment
    # `cleanse` gets. None = no survey service in this environment, and
    # the step finishes immediately rather than guessing.
    survey_targets: Callable[[], list[tuple[int, int]]] | None = None
    survey_coverage: Callable[[], str] | None = None
    # Fight only what comes this close while surveying (R176 Q1): a
    # survey is not a clearance, and the reflex ladder plus chicken stay
    # on above this either way.
    survey_engage_radius: int = 30
    # Hard cap on survey walking, as legs. Not a tuning knob: a healthy
    # survey of a Cold-Plains-sized area is well under this, so hitting
    # it means something is wrong (a frontier that never closes, a
    # target oscillation) and the game should end rather than stretch.
    survey_max_legs: int = 200
    # Whether this game has already alerted about a target on unsurveyed
    # ground (R176 Q2: no auto-survey mid-run — say it loudly, once, and
    # recommend the survey run instead). Once, because the same run will
    # often give up on several such targets and each repeat of the alert
    # buys nothing.
    unsurveyed_alerted: bool = False


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

    def wanted_items(
        self, snap: GameSnapshot, centre: tuple[int, int], radius: int
    ) -> list[GroundItem]:
        carried = self.services.carried()
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
                # they route to the belt — but a belt column that has
                # already refused this type will refuse it again, and
                # re-attempting it every tick is how run 4 spent its time.
                if potion_type_of(item) in self.services.belt_full:
                    continue
            elif self.services.inventory_full:
                continue
            found.append(item)
        return found

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
        if _chebyshev(item.position, player.position) > self.services.pickup_reach:
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
        if attempts >= self.services.pickup_attempts:
            self.services.stuck.add(item.unit_id)
            potion = potion_type_of(item)
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
                # Recorded per TYPE, because that is the granularity the belt
                # refuses at — same reasoning as `fill_belt`'s own `full` set.
                if potion not in self.services.belt_full:
                    self.services.belt_full.add(potion)
                    self.services.alert(
                        f"belt full for {potion}: a {potion} potion at "
                        f"{item.position} would not come up after "
                        f"{self.services.pickup_attempts} attempts. Leaving "
                        f"{potion} potions this game; the inventory has "
                        "nothing to do with it."
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
        self.services.attempts[item.unit_id] = attempts + 1
        self.services.last_try[item.unit_id] = now
        ctx.executor.execute(PickUpItem(item.unit_id, item.position))
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
        try:
            ctx.executor.execute(action)
        except NavigationError as exc:
            self.services.log(f"could not walk: {exc}")
            _note_unsurveyed(self.services, exc)
            return False
        return True

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
        """
        if snap.ui is None or not snap.ui.blocks_input or snap.in_town:
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

        # 1 — step off the drop pile before anything near it gets clicked.
        if services.cleanse_dropped_at is not None:
            if _chebyshev(origin, services.cleanse_dropped_at) < services.cleanse_standoff:
                away = _point_away(
                    origin, services.cleanse_dropped_at,
                    services.cleanse_standoff + 4,
                )
                if self.send(ctx, MoveTo(away)):
                    self.services.log(
                        f"cleanse hygiene: stepping off the drop pile at "
                        f"{services.cleanse_dropped_at} toward {away}"
                    )
                    return True
                # Boxed in: clear the marker rather than loop on a walk
                # that cannot happen. One risky retry beats a hang.
                self.services.log(
                    "cleanse hygiene: could not step off the drop pile; "
                    "accepting the risk rather than looping"
                )
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
            if self.send(ctx, MoveTo(away)):
                self.services.log(
                    f"cleanse hygiene: walking clear of wanted item at "
                    f"{nearest.position} before dropping junk"
                )
                return True
            self.services.log(
                "cleanse hygiene: could not walk clear of the wanted item; "
                "dropping here rather than looping"
            )

        services.cleanse_queued = False
        dropped = services.cleanse()
        if dropped:
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
            f"not come up after {self.services.pickup_attempts} attempts. "
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

    def patrol_points(self, centre: tuple[int, int]) -> list[tuple[int, int]]:
        """The ring, computed once from the centre and the radius.

        Sized as a fraction of `radius` so that changing the radius — the
        one number the user tunes — moves the whole pattern with it. At
        radius 96 the ring sits at ~63: adjacent points are ~49 apart and
        the furthest edge of the circle is ~33 from the nearest point,
        which is inside even T51's worst-case 46.
        """
        if self._points is None:
            ring = max(1, round(self.radius * self.services.patrol_ring))
            count = max(1, self.services.patrol_points)
            self._points = [
                (
                    centre[0] + round(ring * math.cos(2 * math.pi * i / count)),
                    centre[1] + round(ring * math.sin(2 * math.pi * i / count)),
                )
                for i in range(count)
            ]
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
        points = self.patrol_points(self._centre)  # type: ignore[arg-type]
        target = points[self._index]
        here = snap.player.position  # type: ignore[union-attr]

        distance = _chebyshev(here, target)
        if distance <= self.services.patrol_reach:
            self.services.log(f"patrol: reached {target}")
            self._advance()
            return StepOutcome(done=False, acted=True, note=f"patrol reached {target}")

        # Progress, not effort: a leg that closed the gap earns another,
        # however many it takes. Only legs that achieve nothing count
        # against the point.
        if self._closest is None or distance < self._closest:
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

        leg = _hop(here, target, self.services.patrol_step)
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
    name: str = "clear_radius"
    _empty_since: float | None = None
    _centre: tuple[int, int] | None = None
    # Monsters inside the radius that we have given up reaching, and where
    # each was standing when we did. The position is what allows the
    # write-off to expire (see `_reachable`); a bare set could not.
    _unreachable: dict[int, tuple[int, int]] = field(default_factory=dict)
    # Per monster: the closest we have got, and how many closing ticks have
    # achieved nothing since. Same shape as the patrol's own two fields.
    _closest_to: dict[int, int] = field(default_factory=dict)
    _no_progress: dict[int, int] = field(default_factory=dict)

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
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        centre = self.centre(snap, ctx)
        if centre is None or snap.player is None:
            return StepOutcome(done=False)
        now = self.services.clock()

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
            closing = self.services.combat.approach(snap, nearest.position)
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
        if not self.patrol_complete and snap.player is not None:
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
    _written_off: int = 0
    _legs: int = 0
    _current: tuple[int, int] | None = None
    _closest: int | None = None
    _attempts: int = 0
    # Monsters a failed walk proved unreachable, and where they stood —
    # the clearance's rule (expiry on movement) in miniature, so a walled
    # monster cannot pin the survey the way one pinned the clearance.
    _unreachable: dict[int, tuple[int, int]] = field(default_factory=dict)

    def _fightable(self, m) -> bool:
        where = self._unreachable.get(m.unit_id)
        if where is None:
            return True
        if _chebyshev(m.position, where) <= self.services.unreachable_forget:
            return False
        del self._unreachable[m.unit_id]
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

        # Fighting wins the tick, but only up close (R176 Q1).
        near = [
            m for m in snap.live_monsters
            if _chebyshev(m.position, origin) <= self.services.survey_engage_radius
            and self._fightable(m)
        ]
        if near:
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
        if self._closest is None or distance < self._closest:
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

        leg = _hop(origin, target, self.services.patrol_step)
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
            ),
            factory=lambda p: ClearRadiusStep(
                services,
                radius=p["radius"],
                centre_note=p["center"],
                patrol=p["patrol"],
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
