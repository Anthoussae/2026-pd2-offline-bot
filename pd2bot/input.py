"""The only code in this project allowed to send input to the game.

Why a gate, structurally: during M1 a test click was sent while the in-game
ESC menu happened to be open, and it activated "Save and Exit Game"
(spike-log.md). A screen coordinate means whatever the currently-open panel
says it means, and a click delivered to the wrong window means nothing we
intended at all. So there is exactly one send path, it re-checks both
conditions at the moment of sending, and it refuses loudly instead of
trusting its caller:

    1. `uistate.can_act()` — in a game, no input-swallowing panel open
    2. the game window is the foreground window

There is deliberately no bypass flag and no unguarded variant. Tests use
fakes; menu-scoped input (clicking while *not* in a game, which M4 needs for
game creation) will be a separate, separately-guarded method added then —
not a hole poked in this one.

The check-then-send race is real but tiny: a panel can only appear between
the check and the click if the game spontaneously opens one (death screen,
level-up has none, hostility popups don't exist offline) — accepted and
documented rather than pretended away.
"""

from __future__ import annotations

import ctypes
import time

from pd2bot import offsets, uistate
from pd2bot.memory import GameSession
from pd2bot.screen import clickable, projection_for
from pd2bot.units import player_unit, unit_position
from pd2bot.window import GameWindow

user32 = ctypes.windll.user32

_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_MOUSE_LEFTDOWN, _MOUSE_LEFTUP = 0x0002, 0x0004
_MOUSE_RIGHTDOWN, _MOUSE_RIGHTUP = 0x0008, 0x0010
_KEY_UP = 0x0002

# Virtual-key codes the bot uses (Win32 VK_*). Kept here because this module
# owns the SendInput plumbing; the *meaning* of a key (which skill, which
# belt column) lives with the caller's config, not here.
VK_SHIFT = 0x10
VK_F1, VK_F2, VK_F3, VK_F4, VK_F5, VK_F6 = 0x70, 0x71, 0x72, 0x73, 0x74, 0x75
VK_1, VK_2, VK_3, VK_4 = 0x31, 0x32, 0x33, 0x34
# NPC dialogs are keyboard-navigable: arrows move the highlight, Enter
# selects (user discovery, R104). Sent through PanelInput, never here — a
# world-gated Enter is meaningless, and an ungated one chooses dialog
# options by accident, which is the R89 defect.
VK_UP, VK_DOWN, VK_RETURN = 0x26, 0x28, 0x0D
VK_I = 0x49  # the inventory toggle (default binding)

# Down/up spacing: a real click is never instantaneous, and the game samples
# input per frame (25 fps sim); 60 ms was proven against the live client in M1
# (spike/probe_click.py). The pre-click pause lets the cursor-move register.
_PRE_CLICK_PAUSE_S = 0.05
_CLICK_HOLD_S = 0.06
# A modifier pressed in the SAME frame as its click is a race: the game can
# process the click first and see it unmodified. Harmless on most items — an
# unshifted right-click on a potion just drinks it — which is exactly why it
# survived every deposit until T27 met a Tome of Identify, where the naked
# right-click CAST it and the identify cursor then ate the retry too (R113,
# user-observed). One frame of settle on each side removes the race: shift
# provably down before the click, provably still down when it resolves.
_MODIFIER_SETTLE_S = 0.06


class InputRefused(RuntimeError):
    """The gate said no. The message says which condition failed."""


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


def _send_mouse_flag(flags: int) -> None:
    event = _INPUT(type=_INPUT_MOUSE)
    event.union.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))


def _send_key(vk: int, flags: int) -> None:
    event = _INPUT(type=_INPUT_KEYBOARD)
    event.union.ki = _KEYBDINPUT(vk, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))


_KEYEVENTF_UNICODE = 0x0004


def _send_char(char: str) -> None:
    """Type one character via KEYEVENTF_UNICODE (layout-independent).

    Used by chat.py to type text into the in-game chat box; no VK mapping,
    so any character the game font can show can be sent.
    """
    code = ord(char)
    down = _INPUT(type=_INPUT_KEYBOARD)
    down.union.ki = _KEYBDINPUT(0, code, _KEYEVENTF_UNICODE, 0, None)
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
    up = _INPUT(type=_INPUT_KEYBOARD)
    up.union.ki = _KEYBDINPUT(0, code, _KEYEVENTF_UNICODE | _KEY_UP, 0, None)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))


class GatedInput:
    """All input goes through here, and the gate runs on every send."""

    def __init__(
        self,
        session: GameSession,
        window: GameWindow | None = None,
        ui_array: int | None = None,
    ) -> None:
        self.session = session
        self.window = window if window is not None else GameWindow(session.process_id)
        # Resolving the UI array parses client code; do it once, like Perception.
        self._ui_array = (
            ui_array if ui_array is not None else uistate.find_ui_array(session)
        )

    # -- the gate ------------------------------------------------------------

    def check(self) -> None:
        """Raise InputRefused unless input would mean what the caller intends.

        Public so callers (and the navdemo CLI) can *ask* without sending.
        """
        if not uistate.is_in_game(self.session):
            raise InputRefused("not in a game — the client is in the menus")
        state = uistate.read_ui_state(self.session, self._ui_array)
        if state.blocks_input:
            raise InputRefused(
                f"a blocking panel is open ({', '.join(state.names)}) — "
                "a click would land on the panel, not the world"
            )
        if not self.window.is_foreground():
            raise InputRefused(
                "the game window is not in the foreground — input would go "
                "to another application"
            )

    # -- sends (all gated) -----------------------------------------------------

    def click_screen(
        self, sx: int, sy: int, button: str = "left", *, stand_still: bool = False
    ) -> None:
        """Gated click at absolute screen coordinates inside the client area.

        `stand_still` holds SHIFT across the click — the game's attack-in-
        place modifier (M5 combat: strike a monster without walking into the
        pack). The release is in a `finally` so no refusal or failure can
        ever leave shift stuck down for input that comes later.
        """
        self.check()
        rect = self.window.client_rect()
        if not clickable(rect, sx, sy):
            raise InputRefused(
                f"({sx}, {sy}) is outside the safe click region of {rect} "
                "(window edge or HUD strip)"
            )
        down, up = (
            (_MOUSE_LEFTDOWN, _MOUSE_LEFTUP)
            if button == "left"
            else (_MOUSE_RIGHTDOWN, _MOUSE_RIGHTUP)
        )
        user32.SetCursorPos(sx, sy)
        time.sleep(_PRE_CLICK_PAUSE_S)
        self.check()  # re-check at the last moment; state may have moved
        if stand_still:
            _send_key(VK_SHIFT, 0)
            time.sleep(_MODIFIER_SETTLE_S)  # same-frame race, see the constant
        try:
            _send_mouse_flag(down)
            time.sleep(_CLICK_HOLD_S)
            _send_mouse_flag(up)
            if stand_still:
                time.sleep(_MODIFIER_SETTLE_S)
        finally:
            if stand_still:
                _send_key(VK_SHIFT, _KEY_UP)

    def click_world(
        self,
        wx: int,
        wy: int,
        button: str = "left",
        *,
        stand_still: bool = False,
    ) -> tuple[int, int]:
        """Gated click on a world subtile. Returns the screen point used.

        Reads the player position fresh: the camera follows the player, so a
        stale position projects every target to the wrong pixel.
        """
        unit = player_unit(self.session)
        position = (
            unit_position(self.session, unit, offsets.UNIT_TYPE_PLAYER)
            if unit is not None
            else None
        )
        if position is None:
            raise InputRefused("player position unreadable — cannot project a world click")
        projection = projection_for(position, self.window.client_rect())
        sx, sy = projection.world_to_screen(wx, wy)
        self.click_screen(sx, sy, button, stand_still=stand_still)
        return (sx, sy)

    def press_key(self, vk: int) -> None:
        """Gated key press (down+up). Kept minimal until a milestone needs more."""
        self.check()
        _send_key(vk, 0)
        time.sleep(_CLICK_HOLD_S)
        _send_key(vk, _KEY_UP)
