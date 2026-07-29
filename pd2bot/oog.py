"""Out-of-game perception: which menu screen is up, and where its buttons are.

In a game, perception reads units and panels. At the menus there is no player
unit and the in-game UI array means nothing — before this module the bot knew
only *that* it was at the menus, never *which screen*. But D2's menus are data
too: every button, textbox and image on screen is a node in a linked list of
Control structs owned by D2Win.dll (offsets.py, "D2Win" section). Walking
that list gives both "which screen is this" (by fingerprint) and "where is
the Hell button" (by rect) — from memory, no pixels. It is the same structure
D2BS's getLocation()/clickControl built kolbot's entire out-of-game layer on.

Two facts that shape the code:

- Menu coordinates live in a fixed 800x600 space no matter how big the window
  is. dwPosY is the control's BOTTOM edge (D2BS clicks at y - h/2), so a
  button "at (264, 383)" has its clickable center at (400, ~365).
- Screens are classified by *fingerprint* — a couple of controls at positions
  distinctive enough to name the screen (mined from kolbot's Control.js,
  which encodes twenty years of community knowledge of these layouts).
  Anything that matches nothing is UNKNOWN, and callers must treat UNKNOWN as
  "stop and describe", never "click and hope".

The list mutates while we read it (menus animate, screens change), so the
walk is bounded, cycle-guarded, and returns what it could read — same
defensive posture as the unit hash table in units.py.

    python -m pd2bot.oog            dump the control list + classification
    python -m pd2bot.oog --watch    keep dumping at ~2 Hz
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pd2bot import offsets, uistate
from pd2bot.memory import GameSession

# The longest real menu list observed is ~40 controls (char select); 128 means
# a corrupt pNext chain, not a big screen.
_MAX_CONTROLS = 128

# Coordinate sanity: menu space is 800x600, but a few real controls hang off
# the edges (kolbot's SplashScreen is 800x600 at y=599). Anything far outside
# means we are reading garbage, and the walk stops trusting the chain.
_COORD_LIMIT = 4096


@dataclass(frozen=True)
class MenuControl:
    """One node of the D2Win control list, in 800x600 menu space."""

    address: int
    ctype: int
    state: int
    x: int  # left edge
    y: int  # BOTTOM edge (not top — see module docstring)
    width: int
    height: int
    text: str | None  # buttons only; None elsewhere

    @property
    def center(self) -> tuple[int, int]:
        """The clickable center in menu space (y is the bottom edge)."""
        return (self.x + self.width // 2, self.y - self.height // 2)

    @property
    def type_name(self) -> str:
        return offsets.CONTROL_TYPE_NAMES.get(self.ctype, f"type_{self.ctype}")

    def matches(self, x: int, y: int, width: int, height: int) -> bool:
        """Exact fingerprint match on position and size."""
        return (
            self.x == x
            and self.y == y
            and self.width == width
            and self.height == height
        )


def read_controls(session: GameSession) -> list[MenuControl]:
    """Walk the control list. Empty when in a game or mid-transition."""
    head = session.ptr(session.win(offsets.D2WIN_FIRST_CONTROL))
    if head is None:
        return []

    controls: list[MenuControl] = []
    seen: set[int] = set()
    node: int | None = head
    while node is not None and node not in seen and len(controls) < _MAX_CONTROLS:
        seen.add(node)
        try:
            ctype, state, x, y, w, h = _read_control_fields(session, node)
        except Exception:
            break  # torn pointer mid-transition: keep what we have
        if not _plausible(x, y, w, h):
            break  # garbage coordinates: stop trusting the chain
        text = None
        if ctype == offsets.CONTROL_TYPE_BUTTON:
            try:
                text = session.wstring(
                    node + offsets.CONTROL_BUTTON_TEXT,
                    offsets.CONTROL_BUTTON_TEXT_CHARS,
                )
            except Exception:
                text = None
        controls.append(MenuControl(node, ctype, state, x, y, w, h, text))
        node = session.ptr(node + offsets.CONTROL_NEXT)
    return controls


def _read_control_fields(
    session: GameSession, node: int
) -> tuple[int, int, int, int, int, int]:
    ctype = session.u32(node + offsets.CONTROL_TYPE)
    state = session.u32(node + offsets.CONTROL_STATE)
    x = session.i32(node + offsets.CONTROL_POS_X)
    y = session.i32(node + offsets.CONTROL_POS_Y)
    w = session.i32(node + offsets.CONTROL_SIZE_X)
    h = session.i32(node + offsets.CONTROL_SIZE_Y)
    return ctype, state, x, y, w, h


def _plausible(x: int, y: int, w: int, h: int) -> bool:
    return (
        -_COORD_LIMIT < x < _COORD_LIMIT
        and -_COORD_LIMIT < y < _COORD_LIMIT
        and 0 <= w < _COORD_LIMIT
        and 0 <= h < _COORD_LIMIT
    )


class Screen(Enum):
    IN_GAME = "in_game"
    MAIN_MENU = "main_menu"
    CHAR_SELECT = "char_select"
    DIFFICULTY = "difficulty"
    ERROR_POPUP = "error_popup"
    LOADING = "loading"
    UNKNOWN = "unknown"


# Fingerprints, mined from kolbot libs/modules/Control.js (positions are
# dwPosX/dwPosY/dwSizeX/dwSizeY in 800x600 menu space; comments give the
# kolbot name). A screen matches when ALL its fingerprint controls are
# present. Order matters: popups overlay their parent screen's controls, so
# the most specific screens are tested first.
_FP_OK_CENTERED = (351, 337, 96, 32)  # OkCentered (error popup button)
_FP_DIFF_NORMAL = (264, 297, 272, 35)  # NormalSP
_FP_DIFF_NIGHTMARE = (264, 340, 272, 35)  # NightmareSP
_FP_DIFF_HELL = (264, 383, 272, 35)  # HellSP
_FP_CHAR_CREATE = (33, 528, 168, 60)  # CharSelectCreate
_FP_CHAR_OK = (627, 572, 128, 35)  # BottomRightOk
_FP_MAIN_SINGLE = (264, 324, 272, 35)  # SinglePlayer
_FP_MAIN_EXIT = (264, 568, 272, 35)  # MainMenuExit

# The difficulty buttons, in the order the cycle wants them.
DIFFICULTY_FINGERPRINTS = {
    offsets.DIFFICULTY_NORMAL: _FP_DIFF_NORMAL,
    offsets.DIFFICULTY_NIGHTMARE: _FP_DIFF_NIGHTMARE,
    offsets.DIFFICULTY_HELL: _FP_DIFF_HELL,
}

CHAR_SELECT_OK = _FP_CHAR_OK
SINGLE_PLAYER_BUTTON = _FP_MAIN_SINGLE


def _has(controls: list[MenuControl], fingerprint: tuple[int, int, int, int]) -> bool:
    return any(c.matches(*fingerprint) for c in controls)


def classify(controls: list[MenuControl], in_game: bool) -> Screen:
    """Name the current screen, or UNKNOWN. UNKNOWN means stop, not guess."""
    if in_game:
        return Screen.IN_GAME
    if not controls:
        # The menus always have controls; an empty list out of game means a
        # loading screen or a mid-transition read.
        return Screen.LOADING
    # Most-specific first: the difficulty popup and error popups sit on top
    # of char select, whose own controls may still be in the list.
    if (
        _has(controls, _FP_DIFF_NORMAL)
        and _has(controls, _FP_DIFF_NIGHTMARE)
        and _has(controls, _FP_DIFF_HELL)
    ):
        return Screen.DIFFICULTY
    if _has(controls, _FP_OK_CENTERED):
        return Screen.ERROR_POPUP
    if _has(controls, _FP_CHAR_CREATE) and _has(controls, _FP_CHAR_OK):
        return Screen.CHAR_SELECT
    if _has(controls, _FP_MAIN_SINGLE) and _has(controls, _FP_MAIN_EXIT):
        return Screen.MAIN_MENU
    return Screen.UNKNOWN


def find_control(
    controls: list[MenuControl], fingerprint: tuple[int, int, int, int]
) -> MenuControl | None:
    for control in controls:
        if control.matches(*fingerprint):
            return control
    return None


def read_screen(session: GameSession) -> tuple[Screen, list[MenuControl]]:
    """One coherent OOG observation: the screen name plus its controls."""
    controls = read_controls(session)
    return classify(controls, uistate.is_in_game(session)), controls


# --- CLI ---------------------------------------------------------------------


def format_dump(screen: Screen, controls: list[MenuControl]) -> str:
    lines = [f"screen: {screen.value}   ({len(controls)} controls)"]
    for c in controls:
        text = f'  "{c.text}"' if c.text else ""
        lines.append(
            f"  {c.type_name:<10} at ({c.x:>4},{c.y:>4}) size {c.width:>3}x{c.height:<3}"
            f" state {c.state} center {c.center}{text}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    from pd2bot.memory import GameNotRunning, NeedsAdministrator

    parser = argparse.ArgumentParser(
        description="Dump the out-of-game menu control list and screen classification."
    )
    parser.add_argument("--watch", action="store_true", help="keep dumping at ~2 Hz")
    args = parser.parse_args(argv)

    try:
        session = GameSession()
    except (GameNotRunning, NeedsAdministrator) as exc:
        print(exc)
        return 1

    while True:
        screen, controls = read_screen(session)
        print(format_dump(screen, controls))
        if not args.watch:
            return 0
        time.sleep(0.5)
        print()


if __name__ == "__main__":
    raise SystemExit(main())
