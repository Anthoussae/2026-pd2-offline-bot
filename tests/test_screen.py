"""Projection math: world subtiles <-> screen pixels."""

from pd2bot.input.screen import (
    EDGE_MARGIN_PX,
    PX_PER_SUBTILE_X,
    PX_PER_SUBTILE_Y,
    Projection,
    clickable,
    hud_height,
    projection_for,
)
from pd2bot.input.window import ClientRect

RECT = ClientRect(left=100, top=50, width=800, height=600)
CENTER = (500, 350)


def test_rect_center():
    assert RECT.center == CENTER


def test_player_projects_to_center():
    projection = projection_for((5000, 5000), RECT)
    assert projection.world_to_screen(5000, 5000) == CENTER


def test_pure_x_step_goes_down_right():
    projection = projection_for((5000, 5000), RECT)
    # +x in world = toward lower-right on screen.
    assert projection.world_to_screen(5001, 5000) == (
        CENTER[0] + PX_PER_SUBTILE_X,
        CENTER[1] + PX_PER_SUBTILE_Y,
    )


def test_pure_y_step_goes_down_left():
    projection = projection_for((5000, 5000), RECT)
    assert projection.world_to_screen(5000, 5001) == (
        CENTER[0] - PX_PER_SUBTILE_X,
        CENTER[1] + PX_PER_SUBTILE_Y,
    )


def test_isometric_ratio_is_two_to_one():
    """The diamond geometry: a floor tile is twice as wide as it is tall.
    Live calibration measured 2.000; a change breaking this means the
    constants were mis-copied, not re-measured."""
    assert PX_PER_SUBTILE_X == 2 * PX_PER_SUBTILE_Y


def test_round_trip():
    projection = projection_for((1234, 987), RECT)
    for target in [(1234, 987), (1250, 990), (1200, 1000), (1239, 967)]:
        sx, sy = projection.world_to_screen(*target)
        wx, wy = projection.screen_to_world(sx, sy)
        assert round(wx) == target[0]
        assert round(wy) == target[1]


def test_projection_is_relative_to_player():
    # Same world target, player moved: different pixel. The camera follows.
    a = Projection(player_world=(100, 100), screen_center=CENTER)
    b = Projection(player_world=(110, 100), screen_center=CENTER)
    assert a.world_to_screen(120, 100) != b.world_to_screen(120, 100)


def test_clickable_rejects_hud_strip():
    # Bottom HUD band swallows world clicks.
    hud = hud_height(RECT)
    assert not clickable(RECT, CENTER[0], RECT.top + RECT.height - hud + 1)
    assert clickable(RECT, CENTER[0], RECT.top + RECT.height - hud - 1)


def test_hud_scales_with_the_window():
    """A fixed pixel count would silently be wrong at another resolution."""
    tall = ClientRect(left=0, top=0, width=1536, height=864)
    short = ClientRect(left=0, top=0, width=800, height=600)
    assert hud_height(tall) > hud_height(short)
    # Same relative point is judged the same way in both windows.
    assert clickable(tall, 700, round(tall.height * 0.7))
    assert clickable(short, 400, round(short.height * 0.7))


def test_clickable_rejects_edges_and_outside():
    assert not clickable(RECT, RECT.left + 1, CENTER[1])  # inside margin
    assert not clickable(RECT, RECT.left - 50, CENTER[1])  # outside window
    assert clickable(RECT, RECT.left + EDGE_MARGIN_PX, CENTER[1])
