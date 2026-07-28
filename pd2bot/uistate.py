"""Which UI panels are open, and whether it is safe to act.

Why this module exists: during M1 a test click was sent while the in-game ESC
menu happened to be open, and it landed on "Save and Exit Game". A screen
coordinate means whatever the currently-open panel says it means, so nothing
may send input without consulting this module first.

Finding the UI array
--------------------
BH exposes UI state only as a *function* (`GetUiVar_I`), because BH runs inside
the game and can call it. From outside we need the data instead, so we read the
function's own machine code and pull the array address out of it:

    +00: 83 F8 26              cmp eax, 0x26            ; bounds check
    +03: 72 1F                 jb  +0x24
         ...                                            ; assert path
    +24: 8B 04 85 <abs32>      mov eax, [eax*4 + abs32]  <-- the array
    +2B: C3                    ret

Deriving the address at runtime rather than hardcoding it means a patch that
moves the array is picked up automatically instead of silently returning
garbage. The result is sanity-checked before it is trusted (see `find_ui_array`).
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.memory import GameSession

# `mov eax, [reg*4 + disp32]` — the ModRM/SIB pair differs only by index
# register, and we accept either since the encoding is what matters.
_INDEXED_LOAD_PATTERNS = (
    b"\x8b\x04\x85",  # [eax*4 + disp32]
    b"\x8b\x04\x8d",  # [ecx*4 + disp32]
    b"\x8b\x04\x95",  # [edx*4 + disp32]
)
_SCAN_BYTES = 96

# Independent cross-check: BH documents AutomapOn as its own variable
# (D2Ptrs.h:185, 1.13c = 0xFADA8). That address must be the UI array's
# UI_AUTOMAP slot. Two unrelated BH facts agreeing is strong evidence the
# array we found is the right one.
_AUTOMAP_ON_OFFSET = 0xFADA8


class UIArrayNotFound(RuntimeError):
    """The UI-state array could not be located or failed its sanity checks."""


def find_ui_array(session: GameSession) -> int:
    """Locate the UI-state array by parsing GetUiVar_I's code. Returns an absolute address."""
    code = session.raw(session.client(offsets.GET_UI_VAR_FN), _SCAN_BYTES)

    for pattern in _INDEXED_LOAD_PATTERNS:
        index = code.find(pattern)
        if index == -1 or index + len(pattern) + 4 > len(code):
            continue
        start = index + len(pattern)
        address = int.from_bytes(code[start : start + 4], "little")
        if _passes_sanity_checks(session, address):
            return address

    raise UIArrayNotFound(
        "Could not find the indexed load inside GetUiVar_I. The client's code "
        "may have changed; fall back to a differential scan (open vs closed menu) "
        "and re-derive the address."
    )


def _passes_sanity_checks(session: GameSession, address: int) -> bool:
    relative = address - session.client_base
    if not 0 < relative < 0x200000:
        return False
    # The array's UI_AUTOMAP slot must coincide with BH's separately documented
    # AutomapOn variable.
    return relative + offsets.UI_AUTOMAP * 4 == _AUTOMAP_ON_OFFSET


@dataclass(frozen=True)
class UIState:
    """Which panels are open right now."""

    open_panels: frozenset[int]

    def is_open(self, panel: int) -> bool:
        return panel in self.open_panels

    @property
    def names(self) -> list[str]:
        return sorted(offsets.UI_NAMES.get(p, f"ui_{p:#x}") for p in self.open_panels)

    @property
    def blocks_input(self) -> bool:
        """True when a panel is up that would swallow or redirect a click."""
        return bool(self.open_panels & _BLOCKING_PANELS)


# Not every slot in the array is a "panel is on screen" boolean. Calibrated
# live on 2026-07-28 by toggling panels and watching which slots moved:
#
#   0x01 inventory   toggles exactly with the panel          -> real, blocking
#   0x02 character   toggles exactly with the panel          -> real, blocking
#   0x09 esc menu    toggles exactly with the panel          -> real, blocking
#                    (the panel that turned an M1 test click into "Save and
#                    Exit Game" — the single most important entry here)
#   0x0A automap     toggles exactly with the panel          -> real, but the
#                    world is still clickable underneath     -> NOT blocking
#   0x00 (UI_GAME)   always 1 while in a game                -> a state flag,
#                                                               not a panel
#   0x06, 0x13       always 1, never move                    -> internal
#   0x23             on during play, off while the esc menu is up -> looks like
#                    a "gameplay running" flag, not a panel
#   0x14             on at rest, moves on its own            -> not a display
#                                                               flag
#
# Membership below is limited to slots that mean "this panel is displayed".
# Treating the always-on slots as open panels made can_act() report NO during
# ordinary play.
#
# The automap observation doubles as proof the array itself is the right one:
# its slot is the address BH documents separately as AutomapOn, and it moved in
# lockstep with the automap key.
_ALWAYS_ON_SLOTS = frozenset(
    {offsets.UI_GAME, 0x06, offsets.UI_ESCMENU_EX, 0x23, offsets.UI_WPMENU}
)

_BLOCKING_PANELS = frozenset(
    {
        offsets.UI_INVENTORY,
        offsets.UI_CHARACTER,
        offsets.UI_SKILLTREE,
        offsets.UI_NPCMENU,
        offsets.UI_ESCMENU_MAIN,
        offsets.UI_NPCSHOP,
        offsets.UI_QUEST,
        offsets.UI_QUEST_LOG,
        offsets.UI_CHAT_CONSOLE,
    }
)

_PANEL_COUNT = 0x26  # the bounds check compiled into GetUiVar_I


def read_ui_state(session: GameSession, ui_array: int | None = None) -> UIState:
    """Read which panels are open. Pass `ui_array` to avoid re-parsing each tick."""
    array = ui_array if ui_array is not None else find_ui_array(session)
    raw = session.raw(array, _PANEL_COUNT * 4)
    open_panels = {
        index
        for index in range(_PANEL_COUNT)
        if index not in _ALWAYS_ON_SLOTS
        and int.from_bytes(raw[index * 4 : index * 4 + 4], "little")
    }
    return UIState(frozenset(open_panels))


def is_in_game(session: GameSession) -> bool:
    """True when a game is loaded (the player unit exists)."""
    return session.ptr(session.client(offsets.PLAYER_UNIT_PTR)) is not None


def can_act(session: GameSession, ui_array: int | None = None) -> bool:
    """True when input would reach the game world rather than a panel.

    Callers that actually send input must *also* confirm the game window is in
    the foreground — that check belongs to the input layer (M3), not here.
    """
    return is_in_game(session) and not read_ui_state(session, ui_array).blocks_input
