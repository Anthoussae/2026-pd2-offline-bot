"""Generated area maps: whole-area walkability before we have been there.

Perception only sees the player's room and its neighbours; global routing
needs the rest of the area. D2 builds each game's maps deterministically
from the map seed, so a headless generator running real game code
(d2mapapi_mod's `piped` variant — see README for building it) can produce
any area's collision grid offline. Live memory collision (collision.py)
remains the ground truth; the fidelity runner below measures how much the
generated picture disagrees with it (PD2 modifies some maps).

Child-process protocol (d2mapapi_mod piped.cpp):
  spawn:  d2mapapi_piped <D2 game path>     (falls back to registry)
  hello:  int32 status; on failure a length-prefixed JSON {"error": ...}
  query:  12 bytes = uint32 seed, uint32 difficulty (0/1/2), uint32 levelId
  reply:  uint32 length + JSON

Reply JSON (collisionmap.h): `offset` {x,y} and `crop` {x0,y0,x1,y1} in
subtiles; `mapData` rows RLE-encoded as alternating run lengths starting
with NON-walkable, -1 ending each row; `exits` keyed by destination area.
The grid covers exactly the crop rect; world subtile of cell (cx, cy) =
(offset.x + crop.x0 + cx, offset.y + crop.y0 + cy).

    python -m pd2bot.mapdata --exe PATH --area 3 --seed 0x... [--difficulty 2]
    python -m pd2bot.mapdata --exe PATH --fidelity [--areas 3 4]   (live game)
"""

from __future__ import annotations

import json
import struct
import subprocess
from dataclasses import dataclass

# Area ids from the game's levels.txt numbering (cross-checked against
# kolbot sdk `sdk.areas`): the ones this milestone and the next two care
# about. Not exhaustive on purpose.
AREA_ROGUE_ENCAMPMENT = 1
AREA_BLOOD_MOOR = 2
AREA_COLD_PLAINS = 3
AREA_STONY_FIELD = 4
AREA_DARK_WOOD = 5
AREA_BLACK_MARSH = 6
AREA_FORGOTTEN_TOWER = 17
AREA_TOWER_CELLAR_1 = 18
AREA_TOWER_CELLAR_5 = 22  # the Countess

DIFFICULTY_NORMAL = 0
DIFFICULTY_NIGHTMARE = 1
DIFFICULTY_HELL = 2


class MapServiceError(RuntimeError):
    """The generator child process failed or answered with an error."""


@dataclass(frozen=True)
class AreaMap:
    """One generated area, in world subtiles. Implements the Grid protocol."""

    area_id: int
    origin: tuple[int, int]  # world subtile of cell (0, 0)
    width: int
    height: int
    walkable_cells: bytes  # 1 walkable / 0 not, row-major, width*height
    # Exits as reported (destination area id -> points in the same frame as
    # `origin`). Point frame verified against live memory in the fidelity
    # run; M4 consumes these for area transitions.
    exits: dict[int, list[tuple[int, int]]]

    def is_known(self, x: int, y: int) -> bool:
        return (
            0 <= x - self.origin[0] < self.width
            and 0 <= y - self.origin[1] < self.height
        )

    def is_walkable(self, x: int, y: int) -> bool:
        cx, cy = x - self.origin[0], y - self.origin[1]
        if not (0 <= cx < self.width and 0 <= cy < self.height):
            return False
        return self.walkable_cells[cy * self.width + cx] == 1


def decode_area_map(payload: dict) -> AreaMap:
    """Parse one reply. Split from the process plumbing so tests can feed
    captured responses without a child process."""
    if "error" in payload:
        raise MapServiceError(payload["error"])

    offset = payload["offset"]
    crop = payload["crop"]
    width = crop["x1"] - crop["x0"]
    height = crop["y1"] - crop["y0"]
    if width <= 0 or height <= 0:
        raise MapServiceError(f"empty crop rect in area {payload.get('id')}")

    cells = bytearray(width * height)  # starts all non-walkable
    x = y = 0
    walkable = False
    row_base = 0
    for run in payload["mapData"]:
        if run < 0:  # end of row; anything unmentioned stays non-walkable
            y += 1
            if y >= height:
                break
            x = 0
            walkable = False
            row_base = y * width
            continue
        run = min(run, width - x)
        if walkable:
            for i in range(row_base + x, row_base + x + run):
                cells[i] = 1
        x += run
        walkable = not walkable

    exits: dict[int, list[tuple[int, int]]] = {}
    for area, exit_info in payload.get("exits", {}).items():
        exits[int(area)] = [(p["x"], p["y"]) for p in exit_info.get("offsets", [])]

    return AreaMap(
        area_id=payload["id"],
        origin=(offset["x"] + crop["x0"], offset["y"] + crop["y0"]),
        width=width,
        height=height,
        walkable_cells=bytes(cells),
        exits=exits,
    )


class MapService:
    """The d2mapapi_piped child process, kept alive across queries.

    The process caches (seed, difficulty) sessions internally, so repeated
    queries for one game are cheap. If it dies, the next query respawns it
    once before giving up.
    """

    def __init__(self, exe_path: str, d2_path: str | None = None) -> None:
        self.exe_path = exe_path
        self.d2_path = d2_path
        self._proc: subprocess.Popen | None = None

    # -- plumbing -------------------------------------------------------------

    def _read_exact(self, count: int) -> bytes:
        assert self._proc is not None and self._proc.stdout is not None
        data = b""
        while len(data) < count:
            chunk = self._proc.stdout.read(count - len(data))
            if not chunk:
                raise MapServiceError("generator closed the pipe mid-reply")
            data += chunk
        return data

    def _spawn(self) -> None:
        command = [self.exe_path]
        if self.d2_path:
            command.append(self.d2_path)
        try:
            self._proc = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE
            )
        except OSError as exc:
            raise MapServiceError(f"could not start {self.exe_path}: {exc}") from exc
        status = struct.unpack("<i", self._read_exact(4))[0]
        if status != 0:
            length = struct.unpack("<I", self._read_exact(4))[0]
            error = json.loads(self._read_exact(length))
            self._proc = None
            raise MapServiceError(error.get("error", "generator failed to start"))

    def close(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc = None

    def __enter__(self) -> MapService:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- the query --------------------------------------------------------------

    def query(self, seed: int, difficulty: int, area_id: int) -> AreaMap:
        for attempt in (1, 2):  # one respawn if the child died under us
            if self._proc is None or self._proc.poll() is not None:
                self._spawn()
            try:
                assert self._proc is not None and self._proc.stdin is not None
                self._proc.stdin.write(struct.pack("<3I", seed, difficulty, area_id))
                self._proc.stdin.flush()
                length = struct.unpack("<I", self._read_exact(4))[0]
                payload = json.loads(self._read_exact(length))
                return decode_area_map(payload)
            except (OSError, MapServiceError):
                self.close()
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")


# --- fidelity: generated vs live ground truth ---------------------------------


def compare_with_live(area_map: AreaMap, local) -> tuple[int, int, list[tuple[int, int]]]:
    """(cells compared, mismatches, sample mismatch positions) over the
    overlap between a generated area and the live stitched collision."""
    bounds = local.bounds
    if bounds is None:
        return (0, 0, [])
    compared = mismatched = 0
    samples: list[tuple[int, int]] = []
    for y in range(bounds[1], bounds[3]):
        for x in range(bounds[0], bounds[2]):
            if not (local.is_known(x, y) and area_map.is_known(x, y)):
                continue
            compared += 1
            if local.is_walkable(x, y) != area_map.is_walkable(x, y):
                mismatched += 1
                if len(samples) < 12:
                    samples.append((x, y))
    return (compared, mismatched, samples)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, help="path to d2mapapi_piped.exe")
    parser.add_argument("--d2", default=None, help="D2 game dir (default: registry)")
    parser.add_argument("--difficulty", type=int, default=DIFFICULTY_HELL)
    parser.add_argument("--area", type=int, help="query one area and print stats")
    parser.add_argument("--seed", type=lambda v: int(v, 0), help="map seed (with --area)")
    parser.add_argument(
        "--fidelity",
        action="store_true",
        help="live: compare generated vs memory collision where you stand",
    )
    args = parser.parse_args(argv)

    if args.area is not None and args.seed is not None:
        with MapService(args.exe, args.d2) as service:
            area_map = service.query(args.seed, args.difficulty, args.area)
        print(
            f"area {area_map.area_id}: origin {area_map.origin} "
            f"size {area_map.width}x{area_map.height}"
        )
        walkable = sum(area_map.walkable_cells)
        print(f"  walkable {walkable}/{area_map.width * area_map.height} cells")
        for destination, points in sorted(area_map.exits.items()):
            print(f"  exit -> area {destination} at {points}")
        return 0

    if not args.fidelity:
        print("nothing to do: pass --area + --seed, or --fidelity", file=sys.stderr)
        return 2

    from pd2bot.collision import read_local_collision
    from pd2bot.perception.memory import GameNotRunning, GameSession, NeedsAdministrator
    from pd2bot.perception.world import read_area, read_map_seed

    try:
        session = GameSession()
    except (GameNotRunning, NeedsAdministrator) as exc:
        print(exc, file=sys.stderr)
        return 1

    area = read_area(session)
    seed = read_map_seed(session)
    if area is None or seed is None:
        print("not in a game", file=sys.stderr)
        return 1

    local = read_local_collision(session)
    with MapService(args.exe, args.d2) as service:
        area_map = service.query(seed, args.difficulty, area.level_no)

    compared, mismatched, samples = compare_with_live(area_map, local)
    print(
        f"area {area.level_no} seed 0x{seed:08X} difficulty {args.difficulty}: "
        f"generated origin {area_map.origin} size {area_map.width}x{area_map.height}"
    )
    if compared == 0:
        print("  no overlap — is the generated origin frame wrong?")
        return 1
    rate = mismatched / compared
    print(f"  compared {compared} cells, {mismatched} mismatches ({rate:.2%})")
    if samples:
        print(f"  sample mismatch positions: {samples}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
