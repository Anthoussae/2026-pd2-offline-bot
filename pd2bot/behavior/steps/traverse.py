"""TraverseStep: cross an area to its exit, collecting on the way.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.behavior.actions import (
    InteractObject,
    MoveTo,
)
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.steps.pickup import _PickupMixin
from pd2bot.behavior.steps.services import RunServices
from pd2bot.behavior.steps.util import (
    _chebyshev,
    _route_leg,
)
from pd2bot.nav import mapframe
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception.snapshot import GameSnapshot


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
    # `line = true` in the run file: this traverse REQUIRES a recorded
    # route line for its area and stops loudly if none exists. (Checked
    # at first in-area tick — the map seed is unknowable at build time.)
    require_line: bool = False
    name: str = "traverse"
    _strayed: bool = False
    _last_stray_emit: float = 0.0
    _line_missing_reported: bool = False
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
        items = self._draw_order(
            self.wanted_items(snap, origin, self.services.pickup_radius)
        )
        if items:
            if self.collect(snap, ctx, items[0]):
                return StepOutcome(
                    done=False, acted=True,
                    note=f"collecting item {items[0].unit_id} at {items[0].position}",
                )
            # Claimed but still resolving (the retry pacing): hold the
            # walk rather than march away from a click in flight.
            return StepOutcome(done=False, waiting=True, note="pickup resolving")
        # A queued cleanse, run here for the same reason the clearance and
        # the sweep run one: this step COLLECTS, so it is a step that can
        # fill the inventory — and until 2026-08-08 it was the only such
        # step that could never empty it again.
        #
        # That gap cost the descent. `collect` queues a cleanse when a
        # non-potion will not come up, and `_mark_inventory_full`
        # suppresses every non-potion pickup for the REST OF THE GAME.
        # A descent run is `town_preamble, waypoint, traverse x6` — not
        # one of which called `maybe_cleanse` — so the queue was set on
        # Cellar 1 and served on no floor at all, and the Countess's own
        # drops were being skipped by a flag raised twenty minutes before
        # she was reached. Observed by the operator, 2026-08-08.
        #
        # Placed AFTER the pickup attempt and BEFORE the walk: collecting
        # is the better use of a tick, and `maybe_cleanse` declines by
        # itself whenever a hostile is close enough to punish standing
        # still.
        if self.maybe_cleanse(snap, ctx):
            return StepOutcome(done=False, acted=True, note="inventory cleansed")
        # Mandatory orders (R241 item 7): below combat and the pickups
        # above, ABOVE onward travel — a wanted drop left behind pulls the
        # step back before it walks on toward the exit. None when the
        # pilot flag is off or nothing is owed.
        order_outcome = self.service_orders(snap, ctx)
        if order_outcome is not None:
            return order_outcome
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

        # The leash (R241): with a recorded line and a real stray, the
        # next leg walks BACK to the line instead of onward — posture
        # permitting — so combat excursions do not compound into drift.
        leash_target = self._leash(snap, origin)

        leg = _route_leg(self.services, origin, leash_target or self._exit)
        if leg is None and leash_target is not None:
            # The line point is unreachable right now (atlas gap between
            # here and there). Fall back to the exit rather than stall.
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

    def _leash(
        self, snap: GameSnapshot, origin: tuple[int, int]
    ) -> tuple[int, int] | None:
        """The route leash (R241): the point to walk back to, or None.

        None means "no leash applies this tick": no line recorded, not
        strayed beyond the threshold, or the posture is waiting for the
        neighbourhood to empty before returning (cautious/aggressive/
        berserk wait; brisk returns immediately — it only ever fought
        what obstructed the corridor). Emits `route.stray` on the
        crossing and every ~5 s while out, never per tick.
        """
        line_for = self.services.route_line_for
        if line_for is None or snap.area is None:
            return None
        line = line_for(snap.area.level_no)
        if line is None:
            if self.require_line and not self._line_missing_reported:
                self._line_missing_reported = True
                raise NavigationError(
                    f"step requires a route line for area "
                    f"{snap.area.level_no} and none is recorded — walk it "
                    "once with drills/t84_record_line.py"
                )
            return None
        stray = line.stray_from(origin)
        threshold = self.services.route_stray_subtiles
        now = self.services.clock()
        outside = stray.distance > threshold
        if outside and (
            not self._strayed or now - self._last_stray_emit >= 5.0
        ):
            self._last_stray_emit = now
            self.services.runlog.event(
                "route.stray",
                distance=round(stray.distance, 1),
                nearest=list(stray.nearest),
                progress=round(stray.progress, 3),
                returning=self._return_allowed(snap),
            )
        self._strayed = outside
        if not outside:
            return None
        # The goal-off-line guard: when the EXIT itself lies at least as
        # far off the line as we do, "return first" would walk AWAY from
        # the goal and re-stray on the next leg, forever — the line ends
        # somewhere and the staircase is beyond it. The leash exists to
        # undo combat drift, not to forbid finishing the route.
        if self._exit is not None:
            exit_stray = line.stray_from(self._exit)
            if exit_stray.distance >= stray.distance - threshold:
                return None
        if not self._return_allowed(snap):
            return None
        return stray.nearest

    def _return_allowed(self, snap: GameSnapshot) -> bool:
        """Brisk walks back through trouble; everyone else waits for the
        neighbourhood to empty first (the R241 return policy)."""
        if self.posture == "brisk":
            return True
        radius = self.services.route_return_hostile_radius
        me = snap.player.position
        return not any(
            m.is_alive and _chebyshev(m.position, me) <= radius
            for m in snap.monsters
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

