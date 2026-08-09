"""oog.py against fake control lists: walking, classification, safety rails."""

from __future__ import annotations

import struct

from conftest import WIN_BASE, FakeMemory, FakeSession, u32, wchars

from pd2bot import offsets
from pd2bot.perception import oog

_FIRST_CONTROL_PTR = WIN_BASE + offsets.D2WIN_FIRST_CONTROL
_CONTROL_SIZE = 0x64 + offsets.CONTROL_BUTTON_TEXT_CHARS * 2


def make_control(
    memory: FakeMemory,
    address: int,
    *,
    ctype: int = offsets.CONTROL_TYPE_BUTTON,
    state: int = 5,
    rect: tuple[int, int, int, int] = (0, 0, 10, 10),
    text: str | None = None,
    next_address: int = 0,
) -> int:
    x, y, w, h = rect
    fields = {
        offsets.CONTROL_TYPE: u32(ctype),
        offsets.CONTROL_STATE: u32(state),
        offsets.CONTROL_POS_X: struct.pack("<i", x),
        offsets.CONTROL_POS_Y: struct.pack("<i", y),
        offsets.CONTROL_SIZE_X: struct.pack("<i", w),
        offsets.CONTROL_SIZE_Y: struct.pack("<i", h),
        offsets.CONTROL_NEXT: u32(next_address),
    }
    if text is not None:
        fields[offsets.CONTROL_BUTTON_TEXT] = wchars(
            text, offsets.CONTROL_BUTTON_TEXT_CHARS
        )
    else:
        # Buttons always have a text buffer; empty string for the rest keeps
        # reads inside the allocation.
        fields[offsets.CONTROL_BUTTON_TEXT] = wchars(
            "", offsets.CONTROL_BUTTON_TEXT_CHARS
        )
    memory.write_fields(address, fields)
    return address


def set_next(memory: FakeMemory, control: int, target: int) -> None:
    """Rewrite an existing control's pNext in place.

    A fresh memory.write() would create a second region overlapping the
    control's allocation, and FakeMemory.read would keep answering from the
    original — mutate the existing bytes instead.
    """
    region = memory.regions[control]
    region[offsets.CONTROL_NEXT : offsets.CONTROL_NEXT + 4] = u32(target)


def link(memory: FakeMemory, *addresses: int) -> None:
    """Point FirstControl at the first address and chain pNext through the rest."""
    memory.write(_FIRST_CONTROL_PTR, u32(addresses[0] if addresses else 0))
    for here, there in zip(addresses, list(addresses[1:]) + [0], strict=True):
        set_next(memory, here, there)


def not_in_game(memory: FakeMemory, client_base: int = 0x6FAB0000) -> None:
    memory.write(client_base + offsets.PLAYER_UNIT_PTR, u32(0))


def session_with(memory: FakeMemory) -> FakeSession:
    not_in_game(memory)
    return FakeSession(memory)


def test_walks_a_linked_list_and_reads_button_text():
    memory = FakeMemory()
    a = make_control(memory, 0x1000, rect=(264, 383, 272, 35), text="HELL")
    b = make_control(
        memory, 0x2000, ctype=offsets.CONTROL_TYPE_TEXTBOX, rect=(10, 20, 30, 40)
    )
    link(memory, a, b)
    session = session_with(memory)

    controls = oog.read_controls(session)

    assert len(controls) == 2
    assert controls[0].text == "HELL"
    assert controls[0].center == (264 + 136, 383 - 17)
    assert controls[1].text is None  # not a button
    assert controls[1].type_name == "textbox"


def test_empty_when_first_control_is_null():
    memory = FakeMemory()
    memory.write(_FIRST_CONTROL_PTR, u32(0))
    session = FakeSession(memory)

    assert oog.read_controls(session) == []


def test_cycle_in_pnext_terminates():
    memory = FakeMemory()
    a = make_control(memory, 0x1000)
    b = make_control(memory, 0x2000)
    link(memory, a, b)
    set_next(memory, b, a)  # b -> a -> b -> ...
    session = session_with(memory)

    controls = oog.read_controls(session)

    assert [c.address for c in controls] == [a, b]


def test_garbage_coordinates_stop_the_walk():
    memory = FakeMemory()
    a = make_control(memory, 0x1000, rect=(264, 383, 272, 35))
    bad = make_control(memory, 0x2000, rect=(999999, 5, 5, 5))
    c = make_control(memory, 0x3000)
    link(memory, a, bad, c)
    session = session_with(memory)

    controls = oog.read_controls(session)

    assert [c.address for c in controls] == [a]  # stopped at the garbage node


def test_unreadable_node_keeps_what_was_read():
    memory = FakeMemory()
    a = make_control(memory, 0x1000)
    link(memory, a)
    set_next(memory, a, 0xDEAD0000)  # unmapped
    session = session_with(memory)

    controls = oog.read_controls(session)

    assert [c.address for c in controls] == [a]


def _difficulty_screen(memory: FakeMemory) -> None:
    a = make_control(memory, 0x1000, rect=(264, 297, 272, 35), text="NORMAL")
    b = make_control(memory, 0x2000, rect=(264, 340, 272, 35), text="NIGHTMARE")
    c = make_control(memory, 0x3000, rect=(264, 383, 272, 35), text="HELL")
    # char select's own controls may still be in the list under the popup
    d = make_control(memory, 0x4000, rect=(33, 528, 168, 60), text="CREATE")
    e = make_control(memory, 0x5000, rect=(627, 572, 128, 35), text="OK")
    link(memory, a, b, c, d, e)


def test_classify_difficulty_beats_char_select():
    memory = FakeMemory()
    _difficulty_screen(memory)
    session = session_with(memory)

    screen, controls = oog.read_screen(session)

    assert screen is oog.Screen.DIFFICULTY
    hell = oog.find_control(controls, oog.DIFFICULTY_FINGERPRINTS[offsets.DIFFICULTY_HELL])
    assert hell is not None and hell.text == "HELL"


def test_classify_char_select():
    memory = FakeMemory()
    a = make_control(memory, 0x1000, rect=(33, 528, 168, 60), text="CREATE")
    b = make_control(memory, 0x2000, rect=(627, 572, 128, 35), text="OK")
    link(memory, a, b)
    session = session_with(memory)

    assert oog.read_screen(session)[0] is oog.Screen.CHAR_SELECT


def test_classify_main_menu():
    memory = FakeMemory()
    a = make_control(memory, 0x1000, rect=(264, 324, 272, 35), text="SINGLE PLAYER")
    b = make_control(memory, 0x2000, rect=(264, 568, 272, 35), text="EXIT DIABLO II")
    link(memory, a, b)
    session = session_with(memory)

    assert oog.read_screen(session)[0] is oog.Screen.MAIN_MENU


def test_classify_error_popup_beats_char_select():
    memory = FakeMemory()
    a = make_control(memory, 0x1000, rect=(33, 528, 168, 60))
    b = make_control(memory, 0x2000, rect=(627, 572, 128, 35))
    c = make_control(memory, 0x3000, rect=(351, 337, 96, 32), text="OK")
    link(memory, a, b, c)
    session = session_with(memory)

    assert oog.read_screen(session)[0] is oog.Screen.ERROR_POPUP


def test_classify_unknown_rather_than_guess():
    memory = FakeMemory()
    a = make_control(memory, 0x1000, rect=(1, 2, 3, 4))
    link(memory, a)
    session = session_with(memory)

    assert oog.read_screen(session)[0] is oog.Screen.UNKNOWN


def test_classify_loading_when_no_controls_out_of_game():
    memory = FakeMemory()
    memory.write(_FIRST_CONTROL_PTR, u32(0))
    session = session_with(memory)

    assert oog.read_screen(session)[0] is oog.Screen.LOADING


def test_classify_in_game_wins():
    memory = FakeMemory()
    _difficulty_screen(memory)  # stale list from before the game loaded
    session = FakeSession(memory)
    memory.write(session.client_base + offsets.PLAYER_UNIT_PTR, u32(0x7000))

    assert oog.read_screen(session)[0] is oog.Screen.IN_GAME
