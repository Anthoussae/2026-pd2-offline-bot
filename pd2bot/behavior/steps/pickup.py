"""_PickupMixin: sprite-aimed ground pickup and the inventory cleanse hook.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.behavior.actions import (
    PICKUP_AIM_POINTS,
    MoveTo,
    PickUpItem,
)
from pd2bot.behavior.engine import EngineContext
from pd2bot.behavior.steps.services import RunServices
from pd2bot.behavior.steps.util import (
    _chebyshev,
    _note_unsurveyed,
    _point_away,
)
from pd2bot.nav import mapframe
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception.items import CarriedItems
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.perception.uistate import blocking_panels
from pd2bot.perception.units import GroundItem
from pd2bot.pickit import belt_count, potion_type_of


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

    @staticmethod
    def _draw_order(items: list[GroundItem]) -> list[GroundItem]:
        """Collection order for a pile: the FRONT sprite first (P3, C).

        A click at one item's aim offset lands on whatever sprite is drawn
        OVER that screen point — the neighbour in front — which is the
        "clicked A got B" that cost T71 run 4 nine of thirteen misses.
        Lifting the front item first uncovers the one behind it, so the
        next click has a clear target. Front = largest screen depth, and
        the codebase's projection convention fixes that direction:
        `mapframe` has `sy = wx + wy` (larger y is lower on screen, drawn
        last, on top), so front-first is `wx + wy` DESCENDING. Replaces
        the old nearest-to-player sort, whose order was unrelated to which
        sprite occludes which; the extra walk within a pickup radius is
        negligible against the click cost a miss spends (T71: 12 s).
        """
        return sorted(
            items, key=lambda i: i.position[0] + i.position[1], reverse=True
        )

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

    def _neighbours_within(
        self, snap: GameSnapshot, item: GroundItem, radius: int = 2
    ) -> int:
        """Other ground items within `radius` subtiles of `item`."""
        return sum(
            1
            for other in snap.ground_items
            if other.unit_id != item.unit_id
            and _chebyshev(other.position, item.position) <= radius
        )

    def _write_off_reason(self, item, potion: str | None, near: int) -> str:
        """The diagnosis for a spent click budget, given the neighbour count.

        Four causes, distinguished as far as observation allows (P4). It
        REPORTS the caller's decision; the belt-full/inventory-full
        reasoning stays load-bearing (T56). Item sizes are unreadable
        (P1), so "inventory full" is always an inference from persistence.
        """
        if potion is not None:
            # A potion routes to the BELT: "won't come up" means belt-full
            # ONLY while the belt count agrees (T56), else a click miss.
            return (
                "clicks did not land (belt has room)"
                if self._belt_has_room(potion)
                else f"belt full for {potion}"
            )
        if near > 0:
            # A neighbour in reach: the clicks most likely landed on IT
            # (T71 run 4: 9 of 13 misses had a collected neighbour that
            # close). This is NOT the inventory being full.
            return f"pile ambiguity — clicks likely landed on a neighbour ({near} near)"
        # No neighbour, nothing moved: either the aim schedule cannot
        # reach this item's class (T65's kind-619, 245 probes 0 hits) or
        # the inventory is genuinely full. Persistence cannot tell them
        # apart — say so rather than assert one.
        return "aim failure for this item class, or a full inventory (unreadable)"

    def _log_click_write_off(
        self,
        snap: GameSnapshot,
        item: GroundItem,
        attempts: int,
        potion: str | None,
        near: int,
    ) -> None:
        """Emit `item.abandoned` for a spent click budget, with the reason
        and the neighbour count that produced it. Never raises."""
        log = getattr(self.services, "runlog", None)
        if log is None or not getattr(log, "enabled", False):
            return
        frame = self.services.frame() if self.services.frame else None
        log.event(
            "item.abandoned",
            unit_id=item.unit_id,
            item=self._logged_name(item.kind),
            item_kind=item.kind,
            reason=self._write_off_reason(item, potion, near),
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
            near = self._neighbours_within(snap, item)
            # The click budget is spent. Whatever the diagnosis concludes,
            # SAY SO — until 2026-08-06 every branch here returned silently,
            # and T71 run 4's eleven click-budget write-offs (a Nef rune and
            # a flawless emerald among them) left no event at all.
            self._log_click_write_off(snap, item, attempts, potion, near)
            if potion is not None:
                # A potion routes to the BELT, so a potion that will not come
                # up says the belt is full for its type — NOT that the
                # inventory grid is (Stage B run 4 conflated them and starved
                # the belt). But "won't come up" only MEANS belt-full while
                # the belt count agrees (T56); with room in the belt the
                # failure is the CLICK's, and the type stays wanted.
                if self._belt_has_room(potion):
                    self.services.alert(
                        f"pickup: a {potion} potion at {item.position} would "
                        f"not come up after {self.services.pickup_click_attempts} "
                        "attempts even though the belt has room — click misses "
                        f"suspected. Leaving that one; {potion} potions stay wanted."
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
            if near > 0:
                # PILE AMBIGUITY (P4): a neighbour in reach almost certainly
                # ate the clicks, so this is NOT the inventory being full —
                # and marking it full would abandon every OTHER non-potion
                # item this game for a single missed rune in a pile. Write
                # THIS item off and keep going; no cleanse (junk on the floor
                # is not junk in the grid).
                self.services.alert(
                    f"pickup: item kind {item.kind} at {item.position} would "
                    f"not come up after {self.services.pickup_click_attempts} "
                    f"attempts with {near} item(s) packed within 2 subtiles — "
                    "pile ambiguity, the clicks likely landed on a neighbour. "
                    "Leaving that one; still collecting the rest."
                )
                return False
            # No neighbour, nothing moved: aim failure for this item class OR
            # a genuinely full inventory — persistence cannot tell them apart
            # (item sizes are unreadable, P1). Keep the conservative
            # inventory-full behaviour (suppress non-potion pickups, queue a
            # cleanse), because a real full grid must not be ignored; the
            # honest reason above records that it might instead be an aim
            # failure for this class (T65's kind-619).
            self._mark_inventory_full(item)
            # A failed pickup is the tell for accidental-pickup junk taking
            # up room (R117): cleanse at the next safe moment — unless this
            # item already failed AFTER a cleanse-and-step-off retry, which
            # differed in everything a cleanse can change, so re-queueing one
            # is how the R173 loop span forever.
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



