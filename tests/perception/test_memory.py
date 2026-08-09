"""Tests for the typed-read layer.

GameSession talks to a live process, so these exercise the read helpers through
a fake pymem backend rather than the real game.
"""

import struct

import pytest

import pd2bot.perception.memory
from pd2bot.perception.memory import GameSession, Module, Region


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


# -- the content scanner (T39's instrument) ---------------------------------
#
# The straddle case is the one that matters: a match sitting across a chunk
# boundary that the scan skipped would report "not in memory", and that is a
# conclusion about the GAME drawn from a bug in the INSTRUMENT — the exact
# false negative T39 was built to avoid.


class ScanSession(GameSession):
    """A GameSession whose address space is one flat buffer."""

    def __init__(self, data: bytes, origin: int = 0x10000) -> None:
        self._pm = FakePymem(data, origin)
        self.client_base = origin
        self._win_base = None
        self._region = Region(origin, len(data), 0x04)

    def regions(self):
        return [self._region]


@pytest.fixture
def small_chunks(monkeypatch):
    monkeypatch.setattr(pd2bot.perception.memory, "_CHUNK", 64)


def test_search_finds_a_match_inside_one_chunk(small_chunks):
    session = ScanSession(b"." * 20 + b"needle" + b"." * 200)
    assert session.search(b"needle") == [0x10000 + 20]


def test_search_finds_a_match_straddling_a_chunk_boundary(small_chunks):
    """The match starts at 62 and runs past the 64-byte chunk edge."""
    session = ScanSession(b"." * 62 + b"needle" + b"." * 200)
    assert session.search(b"needle") == [0x10000 + 62]


def test_search_reports_every_occurrence_once(small_chunks):
    data = b"." * 10 + b"mark" + b"." * 100 + b"mark" + b"." * 50
    session = ScanSession(data)
    assert session.search(b"mark") == [0x10000 + 10, 0x10000 + 114]


def test_search_honours_the_limit(small_chunks):
    session = ScanSession((b"mark" + b"." * 12) * 10)
    assert len(session.search(b"mark", limit=3)) == 3


def test_search_refuses_an_empty_needle():
    with pytest.raises(ValueError):
        ScanSession(b"...").search(b"")


def test_describe_names_an_address_inside_a_module():
    session = ScanSession(b"...")
    modules = [Module("D2Client.dll", 0x6FAB0000, 0x200000)]
    assert session.describe(0x6FAB1234, modules) == "D2Client.dll+0x1234"
    assert session.describe(0x00190000, modules) == "heap:0x190000"
