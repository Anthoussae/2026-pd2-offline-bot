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
from pathlib import Path

# Bound directly rather than reached through `time`, because the tests
# replace this module's `time` with a stub that has only `sleep` — and
# the latch cache must not be the reason input becomes untestable.
from time import monotonic as _monotonic

from pd2bot import offsets, watchdog
from pd2bot.input.screen import clickable, projection_for
from pd2bot.input.window import GameWindow
from pd2bot.perception import uistate
from pd2bot.perception.memory import GameSession
from pd2bot.perception.units import player_unit, unit_position

user32 = ctypes.windll.user32

_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_MOUSE_LEFTDOWN, _MOUSE_LEFTUP = 0x0002, 0x0004
_MOUSE_RIGHTDOWN, _MOUSE_RIGHTUP = 0x0008, 0x0010
_KEY_UP = 0x0002
# How long a watchdog-latch read is reused before looking again. `check()`
# runs on every send; a stat per click buys nothing at this timescale.
_LATCH_RECHECK_S = 0.5

# Virtual-key codes the bot uses (Win32 VK_*). Kept here because this module
# owns the SendInput plumbing; the *meaning* of a key (which skill, which
# belt column) lives with the caller's config, not here.
VK_SHIFT = 0x10
# Ctrl+right-click drops an inventory item (R117). VK_CONTROL is the one
# the client honours — verified live in T44, first variant, gem dropped
# and found on the ground.
#
# VK_LCONTROL exists only as a documented alternative, and the story is
# worth keeping: T43 concluded ctrl was being ignored, because the item
# it dropped could not be found on the floor. That was wrong. The drop
# had worked; T43 read the ground ONCE, immediately, and a just-dropped
# item takes a moment to enter the unit table. The antidote it "lost" was
# later found lying exactly where it fell.
#
# So the bug was in the instrument, not the game — the same shape as the
# whole P3 calibration crisis (R86). A verification that polls would have
# passed first time, and the speculative per-side keycode below was never
# needed. Keep it for the day some other client really does read key
# state per-side; do not reach for it before a poll-based test says so.
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_F1, VK_F2, VK_F3, VK_F4, VK_F5, VK_F6 = 0x70, 0x71, 0x72, 0x73, 0x74, 0x75
VK_1, VK_2, VK_3, VK_4 = 0x31, 0x32, 0x33, 0x34
# NPC dialogs are keyboard-navigable: arrows move the highlight, Enter
# selects (user discovery, R104). Sent through PanelInput, never here — a
# world-gated Enter is meaningless, and an ungated one chooses dialog
# options by accident, which is the R89 defect.
VK_UP, VK_DOWN, VK_RETURN = 0x26, 0x28, 0x0D
VK_I = 0x49  # the inventory toggle (default binding)
# ALT — in PD2 a TOGGLE of the ground-item label display (user, 2026-08-03),
# not vanilla's hold-to-show. Labels are the big click targets for pickup;
# the toggle protocol is labels ON to pick, OFF to travel (T63).
VK_MENU = 0x12

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


_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


def _send_mouse_move(sx: int, sy: int) -> None:
    """Move the cursor with a REAL mouse-move event, not a teleport.

    `SetCursorPos` repositions the cursor without a WM_MOUSEMOVE reaching
    the game, so the client's hover state never re-evaluates — measured
    by T60 (2026-08-03): a 421-probe sweep directly across a potion never
    set the hovered-item pointer (round 1), while a pointer latched by
    the user's real hand never CLEARED under the same sweep (round 2).
    T58's hunt worked precisely because a human hand made the moves. A
    SendInput absolute move is the synthetic equivalent of that hand:
    the cursor lands at (sx, sy) AND the game hears about it.
    Coordinates are normalized over the virtual desktop (0..65535).
    """
    vx = user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    if vw <= 1 or vh <= 1:  # pragma: no cover - a broken metrics read
        user32.SetCursorPos(sx, sy)
        return
    nx = round((sx - vx) * 65535 / (vw - 1))
    ny = round((sy - vy) * 65535 / (vh - 1))
    event = _INPUT(type=_INPUT_MOUSE)
    event.union.mi = _MOUSEINPUT(
        nx, ny, 0,
        _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
        0, None,
    )
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))


def _send_mouse_move_relative(dx: int, dy: int) -> None:
    """One RELATIVE mouse move — deltas, the way a physical mouse reports.

    T60 run 3 measured that the game's hover state ignores absolute
    synthetic moves entirely (421 probes across a potion, zero pointer
    flips, while the LABEL highlighted — labels poll the cursor position,
    the hover pointer listens to motion). Relative deltas are the other
    dialect of mouse motion, and the one DirectInput-era clients track.
    Subject to pointer acceleration, so callers must close the loop
    against the real cursor position (see `GatedInput.glide_screen`).
    """
    event = _INPUT(type=_INPUT_MOUSE)
    event.union.mi = _MOUSEINPUT(dx, dy, 0, _MOUSEEVENTF_MOVE, 0, None)
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _cursor_pos() -> tuple[int, int]:
    point = _POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


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
        latch_path: Path | None = None,
    ) -> None:
        self.session = session
        self.window = window if window is not None else GameWindow(session.process_id)
        # Resolving the UI array parses client code; do it once, like Perception.
        self._ui_array = (
            ui_array if ui_array is not None else uistate.find_ui_array(session)
        )
        # The watchdog's latch (see `pd2bot.watchdog`). Cached for a beat
        # because `check()` runs on EVERY send and a stat per click is a
        # syscall nobody asked for; half a second is far shorter than any
        # window in which it matters.
        self._latch_path = latch_path
        self._latch_checked_at: float | None = None
        self._latch_active = False

    # -- the gate ------------------------------------------------------------

    def _watchdog_fired(self) -> bool:
        """Has the watchdog process chickened for us?

        Checked HERE, in the one send path, for the same reason
        everything else is: there is no bypass, and a caller cannot
        forget. Deliberately NOT checked in `MenuInput` — the latch must
        stop *world* input while leaving the *menu* path open, so
        `cycle.leave_game` can still complete the clean Save-and-Exit
        that should follow a watchdog pause. That asymmetry is the
        design, not an oversight.
        """
        now = _monotonic()
        if (
            self._latch_checked_at is not None
            and now - self._latch_checked_at < _LATCH_RECHECK_S
        ):
            return self._latch_active
        self._latch_checked_at = now
        path = self._latch_path if self._latch_path is not None else watchdog.LATCH_FILE
        self._latch_active = watchdog.active_latch(path) is not None
        return self._latch_active

    def check(self) -> None:
        """Raise InputRefused unless input would mean what the caller intends.

        Public so callers (and the navdemo CLI) can *ask* without sending.
        """
        if self._watchdog_fired():
            raise InputRefused(
                "the watchdog chickened — the game is paused and world "
                "input is disarmed until a human clears the latch"
            )
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
        # A real move event, not SetCursorPos: the game resolves what a
        # click is ON from its hover state, and hover only updates when a
        # mouse-move actually arrives (T60). A teleported cursor clicks
        # whatever the game still THINKS is under the old position.
        _send_mouse_move(sx, sy)
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

    def project_world(self, wx: int, wy: int) -> tuple[int, int]:
        """Where a world subtile lands on screen, from a FRESH player read.

        The camera follows the player, so a stale position projects every
        target to the wrong pixel. Public because hover-verified pickup
        (T58) projects once and then probes screen points around it.
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
        return projection.world_to_screen(wx, wy)

    def hover_screen(self, sx: int, sy: int) -> None:
        """Gated cursor move with NO click — the probe half of hover-verified
        pickup (T58): put the cursor somewhere, let the game notice, read
        back what it says is under it. Same guard, same safe-region check as
        a click, because a synthetic cursor move is still input. The move is
        a real SendInput event — a `SetCursorPos` teleport never reaches the
        game's hover logic, which T60 measured as a pointer that neither
        updates nor clears under a 400-probe sweep."""
        self.check()
        rect = self.window.client_rect()
        if not clickable(rect, sx, sy):
            raise InputRefused(
                f"({sx}, {sy}) is outside the safe click region of {rect} "
                "(window edge or HUD strip)"
            )
        _send_mouse_move(sx, sy)

    def glide_screen(
        self,
        sx: int,
        sy: int,
        *,
        step: int = 8,
        settle_s: float = 0.004,
        max_steps: int = 400,
    ) -> None:
        """Gated cursor WALK to (sx, sy): a train of small relative moves,
        feedback-corrected against the real cursor position each step, the
        way a hand crosses a screen. Exists because the game's hover state
        ignores teleports — both `SetCursorPos` and absolute SendInput
        (T60 runs 1-3) — while labels highlight off the polled position.
        Acceleration may scale any single delta; the closed loop absorbs
        that. Raises InputRefused if the walk never converges."""
        self.check()
        rect = self.window.client_rect()
        if not clickable(rect, sx, sy):
            raise InputRefused(
                f"({sx}, {sy}) is outside the safe click region of {rect} "
                "(window edge or HUD strip)"
            )
        for _ in range(max_steps):
            cx, cy = _cursor_pos()
            if abs(cx - sx) <= 1 and abs(cy - sy) <= 1:
                return
            dx = max(-step, min(step, sx - cx))
            dy = max(-step, min(step, sy - cy))
            _send_mouse_move_relative(dx, dy)
            time.sleep(settle_s)
        raise InputRefused(
            f"cursor glide never converged on ({sx}, {sy}) — "
            "pointer acceleration fighting the loop?"
        )

    def click_world(
        self,
        wx: int,
        wy: int,
        button: str = "left",
        *,
        stand_still: bool = False,
    ) -> tuple[int, int]:
        """Gated click on a world subtile. Returns the screen point used."""
        sx, sy = self.project_world(wx, wy)
        self.click_screen(sx, sy, button, stand_still=stand_still)
        return (sx, sy)

    def press_key(self, vk: int) -> None:
        """Gated key press (down+up). Kept minimal until a milestone needs more."""
        self.check()
        _send_key(vk, 0)
        time.sleep(_CLICK_HOLD_S)
        _send_key(vk, _KEY_UP)

    def press_key_with_shift(self, vk: int) -> None:
        """Gated Shift+key chord: Shift provably down before the key.

        Shift+belt-key is the game's give-potion-to-mercenary chord —
        user-verified by hand at R183, which CORRECTED R179's assumed
        Alt: T54 run 2 sent three Alt chords and the player drank every
        potion, because Alt is not a chord the belt knows. The lesson is
        recorded where it was paid: verify a binding against the game
        before automating it.

        The same-frame race that bought `_MODIFIER_SETTLE_S` (R113: a
        shift-click processed as unmodified) applies here too, so the
        chord is sequenced like `stand_still`'s shift: Shift down, one
        settle, the key, one settle, Shift up — and the release lives in
        a `finally`, because a stuck Shift would silently reinterpret
        every click and belt key that comes after it.
        """
        self.check()
        _send_key(VK_SHIFT, 0)
        time.sleep(_MODIFIER_SETTLE_S)
        try:
            _send_key(vk, 0)
            time.sleep(_CLICK_HOLD_S)
            _send_key(vk, _KEY_UP)
            time.sleep(_MODIFIER_SETTLE_S)
        finally:
            _send_key(VK_SHIFT, _KEY_UP)
