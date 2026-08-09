"""The production assembly — the seams review 005's checklist named.

The review's sharpest test-coverage note was that *no test constructs the
production wiring*, which is why issues 001 and 004 were invisible to a
584-test suite: every test passed the parameters a real caller might omit.
These tests construct it. They cannot reach a live client, so they assert
on what `build_bot` RESOLVED rather than on what it does — which is the
half that was silently defaultable.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.behavior.combat import load_class_config
from pd2bot.perception.items import CarriedItem, CarriedItems
from pd2bot.pickit import cleanse_keep, load_item_table, load_pickit
from pd2bot.safety import SafetyInterrupt, Verdict
from pd2bot.wiring import (
    BELT_ROWS,
    BotPaths,
    SessionBaseline,
    WiringError,
    belt_capacity,
    route_service,
    safety_poll_for,
    town_config_for,
    walkability,
)

REPO = Path(__file__).resolve().parent.parent
PATHS = BotPaths()


@pytest.fixture(scope="module")
def class_config():
    return load_class_config(PATHS.class_config)


# -- belt capacity from the class config ------------------------------------------


def test_belt_capacity_is_derived_from_the_layout(class_config):
    """`Pickit.belt_capacity` decides when a potion rule stops matching, and
    it depends on the R53 layout — healing owns two columns, so it holds
    twice as many. Hardcoding it in two files is how they drift apart."""
    capacity = belt_capacity(class_config)
    assert capacity == {"healing": 8, "mana": 4, "rejuv": 4}
    for potion_type, cells in capacity.items():
        columns = sum(1 for c in class_config.belt.columns if c == potion_type)
        assert cells == columns * BELT_ROWS


def test_belt_capacity_follows_a_relaid_belt(class_config):
    """The property that matters is not the numbers, it is that changing the
    layout changes them."""
    three_healing = replace(
        class_config.belt, columns=("mana", "healing", "healing", "healing")
    )
    capacity = belt_capacity(replace(class_config, belt=three_healing))
    assert capacity == {"healing": 12, "mana": 4, "rejuv": 0}


def test_the_shipped_default_matches_the_shipped_class_config(class_config):
    """`pickit.DEFAULT_BELT_CAPACITY` exists so a bare Pickit behaves. If it
    ever disagrees with the config, one of the two is lying."""
    from pd2bot.pickit import DEFAULT_BELT_CAPACITY

    assert belt_capacity(class_config) == DEFAULT_BELT_CAPACITY


# -- one source for the belt minimums ---------------------------------------------


def test_town_config_takes_its_minimums_from_the_class_config(class_config):
    """min_healing/min_mana/min_rejuv live on BOTH TownConfig and
    BeltConfig — the same duplication shape review 004 flagged for the
    potion reserve. The wiring cannot merge the types, but it can make sure
    only one of them is ever the source."""
    tuned = replace(
        class_config.belt, min_healing=7, min_mana=5, min_rejuv=3
    )
    config = town_config_for(replace(class_config, belt=tuned))
    assert (config.min_healing, config.min_mana, config.min_rejuv) == (7, 5, 3)


def test_town_config_keeps_every_other_field_of_its_base(class_config):
    base = replace(town_config_for(class_config), npc_standoff=99)
    assert town_config_for(class_config, base).npc_standoff == 99


# -- the route service (R181) -----------------------------------------------------


class _CountingGridNav:
    """A fake navigator over a scripted grid, counting grid reads."""

    def __init__(self, walkable, pos=(100, 100)):
        self._walkable = walkable
        self.pos = pos
        self.grid_reads = 0

    def position(self):
        return self.pos

    def grid(self):
        self.grid_reads += 1
        walkable = self._walkable
        return SimpleNamespace(
            is_walkable=lambda x, y: walkable(x, y),
            is_known=lambda x, y: True,
        )


def test_route_service_plans_over_the_grid():
    nav = _CountingGridNav(lambda x, y: True)
    route = route_service(nav)((140, 100))
    assert route is not None
    assert route[-1] == (140, 100)


def test_route_service_answers_none_when_no_path_exists():
    # Everything past x=120 is wall, thicker than nearest_walkable's
    # 15-subtile search: the map's honest "no route exists".
    nav = _CountingGridNav(lambda x, y: x < 120)
    assert route_service(nav)((140, 100)) is None


def test_route_service_caches_per_origin_bucket():
    """Unchanged origin bucket + same target = ONE plan over many legs —
    re-planning every tick is the tick-rate waste this repo keeps
    refusing."""
    nav = _CountingGridNav(lambda x, y: True)
    route = route_service(nav)
    first = route((140, 100))
    assert route((140, 100)) == first
    assert nav.grid_reads == 1
    nav.pos = (102, 100)  # same 8-subtile bucket: still cached
    route((140, 100))
    assert nav.grid_reads == 1
    nav.pos = (110, 100)  # new bucket: re-plan
    route((140, 100))
    assert nav.grid_reads == 2


def test_route_service_does_not_cache_a_no_route_answer():
    """T55 run 1: a torn live-collision read produced spurious no-routes;
    a cached None would hand the callers' confirmation retry the same
    wrong answer for free. Every None is recomputed over a fresh grid."""
    torn = {"now": True}
    nav = _CountingGridNav(lambda x, y: not torn["now"])
    route = route_service(nav)
    assert route((140, 100)) is None  # the torn read
    torn["now"] = False
    assert route((140, 100)) is not None  # a fresh grid, the honest answer
    assert nav.grid_reads == 2


def test_route_service_walks_straight_when_position_is_unreadable():
    # A torn read must not write a target off: the answer degrades to the
    # old bearing hop, not to "no route".
    def boom():
        raise RuntimeError("left the game?")

    nav = SimpleNamespace(position=boom, grid=lambda: None)
    assert route_service(nav)((140, 100)) == [(140, 100)]


# -- the cleanse whitelist and its baseline ---------------------------------------


def test_the_shipped_pickit_enables_the_cleanse():
    """The gate opened when the last name resolved (R128). If a future edit
    reintroduces a pending name, the cleanse switches itself off and this
    test says so rather than letting it happen quietly."""
    pickit = load_pickit(
        PATHS.pickit, item_table=load_item_table(PATHS.item_table)
    )
    assert not pickit.pending_names
    assert cleanse_keep(pickit) is not None


def carried(*items):
    return CarriedItems(items=tuple(items), skipped=0)


def inv(uid, cell=(0, 0)):
    return CarriedItem(uid, 522, 6, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, cell, 33)


def test_the_session_baseline_captures_once_and_never_again():
    """Captured per SESSION, not per game. A per-game baseline would
    re-protect whatever the bot picked up last game, forever — which is why
    the TownLayer's implicit one is 'a floor, not the goal' (review 001)."""
    inventory = [inv(1), inv(2)]
    baseline = SessionBaseline(
        session=object(),
        carried=lambda s: carried(*inventory),
        read_player_fn=lambda s: SimpleNamespace(hp=1),
    )
    assert baseline() == {1, 2}
    # The bot picks something up during the run...
    inventory.append(inv(3))
    # ... and it is NOT protected: the baseline is what predated the bot.
    assert baseline() == {1, 2}
    assert baseline.captured


def test_the_session_baseline_refuses_to_capture_outside_a_game():
    """Out of a game the inventory reads EMPTY, and an empty baseline does
    not mean 'protect nothing' — it means 'we did not look'. Handing that to
    the cleanse is the silent worst case issue 001 was written about."""
    baseline = SessionBaseline(
        session=object(),
        carried=lambda s: carried(),
        read_player_fn=lambda s: None,
    )
    with pytest.raises(WiringError, match="outside a game"):
        baseline()
    assert not baseline.captured


def test_the_session_baseline_can_legitimately_be_empty():
    """A character who really is carrying nothing protects nothing — the
    refusal above is about not KNOWING, not about being empty."""
    baseline = SessionBaseline(
        session=object(),
        carried=lambda s: carried(),
        read_player_fn=lambda s: SimpleNamespace(hp=1),
    )
    assert baseline() == set()
    assert baseline.captured


# -- the walkability predicate ----------------------------------------------------


def grid(known=True, walkable=True):
    return SimpleNamespace(
        is_known=lambda x, y: known, is_walkable=lambda x, y: walkable
    )


def test_unknown_ground_is_not_walkable():
    """`is_known` is a different question from `is_walkable` and it comes
    first: warping into ground nobody has ever read burns the cast, the mana
    and 12% of max hp for a teleport the game refuses."""
    assert not walkability(SimpleNamespace(grid=lambda: grid(known=False)))((5, 5))


def test_known_and_walkable_ground_passes():
    assert walkability(SimpleNamespace(grid=lambda: grid()))((5, 5))


def test_known_but_blocked_ground_fails():
    assert not walkability(SimpleNamespace(grid=lambda: grid(walkable=False)))((5, 5))


def test_an_unreadable_grid_answers_false_rather_than_raising():
    """Mid-load is exactly when a read fails AND an escape is most wanted.
    'This escape is not available' is a decision the ladder already makes."""

    def boom():
        raise RuntimeError("mid-load")

    assert not walkability(SimpleNamespace(grid=boom))((5, 5))


def test_the_grid_is_re_fetched_every_call():
    """The atlas grows as rooms load; a cached grid would keep calling
    ground 'unknown' that the character can now see."""
    calls = []

    def fresh():
        calls.append(1)
        return grid()

    is_walkable = walkability(SimpleNamespace(grid=fresh))
    is_walkable((1, 1))
    is_walkable((2, 2))
    assert len(calls) == 2


# -- the safety poll: what a blocking walk asks before it keeps blocking ------
#
# 2026-08-07: a walk blocked for 24 s, and for those 24 s neither the
# chicken nor the operator's abort could be heard. These pin the wiring
# that fixes it -- including the part that is easy to get wrong, which
# is not the mechanism but whether anything actually calls it.


class PollingMonitor:
    def __init__(self, raises=None) -> None:
        self.raises = raises
        self.polls = 0

    def poll(self) -> None:
        self.polls += 1
        if self.raises is not None:
            raise self.raises


def test_the_safety_poll_asks_the_monitor():
    monitor = PollingMonitor()
    safety_poll_for(monitor, None)()
    assert monitor.polls == 1


def test_the_safety_poll_raises_an_abort_as_an_interrupt():
    """Not as a bare StopRequested: that is a RuntimeError, and the broad
    handlers between a walk and the tick loop would swallow it."""
    monitor = PollingMonitor()
    with pytest.raises(SafetyInterrupt) as raised:
        safety_poll_for(monitor, lambda: True)()
    assert raised.value.verdict.kind == "stop"


def test_the_safety_poll_asks_the_monitor_before_the_stop():
    """Review 2026-08-02 issue 001, restated here: a stop rides
    ChickenExit into the leave-game path, which SENDS INPUT. It must
    never preempt a death."""
    death = SafetyInterrupt(Verdict("death", "dead"))
    monitor = PollingMonitor(raises=death)
    with pytest.raises(SafetyInterrupt) as raised:
        safety_poll_for(monitor, lambda: True)()
    assert raised.value.verdict.is_death  # not the stop


def test_the_safety_poll_is_quiet_when_all_is_well():
    safety_poll_for(PollingMonitor(), lambda: False)()


def test_live_navigator_hands_the_poll_to_the_navigator(monkeypatch):
    """The test that catches "the fix exists but nothing calls it"."""
    from pd2bot import navigate

    monkeypatch.setattr(navigate, "GatedInput", lambda session: SimpleNamespace())
    sentinel = safety_poll_for(PollingMonitor(), None)
    nav = navigate.live_navigator(None, None, 2, safety_poll=sentinel)
    assert nav._safety_poll is sentinel


def test_a_navigator_built_without_a_monitor_still_walks(monkeypatch):
    """The CLI, the survey tool and the drills have no monitor at all."""
    from pd2bot import navigate

    monkeypatch.setattr(navigate, "GatedInput", lambda session: SimpleNamespace())
    nav = navigate.live_navigator(None, None, 2)
    assert nav._safety_poll is None
    nav._safety()  # the no-op path, exercised rather than assumed
