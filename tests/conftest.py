"""Shared test helpers: a fake game process built out of plain bytes.

The real GameSession reads a live process, so tests build a sparse address ->
bytes map and read through the same typed helpers. This lets the traversal and
decoding logic be tested exactly as it runs, without a running game.
"""

from __future__ import annotations

import struct

from pd2bot.perception.memory import GameSession

CLIENT_BASE = 0x6FAB0000
WIN_BASE = 0x6F8E0000


class FakeMemory:
    """A sparse, writable address space."""

    def __init__(self) -> None:
        self.regions: dict[int, bytearray] = {}

    def write(self, address: int, data: bytes) -> int:
        self.regions[address] = bytearray(data)
        return address

    def write_fields(self, address: int, fields: dict[int, bytes]) -> int:
        """Write {offset: bytes} into one allocation starting at `address`."""
        size = max(off + len(val) for off, val in fields.items())
        buffer = bytearray(size)
        for offset, value in fields.items():
            buffer[offset : offset + len(value)] = value
        self.regions[address] = buffer
        return address

    def read(self, address: int, size: int) -> bytes:
        for start, data in self.regions.items():
            if start <= address and address + size <= start + len(data):
                begin = address - start
                return bytes(data[begin : begin + size])
        raise ValueError(f"unmapped read of {size} bytes at 0x{address:X}")


class FakeSession(GameSession):
    """A GameSession backed by FakeMemory instead of a real process."""

    def __init__(
        self,
        memory: FakeMemory,
        client_base: int = CLIENT_BASE,
        win_base: int = WIN_BASE,
    ) -> None:
        self.memory = memory
        self.client_base = client_base
        self._win_base = win_base

    def raw(self, address: int, size: int) -> bytes:
        return self.memory.read(address, size)

    def u8(self, address: int) -> int:
        return self.raw(address, 1)[0]

    def u16(self, address: int) -> int:
        return struct.unpack("<H", self.raw(address, 2))[0]

    def u32(self, address: int) -> int:
        return struct.unpack("<I", self.raw(address, 4))[0]

    def i32(self, address: int) -> int:
        return struct.unpack("<i", self.raw(address, 4))[0]

    def ptr(self, address: int) -> int | None:
        return self.u32(address) or None

    def cstring(self, address: int, max_length: int) -> str:
        return self.raw(address, max_length).split(b"\x00", 1)[0].decode("ascii", "replace")

    def wstring(self, address: int, max_chars: int) -> str:
        text = self.raw(address, max_chars * 2).decode("utf-16-le", "replace")
        return text.split("\x00", 1)[0]


def wchars(text: str, total_chars: int) -> bytes:
    """Encode a wchar_t[total_chars] buffer holding `text` NUL-terminated."""
    return (text + "\x00" * (total_chars - len(text))).encode("utf-16-le")


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def u16(value: int) -> bytes:
    return struct.pack("<H", value)


def stat_array(stats: dict[int, int]) -> bytes:
    """Encode Stat{wSubIndex, wStatIndex, dwStatValue} entries."""
    return b"".join(struct.pack("<HHI", 0, index, value) for index, value in stats.items())
