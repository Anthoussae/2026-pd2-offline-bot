"""The explored-map atlas: merging, persistence, and honest failure modes."""

import base64
import json
import struct

from pd2bot import offsets
from pd2bot.collision import LocalCollision, RoomCollision, strip_transient
from pd2bot.mapstore import MapStore

SEED = 0x1234ABCD
HELL = 2
COLD_PLAINS = 3


def room(origin, size=(3, 2), blocked=()):
    width, height = size
    cells = bytearray(2 * width * height)
    for bx, by in blocked:
        index = ((by - origin[1]) * width + (bx - origin[0])) * 2
        cells[index : index + 2] = struct.pack("<H", offsets.COLL_BLOCK_WALL)
    return RoomCollision(origin=origin, width=width, height=height, cells=bytes(cells))


def test_record_then_reload_round_trip(tmp_path):
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    assert area.room_count == 0
    assert not area.is_known(0, 0)  # empty atlas is honest, not walkable

    changed = area.record(LocalCollision([room((0, 0), blocked=[(1, 0)]), room((3, 0))]))
    assert changed == 2

    # A brand-new store (fresh process) sees the same picture from disk.
    reloaded = MapStore(tmp_path).open(SEED, HELL, COLD_PLAINS)
    assert reloaded.room_count == 2
    assert reloaded.is_known(1, 0) and not reloaded.is_walkable(1, 0)
    assert reloaded.is_walkable(4, 1)
    assert not reloaded.is_known(0, 5)


def test_reseeing_a_room_updates_rather_than_duplicates(tmp_path):
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    area.record(LocalCollision([room((0, 0))]))
    assert area.record(LocalCollision([room((0, 0))])) == 0  # identical: no-op
    assert area.record(LocalCollision([room((0, 0), blocked=[(0, 0)])])) == 1
    assert area.room_count == 1
    assert not area.is_walkable(0, 0)  # the latest reading won


def test_atlas_grows_across_visits(tmp_path):
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    area.record(LocalCollision([room((0, 0))]))
    area.record(LocalCollision([room((3, 0))]))  # walked on; new rooms in view
    assert area.room_count == 2
    assert area.bounds == (0, 0, 6, 2)


def test_different_seed_is_a_different_file(tmp_path):
    store = MapStore(tmp_path)
    store.open(SEED, HELL, COLD_PLAINS).record(LocalCollision([room((0, 0))]))
    other = store.open(0x9999, HELL, COLD_PLAINS)
    assert other.room_count == 0  # a re-rolled map starts honestly blank
    assert store.path_for(SEED, HELL, COLD_PLAINS) != store.path_for(0x9999, HELL, COLD_PLAINS)


def test_corrupt_file_starts_blank_instead_of_lying(tmp_path):
    store = MapStore(tmp_path)
    path = store.path_for(SEED, HELL, COLD_PLAINS)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert MapStore(tmp_path).open(SEED, HELL, COLD_PLAINS).room_count == 0


def test_damaged_room_entry_is_dropped_but_rest_survive(tmp_path):
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    area.record(LocalCollision([room((0, 0)), room((3, 0))]))

    payload = json.loads(store.path_for(SEED, HELL, COLD_PLAINS).read_text("utf-8"))
    payload["rooms"][0]["cells"] = base64.b64encode(b"\x00\x00").decode()  # wrong size
    store.path_for(SEED, HELL, COLD_PLAINS).write_text(json.dumps(payload), "utf-8")

    reloaded = MapStore(tmp_path).open(SEED, HELL, COLD_PLAINS)
    assert reloaded.room_count == 1


def test_store_caches_open_areas(tmp_path):
    store = MapStore(tmp_path)
    assert store.open(SEED, HELL, COLD_PLAINS) is store.open(SEED, HELL, COLD_PLAINS)


# --- occupancy must never become terrain (found by the first survey walk) ---


def occupied(origin, size=(3, 2), flags_at=None):
    """A room grid with occupancy flags set on one cell."""
    width, height = size
    cells = bytearray(2 * width * height)
    if flags_at:
        (bx, by), flags = flags_at
        index = ((by - origin[1]) * width + (bx - origin[0])) * 2
        cells[index : index + 2] = struct.pack("<H", flags)
    return RoomCollision(origin=origin, width=width, height=height, cells=bytes(cells))


def test_monster_movement_does_not_count_as_new_knowledge():
    """The 247-updates bug: a monster stepping about rewrote the room every
    time it was seen, thrashing the file with no new map information."""
    store_room = occupied((0, 0), flags_at=((1, 0), offsets.COLL_MONSTERS))
    same_place_no_monster = occupied((0, 0))
    assert strip_transient(store_room.cells) == strip_transient(same_place_no_monster.cells)


def test_corpse_is_not_frozen_into_the_atlas_as_a_wall(tmp_path):
    """IS_ON_FLOOR counts as unwalkable, so a corpse or dropped item present
    during a survey would have become a permanent phantom wall."""
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    corpse = offsets.COLL_IS_ON_FLOOR | offsets.COLL_DEAD_BODIES
    area.record(LocalCollision([occupied((0, 0), flags_at=((1, 0), corpse))]))

    assert area.is_walkable(1, 0)  # the ground under a corpse is still ground
    assert MapStore(tmp_path).open(SEED, HELL, COLD_PLAINS).is_walkable(1, 0)


def test_real_walls_still_persist(tmp_path):
    """Stripping occupancy must not strip terrain."""
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    area.record(LocalCollision([occupied((0, 0), flags_at=((1, 0), offsets.COLL_BLOCK_WALL))]))
    assert not area.is_walkable(1, 0)
    assert not MapStore(tmp_path).open(SEED, HELL, COLD_PLAINS).is_walkable(1, 0)


def test_wall_behind_a_monster_is_still_recorded(tmp_path):
    """A monster standing against a wall must not erase the wall."""
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    both = offsets.COLL_BLOCK_WALL | offsets.COLL_MONSTERS
    area.record(LocalCollision([occupied((0, 0), flags_at=((1, 0), both))]))
    assert not area.is_walkable(1, 0)


def test_repeated_sightings_with_monsters_record_once(tmp_path):
    """The churn fix, end to end: same terrain, monsters moving around."""
    store = MapStore(tmp_path)
    area = store.open(SEED, HELL, COLD_PLAINS)
    monster = offsets.COLL_MONSTERS
    first = area.record(LocalCollision([occupied((0, 0), flags_at=((1, 0), monster))]))
    assert first == 1  # genuinely new room
    for cell in [(0, 0), (2, 1), (1, 1), (2, 0)]:  # the monster wanders
        again = area.record(
            LocalCollision([occupied((0, 0), flags_at=(cell, offsets.COLL_MONSTERS))])
        )
        assert again == 0, f"monster at {cell} was mistaken for new terrain"
