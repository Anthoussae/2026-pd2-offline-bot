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

from pd2bot import offsets
from pd2bot.input.gated import (
    _CLICK_HOLD_S,
    _KEY_UP,
    _MODIFIER_SETTLE_S,
    _MOUSE_LEFTDOWN,
    _MOUSE_LEFTUP,
    _MOUSE_RIGHTDOWN,
    _MOUSE_RIGHTUP,
    _PRE_CLICK_PAUSE_S,
    VK_CONTROL,
    VK_SHIFT,
    InputRefused,
    _send_key,
    _send_mouse_flag,
    user32,
)
from pd2bot.input.window import GameWindow
from pd2bot.perception import uistate
from pd2bot.perception.memory import GameSession


class PanelInput:
    """Panel-scoped input: every send names the panel it believes is open."""

    def __init__(
        self,
        session: GameSession,
        window: GameWindow | None = None,
        ui_array: int | None = None,
        *,
        ctrl_vk: int = VK_CONTROL,
        modifier_settle_s: float = _MODIFIER_SETTLE_S,
    ) -> None:
        self.session = session
        self.window = window if window is not None else GameWindow(session.process_id)
        self._ui_array = (
            ui_array if ui_array is not None else uistate.find_ui_array(session)
        )
        # Which control key to send, and how long to let a modifier settle.
        # Both are parameters rather than constants because T43 proved the
        # defaults are not automatically right: a ctrl+right-click went in
        # as an unmodified click and drank the potion it was aimed at. A
        # drill can now COMPARE spellings through this same gated path
        # instead of hand-rolling raw sends that skip the guard.
        self._ctrl_vk = ctrl_vk
        self._modifier_settle_s = modifier_settle_s

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

    def press_key(self, expected_panel: int, vk: int) -> None:
        """Guarded keypress while a named panel is open.

        Exists because NPC dialogs can be driven by keyboard — arrows move
        the highlight, Enter selects (user discovery, R104) — and neither
        existing path may do it: `GatedInput` refuses while a blocking panel
        is open (rightly: the key is not going to the world), and `MenuInput`
        refuses in a game without the ESC menu. Same narrow guard as `click`:
        the caller names the panel it believes is open, and that belief is
        re-checked against a fresh read at send time.

        The keys this exists to send are the dangerous ones — Enter into a
        dialog CHOOSES something (R89) — so there is no unguarded variant
        and no bypass, exactly as for clicks.
        """
        self.check(expected_panel)
        _send_key(vk, 0)
        time.sleep(_CLICK_HOLD_S)
        _send_key(vk, _KEY_UP)

    def click(
        self,
        expected_panel: int,
        sx: int,
        sy: int,
        button: str = "left",
        *,
        shift: bool = False,
        ctrl: bool = False,
        move_settle_s: float | None = None,
    ) -> None:
        """Guarded click at absolute screen coordinates inside a named panel.

        `move_settle_s` overrides the pause between the cursor move and the
        press. The default (50 ms, M1-proven against world clicks) is barely
        over one 25 fps sim frame, and some panel controls only react to a
        press once the hover has been processed — so a control that ignores
        a normal click may take a slower one. Exposed rather than raised
        blindly because a longer pause costs real time on every click; the
        T24 battery measures which controls actually need it.

        Modifiers (`shift` moves items, `ctrl`+right DROPS them — R117) are
        settled a frame on each side of the click: a modifier sent in the
        SAME frame as its click is a race the game can resolve as an
        unmodified click, which is how a Tome of Identify got USED instead
        of stashed (R113). For ctrl the unmodified reading is worse — a
        plain right-click on a potion drinks it — so the discipline is not
        optional. Releases are in a `finally`, so no failure can leave a
        modifier stuck down for input that comes later.
        """
        self.check(expected_panel, sx, sy)
        down, up = (
            (_MOUSE_LEFTDOWN, _MOUSE_LEFTUP)
            if button == "left"
            else (_MOUSE_RIGHTDOWN, _MOUSE_RIGHTUP)
        )
        user32.SetCursorPos(sx, sy)
        time.sleep(_PRE_CLICK_PAUSE_S if move_settle_s is None else move_settle_s)
        self.check(expected_panel, sx, sy)  # the panel may have closed under us
        modifiers = [
            vk for vk, held in ((VK_SHIFT, shift), (self._ctrl_vk, ctrl)) if held
        ]
        for vk in modifiers:
            _send_key(vk, 0)
        if modifiers:
            time.sleep(self._modifier_settle_s)
        try:
            _send_mouse_flag(down)
            time.sleep(_CLICK_HOLD_S)
            _send_mouse_flag(up)
            if modifiers:
                time.sleep(self._modifier_settle_s)
        finally:
            for vk in reversed(modifiers):
                _send_key(vk, _KEY_UP)
