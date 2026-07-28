"""Tests for the typed-read layer.

GameSession talks to a live process, so these exercise the read helpers through
a fake pymem backend rather than the real game.
"""

import struct

import pytest

from pd2bot.memory import GameSession


class FakePymem:
    """Minimal stand-in for pymem.Pymem backed by a bytes buffer at `origin`."""

    def __init__(self, data: bytes, origin: int = 0x1000):
        self.data = data
        self.origin = origin
        self.process_id = 4242
        self.process_handle = 1

    def _slice(self, address: int, size: int) -> bytes:
        start = address - self.origin
        if start < 0 or start + size > len(self.data):
            raise ValueError(f"read out of range at 0x{address:X}")
        return self.data[start : start + size]

    def read_bytes(self, address, size):
        return self._slice(address, size)

    def read_uchar(self, address):
        return self._slice(address, 1)[0]

    def read_ushort(self, address):
        return struct.unpack("<H", self._slice(address, 2))[0]

    def read_uint(self, address):
        return struct.unpack("<I", self._slice(address, 4))[0]

    def read_int(self, address):
        return struct.unpack("<i", self._slice(address, 4))[0]


@pytest.fixture
def session():
    payload = (
        struct.pack("<I", 0xDEADBEEF)  # +0x00 u32
        + struct.pack("<I", 0)  # +0x04 null pointer
        + struct.pack("<I", 0x7FFFF000)  # +0x08 non-null pointer
        + b"Hero\x00\x00\x00\x00"  # +0x0C cstring padded
        + struct.pack("<HH", 1234, 5678)  # +0x14 two u16
        + struct.pack("<i", -7)  # +0x18 i32
    )
    sess = GameSession.__new__(GameSession)  # bypass attaching to a real process
    sess._pm = FakePymem(payload)
    sess.client_base = 0x6FAB0000
    return sess


def test_client_offset_resolves_against_module_base(session):
    assert session.client(0x11BBFC) == 0x6FAB0000 + 0x11BBFC


def test_typed_reads(session):
    assert session.u32(0x1000) == 0xDEADBEEF
    assert session.u16(0x1014) == 1234
    assert session.u16(0x1016) == 5678
    assert session.i32(0x1018) == -7
    assert session.u8(0x1000) == 0xEF


def test_null_pointer_reads_as_none_not_zero(session):
    """Null is an expected state (not in a game, no such unit), not an error."""
    assert session.ptr(0x1004) is None
    assert session.ptr(0x1008) == 0x7FFFF000


def test_cstring_stops_at_terminator(session):
    assert session.cstring(0x100C, 8) == "Hero"


def test_struct_at_unpacks_little_endian(session):
    assert session.struct_at(0x1014, "HH") == (1234, 5678)
    assert session.struct_at(0x1014, "<HH") == (1234, 5678)
