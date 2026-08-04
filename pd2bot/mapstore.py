"""The bot's atlas: every room grid it has ever seen, saved and reusable.

Why this works: in single player, Diablo II fixes the map layout per
character per difficulty — it only re-rolls when the difficulty changes
(user decision 2026-07-28, M3 P3 gate). Since this bot only runs Hell on
one character, every game sees the identical map. So instead of generating
maps offline (attempted; blocked — see the map-knowledge ADR), the bot
*remembers*: each time perception reads the collision grids around the
player (collision.py), they are merged into a per-area file. Knowledge
only grows, and one survey walk through an area gives route planning the
whole picture forever.

The file key is (map seed, difficulty, area), and the seed is the safety:
if the layout ever does change, the new seed misses the cache and the bot
starts honestly blank instead of trusting a stale map.

Only *terrain* is stored. Collision words also carry live occupancy
(monsters, players, items, corpses), which is real for a live read and
noise for a permanent map — see `record()`.

Caveat, documented rather than hidden: difficulty is not yet readable from
memory (an M4 task), so callers state it — the CLI default is Hell. Files
live under `maps/` (gitignored: it is save-data derived from *this*
machine's game, regenerable by walking).
"""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

from pd2bot.collision import LocalCollision, RoomCollision, strip_transient

FORMAT_VERSION = 1
DEFAULT_ROOT = Path("maps")

RoomKey = tuple[int, int, int, int]  # origin x, origin y, width, height


class ExploredArea:
    """One area's remembered rooms. Implements the Grid protocol.

    Mutating and saving go through `record()`; everything else is a read.
    """

    def __init__(
        self, path: Path, seed: int, difficulty: int, area_id: int,
        rooms: dict[RoomKey, RoomCollision] | None = None,
    ) -> None:
        self.path = path
        self.seed = seed
        self.difficulty = difficulty
        self.area_id = area_id
        self._rooms: dict[RoomKey, RoomCollision] = dict(rooms or {})
        self._view = LocalCollision(list(self._rooms.values()))
        # Monotonic content revision (M6 P3, session-review issue 003):
        # bumped by every record() that changed anything — including a
        # re-recorded room whose terrain changed but whose COUNT did not,
        # which is exactly the update a room_count cache key misses.
        self.revision = 0

    # -- Grid protocol --------------------------------------------------------

    def is_walkable(self, x: int, y: int) -> bool:
        return self._view.is_walkable(x, y)

    def is_known(self, x: int, y: int) -> bool:
        return self._view.is_known(x, y)

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        return self._view.bounds

    @property
    def room_count(self) -> int:
        return len(self._rooms)

    @property
    def rooms(self) -> tuple[RoomCollision, ...]:
        """The stored rooms, read-only. Insertion-ordered (dict order), so
        consumers that derive stable lists from them — the survey's
        frontier clustering — get the same answer for the same atlas."""
        return tuple(self._rooms.values())

    # -- growing the atlas ------------------------------------------------------

    def record(self, local: LocalCollision, stats: dict | None = None) -> int:
        """As `_record`, optionally filling `stats` with a breakdown.

        `stats` accumulates `added` / `updated` counts and, under `bits`, a
        histogram of which collision bits actually differed on an update —
        the tool for answering "why is this room being rewritten?" with data
        instead of guesses.
        """
        return self._record(local, stats)

    def _record(self, local: LocalCollision, stats: dict | None = None) -> int:
        """Merge freshly read room grids; save if the terrain changed.

        Occupancy bits are stripped first (`strip_transient`): a monster
        walking past is not new knowledge about the map, and storing it
        would both thrash the file and — via IS_ON_FLOOR, which counts as
        unwalkable — bake a passing corpse into the atlas as a wall.

        Rooms are keyed by (origin, size); a re-seen room replaces its old
        grid. Returns how many rooms were added or genuinely updated.
        """
        changed = 0
        for room in local.rooms:
            key = (room.origin[0], room.origin[1], room.width, room.height)
            terrain = RoomCollision(
                origin=room.origin,
                width=room.width,
                height=room.height,
                cells=strip_transient(room.cells),
            )
            existing = self._rooms.get(key)
            if existing is None:
                self._rooms[key] = terrain
                changed += 1
                if stats is not None:
                    stats["added"] = stats.get("added", 0) + 1
            elif existing.cells != terrain.cells:
                if stats is not None:
                    stats["updated"] = stats.get("updated", 0) + 1
                    _accumulate_bit_changes(
                        existing.cells, terrain.cells, stats.setdefault("bits", {})
                    )
                self._rooms[key] = terrain
                changed += 1
        if changed:
            self._view = LocalCollision(list(self._rooms.values()))
            self.revision += 1
            self._save()
        return changed

    # -- persistence -------------------------------------------------------------

    def _save(self) -> None:
        payload = {
            "version": FORMAT_VERSION,
            "seed": self.seed,
            "difficulty": self.difficulty,
            "area": self.area_id,
            "rooms": [
                {
                    "x": room.origin[0],
                    "y": room.origin[1],
                    "w": room.width,
                    "h": room.height,
                    "cells": base64.b64encode(room.cells).decode("ascii"),
                }
                for room in self._rooms.values()
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write cannot leave a torn file.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self.path)


def _accumulate_bit_changes(old: bytes, new: bytes, into: dict[int, int]) -> None:
    """Count, per collision bit, how many cells changed on that bit."""
    count = len(old) // 2
    for before, after in zip(
        struct.unpack(f"<{count}H", old), struct.unpack(f"<{count}H", new), strict=True
    ):
        difference = before ^ after
        while difference:
            lowest = difference & -difference
            into[lowest] = into.get(lowest, 0) + 1
            difference ^= lowest


class MapStore:
    """Opens (and caches) ExploredArea files under one root directory."""

    def __init__(self, root: Path | str = DEFAULT_ROOT) -> None:
        self.root = Path(root)
        self._open: dict[tuple[int, int, int], ExploredArea] = {}

    def path_for(self, seed: int, difficulty: int, area_id: int) -> Path:
        return self.root / f"{seed:08x}-d{difficulty}" / f"area-{area_id:03d}.json"

    def open(self, seed: int, difficulty: int, area_id: int) -> ExploredArea:
        key = (seed, difficulty, area_id)
        if key not in self._open:
            self._open[key] = self._load(key)
        return self._open[key]

    def _load(self, key: tuple[int, int, int]) -> ExploredArea:
        seed, difficulty, area_id = key
        path = self.path_for(seed, difficulty, area_id)
        rooms: dict[RoomKey, RoomCollision] = {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") == FORMAT_VERSION and payload.get("seed") == seed:
                for entry in payload["rooms"]:
                    cells = base64.b64decode(entry["cells"])
                    if len(cells) != 2 * entry["w"] * entry["h"]:
                        continue  # damaged entry; drop it, keep the rest
                    rooms[(entry["x"], entry["y"], entry["w"], entry["h"])] = RoomCollision(
                        origin=(entry["x"], entry["y"]),
                        width=entry["w"],
                        height=entry["h"],
                        cells=cells,
                    )
        except FileNotFoundError:
            pass  # first visit to this area: an empty atlas is the true state
        except (OSError, ValueError, KeyError, TypeError):
            # Unreadable or corrupt: better an honest blank map than a wrong
            # one. The file is overwritten on the next record().
            rooms = {}
        return ExploredArea(path, seed, difficulty, area_id, rooms)
