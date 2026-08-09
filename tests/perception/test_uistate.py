"""Tests for UI-state discovery and decoding.

The instruction bytes below were captured from the live PD2 client on
2026-07-28 (D2Client.dll base 0x6FAB0000, Season 13). Keeping them as a fixture
means the parser is testable without a running game.
"""

import struct

import pytest

from pd2bot import offsets
from pd2bot.perception.memory import GameSession
from pd2bot.perception.uistate import (
    UIArrayNotFound,
    UIState,
    can_act,
    find_ui_array,
    is_in_game,
    read_ui_state,
)

CLIENT_BASE = 0x6FAB0000
UI_ARRAY = 0x6FBAAD80  # what the parser should recover: D2Client + 0xFAD80

# Real bytes at D2Client!GetUiVar_I, captured live — the full window the parser
# scans, including the padding and the start of the next function, so the test
# exercises the same read size as production.
#   cmp eax,0x26 / jb +0x24 / <assert path> / mov eax,[eax*4+0x6FBAAD80] / ret
GET_UI_VAR_CODE = bytes.fromhex(
    "83F826721F68380C0000E883DBF4FF50"
    "689F35B86FE866DBF4FF83C40C6AFFE8"
    "4052F4FF8B048580ADBA6FC3CCCCCCCC"
    "B980C9BC6FFF15B0EAB76F85C0747D56"
    "57B980C9BC6FE80FEFF4FF8BF083C608"
    "E835EFF4FF8B1520CABC6F8BCED1F983"
)


class FakeSession(GameSession):
    """A GameSession whose reads come from a dict of {address: bytes}."""

    def __init__(self, regions: dict[int, bytes], client_base: int = CLIENT_BASE):
        self.regions = regions
        self.client_base = client_base

    def raw(self, address: int, size: int) -> bytes:
        for start, data in self.regions.items():
            if start <= address and address + size <= start + len(data):
                begin = address - start
                return data[begin : begin + size]
        raise ValueError(f"unmapped read at 0x{address:X}")

    def ptr(self, address: int):
        value = int.from_bytes(self.raw(address, 4), "little")
        return value or None


def ui_array_bytes(open_panels: set[int]) -> bytes:
    return b"".join(
        struct.pack("<I", 1 if i in open_panels else 0) for i in range(0x26)
    )


@pytest.fixture
def session():
    return FakeSession(
        {
            CLIENT_BASE + offsets.GET_UI_VAR_FN: GET_UI_VAR_CODE,
            UI_ARRAY: ui_array_bytes(set()),
            CLIENT_BASE + offsets.PLAYER_UNIT_PTR: struct.pack("<I", 0x0AF00000),
        }
    )


def test_finds_the_ui_array_in_real_client_code(session):
    assert find_ui_array(session) == UI_ARRAY


def test_found_array_agrees_with_bh_automap_variable(session):
    """Cross-check: BH documents AutomapOn (0xFADA8) separately from the array.

    It must be the array's UI_AUTOMAP slot; if it isn't, we found the wrong thing.
    """
    relative = find_ui_array(session) - CLIENT_BASE
    assert relative + offsets.UI_AUTOMAP * 4 == 0xFADA8


def test_rejects_an_address_outside_the_module(session):
    """A plausible-looking load to somewhere else must not be accepted."""
    bogus = (b"\x8b\x04\x85" + struct.pack("<I", 0x11110000) + b"\xc3").ljust(96, b"\xcc")
    broken = FakeSession({CLIENT_BASE + offsets.GET_UI_VAR_FN: bogus})
    with pytest.raises(UIArrayNotFound):
        find_ui_array(broken)


def test_rejects_an_in_module_address_that_fails_the_automap_identity(session):
    """In range but at the wrong place: the automap cross-check must reject it."""
    wrong = (b"\x8b\x04\x85" + struct.pack("<I", CLIENT_BASE + 0x50000) + b"\xc3").ljust(
        96, b"\xcc"
    )
    broken = FakeSession({CLIENT_BASE + offsets.GET_UI_VAR_FN: wrong})
    with pytest.raises(UIArrayNotFound):
        find_ui_array(broken)


def test_raises_when_the_instruction_is_absent(session):
    nothing = FakeSession({CLIENT_BASE + offsets.GET_UI_VAR_FN: b"\x90" * 96})
    with pytest.raises(UIArrayNotFound):
        find_ui_array(nothing)


def test_reads_open_panels(session):
    session.regions[UI_ARRAY] = ui_array_bytes({offsets.UI_INVENTORY, offsets.UI_AUTOMAP})
    state = read_ui_state(session, UI_ARRAY)
    assert state.is_open(offsets.UI_INVENTORY)
    assert state.is_open(offsets.UI_AUTOMAP)
    assert not state.is_open(offsets.UI_ESCMENU_MAIN)
    assert state.names == ["automap", "inventory"]


def test_esc_menu_blocks_input():
    """The exact M1 incident: a click with the ESC menu open hit Save and Exit."""
    assert UIState(frozenset({offsets.UI_ESCMENU_MAIN})).blocks_input


def test_automap_does_not_block_input():
    """The automap overlays the world; clicks still reach the game."""
    assert not UIState(frozenset({offsets.UI_AUTOMAP})).blocks_input


def test_nothing_open_does_not_block_input():
    assert not UIState(frozenset()).blocks_input


def test_is_in_game_follows_the_player_unit(session):
    assert is_in_game(session)
    session.regions[CLIENT_BASE + offsets.PLAYER_UNIT_PTR] = struct.pack("<I", 0)
    assert not is_in_game(session)


def test_can_act_requires_both_in_game_and_no_blocking_panel(session):
    assert can_act(session, UI_ARRAY)

    session.regions[UI_ARRAY] = ui_array_bytes({offsets.UI_ESCMENU_MAIN})
    assert not can_act(session, UI_ARRAY)

    session.regions[UI_ARRAY] = ui_array_bytes(set())
    session.regions[CLIENT_BASE + offsets.PLAYER_UNIT_PTR] = struct.pack("<I", 0)
    assert not can_act(session, UI_ARRAY)


def test_stash_and_waypoint_panels_block_input():
    """P2's live calibration: the stash raises ONLY its own slot (inventory
    stays 0), and the waypoint slot is a real display flag after all — both
    swallow clicks over most of the screen, so both must block. Without
    this, can_act() said YES with the stash open (the M1 shape, one panel
    over)."""
    assert UIState(frozenset({offsets.UI_STASH})).blocks_input
    assert UIState(frozenset({offsets.UI_WPMENU})).blocks_input


def test_waypoint_slot_is_reported_again(session):
    """0x14 left the always-on filter after the controlled toggle drill —
    read_ui_state must report it like any other panel."""
    session.regions[UI_ARRAY] = ui_array_bytes({offsets.UI_WPMENU})
    state = read_ui_state(session, UI_ARRAY)
    assert state.is_open(offsets.UI_WPMENU)
    assert state.names == ["waypoint_menu"]
