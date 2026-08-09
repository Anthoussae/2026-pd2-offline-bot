"""Town: driving panels and dialogs - points, clicks, rows, NPC menus.

Split from town.py 2026-08-09; method bodies unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

from pd2bot import offsets
from pd2bot.behavior.town.config import (
    TownError,
    Uncalibrated,
)
from pd2bot.input.gated import VK_DOWN, VK_RETURN
from pd2bot.input.screen import projection_for
from pd2bot.perception import uistate
from pd2bot.uipoints import UIPoint


class _PanelMixin:
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
        for attempt in range(1 + self.config.interact_retries):
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
                self.runlog.event(
                    "npc.interact", npc=name, npc_kind=kind,
                    clicked=list(clicked), attempts=attempt + 1,
                    requested=True,
                )
                return clicked
        player = self._read_player(self.session)
        raise TownError(
            f"{name}'s dialog never opened after "
            f"{1 + self.config.interact_retries} attempts — last click at "
            f"{clicked}, player at {player.position if player else 'unreadable'}"
        )

    # -- step 1: heal ------------------------------------------------------------

