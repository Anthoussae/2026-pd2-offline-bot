"""Town: walking, approaching allies and objects, clearing stray UI.

Split from town.py 2026-08-09; method bodies unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

from pd2bot import offsets
from pd2bot.behavior.town.config import (
    TownError,
    TownStopped,
    Uncalibrated,
)
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception import uistate


class _WalkMixin:
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

    def _walk_all_the_way(self, destination: tuple[int, int]) -> None:
        """Keep walking until `walk_to` says it is done, not merely back.

        Since 2026-08-07 `walk_to` returns on a 2 s wall clock whether or
        not it arrived, so the tick loop keeps breathing during a long
        leg (the chicken-starvation fix). Field steps were already built
        for that — they re-check distance every tick and re-issue — but
        the TOWN layer was not: it crossed town in ONE call and trusted
        the call to block until arrival.

        Live on 2026-08-08 that was a `heal: FAILED after 2.1s` — exactly
        one walk budget. The bot walked 2 s toward Akara, was told the
        walk had "finished", looked for her, and correctly reported she
        was not there. Nothing was wrong with the town layer's logic; the
        contract underneath it had changed.

        A capped return is not arrival, so loop. The navigator carries
        its own give-up ladder across calls, so a genuinely unreachable
        destination still raises `NavigationError` here rather than
        spinning; the wall clock is a second bound for the case where
        something crawls forever without ever quite failing.
        """
        deadline = self._clock() + self.config.approach_timeout_s
        while True:
            # Timed separately from the walk (T87 follow-up): the 15 s hole
            # between two 1-second legs sat BEFORE the leg timer started,
            # and this call — the operator-abort poll, which reads the
            # in-game chat list — is one of only two things in that window.
            check_began = self._clock()
            self._check_stop()
            stop_check_s = self._clock() - check_began
            began = self._clock()
            result = self.walk_to(destination)
            self._log_leg(
                destination, result, self._clock() - began, stop_check_s
            )
            if not getattr(result, "capped", False):
                return  # arrived, or stopped short for a reason of its own
            if self._clock() >= deadline:
                raise TownError(
                    f"still short of {destination} after "
                    f"{self.config.approach_timeout_s:.0f}s of capped legs — "
                    "the route may be crawling or blocked"
                )

    def _log_leg(
        self, destination, result, seconds: float, stop_check_s: float = 0.0
    ) -> None:
        """One `nav.leg` per town walk_to call. Telemetry only; never raises.

        Written for T87 (2026-08-13): the same 24-subtile spawn-to-waypoint
        walk took 4.5 s in trial 1 and ~18.5 s in trials 2-5, and the event
        log could not say why — the town walk's legs were the one stretch
        of the bot's life below the log's resolution. The WalkResult
        already carries the whole story (clicks, replans, its own trail);
        this puts it on the record. Slow legs (> 4 s) carry the trail.
        """
        log = getattr(self, "runlog", None)
        if log is None or not getattr(log, "enabled", False):
            return
        try:
            arrived = getattr(result, "arrived_at", None)
            fields = {
                "target": list(destination),
                "arrived_at": list(arrived) if arrived else None,
                "seconds": round(seconds, 2),
                "clicks": getattr(result, "clicks", None),
                "reclicks": getattr(result, "reclicks", None),
                "replans": getattr(result, "replans", None),
                "waypoints": getattr(result, "waypoints", None),
                "capped": getattr(result, "capped", None),
                "stop_check_s": round(stop_check_s, 2),
            }
            if seconds > 4.0:
                fields["trail"] = list(getattr(result, "log", ()))[-6:]
            log.event("nav.leg", **fields)
        except Exception:  # noqa: BLE001 - telemetry must not cost the walk
            return

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
                self._walk_all_the_way(destination)
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
            names = ", ".join(
                sorted(
                    offsets.UI_NAMES.get(panel, f"ui_{panel:#x}")
                    for panel in stray
                )
            )
            found.append(names)
            try:
                self.menu.press_escape()
            except Exception:  # noqa: BLE001 - recovery must not raise
                break
            self._sleep(self.config.panel_settle_s)
        # ONE event per accident, not per retry (review 003). Nothing in
        # the field opens a panel on purpose, so an unrequested one IS an
        # accident (R220 Q7) — but a panel that took three ESCs to close
        # is ONE accident, and emitting inside the loop would inflate the
        # very count this event exists to answer (`item.dropped` fires on
        # the transition for the same reason). Carries whether the
        # recovery actually worked, which a per-retry emit could not say.
        if found:
            self.runlog.event(
                "npc.accidental", panels=found[0], attempts=len(found),
                cleared=not self._any_panel_open(), requested=False,
            )
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
            read_began = self._clock()
            player = self._read_player(self.session)
            read_s = self._clock() - read_began
            if read_s > 1.0:
                # The other suspect in the T87 15-second hole. Telemetry
                # only; a slow read is news, not a failure.
                try:
                    self.runlog.event(
                        "nav.slow_read", what="read_player",
                        seconds=round(read_s, 2),
                    )
                except Exception:  # noqa: BLE001
                    pass
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

