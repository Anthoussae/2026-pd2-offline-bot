"""Tests for the assembled snapshot."""

import struct

from pd2bot import offsets
from pd2bot.snapshot import Perception
from tests.conftest import CLIENT_BASE, FakeSession, u32
from tests.test_player import UNIT, build as build_player_world
from tests.test_uistate import GET_UI_VAR_CODE, UI_ARRAY, ui_array_bytes


def build(in_game: bool = True, open_panels: set[int] | None = None) -> FakeSession:
    session = build_player_world(in_game=in_game)
    mem = session.memory
    mem.write(CLIENT_BASE + offsets.GET_UI_VAR_FN, GET_UI_VAR_CODE)
    mem.write(UI_ARRAY, ui_array_bytes(open_panels or set()))
    # The player's room chain exists (test_player builds it) but holds no units.
    mem.write_fields(
        0x0AF06000,  # ROOM1 from test_player
        {
            offsets.ROOM1_ROOM2: u32(0x0AF07000),
            offsets.ROOM1_UNIT_FIRST: u32(0),
            offsets.ROOM1_ROOMS_NEAR: u32(0),
            offsets.ROOM1_ROOMS_NEAR_COUNT: u32(0),
        },
    )
    return session


def test_snapshot_gathers_everything():
    snap = Perception(build()).snapshot()
    assert snap.in_game
    assert snap.player.name == "MaqiuDoubing"
    assert snap.area.level_no == 1
    assert snap.map_seed == 0x1A2B3C4D
    assert snap.ui is not None
    assert snap.taken_at > 0


def test_out_of_game_snapshot_is_empty_but_usable():
    """Callers should be able to read the world fields without checking first."""
    snap = Perception(build(in_game=False)).snapshot()
    assert not snap.in_game
    assert snap.player is None
    assert snap.monsters == ()
    assert snap.ground_items == ()
    assert not snap.can_act


def test_can_act_is_false_when_a_panel_is_open():
    assert Perception(build()).snapshot().can_act
    blocked = Perception(build(open_panels={offsets.UI_ESCMENU_MAIN})).snapshot()
    assert not blocked.can_act


def test_ui_array_is_resolved_once_not_per_snapshot():
    perception = Perception(build())
    first = perception._ui_array
    perception.snapshot()
    assert perception._ui_array == first == UI_ARRAY


def test_in_game_but_still_loading_does_not_crash():
    """Player unit exists, its pointers do not yet."""
    session = build()
    session.memory.write_fields(
        UNIT, {offsets.UNIT_PATH: u32(0), offsets.UNIT_DATA: u32(0), offsets.UNIT_ACT: u32(0)}
    )
    snap = Perception(session).snapshot()
    assert snap.in_game
    assert snap.player is None
    assert snap.area is None


def test_live_monsters_filters_corpses():
    from pd2bot.snapshot import GameSnapshot
    from pd2bot.units import Monster

    alive = Monster(1, 10, (0, 0), hp=10, max_hp=10, is_champion=False, is_boss=False,
                    is_minion=False)
    dead = Monster(2, 10, (0, 0), hp=0, max_hp=10, is_champion=False, is_boss=False,
                   is_minion=False)
    snap = GameSnapshot(in_game=True, taken_at=0.0, monsters=(alive, dead))
    assert snap.live_monsters == (alive,)


def test_fake_ui_array_encoding_matches_dword_entries():
    """Guard on the test helper itself: entries are DWORDs, not bytes."""
    data = ui_array_bytes({offsets.UI_INVENTORY})
    assert len(data) == 0x26 * 4
    assert struct.unpack_from("<I", data, offsets.UI_INVENTORY * 4)[0] == 1
