"""Parse Diablo II's per-character keybinding file (`<char>.key`).

The client stores the player's ACTUAL bindings — the thing the bot has
always assumed instead of read — in a small binary file per character:
`<D2 root>\\Save\\ProjectD2\\<CharName>.key` for PD2, written whenever
the player rebinds. Reading it is what lets the bot stop hardcoding
"(default binding)" assumptions (R247; the operator's fact-finding on
2026-08-13 cracked the format live).

The format, pinned empirically against the operator's install (there is
no official documentation — the mitigation is that records are
SELF-VALIDATING and the parser refuses rather than guesses):

- A small variable header (4 bytes on the character file, 8 on
  `default.key` — two framings observed live), then **108 records of
  20 bytes**, one per bindable game function, in the game's fixed
  function order.
- Each record embeds its own function index, which is what makes the
  scan honest: the parser tries candidate alignments and accepts the
  one where the indices count 0, 1, 2, … — anything else is refused.
- Key codes are plain Win32 VKs; `0xFFFF` means unbound; each record
  carries a primary and a secondary key slot (vanilla's I/B inventory
  pair is the visible example).

Function labels: pinned from `default.key` (whose values are the game's
documented defaults) and cross-checked against the operator's live
bindings (skills on F1–F6 = entries 14–19, matching the R47.1 capture;
belt '1'–'4' = entries 23–26; inventory I/B = entry 1).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

RECORD_SIZE = 20
# How many leading records must validate (index == position) before an
# alignment is believed. High enough that no accidental byte pattern
# passes; low enough that a short/truncated file is still refused by the
# full-count check below, not by the anchor.
ANCHOR_RUN = 16
UNBOUND = 0xFFFF

# -- the function indices the bot cares about ---------------------------------
#
# Entry order is the game's own bindable-function list. Labels verified
# 2026-08-13 against default.key (vanilla defaults) and the operator's
# live file:
#   entry 1  defaults I/B          -> inventory
#   entry 7  defaults TAB          -> automap
#   entries 14..21 default F1..F8  -> skill hotkeys 1..8 (PD2 adds
#                                     QWER-row secondaries)
#   entries 23..26 default 1..4    -> belt 1..4
CHARACTER = 0
INVENTORY = 1
AUTOMAP = 7
SKILL_HOTKEYS = tuple(range(14, 22))  # slots 1..8
BELT = tuple(range(23, 27))  # columns 0..3
# Show Items (the ALT label toggle the pickup protocol depends on, T63).
# Pinned 2026-08-13 by scanning for VK 0x12: the PD2 character file
# carries it at entry 37; the vanilla-era default.key in the same
# install carries it at entry 63 — PD2's bindable-function list
# DIVERGES from vanilla's somewhere past the belt entries, so indices
# above ~26 must only ever be trusted against a PD2-written file. The
# consumer (keys.load_bindings) falls back to ALT with a notice when
# this entry reads unbound, because a wrong label toggle would starve
# pickup silently.
SHOW_ITEMS = 37


class KeyfileError(RuntimeError):
    """The file did not parse as a keybinding file; details inside."""


@dataclass(frozen=True)
class Binding:
    """One bindable function's keys. None = that slot is unbound."""

    index: int
    primary: int | None
    secondary: int | None

    @property
    def any_key(self) -> int | None:
        """The key a press should use: primary, else secondary."""
        return self.primary if self.primary is not None else self.secondary


def _key(raw: int) -> int | None:
    return None if raw == UNBOUND else raw


# The two record layouts observed live (both 20 bytes; little-endian):
#   A — default.key framing:   pad, index, primary, one, index2, secondary, pad
#   B — character-file framing: primary, one, index, secondary, then 8
#       trailing bytes the parser does not interpret.
# A record validates when its embedded index equals its position (and,
# for A, both copies agree). The FRAMING validates when a long run of
# records validates from a candidate start offset — self-validation is
# the whole defense for an undocumented format.
_LAYOUT_A = struct.Struct("<HIHIIHH")
_LAYOUT_B = struct.Struct("<HIIH8s")


def _parse_at(data: bytes, start: int, layout: str) -> list[Binding] | None:
    """Every record from `start` under `layout`, or None if any refuses."""
    out: list[Binding] = []
    position = 0
    offset = start
    while offset + RECORD_SIZE <= len(data):
        chunk = data[offset : offset + RECORD_SIZE]
        if layout == "A":
            _, index, primary, one, index2, secondary, _ = _LAYOUT_A.unpack(chunk)
            if index != position or index2 != position or one != 1:
                return None
        else:
            primary, one, index, secondary, _ = _LAYOUT_B.unpack(chunk)
            if index != position or one != 1:
                return None
        out.append(
            Binding(index=position, primary=_key(primary), secondary=_key(secondary))
        )
        position += 1
        offset += RECORD_SIZE
    return out if out else None


def parse_keyfile(data: bytes) -> dict[int, Binding]:
    """Parse the file body, whatever its header framing.

    Tries every plausible start offset and both layouts; accepts the
    first combination whose records self-validate all the way down.
    Raises `KeyfileError` when nothing does — a keybinding source that
    cannot prove itself must refuse, because every consumer of a wrong
    parse would press wrong keys with full confidence.
    """
    for start in range(0, min(RECORD_SIZE, len(data)) + 1):
        for layout in ("A", "B"):
            records = _parse_at(data, start, layout)
            if records is not None and len(records) >= ANCHOR_RUN:
                return {b.index: b for b in records}
    raise KeyfileError(
        f"no self-validating record alignment found in {len(data)} bytes — "
        "not a keybinding file, or a format this parser has not seen "
        "(see pd2bot/input/keyfile.py for the pinned format)"
    )


def read_keyfile(path: str | Path) -> dict[int, Binding]:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise KeyfileError(f"could not read {path}: {exc}") from exc
    try:
        return parse_keyfile(data)
    except KeyfileError as exc:
        raise KeyfileError(f"{path}: {exc}") from exc
