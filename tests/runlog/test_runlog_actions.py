"""P3: every executed action becomes an event, with all three frames."""

from pd2bot.behavior.actions import (
    AttackUnit,
    CastAtPoint,
    CastSelf,
    DrinkPotion,
    GiveMercPotion,
    InteractObject,
    MoveTo,
    ParkSkill,
    PickUpItem,
)
from pd2bot.behavior.execute import RecordingExecutor
from pd2bot.nav.mapframe import MapFrame
from pd2bot.perception.world import Area
from pd2bot.pickit import ItemTable
from pd2bot.runlog import NullRunLog, RunLog, load

TOWER = Area(level_no=20, position=(2000, 1600), size=(8, 8))
ARRIVAL = (10006, 8002)
STAIRCASE = (10002, 8013)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


def executor(tmp_path, **kw):
    clock = Clock()
    log = RunLog("t", root=tmp_path, clock=clock, wall=lambda: 1786000000.0)
    ex = RecordingExecutor(
        clock=clock,
        runlog=log,
        frame=lambda: MapFrame.from_area(TOWER),
        player_position=lambda: ARRIVAL,
        skill_names={83: "desecrate", 95: "revive"},
        vitals=lambda: {"hp": 1737, "max_hp": 2000, "mana": 402, "max_mana": 500},
        **kw,
    )
    return ex, log


def only(events, kind):
    matches = [e for e in events if e["kind"] == kind]
    assert len(matches) == 1, f"expected one {kind}, got {len(matches)}"
    return matches[0]


# -- movement, the user's headline requirement ---------------------------------


def test_a_movement_command_carries_absolute_local_and_relative_coordinates(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(MoveTo(STAIRCASE))
    event = only(load(log.directory), "action.move")
    target = event["target"]
    assert target["world"] == [10002, 8013]      # absolute, game coordinates
    assert target["local"] == [2, 13]            # relative to the map
    assert target["rel"] == [-4, 11]             # relative to the character
    assert target["dist"] == 11
    assert target["bearing"] == "SW"
    assert target["frame"] == "area-020"
    # Where it started, so a leg reads as a leg rather than a destination.
    assert event["origin"]["world"] == list(ARRIVAL)


def test_a_movement_command_names_the_unit_it_was_for(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(MoveTo((1010, 1010), toward=66))
    assert only(load(log.directory), "action.move")["toward"] == 66


# -- the rest of the funnel ------------------------------------------------------


def test_an_attack_records_its_target_unit_and_place(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(AttackUnit(66, (10004, 8006)))
    event = only(load(log.directory), "action.attack")
    assert event["unit_id"] == 66
    assert event["target"]["local"] == [4, 6]


def test_casts_record_the_skill_by_name(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(CastAtPoint(83, (10004, 8006)))
    ex.execute(CastSelf(95))
    events = load(log.directory)
    assert only(events, "action.cast")["skill"] == "desecrate"
    assert only(events, "action.cast_self")["skill"] == "revive"


def test_an_unnamed_skill_is_reported_honestly_not_guessed(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(CastSelf(4242))
    assert only(load(log.directory), "action.cast_self")["skill"] == "skill 4242"


def test_a_staircase_click_records_where_it_aimed(tmp_path):
    # The open Forgotten Tower question, made answerable: the target and
    # the screen point the click actually used.
    ex, log = executor(tmp_path)
    ex._last_click_screen = (812, 344)
    ex.execute(InteractObject(STAIRCASE))
    event = only(load(log.directory), "action.interact")
    assert event["target"]["world"] == [10002, 8013]
    assert event["click_screen"] == [812, 344]


def test_a_pickup_attempt_names_the_item_and_its_aim(tmp_path):
    ex, log = executor(tmp_path)
    ex.item_names = lambda kind: "thul_rune" if kind == 702 else None
    ex.execute(PickUpItem(880, (10004, 8004), attempt=3, kind=702))
    event = only(load(log.directory), "action.pickup_attempt")
    assert event["item"] == "thul_rune"
    assert event["item_kind"] == 702
    assert event["attempt"] == 3
    assert event["target"]["local"] == [4, 4]


def test_an_unnamed_item_kind_renders_as_its_number(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(PickUpItem(880, (10004, 8004), kind=1234))
    assert only(load(log.directory), "action.pickup_attempt")["item"] == "kind 1234"


def test_an_item_of_unknown_kind_says_unknown(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(PickUpItem(880, (10004, 8004)))
    assert only(load(log.directory), "action.pickup_attempt")["item"] == "unknown"


def test_potions_and_merc_feeds_carry_vitals(tmp_path):
    # The user asked for HP and mana on every potion event, because "why
    # did it drink?" is unanswerable without them.
    ex, log = executor(tmp_path)
    ex.execute(DrinkPotion(2, "healing"))
    ex.execute(GiveMercPotion(0))
    events = load(log.directory)
    drink = only(events, "action.drink")
    assert (drink["hp"], drink["max_hp"]) == (1737, 2000)
    assert (drink["mana"], drink["max_mana"]) == (402, 500)
    assert drink["potion"] == "healing"
    assert only(events, "action.merc_feed")["column"] == 0


def test_a_park_records_the_skill_it_parked_to(tmp_path):
    ex, log = executor(tmp_path)
    ex.execute(ParkSkill(95))
    assert only(load(log.directory), "action.park_skill")["skill"] == "revive"


# -- the rules hold under instrumentation ------------------------------------------


def test_the_null_log_costs_nothing_at_all(tmp_path):
    # Not an optimisation: a silent log that still read the player would
    # make the instrument observable in the behaviour it instruments.
    reads = []
    ex = RecordingExecutor(
        runlog=NullRunLog(),
        player_position=lambda: (reads.append(1), ARRIVAL)[1],
        frame=lambda: MapFrame.from_area(TOWER),
    )
    ex.execute(MoveTo(STAIRCASE))
    assert reads == []


def test_a_broken_frame_provider_never_breaks_the_action(tmp_path):
    def exploding():
        raise RuntimeError("torn read")

    ex, log = executor(tmp_path)
    ex.frame = exploding
    ex.execute(MoveTo(STAIRCASE))  # must not raise
    event = only(load(log.directory), "action.move")
    assert event["target"]["frame"] == "world"  # honest, not invented
    assert len(ex.trace) == 1  # and the action still happened


def test_an_unreadable_player_leaves_the_relative_frame_out(tmp_path):
    ex, log = executor(tmp_path)
    ex.player_position = lambda: None
    ex.execute(MoveTo(STAIRCASE))
    target = only(load(log.directory), "action.move")["target"]
    assert target["world"] == [10002, 8013]
    assert "rel" not in target and "dist" not in target


def test_the_log_agrees_with_the_executor_trace(tmp_path):
    # The instrument and the thing it instruments must not disagree.
    ex, log = executor(tmp_path)
    for action in (
        MoveTo(STAIRCASE), AttackUnit(1, (10004, 8004)), CastSelf(95),
        InteractObject(STAIRCASE), DrinkPotion(2, "healing"),
    ):
        ex.execute(action)
    actions = [e for e in load(log.directory) if e["kind"].startswith("action.")]
    assert len(actions) == len(ex.trace) == 5


def test_an_unrecognised_action_type_records_itself_rather_than_vanishing(tmp_path):
    class Novel:
        def __repr__(self):
            return "Novel()"

    ex, log = executor(tmp_path)
    ex.execute(Novel())
    assert only(load(log.directory), "action.novel")["action"] == "Novel()"


# -- the item name table -------------------------------------------------------------


def test_the_item_table_resolves_a_kind_back_to_its_name():
    table = ItemTable(
        ids={"thul_rune": (702,), "healing_606": (606,)},
        pending=frozenset(),
        groups={},
    )
    assert table.name_for(702) == "thul_rune"
    assert table.name_for(606) == "healing_606"


def test_an_unknown_kind_has_no_name_rather_than_a_guessed_one():
    table = ItemTable(ids={"thul_rune": (702,)}, pending=frozenset(), groups={})
    assert table.name_for(9999) is None


def test_an_ambiguous_kind_reports_the_ambiguity(tmp_path):
    # Several names can legitimately cover one kind; the log says so
    # rather than silently picking one.
    table = ItemTable(
        ids={"hel_rune": (702,), "hel_rune_s": (702,)},
        pending=frozenset(),
        groups={},
    )
    assert table.name_for(702) == "hel_rune (also hel_rune_s)"
