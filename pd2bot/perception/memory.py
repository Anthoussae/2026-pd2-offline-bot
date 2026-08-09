"""Attaching to the game client and reading its memory.

Everything above this layer works in terms of addresses and typed reads; only
this module knows about pymem and Windows.

A pointer that reads as 0 is normal and meaningful ("not in a game", "no such
unit"), never an error — those surface as None, not exceptions.
"""

from __future__ import annotations

import ctypes
import struct
from dataclasses import dataclass

import pymem
import pymem.exception
import pymem.process

PROCESS_NAME = "Game.exe"
CLIENT_MODULE = "d2client.dll"
WIN_MODULE = "d2win.dll"  # owns the out-of-game menu controls (M4)

# --- content scanning (the differential-scan instrument) --------------------
#
# Every address this bot reads was derived from a *citation* — a BH offset, or
# a function's own machine code (uistate.find_ui_array). That works while BH
# knows about the thing. It does not work for state BH never needed to export,
# and the in-game chat line is the first such case (M5P3 follow-up): BH runs
# in-process and simply never had to find the buffer, so there is no offset to
# cite and nothing to parse.
#
# The remaining move is the one uistate's docstring already names as the
# fallback — a differential scan — but by CONTENT rather than by code: put a
# known rare string into the game, find where it landed, then prove the
# address by watching a second string appear at the same place. That is a
# calibration instrument, not a runtime path: nothing in the bot may scan
# memory in a loop. It produces an address, which then gets a citation of its
# own (the drill that found it) and lives in offsets.py like everything else.

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
# Protections that permit a read. Anything else (NOACCESS, execute-only) is
# skipped rather than attempted: a failed ReadProcessMemory costs a syscall
# per region and tells us nothing.
_READABLE = frozenset({0x02, 0x04, 0x20, 0x40, 0x80})  # R, RW, XR, XRW, XWC

_CHUNK = 4 * 1024 * 1024


class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
    """Laid out for OUR bitness, not the target's.

    Python here is 64-bit and the D2 client is 32-bit, which is fine —
    VirtualQueryEx fills in the caller's struct — but it means the pointer
    fields must be `c_void_p`/`c_size_t` so ctypes inserts the 64-bit
    padding. Hardcoding DWORDs would silently misparse every region.
    """

    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


@dataclass(frozen=True)
class Region:
    """One committed, readable span of the target's address space."""

    base: int
    size: int
    protect: int

    @property
    def end(self) -> int:
        return self.base + self.size


@dataclass(frozen=True)
class Module:
    """A loaded module's runtime span, for naming a raw address."""

    name: str
    base: int
    size: int


class GameNotRunning(RuntimeError):
    """The PD2 client is not running."""


class NeedsAdministrator(RuntimeError):
    """The client is running but we are not allowed to read it."""


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # pragma: no cover - non-Windows or restricted host
        return False


class GameSession:
    """An attached, readable handle on the running game client.

    Construct once and pass it around; there is no global instance and no
    import-time side effect.
    """

    def __init__(self, process_name: str = PROCESS_NAME) -> None:
        try:
            self._pm = pymem.Pymem(process_name)
        except pymem.exception.ProcessNotFound as exc:
            raise GameNotRunning(
                f"{process_name} is not running — start Project Diablo 2 first."
            ) from exc
        except pymem.exception.CouldNotOpenProcess as exc:
            hint = (
                ""
                if _is_admin()
                else " Run this as Administrator: the PD2 client runs elevated."
            )
            raise NeedsAdministrator(
                f"Found {process_name} but could not open it for reading.{hint}"
            ) from exc

        self.client_base = self._module_base(CLIENT_MODULE)
        if self.client_base is None:
            raise RuntimeError(
                f"{CLIENT_MODULE} is not loaded in {process_name} — "
                "is this really the Diablo II client?"
            )
        # Resolved on first use (see win()): everything before M4 lives in
        # D2Client, and the fakes in tests never need to know D2Win exists.
        self._win_base: int | None = None

    # -- setup helpers ------------------------------------------------------

    def _module_base(self, name: str) -> int | None:
        """Runtime base address of a loaded module, matched case-insensitively.

        The client reports itself as 'D2CLIENT.dll'; do not match on case.
        """
        for module in pymem.process.enum_process_module(self._pm.process_handle):
            mod_name = module.name
            if isinstance(mod_name, bytes):
                mod_name = mod_name.decode(errors="replace")
            if mod_name.lower() == name.lower():
                return module.lpBaseOfDll
        return None

    @property
    def process_id(self) -> int:
        return self._pm.process_id

    def client(self, offset: int) -> int:
        """Absolute address of a D2Client.dll-relative offset."""
        return self.client_base + offset

    def win(self, offset: int) -> int:
        """Absolute address of a D2Win.dll-relative offset (menu controls)."""
        if self._win_base is None:
            base = self._module_base(WIN_MODULE)
            if base is None:
                raise RuntimeError(
                    f"{WIN_MODULE} is not loaded — cannot read menu controls."
                )
            self._win_base = base
        return self._win_base + offset

    # -- typed reads --------------------------------------------------------

    def u8(self, address: int) -> int:
        return self._pm.read_uchar(address)

    def u16(self, address: int) -> int:
        return self._pm.read_ushort(address)

    def u32(self, address: int) -> int:
        return self._pm.read_uint(address)

    def i32(self, address: int) -> int:
        return self._pm.read_int(address)

    def raw(self, address: int, size: int) -> bytes:
        return self._pm.read_bytes(address, size)

    def ptr(self, address: int) -> int | None:
        """Read a pointer. Null becomes None — an expected state, not a failure."""
        value = self._pm.read_uint(address)
        return value or None

    def cstring(self, address: int, max_length: int) -> str:
        raw = self._pm.read_bytes(address, max_length)
        return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    def wstring(self, address: int, max_chars: int) -> str:
        """A NUL-terminated wchar_t (UTF-16LE) string, e.g. menu button text."""
        raw = self._pm.read_bytes(address, max_chars * 2)
        text = raw.decode("utf-16-le", errors="replace")
        return text.split("\x00", 1)[0]

    def struct_at(self, address: int, fmt: str) -> tuple:
        """Unpack a little-endian struct in one read (cheaper than field-by-field)."""
        fmt = fmt if fmt.startswith("<") else "<" + fmt
        return struct.unpack(fmt, self._pm.read_bytes(address, struct.calcsize(fmt)))

    # -- scanning (calibration only — never in a runtime loop) --------------

    def modules(self) -> list[Module]:
        """Every loaded module with its runtime span."""
        found = []
        for module in pymem.process.enum_process_module(self._pm.process_handle):
            name = module.name
            if isinstance(name, bytes):
                name = name.decode(errors="replace")
            found.append(Module(name, module.lpBaseOfDll, module.SizeOfImage))
        return found

    def describe(self, address: int, modules: list[Module] | None = None) -> str:
        """Name an address: 'D2Client.dll+0x11BBFC' when it sits in a module.

        An address inside a module is a candidate for a durable offset — it
        is the same distance from the base on every launch. A heap address
        is not, and saying so plainly is the difference between a finding
        and a coincidence.
        """
        for module in modules if modules is not None else self.modules():
            if module.base <= address < module.base + module.size:
                return f"{module.name}+{address - module.base:#x}"
        return f"heap:{address:#x}"

    def regions(self) -> list[Region]:
        """Walk the target's committed, readable address space."""
        info = _MEMORY_BASIC_INFORMATION()
        size = ctypes.sizeof(info)
        found: list[Region] = []
        address = 0
        # A 32-bit target's user space stops at 4GB even when we are 64-bit.
        limit = 0x1_0000_0000
        while address < limit:
            if not ctypes.windll.kernel32.VirtualQueryEx(
                self._pm.process_handle,
                ctypes.c_void_p(address),
                ctypes.byref(info),
                size,
            ):
                break
            base, length = info.BaseAddress or 0, info.RegionSize
            if length == 0:
                break
            if (
                info.State == MEM_COMMIT
                and not info.Protect & PAGE_GUARD
                and info.Protect & 0xFF in _READABLE
            ):
                found.append(Region(base, length, info.Protect))
            address = base + length
        return found

    def search(self, needle: bytes, *, limit: int = 500) -> list[int]:
        """Every address holding `needle`, oldest region first.

        Read in overlapping chunks so a match straddling a chunk boundary is
        still found — the one bug that would make this instrument lie by
        omission, and the failure it would produce ("the text is not in
        memory") is exactly the conclusion we must not reach wrongly.
        """
        if not needle:
            raise ValueError("refusing to scan for an empty needle")
        overlap = len(needle) - 1
        hits: list[int] = []
        for region in self.regions():
            offset = 0
            while offset < region.size:
                span = min(_CHUNK, region.size - offset)
                try:
                    data = self._pm.read_bytes(region.base + offset, span)
                except Exception:
                    break  # region changed under us; the next one is fine
                start = 0
                while True:
                    index = data.find(needle, start)
                    if index == -1:
                        break
                    hits.append(region.base + offset + index)
                    if len(hits) >= limit:
                        return hits
                    start = index + 1
                if span < _CHUNK:
                    break
                offset += _CHUNK - overlap
        return hits
