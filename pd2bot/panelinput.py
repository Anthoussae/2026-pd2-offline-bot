"""The third send path: clicking inside in-game panels, where the other two
gates rightly refuse.

The guard landscape before this module (game-cycle.md, "The second gate"):

    GatedInput  sends only when  in a game AND no blocking panel
    MenuInput   sends only when  NOT in a game, OR the ESC menu is open

M5's town layer must click things that live in neither territory: a row in
the waypoint list, an item cell on the stash screen, an option in an NPC's
dialog menu. Those are *in-game panels* — GatedInput refuses because a
blocking panel is open (correctly: a world click would land on the panel),
and MenuInput refuses because we are in a game without the ESC menu
(correctly: that is not a menu screen). Weakening either guard would reopen
the M1 "Save and Exit Game" hole from a new direction.

So: a separate path whose guard *means* "clicking inside this panel". It is
Chat's construction generalized — Chat types only while the chat console is
verified open; PanelInput clicks only while the panel the caller names is
verified open. The caller states its belief ("I am clicking in the waypoint
list"), and the guard checks that belief against a fresh read of the UI
array, at the moment of sending. A stale belief — the panel closed, the
game exited, focus moved — refuses instead of clicking into whatever took
the panel's place.

Same construction rules as the other gates: no bypass flag, no unguarded
variant, checks re-run at send time, refusals raise InputRefused with the
failed condition. Primitives are imported from input.py — the guard is what
is sacred, not the SendInput plumbing.

Shift support exists because PD2's stash screen moves items with
shift+right-click (R47.8); the release is in a `finally` so a mid-click
failure can never leave shift stuck down.
"""

from __future__ import annotations

import time

from pd2bot import offsets, uistate
from pd2bot.input import (
    _CLICK_HOLD_S,
    _KEY_UP,
    _MOUSE_LEFTDOWN,
    _MOUSE_LEFTUP,
    _MOUSE_RIGHTDOWN,
    _MOUSE_RIGHTUP,
    _PRE_CLICK_PAUSE_S,
    VK_SHIFT,
    InputRefused,
    _send_key,
    _send_mouse_flag,
    user32,
)
from pd2bot.memory import GameSession
from pd2bot.window import GameWindow


class PanelInput:
    """Panel-scoped input: every send names the panel it believes is open."""

    def __init__(
        self,
        session: GameSession,
        window: GameWindow | None = None,
        ui_array: int | None = None,
    ) -> None:
        self.session = session
        self.window = window if window is not None else GameWindow(session.process_id)
        self._ui_array = (
            ui_array if ui_array is not None else uistate.find_ui_array(session)
        )

    # -- the gate ------------------------------------------------------------

    def check(self, expected_panel: int, sx: int | None = None, sy: int | None = None) -> None:
        """Raise InputRefused unless clicking inside `expected_panel` is what
        would actually happen right now."""
        if not uistate.is_in_game(self.session):
            raise InputRefused(
                "not in a game — in-game panels cannot be open; menu screens "
                "are MenuInput's job, not ours"
            )
        state = uistate.read_ui_state(self.session, self._ui_array)
        if not state.is_open(expected_panel):
            name = offsets.UI_NAMES.get(expected_panel, f"ui_{expected_panel:#x}")
            open_names = ", ".join(state.names) or "nothing"
            raise InputRefused(
                f"the {name} panel is not open (open: {open_names}) — the "
                "click would land on whatever is actually on screen"
            )
        if not self.window.is_foreground():
            raise InputRefused(
                "the game window is not in the foreground — input would go "
                "to another application"
            )
        if sx is not None and sy is not None:
            rect = self.window.client_rect()
            if not rect.contains(sx, sy):
                raise InputRefused(
                    f"({sx}, {sy}) is outside the game's client area {rect}"
                )

    # -- sends (all gated) ----------------------------------------------------

    def click(
        self,
        expected_panel: int,
        sx: int,
        sy: int,
        button: str = "left",
        *,
        shift: bool = False,
    ) -> None:
        """Guarded click at absolute screen coordinates inside a named panel."""
        self.check(expected_panel, sx, sy)
        down, up = (
            (_MOUSE_LEFTDOWN, _MOUSE_LEFTUP)
            if button == "left"
            else (_MOUSE_RIGHTDOWN, _MOUSE_RIGHTUP)
        )
        user32.SetCursorPos(sx, sy)
        time.sleep(_PRE_CLICK_PAUSE_S)
        self.check(expected_panel, sx, sy)  # the panel may have closed under us
        if shift:
            _send_key(VK_SHIFT, 0)
        try:
            _send_mouse_flag(down)
            time.sleep(_CLICK_HOLD_S)
            _send_mouse_flag(up)
        finally:
            if shift:
                _send_key(VK_SHIFT, _KEY_UP)
