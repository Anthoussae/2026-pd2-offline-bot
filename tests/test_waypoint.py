"""Waypoint travel: the edge discipline and the verified trip.

Fakes script the world's responses (panel flag, area id); the module under
test must attribute the panel to its own click, refuse uncalibrated rows,
and only report arrival on the observed area change.
"""

from types import SimpleNamespace

import pytest

from pd2bot import offsets
from pd2bot.uistate import UIState
from pd2bot.units import GameObject
from pd2bot.waypoint import WaypointConfig, WaypointError, WaypointTravel
from pd2bot.window import ClientRect
from pd2bot.world import Area

RECT = ClientRect(left=100, top=50, width=1536, height=864)
WP = GameObject(unit_id=1, kind=offsets.OBJ_WAYPOINT_A1, position=(5884, 5709), mode=2)
COLD_PLAINS = 3
ROWS = {COLD_PLAINS: (0.25, 0.5)}


class World:
    """Mutable scripted state the patched readers consult."""

    def __init__(self):
        self.panel_open = False
        self.area = 1
        self.world_clicks = []
        self.panel_clicks = []
        self.walked = []
        self.opens_after_clicks = 1  # nth object click that opens the panel


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
    monkeypatch.setattr(
        "pd2bot.waypoint.uistate.read_ui_state",
        lambda session, ui_array=None: UIState(
            frozenset({offsets.UI_WPMENU} if state.panel_open else set())
        ),
    )
    monkeypatch.setattr(
        "pd2bot.waypoint.read_area",
        lambda session: Area(level_no=state.area, position=(0, 0), size=(100, 100)),
    )
    return state


def travel(world_state, config=None, waypoint=WP):
    clock = FakeClock()

    def click_world(x, y, **kwargs):
        world_state.world_clicks.append((x, y))
        if len(world_state.world_clicks) >= world_state.opens_after_clicks:
            world_state.panel_open = True
        return (0, 0)

    def panel_click(panel_id, sx, sy, button="left", shift=False):
        world_state.panel_clicks.append((panel_id, sx, sy))
        world_state.area = COLD_PLAINS  # the row does its job...
        world_state.panel_open = False  # ...and the panel goes away

    gated = SimpleNamespace(click_world=click_world)
    panel = SimpleNamespace(
        click=panel_click,
        window=SimpleNamespace(client_rect=lambda: RECT),
    )
    return WaypointTravel(
        session=object(),
        gated=gated,
        panel=panel,
        walk_to=lambda pos: world_state.walked.append(pos),
        find_waypoint=lambda: waypoint,
        config=config if config is not None else WaypointConfig(row_fractions=ROWS),
        ui_array=0,
        clock=clock,
        sleep=clock.sleep,
    )


def test_happy_path_walks_clicks_edge_row_arrival(world):
    report = travel(world).take(COLD_PLAINS)
    assert world.walked == [WP.position]
    assert world.world_clicks == [WP.position]
    assert report.arrived and report.clicks == 1
    # Row pixel from the calibrated fraction on the client rect.
    assert world.panel_clicks == [
        (offsets.UI_WPMENU, 100 + round(0.25 * 1536), 50 + round(0.5 * 864))
    ]


def test_uncalibrated_destination_refuses_before_moving(world):
    with pytest.raises(WaypointError, match="no calibrated row"):
        travel(world, config=WaypointConfig()).take(COLD_PLAINS)
    assert world.walked == [] and world.world_clicks == []


def test_panel_already_open_is_a_stuck_flag_refusal(world):
    """The 0-side of the edge: a pre-open panel cannot be attributed to our
    click — the M2 stuck-at-1 observation must refuse, not proceed."""
    world.panel_open = True
    with pytest.raises(WaypointError, match="already reads open"):
        travel(world).take(COLD_PLAINS)
    assert world.world_clicks == [] and world.panel_clicks == []


def test_object_click_is_retried_then_fails_loudly(world):
    world.opens_after_clicks = 99  # never opens
    with pytest.raises(WaypointError, match="never opened"):
        travel(world).take(COLD_PLAINS)
    assert len(world.world_clicks) == 1 + WaypointConfig().click_retries


def test_no_waypoint_object_in_range(world):
    with pytest.raises(WaypointError, match="no waypoint object"):
        travel(world, waypoint=None).take(COLD_PLAINS)


def test_arrival_requires_the_area_to_actually_change(world, monkeypatch):
    def panel_click_no_effect(panel_id, sx, sy, button="left", shift=False):
        world.panel_clicks.append((panel_id, sx, sy))
        world.panel_open = False  # panel closes but the area never changes

    trip = travel(world)
    trip.panel.click = panel_click_no_effect
    with pytest.raises(WaypointError, match="never observed arrival"):
        trip.take(COLD_PLAINS)
