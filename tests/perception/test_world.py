"""world.read_difficulty: parsing GetDifficulty's code for the byte it reads."""

from __future__ import annotations

import pytest
from conftest import CLIENT_BASE, FakeMemory, FakeSession, u32

from pd2bot import offsets
from pd2bot.perception import world

_FN = CLIENT_BASE + offsets.GET_DIFFICULTY_FN
_VAR = CLIENT_BASE + 0xF1234  # anywhere inside the module image


def in_game(memory: FakeMemory) -> None:
    memory.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(0x7000))


def pad(code: bytes) -> bytes:
    return code + b"\xcc" * (24 - len(code))


def test_reads_difficulty_via_short_mov_al():
    memory = FakeMemory()
    in_game(memory)
    memory.write(_FN, pad(b"\xa0" + _VAR.to_bytes(4, "little") + b"\xc3"))
    memory.write(_VAR, bytes([offsets.DIFFICULTY_HELL]))
    session = FakeSession(memory)

    assert world.read_difficulty(session) == offsets.DIFFICULTY_HELL


def test_reads_difficulty_via_movzx():
    memory = FakeMemory()
    in_game(memory)
    memory.write(_FN, pad(b"\x0f\xb6\x05" + _VAR.to_bytes(4, "little") + b"\xc3"))
    memory.write(_VAR, bytes([offsets.DIFFICULTY_NORMAL]))
    session = FakeSession(memory)

    assert world.read_difficulty(session) == offsets.DIFFICULTY_NORMAL


def test_none_when_not_in_a_game():
    memory = FakeMemory()
    memory.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(0))
    session = FakeSession(memory)

    assert world.read_difficulty(session) is None


def test_refuses_unrecognized_code():
    memory = FakeMemory()
    in_game(memory)
    memory.write(_FN, pad(b"\x55\x8b\xec\x90\x90\xc3"))  # no byte-load pattern
    session = FakeSession(memory)

    with pytest.raises(world.DifficultyNotFound):
        world.read_difficulty(session)


def test_refuses_address_outside_the_module():
    memory = FakeMemory()
    in_game(memory)
    outside = 0x00401000  # not within D2Client's image
    memory.write(_FN, pad(b"\xa0" + outside.to_bytes(4, "little") + b"\xc3"))
    session = FakeSession(memory)

    with pytest.raises(world.DifficultyNotFound):
        world.read_difficulty(session)
