"""Finding and watching the game's window.

Input only means what we intend when it lands in the game's window while that
window is the one receiving input. A click delivered anywhere else is at best
lost and at worst does something in another application. This module answers
the input gate's second question (the first is `uistate.can_act`): is the game
window the foreground window *right now*?

Only this module and `input.py` touch user32; everything else stays OS-free,
mirroring how only `memory.py` knows about pymem.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

_SW_RESTORE = 9  # ShowWindow: un-minimize without changing a normal window
_VK_MENU = 0x12  # ALT: inert alone, which is why it is the keystroke used
_KEYEVENTF_KEYUP = 0x0002


def _send_inert_keystroke() -> None:
    """One ALT down/up, to qualify this process for a focus request.

    Deliberately NOT routed through `input.py`'s gate: that gate exists to
    stop input reaching the GAME by accident, and this keystroke is aimed
    at whatever currently has focus precisely so that it does not. Sending
    it through the gate would be a category error — and would deadlock the
    bootstrap, since the gate requires the foreground we are trying to get.
    """
    user32.keybd_event(_VK_MENU, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
    time.sleep(0.02)


class WindowNotFound(RuntimeError):
    """No visible top-level window belongs to the game process."""


@dataclass(frozen=True)
class ClientRect:
    """The window's drawable area, in screen coordinates."""

    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def contains(self, x: int, y: int) -> bool:
        return (
            self.left <= x < self.left + self.width
            and self.top <= y < self.top + self.height
        )


def _windows_of_process(process_id: int) -> list[int]:
    handles: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value == process_id and user32.IsWindowVisible(hwnd):
            handles.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return handles


class GameWindow:
    """A handle on the game's top-level window, looked up by process id."""

    def __init__(self, process_id: int) -> None:
        handles = _windows_of_process(process_id)
        if not handles:
            raise WindowNotFound(
                f"process {process_id} has no visible window — is the game "
                "still starting, or running on another desktop?"
            )
        self.hwnd = handles[0]

    def client_rect(self) -> ClientRect:
        """The drawable area right now. Re-queried every call: the user may
        move the window between two of our actions, and a cached rect would
        turn every projected click into a lie."""
        rect = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(origin))
        return ClientRect(origin.x, origin.y, rect.right, rect.bottom)

    def is_foreground(self) -> bool:
        return user32.GetForegroundWindow() == self.hwnd

    def bring_to_foreground(self, settle_seconds: float = 0.3) -> bool:
        """Try to focus the game window; True if it actually took.

        Windows is allowed to refuse focus stealing, so the result is
        verified with GetForegroundWindow rather than assumed — callers must
        treat False as "do not send input".

        Two attempts, because the polite one has a documented blind spot:
        `SetForegroundWindow` only obeys a process that already owns the
        foreground or the most recent input. That is every interactive run
        (the operator is clicking around, and the click that starts the bot
        is itself the qualifying input) and NO unattended one — a run
        launched through the elevated bridge is a background child that has
        never been foreground and never received input, so its request is
        silently dropped. Found 2026-08-07, when the unattended safety
        canary could not take the window at all.
        """
        user32.ShowWindow(self.hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(self.hwnd)
        time.sleep(settle_seconds)
        if self.is_foreground():
            return True
        return self.force_foreground(settle_seconds)

    def force_foreground(self, settle_seconds: float = 0.3) -> bool:
        """The escalation: qualify for focus, then ask again.

        Two standard manoeuvres, both needed on different Windows builds:

        1. **Send a synthetic ALT.** The foreground rules grant the request
           of a process that received the last input event, so producing one
           qualifies us. ALT is chosen because it is inert on its own — it
           opens no menu without a following key, and it lands on whatever
           is focused now (a terminal), never on the game.
        2. **Attach to the foreground thread's input queue.** While two
           threads share an input queue, either may set the foreground
           window. Attaching is reversed in a `finally`: leaving threads
           attached couples this process's input state to another
           application's for the rest of its life.

        Still verified rather than assumed, and still allowed to fail — a
        locked workstation or a full-screen exclusive app on top will refuse
        both, and "do not send input" remains the correct answer.
        """
        _send_inert_keystroke()
        foreground = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(foreground, None)
        our_thread = kernel32.GetCurrentThreadId()
        attached = False
        try:
            if target_thread and target_thread != our_thread:
                attached = bool(
                    user32.AttachThreadInput(our_thread, target_thread, True)
                )
            user32.ShowWindow(self.hwnd, _SW_RESTORE)
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(our_thread, target_thread, False)
        time.sleep(settle_seconds)
        return self.is_foreground()
