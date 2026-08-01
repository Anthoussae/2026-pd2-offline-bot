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

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot import offsets
from pd2bot.behavior.actions import MoveTo, PickUpItem
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.run import ParamSpec, StepRegistry, StepSpec
from pd2bot.items import CarriedItems
from pd2bot.pickit import Pickit, potion_type_of
from pd2bot.snapshot import GameSnapshot
from pd2bot.units import GroundItem


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _default_alert(reason: str) -> None:  # pragma: no cover - exercised live
    print(f"\n!!  {reason}\n", flush=True)


def _default_log(line: str) -> None:  # pragma: no cover - exercised live
    print(f"  {line}", flush=True)


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
            ctx.executor.execute(MoveTo(item.position))
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
            # up room (R117): ask for a cleanse at the next safe moment.
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

    def maybe_cleanse(self, snap: GameSnapshot, ctx: EngineContext) -> bool:
        """Run a queued inventory cleanse if this is a safe moment.

        Safe = no live hostile within `cleanse_safe_radius`. The cleanse is
        a blocking stretch with the inventory open — the character stands
        still and the ladder is not consulted — so it gets the same
        treatment as the town steps: only where nothing can punish it.
        Never in town (the town preamble has its own cleanse pass).
        """
        services = self.services
        if not services.cleanse_queued or services.cleanse is None:
            return False
        if snap.player is None or snap.in_town:
            return False
        origin = snap.player.position
        if any(
            _chebyshev(m.position, origin) <= services.cleanse_safe_radius
            for m in snap.live_monsters
        ):
            return False
        services.cleanse_queued = False
        dropped = services.cleanse()
        # Whatever was stuck may be liftable now that room was made; give
        # every written-off item one more chance.
        if dropped:
            for unit_id in list(services.stuck):
                services.stuck.discard(unit_id)
                services.attempts.pop(unit_id, None)
            services.inventory_full = False
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
class ClearRadiusStep(_PickupMixin):
    """Kill everything within `radius` of the centre, then settle.

    Termination is deliberately not "no monsters right now": a pack can be
    mid-spawn, a poisoned monster is still alive for a few seconds, and a
    revive can drag something into range. So the step requires the radius to
    read EMPTY continuously for `clear_settle_s` before it calls the job
    done — the same "wait for it to stay true" discipline the town layer's
    verifications use.
    """

    radius: int = 150
    centre_note: str = "arrival"
    name: str = "clear_radius"
    _empty_since: float | None = None
    _centre: tuple[int, int] | None = None

    def centre(self, snap: GameSnapshot, ctx: EngineContext) -> tuple[int, int] | None:
        if self._centre is None:
            noted = ctx.notes.get(self.centre_note)
            if isinstance(noted, tuple):
                self._centre = noted
            elif snap.player is not None:
                # No note (a run that starts mid-area): here is as good a
                # centre as any, and saying so beats refusing to run.
                self._centre = snap.player.position
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
            if _chebyshev(m.position, centre) <= self.radius
        ]
        if in_radius:
            self._empty_since = None
            action = self.services.combat.engage(snap, ctx)
            if action is not None:
                ctx.executor.execute(action)
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
                ctx.executor.execute(closing)
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

        if self._empty_since is None:
            self._empty_since = now
            return StepOutcome(done=False, acted=True, note="radius reads clear")
        if now - self._empty_since >= self.services.clear_settle_s:
            return StepOutcome(
                done=True, acted=True,
                note=f"clear for {self.services.clear_settle_s:.0f}s",
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
class PickupStep(_PickupMixin):
    """Sweep the cleared ground for anything the pickit wants."""

    radius: int = 150
    centre_note: str = "arrival"
    name: str = "pickup"
    _centre: tuple[int, int] | None = None

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        if self.recover_panels(snap):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        if self._centre is None:
            noted = ctx.notes.get(self.centre_note)
            self._centre = (
                noted if isinstance(noted, tuple)
                else (snap.player.position if snap.player else None)
            )
        if self._centre is None:
            return StepOutcome(done=True, note="nowhere to sweep")
        if self.maybe_cleanse(snap, ctx):
            # Space first, sweep second: a written-off item may be liftable
            # once the junk is gone.
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        items = self.wanted_items(snap, self._centre, self.radius)
        if not items:
            return StepOutcome(done=True, acted=True, note="nothing left to pick")
        if snap.player is not None:
            items.sort(key=lambda i: _chebyshev(i.position, snap.player.position))
        acted = self.collect(snap, ctx, items[0])
        return StepOutcome(done=False, acted=acted)


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
            ),
            factory=lambda p: ClearRadiusStep(
                services, radius=p["radius"], centre_note=p["center"]
            ),
        )
    )
    registry.register(
        StepSpec(
            "pickup",
            factory=lambda p: PickupStep(services),
        )
    )
    registry.register(StepSpec("done", factory=lambda p: DoneStep(services)))
    return registry
