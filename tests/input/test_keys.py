"""The keybinding registry: defaults pin, keyfile loading, loud refusals."""

import pytest

from pd2bot.input import keys
from pd2bot.input.keyfile import KeyfileError
from tests.input.test_keyfile import UNBOUND, framing_b, live_shape


def write_keyfile(tmp_path, rows):
    path = tmp_path / "Char.key"
    path.write_bytes(framing_b(rows))
    return path


def test_defaults_match_the_historical_hardcoded_assumptions():
    """'No keyfile' must mean 'exactly the old behavior', never drift."""
    d = keys.default_bindings()
    assert d.skill_keys[:6] == (0x70, 0x71, 0x72, 0x73, 0x74, 0x75)  # F1..F6
    assert d.belt == (0x31, 0x32, 0x33, 0x34)  # 1..4
    assert d.inventory == 0x49  # I
    assert d.show_items == 0x12  # ALT
    assert d.source == "defaults"


def test_the_live_layout_loads_end_to_end(tmp_path):
    b = keys.load_bindings(write_keyfile(tmp_path, live_shape()))
    assert b.skill_keys == tuple(range(0x70, 0x78))
    assert b.belt == (0x31, 0x32, 0x33, 0x34)
    assert b.inventory == 0x49
    assert b.show_items == 0x12
    assert b.source.startswith("keyfile:")
    assert b.notes == ()


def test_rebound_keys_are_read_not_assumed(tmp_path):
    """The whole point: a rebound client changes what the bot presses."""
    from pd2bot.input.keyfile import BELT, INVENTORY

    rows = live_shape()
    rows[INVENTORY] = (0x59, UNBOUND)  # Y
    for column, index in enumerate(BELT):
        rows[index] = (0x37 + column, UNBOUND)  # 7 8 9 0-ish
    b = keys.load_bindings(write_keyfile(tmp_path, rows))
    assert b.inventory == 0x59
    assert b.belt == (0x37, 0x38, 0x39, 0x3A)


def test_an_unbound_required_function_refuses_loudly(tmp_path):
    from pd2bot.input.keyfile import INVENTORY

    rows = live_shape()
    rows[INVENTORY] = (UNBOUND, UNBOUND)
    with pytest.raises(KeyfileError, match="inventory"):
        keys.load_bindings(write_keyfile(tmp_path, rows))


def test_unbound_show_items_falls_back_to_alt_with_a_note(tmp_path):
    """Show Items sits in the PD2-divergent region of the function list;
    a wrong refusal there would ground the bot over a label toggle."""
    from pd2bot.input.keyfile import SHOW_ITEMS

    rows = live_shape()
    rows[SHOW_ITEMS] = (UNBOUND, UNBOUND)
    b = keys.load_bindings(write_keyfile(tmp_path, rows))
    assert b.show_items == keys.VK_MENU
    assert b.notes and "Show Items" in b.notes[0]


def test_skill_slot_lookup_answers_the_toml_verification_question():
    b = keys.default_bindings()
    assert b.skill_slot_for(keys.VK_F5) == 5
    assert b.skill_slot_for(0x5A) is None  # Z drives no skill slot


def test_the_deduped_modules_share_the_registry_constants():
    # chat.py's local VK_ESCAPE turned out to be DEAD code the dedupe
    # removed outright — it only ever sends Enter; the others import
    # their constants from the registry now.
    from pd2bot.input import chat, gated, menu, window

    assert chat.VK_RETURN is keys.VK_RETURN
    assert not hasattr(chat, "VK_ESCAPE")
    assert menu.VK_ESCAPE is keys.VK_ESCAPE
    assert gated.VK_RETURN is keys.VK_RETURN
    assert window._VK_MENU is keys.VK_MENU


def test_key_names_read_like_the_options_screen():
    assert keys.key_name(0x70) == "F1"
    assert keys.key_name(0x49) == "I"
    assert keys.key_name(0x12) == "Alt"
    assert keys.key_name(None) == "unbound"
