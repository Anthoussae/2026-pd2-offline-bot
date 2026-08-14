"""The read-only human-run recorder (R255): detection rules, no session."""

from dataclasses import dataclass, field

from pd2bot.observe import RunObserver


class SinkSpy:
    def __init__(self):
        self.events = []
        self.areas = []

    def area(self, area_id, area_name=None):
        self.areas.append((area_id, area_name))

    def event(self, kind, **fields):
        self.events.append({"kind": kind, **fields})


@dataclass
class Unit:
    unit_id: int
    kind: int
    position: tuple
    is_alive: bool = True


@dataclass
class FakePlayer:
    position: tuple = (100, 100)
    hp: int = 500
    max_hp: int = 500
    mana: int = 200
    max_mana: int = 200


@dataclass
class FakeArea:
    level_no: int = 1


@dataclass
class Snap:
    in_game: bool = True
    player: object = field(default_factory=FakePlayer)
    area: object = field(default_factory=FakeArea)
    monsters: tuple = ()
    corpses: tuple = ()
    ground_items: tuple = ()
    allies: tuple = ()

    @property
    def live_monsters(self):
        return tuple(m for m in self.monsters if m.is_alive)


def kinds(sink):
    return [e["kind"] for e in sink.events]


def test_every_in_game_snapshot_yields_a_sample():
    sink = SinkSpy()
    observer = RunObserver(sink)
    assert observer.observe(Snap()) is True
    assert kinds(sink) == ["observe.area", "observe.sample"]
    sample = sink.events[-1]
    assert sample["player"] == {"world": [100, 100]}
    assert sample["hostiles"] == 0


def test_area_changes_are_events_and_restamp_the_sink():
    sink = SinkSpy()
    observer = RunObserver(sink)
    observer.observe(Snap(area=FakeArea(1)))
    observer.observe(Snap(area=FakeArea(3)))
    observer.observe(Snap(area=FakeArea(3)))  # no repeat
    transitions = [e for e in sink.events if e["kind"] == "observe.area"]
    assert [(t["left"], t["entered"]) for t in transitions] == [(None, 1), (1, 3)]
    assert sink.areas == [(1, "Rogue Encampment"), (3, "Cold Plains")]


def test_a_kill_is_a_corpse_never_a_disappearance():
    sink = SinkSpy()
    observer = RunObserver(sink)
    fallen = Unit(unit_id=7, kind=19, position=(110, 100))
    observer.observe(Snap(monsters=(fallen,)))
    # It walks out of scan range: NOT a kill.
    observer.observe(Snap())
    assert "observe.kill" not in kinds(sink)
    # Later its corpse turns up: that IS the kill, exactly once.
    observer.observe(Snap(corpses=(Unit(7, 19, (110, 100), is_alive=False),)))
    observer.observe(Snap(corpses=(Unit(7, 19, (110, 100), is_alive=False),)))
    kills = [e for e in sink.events if e["kind"] == "observe.kill"]
    assert [(k["unit_id"], k["monster_kind"]) for k in kills] == [(7, 19)]


def test_a_pickup_needs_the_player_beside_the_vanished_item():
    sink = SinkSpy()
    observer = RunObserver(sink)
    ring = Unit(unit_id=41, kind=522, position=(104, 100))
    observer.observe(Snap(ground_items=(ring,)))
    observer.observe(Snap(player=FakePlayer(position=(103, 100))))
    pickups = [e for e in sink.events if e["kind"] == "observe.pickup"]
    assert [(p["unit_id"], p["item_kind"]) for p in pickups] == [(41, 522)]


def test_an_item_unloading_far_away_is_not_a_pickup():
    sink = SinkSpy()
    observer = RunObserver(sink)
    ring = Unit(unit_id=41, kind=522, position=(160, 100))
    observer.observe(Snap(ground_items=(ring,)))
    observer.observe(Snap())  # player at (100, 100), 60 subtiles away
    assert "observe.pickup" not in kinds(sink)


def test_unit_books_reset_on_an_area_change():
    """An id reused by the next area must not read as a kill or pickup."""
    sink = SinkSpy()
    observer = RunObserver(sink)
    observer.observe(Snap(
        area=FakeArea(1),
        monsters=(Unit(7, 19, (110, 100)),),
        ground_items=(Unit(41, 522, (104, 100)),),
    ))
    observer.observe(Snap(
        area=FakeArea(3),
        corpses=(Unit(7, 800, (500, 500), is_alive=False),),
    ))
    assert "observe.kill" not in kinds(sink)
    assert "observe.pickup" not in kinds(sink)


def test_the_recording_survives_a_torn_read_but_ends_on_a_real_exit():
    sink = SinkSpy()
    observer = RunObserver(sink)
    observer.observe(Snap())
    assert observer.observe(Snap(in_game=False)) is True
    assert observer.observe(Snap()) is True  # recovered: counter resets
    assert observer.observe(Snap(in_game=False)) is True
    assert observer.observe(Snap(in_game=False)) is True
    assert observer.observe(Snap(in_game=False)) is False


def test_mid_load_snapshots_record_nothing_and_conclude_nothing():
    sink = SinkSpy()
    observer = RunObserver(sink)
    assert observer.observe(Snap(player=None, area=None)) is True
    assert sink.events == []
