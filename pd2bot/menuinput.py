"""The second send path: clicking menus, where GatedInput rightly refuses.

`GatedInput` (input.py) guards the world: it sends only when we are in a game
with no blocking panel open. But M4's game cycle lives exactly where that
guard says no — the out-of-game menus (no player unit exists) and the in-game
ESC menu (a blocking panel by definition). Weakening the world gate to allow
those would reopen the M1 "Save and Exit Game" hole, so this module is the
promised *separate, separately-guarded* path instead (CLAUDE.md; the M3
navigation doc wrote this contract before any of this code existed).

The two guards are complements, and that is the design:

    GatedInput  sends only when  in a game AND no blocking panel
    MenuInput   sends only when  NOT in a game, OR the ESC menu is open

Neither can do the other's job. A world click can never land on a menu; a
menu click can never land on the world. The click that ended M1 — "Save and
Exit Game" — is now reachable only through the path whose guard *means* it.

Like GatedInput: no bypass flag, no unguarded variant, the guard re-runs at
the moment of sending, refusal raises InputRefused (the same exception — a
refused caller does not care which gate said no). The OS-level primitives are
imported from input.py rather than duplicated; the guard is what is sacred,
not the SendInput plumbing.

Menu geometry: controls live in a fixed 800x600 menu space (oog.py) while
the window is whatever size the user made it, so clicks scale by the client
rect. The scale hypothesis is verified live by P2's click test before P3
trusts it.
"""

from __future__ import annotations

import time

from pd2bot import offsets
from pd2bot.input import (
    _CLICK_HOLD_S,
    _MOUSE_LEFTDOWN,
    _MOUSE_LEFTUP,
    _PRE_CLICK_PAUSE_S,
    InputRefused,
    _send_key,
    _send_mouse_flag,
    user32,
)
from pd2bot.perception import oog, uistate
from pd2bot.perception.memory import GameSession
from pd2bot.window import ClientRect, GameWindow

VK_ESCAPE = 0x1B
_KEY_UP = 0x0002


def menu_to_screen(rect: ClientRect, mx: int, my: int) -> tuple[int, int]:
    """Project a point from 800x600 menu space into the client area.

    The menus keep their 4:3 aspect: the 800x600 space is scaled uniformly
    to fit the client area and centered, leaving black bars on a widescreen
    window (pillarboxing). Proven live 2026-07-29 on a 1536x864 window: the
    first (naive stretch) model clicked 140 px right of the OK button with y
    exactly right — the signature of a horizontally-centered, height-fit
    box (scale 864/600 = 1.44, bars 192 px). Hover calibration confirmed
    the fit before any further clicks were allowed.
    """
    scale = min(rect.width / offsets.MENU_WIDTH, rect.height / offsets.MENU_HEIGHT)
    offset_x = (rect.width - offsets.MENU_WIDTH * scale) / 2
    offset_y = (rect.height - offsets.MENU_HEIGHT * scale) / 2
    sx = rect.left + round(offset_x + mx * scale)
    sy = rect.top + round(offset_y + my * scale)
    return sx, sy


class MenuInput:
    """Menu-scoped input. The guard is the complement of GatedInput's."""

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

    @property
    def ui_array(self) -> int:
        """The resolved UI-state array address (parsed once, reusable)."""
        return self._ui_array

    # -- the gate ------------------------------------------------------------

    def check(self, sx: int | None = None, sy: int | None = None) -> None:
        """Raise InputRefused unless a menu click/keypress is safe right now.

        With coordinates, additionally requires them inside the client area.
        """
        if uistate.is_in_game(self.session):
            state = uistate.read_ui_state(self.session, self._ui_array)
            if not state.is_open(offsets.UI_ESCMENU_MAIN):
                raise InputRefused(
                    "in a game with no ESC menu open — a menu click here would "
                    "be a world click, which is GatedInput's job, not ours"
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

    def click(self, sx: int, sy: int) -> None:
        """Guarded left click at absolute screen coordinates."""
        self.check(sx, sy)
        user32.SetCursorPos(sx, sy)
        time.sleep(_PRE_CLICK_PAUSE_S)
        self.check(sx, sy)  # the screen may have changed under us
        _send_mouse_flag(_MOUSE_LEFTDOWN)
        time.sleep(_CLICK_HOLD_S)
        _send_mouse_flag(_MOUSE_LEFTUP)

    def click_menu(self, mx: int, my: int) -> tuple[int, int]:
        """Guarded click at 800x600 menu-space coordinates. Returns the pixel."""
        sx, sy = menu_to_screen(self.window.client_rect(), mx, my)
        self.click(sx, sy)
        return sx, sy

    def click_control(self, control: oog.MenuControl) -> tuple[int, int]:
        """Guarded click on a control's center (e.g. the Hell button)."""
        return self.click_menu(*control.center)

    def press_escape(self) -> None:
        """Guarded ESC. Context-safe in both worlds: opens/closes the ESC menu
        in a game, backs out one screen at the menus — so the guard is only
        "the click lands in the game": foreground. This is the chicken's
        first move, and it must work while can_act() is still true."""
        if not self.window.is_foreground():
            raise InputRefused(
                "the game window is not in the foreground — ESC would go "
                "to another application"
            )
        _send_key(VK_ESCAPE, 0)
        time.sleep(_CLICK_HOLD_S)
        _send_key(VK_ESCAPE, _KEY_UP)
