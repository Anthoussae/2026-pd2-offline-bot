"""The .key parser: both live framings, self-validation, the label pins."""

import struct

import pytest

from pd2bot.input.keyfile import (
    BELT,
    INVENTORY,
    SHOW_ITEMS,
    SKILL_HOTKEYS,
    KeyfileError,
    parse_keyfile,
)

UNBOUND = 0xFFFF


def framing_a(bindings, header=b"WS%\x00\x7a\x04\x00\x00"):
    """default.key's shape: 8-byte header; pad,index,primary,1,index,secondary,pad."""
    out = bytearray(header)
    for i, (primary, secondary) in enumerate(bindings):
        out += struct.pack("<HIHIIHH", 0, i, primary, 1, i, secondary, 0)
    return bytes(out)


def framing_b(bindings, header=b"%\x00\x00\x00\x00\x00"):
    """The character file's shape: 6 leading bytes, then
    primary,1,index,secondary + an 8-byte tail the parser ignores."""
    out = bytearray(header)
    for i, (primary, secondary) in enumerate(bindings):
        out += struct.pack("<HIIH8s", primary, 1, i, secondary, b"\x00" * 8)
    return bytes(out)


def live_shape():
    """The operator's real layout, as parsed live 2026-08-13: I/B
    inventory, F1..F8 skills, 1..4 belt, ALT at entry 37."""
    rows = [(UNBOUND, UNBOUND)] * 108
    rows[INVENTORY] = (0x49, 0x42)
    for slot, index in enumerate(SKILL_HOTKEYS):
        rows[index] = (0x70 + slot, UNBOUND)
    for column, index in enumerate(BELT):
        rows[index] = (0x31 + column, UNBOUND)
    rows[SHOW_ITEMS] = (0x12, UNBOUND)
    return rows


@pytest.mark.parametrize("framing", [framing_a, framing_b])
def test_both_live_framings_parse_to_the_same_bindings(framing):
    bindings = parse_keyfile(framing(live_shape()))
    assert len(bindings) == 108
    assert bindings[INVENTORY].primary == 0x49
    assert bindings[INVENTORY].secondary == 0x42
    assert [bindings[i].primary for i in SKILL_HOTKEYS] == list(range(0x70, 0x78))
    assert [bindings[i].primary for i in BELT] == [0x31, 0x32, 0x33, 0x34]
    assert bindings[SHOW_ITEMS].primary == 0x12


def test_unbound_slots_read_as_none_and_any_key_prefers_primary():
    bindings = parse_keyfile(framing_b(live_shape()))
    empty = next(b for b in bindings.values() if b.primary is None)
    assert empty.secondary is None and empty.any_key is None
    assert bindings[INVENTORY].any_key == 0x49  # primary wins over B


def test_a_secondary_backs_an_unbound_primary():
    rows = live_shape()
    rows[INVENTORY] = (UNBOUND, 0x42)
    bindings = parse_keyfile(framing_a(rows))
    assert bindings[INVENTORY].any_key == 0x42


def test_garbage_is_refused_not_mislabeled():
    """The format is undocumented; self-validation is the entire defense.
    A file that does not prove itself must raise, because a wrong parse
    would press wrong keys with full confidence."""
    with pytest.raises(KeyfileError):
        parse_keyfile(b"\x00" * 2164)
    with pytest.raises(KeyfileError):
        parse_keyfile(b"")


def test_a_corrupt_record_mid_file_refuses_the_whole_parse():
    data = bytearray(framing_b(live_shape()))
    # Stamp a wrong index into record 40 (6-byte header + 40 records in).
    struct.pack_into("<I", data, 6 + 40 * 20 + 6, 99)
    with pytest.raises(KeyfileError):
        parse_keyfile(bytes(data))
