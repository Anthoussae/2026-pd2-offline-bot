"""World-subtile to screen-pixel projection, and back.

D2 draws an isometric world with the camera locked on the player: the player's
feet sit at the client area's center, and a step of one subtile moves a point
on screen by a fixed pixel offset. From the classic renderer's geometry, one
floor tile (5x5 subtiles) is a 160x80 pixel diamond, so one subtile projects
to 16 px along (x - y) and 8 px along (x + y):

    screen_dx = (dx - dy) * 16
    screen_dy = (dx + dy) * 8      where (dx, dy) = target - player, in subtiles

Treated as a HYPOTHESIS until calibrated live (M3 P1): `python -m pd2bot.navdemo
click-test` clicks a predicted point and compares where the player ends up.
Calibration notes belong here, next to the constants they would correct.

The player anchor may sit slightly above the geometric center in some window
sizes; `PLAYER_ANCHOR_LIFT_PX` holds whatever the live calibration measures
(0 until proven otherwise).
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot.window import ClientRect

# Pixels per subtile along each isometric axis.
#
# MEASURED, not assumed (2026-07-28, `python -m pd2bot.navdemo calibrate`,
# 12 walks in 8 directions against the live client at a 1536x864 client
# area). The unscaled values would be 16/8 — one 160x80 floor-tile diamond
# over 5 subtiles — but PD2 renders at a smaller resolution and upscales,
# so the world arrives 1.25x larger. The fit came out at exactly 20/10 with
# an x/y ratio of 2.000, which is the isometric model agreeing with itself.
#
# These are display-geometry constants, not game constants: re-run the
# calibrate command after any resolution, window-size, or D2GL change.
PX_PER_SUBTILE_X = 20
PX_PER_SUBTILE_Y = 10

# How many pixels above the client-area center the player's feet are drawn.
# Calibration found no systematic offset, so 0 stands (re-check if clicks
# start landing consistently high or low).
PLAYER_ANCHOR_LIFT_PX = 0

# A single click only carries the character so far: calibration walks at
# ~360-480 px from centre consistently completed only 60-70% of the
# distance, while walks at <=320 px landed on target. Waypoints must stay
# inside the reliable range — see MAX_WAYPOINT_SPACING in pathing.py, which
# caps hops at 12 subtiles (~240 px).
RELIABLE_CLICK_RADIUS_PX = 320

# The bottom HUD strip (belt, orbs, skill buttons) swallows clicks meant for
# the world. Held as a fraction of client height rather than a pixel count:
# the interface bar scales with the window, so a fixed value silently
# becomes wrong at another resolution.
HUD_HEIGHT_FRACTION = 0.17
EDGE_MARGIN_PX = 24


@dataclass(frozen=True)
class Projection:
    """Converts between world subtiles and screen pixels for one moment.

    Built from a fresh player position and client rect; do not keep one across
    player movement — the camera follows the player, so every projection is
    relative to where they are *now*.
    """

    player_world: tuple[int, int]
    screen_center: tuple[int, int]

    def world_to_screen(self, wx: int, wy: int) -> tuple[int, int]:
        dx = wx - self.player_world[0]
        dy = wy - self.player_world[1]
        cx, cy = self.screen_center
        return (
            cx + (dx - dy) * PX_PER_SUBTILE_X,
            cy - PLAYER_ANCHOR_LIFT_PX + (dx + dy) * PX_PER_SUBTILE_Y,
        )

    def screen_to_world(self, sx: int, sy: int) -> tuple[float, float]:
        """Inverse of world_to_screen; fractional because pixels are coarser
        than the math."""
        cx, cy = self.screen_center
        a = (sx - cx) / PX_PER_SUBTILE_X  # dx - dy
        b = (sy - (cy - PLAYER_ANCHOR_LIFT_PX)) / PX_PER_SUBTILE_Y  # dx + dy
        return (self.player_world[0] + (a + b) / 2, self.player_world[1] + (b - a) / 2)


def projection_for(player_world: tuple[int, int], rect: ClientRect) -> Projection:
    return Projection(player_world=player_world, screen_center=rect.center)


def hud_height(rect: ClientRect) -> int:
    """Height of the bottom interface bar, in pixels, for this window."""
    return round(rect.height * HUD_HEIGHT_FRACTION)


def clickable(rect: ClientRect, sx: int, sy: int) -> bool:
    """True when a screen point can safely receive a world click: inside the
    client area, off the edges, and above the HUD strip."""
    return (
        rect.left + EDGE_MARGIN_PX <= sx < rect.left + rect.width - EDGE_MARGIN_PX
        and rect.top + EDGE_MARGIN_PX <= sy < rect.top + rect.height - hud_height(rect)
    )
