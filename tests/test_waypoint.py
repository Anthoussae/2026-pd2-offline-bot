"""Waypoint travel: the edge discipline and the verified trip.

The module delegates approach, object-clicking and in-panel clicking to the
interaction layer (R87), so these tests drive a real `TownLayer` over the
same scripted-world fakes the town tests use. That is deliberate: a test
that stubbed out the interaction layer would pass just as happily against
the naive copy this module used to carry.
"""

from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.town import TownConfig, TownError, TownLayer
from pd2bot.uipoints import default_points
from pd2bot.uistate import UIState
from pd2bot.units import GameObject
from pd2bot.waypoint import WaypointConfig, WaypointError, WaypointTravel
from pd2bot.window import ClientRect
from pd2bot.world import Area

RECT = ClientRect(left=100, top=50, width=1536, height=864)
WP_POS = (5884, 5709)
WP = GameObject(unit_id=1, kind=offsets.OBJ_WAYPOINT_A1, position=WP_POS, mode=2)
COLD_PLAINS = offsets.AREA_COLD_PLAINS
TOWN = offsets.AREA_ROGUE_ENCAMPMENT
ROW = (0.25, 0.5)
ROW_PIXEL = (100 + round(0.25 * 1536), 50 + round(0.5 * 864))


class World:
    """Mutable scripted state the patched readers consult."""

    def __init__(self):
        self.panels: set[int] = set()
        self.area = TOWN
        self.player_pos = (5880, 5720)
        self.world_clicks = []
        self.panel_clicks = []
        self.walked = []
        self.waypoint = WP
        self.opens_after_clicks = 1  # nth object click that opens the panel
        self.row_travels = True  # does the row click do its job?


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def world(monkeypatch):
    state = World()
    read_ui = lambda session=None, ui_array=None: UIState(frozenset(state.panels))  # noqa: E731
    monkeypatch.setattr("pd2bot.waypoint.uistate.read_ui_state", read_ui)
    monkeypatch.setattr("pd2bot.town.uistate.read_ui_state", read_ui)
    area = lambda session=None: Area(  # noqa: E731
        level_no=state.area, position=(0, 0), size=(100, 100)
    )
    monkeypatch.setattr("pd2bot.waypoint.read_area", area)
    return state


def build(state, *, config=None, points_override=None):
    clock = FakeClock()

    def click_world(x, y, **kwargs):
        state.world_clicks.append((x, y))
        if len(state.world_clicks) >= state.opens_after_clicks:
            state.panels.add(offsets.UI_WPMENU)
        return (0, 0)

    def panel_click(panel_id, sx, sy, button="left", shift=False, **kwargs):
        state.panel_clicks.append((panel_id, sx, sy))
        # Only the ROW travels. An ACT TAB click (M6 P2) swaps the list
        # inside the same panel and changes nothing observable — a fake
        # that closed the panel on any click would make the tab look
        # like a row and hide exactly the bug the tab step could have.
        if (
            panel_id == offsets.UI_WPMENU
            and (sx, sy) == ROW_PIXEL
            and state.row_travels
        ):
            state.panels.discard(offsets.UI_WPMENU)
            state.area = COLD_PLAINS

    points = default_points()
    for name, fraction in (points_override or {"waypoint.cold_plains": ROW}).items():
        points[name] = points[name].__class__(
            name=points[name].name,
            panel=points[name].panel,
            fraction=fraction,
            opens=points[name].opens,
            note=points[name].note,
        )

    town = TownLayer(
        session=object(),
        gated=SimpleNamespace(click_world=click_world),
        panel=SimpleNamespace(
            click=panel_click,
            window=SimpleNamespace(client_rect=lambda: RECT),
            _ui_array=0,
        ),
        menu=SimpleNamespace(press_escape=lambda: state.panels.clear()),
        walk_to=lambda pos: state.walked.append(pos),
        snapshot=lambda: SimpleNamespace(
            allies=(), objects=(state.waypoint,) if state.waypoint else ()
        ),
        config=TownConfig(ui_points=points),
        read_player_fn=lambda session: SimpleNamespace(position=state.player_pos),
        clock=clock,
        sleep=clock.sleep,
    )
    return WaypointTravel(
        session=object(),
        interact=town,
        config=config if config is not None else WaypointConfig(),
        ui_array=0,
        clock=clock,
        sleep=clock.sleep,
    )


def test_happy_path_opens_the_edge_clicks_the_row_and_verifies_arrival(world):
    report = build(world).take(COLD_PLAINS)
    # Two clicks since M6 P2: the act tab, then the row. The tab is
    # clicked unconditionally (which tab is showing cannot be read from
    # memory, and re-clicking the active one is harmless).
    assert report.arrived and report.clicks == 2
    assert world.world_clicks == [WP_POS]
    tab_pixel = default_points()["waypoint.tab_act1"].pixel(RECT)
    assert world.panel_clicks == [
        (offsets.UI_WPMENU, *tab_pixel),
        (offsets.UI_WPMENU, *ROW_PIXEL),
    ]
    assert world.area == COLD_PLAINS


def test_unknown_destination_refuses_before_moving(world):
    with pytest.raises(WaypointError, match="not a configured waypoint destination"):
        build(world).take(99)
    assert world.walked == [] and world.world_clicks == []


def test_uncalibrated_destination_refuses_before_moving(world):
    """An uncalibrated row can only fail; failing after the walk teaches
    nothing that failing here does not."""
    from pd2bot.town import Uncalibrated

    trip = build(world, points_override={"waypoint.cold_plains": None})
    with pytest.raises(Uncalibrated, match=r"waypoint\.cold_plains"):
        trip.take(COLD_PLAINS)
    assert world.walked == [] and world.world_clicks == []


def test_panel_already_open_is_a_stuck_flag_refusal(world):
    """The 0-side of the edge: a pre-open panel cannot be attributed to our
    click — the M2 stuck-at-1 observation must refuse, not proceed.

    `close_panels` runs first and ESC clears it, so this scripts a panel
    that will not close, which is what a stuck flag would actually look
    like."""
    world.panels.add(offsets.UI_WPMENU)
    trip = build(world)
    trip.interact.menu = SimpleNamespace(press_escape=lambda: None)  # nothing closes
    with pytest.raises(Exception) as caught:
        trip.take(COLD_PLAINS)
    assert "waypoint_menu" in str(caught.value) or "already reads open" in str(
        caught.value
    )
    assert world.panel_clicks == []


def test_object_click_is_retried_then_fails_loudly(world):
    world.opens_after_clicks = 99  # never opens
    with pytest.raises(Exception, match="never opened its panel"):
        build(world).take(COLD_PLAINS)
    assert len(world.world_clicks) > 1  # retried, not one hopeful click


def test_walks_toward_a_waypoint_that_is_out_of_perception_range(world):
    """Shape 1, which this module used to fail outright: the client only
    keeps nearby rooms loaded, so a distant waypoint is not merely far — it
    is absent from the unit table. Walk to the configured spot, then look
    again."""
    world.waypoint = None
    world.player_pos = (5600, 5600)  # far from the configured waypoint
    with pytest.raises(Exception, match="still not visible"):
        build(world).take(COLD_PLAINS)
    assert world.walked, "never walked toward the configured waypoint position"


def test_does_not_walk_onto_the_waypoint_object(world):
    """Shape 2: walking ONTO it means the navigator's own travel click lands
    on it, opening the panel before we ever click — which then trips the
    edge check. Approach walks stop short."""
    world.waypoint = None
    world.player_pos = (5600, 5600)
    with pytest.raises(TownError):
        build(world).take(COLD_PLAINS)
    assert world.walked and WP_POS not in world.walked


def test_arrival_requires_the_area_to_actually_change(world):
    """The row click closed the panel but we are still where we started —
    a mis-aimed row must not read as a trip."""
    trip = build(world)

    def closes_but_no_travel(panel_id, sx, sy, button="left", shift=False, **kwargs):
        world.panel_clicks.append((panel_id, sx, sy))
        # The ROW closes the panel without travelling — the defect under
        # test. The act tab (M6 P2) leaves the panel up, as a real one does.
        if (sx, sy) == ROW_PIXEL:
            world.panels.discard(offsets.UI_WPMENU)

    trip.interact.panel = SimpleNamespace(
        click=closes_but_no_travel,
        window=SimpleNamespace(client_rect=lambda: RECT),
        _ui_array=0,
    )
    with pytest.raises(WaypointError, match="never observed arrival"):
        trip.take(COLD_PLAINS)


def test_a_row_click_that_misses_is_retried(world):
    """The defect that cost three live runs at Charsi's dialog, which this
    module carried its own copy of: one click, no settle, no retry."""
    misses = {"left": 2}

    def flaky(panel_id, sx, sy, button="left", shift=False, **kwargs):
        world.panel_clicks.append((panel_id, sx, sy))
        if misses["left"] > 0:
            misses["left"] -= 1
            return  # the click landed on nothing
        world.panels.discard(offsets.UI_WPMENU)
        world.area = COLD_PLAINS

    trip = build(world)
    trip.interact.panel = SimpleNamespace(
        click=flaky,
        window=SimpleNamespace(client_rect=lambda: RECT),
        _ui_array=0,
    )
    assert trip.take(COLD_PLAINS).arrived
    assert len(world.panel_clicks) == 3
