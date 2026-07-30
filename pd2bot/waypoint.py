"""Waypoint travel: click the waypoint object, pick a destination, verify
arrival — every step proven by perception, never by hope.

The flow (M5 P3; the route decision is R46 Q1 — waypoints are how all
future runs will move between areas):

    find the waypoint object (P1's object scan)
    -> walk near it (M3's navigator)
    -> confirm the waypoint panel is CLOSED (the 0 side of the edge)
    -> gated world click on the object
    -> watch the panel flag go 0 -> 1 (THE EDGE — see below)
    -> PanelInput click on the destination row (hover-calibrated fraction)
    -> poll until the area id reads the destination and the player is back
    -> confirm the panel is gone

Why the edge and not just "is the panel open": the waypoint slot (0x14)
carries two conflicting live observations — M2 saw it stuck at 1, P2's
controlled drill saw it toggle cleanly (see uistate.py). The fail-safe
resolution is to require the 0 -> 1 *transition* attributable to our own
click. If the slot is ever stuck at 1 again, this flow refuses at the
first step instead of clicking rows into a panel that may not exist
(uistate.py also put the slot in the blocking set, so a stuck flag halts
world input loudly rather than silently).

Row positions are client-rect fractions, hover-calibrated per destination
(M4's Save-and-Exit precedent: the panel has no readable control structs).
An uncalibrated destination refuses before any click. Re-calibrate after
any window or resolution change.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot import offsets, uistate
from pd2bot.input import GatedInput, InputRefused
from pd2bot.memory import GameSession
from pd2bot.panelinput import PanelInput
from pd2bot.units import GameObject
from pd2bot.world import read_area


class WaypointError(RuntimeError):
    """Waypoint travel failed; the message names the step."""


@dataclass(frozen=True)
class WaypointConfig:
    # Destination rows as client-rect fractions, hover-calibrated (P3
    # drill). Keyed by area id. Empty entries refuse rather than guess.
    row_fractions: dict[int, tuple[float, float]] = field(default_factory=dict)
    walk_within: int = 5  # subtiles from the waypoint object before clicking
    open_timeout_s: float = 5.0
    click_retries: int = 2  # re-clicks on the object if the panel stays shut
    travel_timeout_s: float = 30.0  # row click -> arrival (includes the load)
    poll_s: float = 0.2


@dataclass
class TravelReport:
    dest_area: int
    clicks: int = 0
    arrived: bool = False
    log: list[str] = field(default_factory=list)


class WaypointTravel:
    """Drives one waypoint trip. All timing injectable; tests use fakes."""

    def __init__(
        self,
        session: GameSession,
        gated: GatedInput,
        panel: PanelInput,
        walk_to: Callable[[tuple[int, int]], object],
        find_waypoint: Callable[[], GameObject | None],
        config: WaypointConfig | None = None,
        *,
        ui_array: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        self.gated = gated
        self.panel = panel
        self.walk_to = walk_to
        self.find_waypoint = find_waypoint
        self.config = config if config is not None else WaypointConfig()
        self._ui_array = (
            ui_array if ui_array is not None else uistate.find_ui_array(session)
        )
        self._clock = clock
        self._sleep = sleep

    # -- pieces, each verifiable on its own -----------------------------------

    def _panel_open(self) -> bool:
        state = uistate.read_ui_state(self.session, self._ui_array)
        return state.is_open(offsets.UI_WPMENU)

    def open_panel(self, report: TravelReport) -> None:
        """Walk to the waypoint object and click it until the panel edge."""
        waypoint = self.find_waypoint()
        if waypoint is None:
            raise WaypointError("no waypoint object in perception range")
        self.walk_to(waypoint.position)
        report.log.append(f"at waypoint object {waypoint.position}")

        if self._panel_open():
            # The 0-side of the edge failed: either something else opened the
            # panel, or the slot is stuck at 1 (the M2 observation). Refuse —
            # a row click into an unverifiable panel is the M1 shape.
            raise WaypointError(
                "the waypoint panel already reads open before our click — "
                "cannot attribute the panel to ourselves; refusing to click "
                "rows (stuck-flag suspicion, see uistate.py)"
            )

        for attempt in range(1 + self.config.click_retries):
            fresh = self.find_waypoint()
            if fresh is not None:
                waypoint = fresh
            self.gated.click_world(*waypoint.position)
            report.clicks += 1
            deadline = self._clock() + self.config.open_timeout_s
            while self._clock() < deadline:
                if self._panel_open():
                    report.log.append(f"panel edge 0->1 after click {attempt + 1}")
                    return
                self._sleep(self.config.poll_s)
        raise WaypointError(
            f"waypoint panel never opened after {report.clicks} clicks on the object"
        )

    def click_destination(self, dest_area: int, report: TravelReport) -> None:
        fraction = self.config.row_fractions.get(dest_area)
        if fraction is None:
            raise WaypointError(
                f"destination area {dest_area} has no calibrated row — run the "
                "hover calibration before travel is allowed"
            )
        rect = self.panel.window.client_rect()
        sx = rect.left + round(fraction[0] * rect.width)
        sy = rect.top + round(fraction[1] * rect.height)
        self.panel.click(offsets.UI_WPMENU, sx, sy)
        report.log.append(f"destination row clicked at ({sx}, {sy})")

    def await_arrival(self, dest_area: int, report: TravelReport) -> None:
        deadline = self._clock() + self.config.travel_timeout_s
        while self._clock() < deadline:
            try:
                area = read_area(self.session)
            except Exception:
                area = None  # mid-load reads tear; that is the normal path
            if area is not None and area.level_no == dest_area and not self._panel_open():
                report.arrived = True
                report.log.append(f"arrived: area {dest_area}")
                return
            self._sleep(self.config.poll_s)
        raise WaypointError(
            f"never observed arrival in area {dest_area} within "
            f"{self.config.travel_timeout_s:.0f}s of the row click"
        )

    # -- the trip ---------------------------------------------------------------

    def take(self, dest_area: int) -> TravelReport:
        """Travel to `dest_area` via the waypoint. Raises WaypointError with
        the failed step; InputRefused propagates (the cycle owns focus
        policy, not this module)."""
        report = TravelReport(dest_area=dest_area)
        # Refuse before any movement if the destination is uncalibrated —
        # walking first and failing later would strand the bot at the
        # waypoint with a half-done step.
        if dest_area not in self.config.row_fractions:
            raise WaypointError(
                f"destination area {dest_area} has no calibrated row — run the "
                "hover calibration before travel is allowed"
            )
        try:
            self.open_panel(report)
            self.click_destination(dest_area, report)
            self.await_arrival(dest_area, report)
        except InputRefused:
            raise
        return report
