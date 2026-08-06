"""Level exits: where the current area connects to its neighbours.

Room2 is the STATIC room layer — once a level is initialized it spans the
whole area whether or not the runtime rooms (Room1) around the player are
loaded, so exits are enumerable area-wide from anywhere inside the level.
The algorithm is d2mapapi's own (mapdata.cpp:217-232 — the offline
generator this project already vendors, so the arithmetic is a proven
lineage, not an invention):

    a PresetUnit of type TILE in a Room2 names a warp (dwTxtFileNo);
    the RoomTile whose *nNum equals that number names the DESTINATION
    level (tile -> pRoom2 -> pLevel -> dwLevelNo);
    the exit's world position = room2 tile origin * 5 + preset offset.

These are the single-click staircase/doorway transitions — the Countess
route's only kind (R212 Q3: Black Marsh -> Forgotten Tower and every
cellar-to-cellar connection is one of these). Walkable border seams
between outdoor areas (Cold Plains <-> Stony Field) are a different
mechanism — edge adjacency, not warps — and are deliberately not read
here; nothing on the M6 route needs them.

Defensive-traversal rules as everywhere (the unit-hash-table posture):
bounded walks, cycle guards, unreadable structures skipped and counted
rather than raised — the chains mutate only at level init, but a read
during a transition can still tear.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pd2bot import offsets
from pd2bot.memory import GameSession
from pd2bot.units import player_unit
from pd2bot.world import SUBTILES_PER_TILE

# A level's static room chain is at most a few hundred rooms (the largest
# surveyed area, Cold Plains, has ~114); the caps exist so a torn pointer
# cannot walk forever, not to bound real data.
_MAX_ROOMS = 2048
_MAX_TILES_PER_ROOM = 64
_MAX_PRESETS_PER_ROOM = 512


@dataclass(frozen=True)
class LevelExit:
    """One warp out of the current area: stand here, click, change area."""

    position: tuple[int, int]  # world subtiles — comparable to unit positions
    dest_area: int  # the destination's dwLevelNo

    @property
    def dest_name(self) -> str:
        return offsets.AREA_NAMES.get(self.dest_area, f"area {self.dest_area}")


@dataclass(frozen=True)
class ExitScan:
    """What one enumeration saw — exits plus honesty counters.

    `skipped` counts unreadable rooms/chains; occasional nonzero during an
    area transition is normal, a large count means the read raced a load
    and the caller should re-scan.
    """

    exits: tuple[LevelExit, ...]
    area: int  # the level the scan ran in
    rooms_walked: int = 0
    skipped: int = 0

    def toward(self, dest_area: int) -> tuple[LevelExit, ...]:
        """The exits leading to `dest_area` (usually one; stairs can pair)."""
        return tuple(e for e in self.exits if e.dest_area == dest_area)


def _room_exits(
    session: GameSession, room2: int
) -> tuple[list[LevelExit], int]:
    """One Room2's warp exits, plus a skipped count for its chains."""
    skipped = 0
    # The warp connections: warp number -> destination level id.
    warp_dest: dict[int, int] = {}
    tile = session.ptr(room2 + offsets.ROOM2_ROOM_TILES)
    seen_tiles = 0
    while tile is not None and seen_tiles < _MAX_TILES_PER_ROOM:
        seen_tiles += 1
        try:
            dest_room2 = session.ptr(tile + offsets.ROOMTILE_ROOM2)
            num_ptr = session.ptr(tile + offsets.ROOMTILE_NUM_PTR)
            if dest_room2 is not None and num_ptr is not None:
                dest_level = session.ptr(dest_room2 + offsets.ROOM2_LEVEL)
                if dest_level is not None:
                    warp_dest[session.u32(num_ptr)] = session.u32(
                        dest_level + offsets.LEVEL_NO
                    )
        except Exception:  # noqa: BLE001 - torn chain: skip, count, carry on
            skipped += 1
        tile = session.ptr(tile + offsets.ROOMTILE_NEXT)
    if not warp_dest:
        return [], skipped

    # The warp POSITIONS: TILE presets whose dwTxtFileNo matches a warp.
    found: list[LevelExit] = []
    origin_x = session.u32(room2 + offsets.ROOM2_POS_X) * SUBTILES_PER_TILE
    origin_y = session.u32(room2 + offsets.ROOM2_POS_Y) * SUBTILES_PER_TILE
    preset = session.ptr(room2 + offsets.ROOM2_PRESET)
    seen_presets = 0
    while preset is not None and seen_presets < _MAX_PRESETS_PER_ROOM:
        seen_presets += 1
        try:
            if session.u32(preset + offsets.PRESET_TYPE) == offsets.PRESET_TYPE_TILE:
                dest = warp_dest.get(
                    session.u32(preset + offsets.PRESET_TXT_FILE_NO)
                )
                if dest is not None:
                    found.append(
                        LevelExit(
                            position=(
                                origin_x
                                + session.u32(preset + offsets.PRESET_POS_X),
                                origin_y
                                + session.u32(preset + offsets.PRESET_POS_Y),
                            ),
                            dest_area=dest,
                        )
                    )
        except Exception:  # noqa: BLE001
            skipped += 1
        preset = session.ptr(preset + offsets.PRESET_NEXT)
    return found, skipped


def read_level_exits(session: GameSession) -> ExitScan | None:
    """Every warp exit of the player's current area, or None mid-load.

    Walks the level's static Room2 chain (LEVEL_ROOM2_FIRST -> ROOM2_NEXT)
    with a cycle guard, collecting each room's warp exits. Duplicates
    (the same warp reported via more than one room) are collapsed by
    (position, destination).
    """
    unit = player_unit(session)
    if unit is None:
        return None
    path = session.ptr(unit + offsets.UNIT_PATH)
    if path is None:
        return None
    room1 = session.ptr(path + offsets.PATH_ROOM1)
    if room1 is None:
        return None
    room2 = session.ptr(room1 + offsets.ROOM1_ROOM2)
    if room2 is None:
        return None
    level = session.ptr(room2 + offsets.ROOM2_LEVEL)
    if level is None:
        return None

    area = session.u32(level + offsets.LEVEL_NO)
    exits: dict[tuple[tuple[int, int], int], LevelExit] = {}
    rooms_walked = 0
    skipped = 0
    seen: set[int] = set()
    node = session.ptr(level + offsets.LEVEL_ROOM2_FIRST)
    while node is not None and rooms_walked < _MAX_ROOMS:
        if node in seen:
            break  # cycle: the chain is torn, stop rather than spin
        seen.add(node)
        rooms_walked += 1
        try:
            found, room_skipped = _room_exits(session, node)
            skipped += room_skipped
            for one in found:
                exits[(one.position, one.dest_area)] = one
        except Exception:  # noqa: BLE001 - an unreadable room is skipped whole
            skipped += 1
        node = session.ptr(node + offsets.ROOM2_NEXT)

    return ExitScan(
        exits=tuple(
            sorted(exits.values(), key=lambda e: (e.dest_area, e.position))
        ),
        area=area,
        rooms_walked=rooms_walked,
        skipped=skipped,
    )


class ExitMemory:
    """Remembered exit positions, persisted like the atlas (M6 P2).

    The live read (`read_level_exits`) is the authority — it works with
    no memory at all. What this buys is the FIRST leg of a traversal in
    an area whose exit was already discovered on an earlier run: the
    step can start walking toward the remembered position immediately,
    before deciding anything else, instead of standing still while a
    mid-load read sorts itself out. Keyed by (seed, difficulty, area,
    dest) — the atlas's own staleness guard: a re-rolled map changes the
    seed and simply misses.

    One JSON file for all seeds (`maps/exits.json` by default): exits
    are a handful of coordinates per area, not room grids, and one file
    keeps the save-data footprint obvious. Corrupt or unreadable files
    load as empty rather than raising — this is a cache of rediscoverable
    facts, never the truth.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._known: dict[str, tuple[int, int]] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._known = {
                key: (int(value[0]), int(value[1]))
                for key, value in raw.items()
                if isinstance(value, (list, tuple)) and len(value) == 2
            }
        except (OSError, ValueError):
            self._known = {}

    @staticmethod
    def _key(seed: int, difficulty: int, area: int, dest: int) -> str:
        return f"{seed:08x}-d{difficulty}-a{area}-to-{dest}"

    def recall(
        self, seed: int, difficulty: int, area: int, dest: int
    ) -> tuple[int, int] | None:
        return self._known.get(self._key(seed, difficulty, area, dest))

    def remember(
        self,
        seed: int,
        difficulty: int,
        area: int,
        dest: int,
        position: tuple[int, int],
    ) -> None:
        key = self._key(seed, difficulty, area, dest)
        if self._known.get(key) == tuple(position):
            return  # nothing new: no rewrite churn
        self._known[key] = (int(position[0]), int(position[1]))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._known, indent=1, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            pass  # a cache that cannot save is still a working cache
