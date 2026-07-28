"""Attaching to the game client and reading its memory.

Everything above this layer works in terms of addresses and typed reads; only
this module knows about pymem and Windows.

A pointer that reads as 0 is normal and meaningful ("not in a game", "no such
unit"), never an error — those surface as None, not exceptions.
"""

from __future__ import annotations

import ctypes
import struct

import pymem
import pymem.exception
import pymem.process

PROCESS_NAME = "Game.exe"
CLIENT_MODULE = "d2client.dll"


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

    def struct_at(self, address: int, fmt: str) -> tuple:
        """Unpack a little-endian struct in one read (cheaper than field-by-field)."""
        fmt = fmt if fmt.startswith("<") else "<" + fmt
        return struct.unpack(fmt, self._pm.read_bytes(address, struct.calcsize(fmt)))
