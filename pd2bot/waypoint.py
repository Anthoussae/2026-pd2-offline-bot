"""Waypoint travel: open the panel, pick a destination, verify arrival —
every step proven by perception, never by hope.

The flow (M5 P3; the route decision is R46 Q1 — waypoints are how all
future runs will move between areas):

    confirm the waypoint panel is CLOSED (the 0 side of the edge)
    -> approach and click the waypoint object, panel verified open
    -> click the destination row (a calibrated UIPoint)
    -> watch the panel go away, then poll until the area id is the
       destination

Why the edge and not just "is the panel open": the waypoint slot (0x14)
carries two conflicting live observations — M2 saw it stuck at 1, P2's
controlled drill saw it toggle cleanly (see uistate.py). The fail-safe
resolution is to require the 0 -> 1 *transition* attributable to our own
click. If the slot is ever stuck at 1 again, this flow refuses at the first
step instead of clicking rows into a panel that may not exist.

**Everything else here is delegated on purpose** (R87). Approaching a world
object, clicking it, waiting out the walk it triggers, recovering when a
travel click opens some bystander's panel, settling before an in-panel
click and retrying it — the town layer paid for every one of those live,
several of them twice. This module owned a second, naive copy of all of
them: it walked ONTO the waypoint (so its own travel click could open the
panel and trip the edge check above), gave up if the object was out of
perception range, and clicked the destination row exactly once with no
settle and no retry — the identical defect that cost three live runs at
Charsi's dialog. None of that is re-solved here; it is the same
`InteractionLayer` the town steps use.

What remains genuinely waypoint-specific is the edge discipline and the
arrival proof: an area id that reads as the destination. A row click that
lands wrong leaves you where you were, and this says so.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot import offsets
from pd2bot.input import InputRefused
from pd2bot.perception import uistate
from pd2bot.perception.memory import GameSession
from pd2bot.perception.world import read_area
from pd2bot.town import TownLayer


class WaypointError(RuntimeError):
    """Waypoint travel failed; the message names the step."""


@dataclass(frozen=True)
class WaypointConfig:
    # Area id -> the calibrated UIPoint naming its row. The fractions
    # themselves live in uipoints.py with their provenance; an area absent
    # here, or present but uncalibrated, refuses before anything moves.
    destination_points: dict[int, str] = field(
        default_factory=lambda: {
            offsets.AREA_COLD_PLAINS: "waypoint.cold_plains",
            offsets.AREA_ROGUE_ENCAMPMENT: "waypoint.rogue_encampment",
            offsets.AREA_BLACK_MARSH: "waypoint.black_marsh",
            offsets.AREA_ARCANE_SANCTUARY: "waypoint.arcane_sanctuary",
            offsets.AREA_HALLS_OF_PAIN: "waypoint.halls_of_pain",
        }
    )
    # Area id -> the ACT TAB to click before the row (M6 P2, T69). The
    # tab is clicked for EVERY destination, unconditionally: clicking the
    # already-active tab is harmless, and "which tab is showing" is not
    # readable from memory — an unconditional click needs no such read.
    destination_tabs: dict[int, str] = field(
        default_factory=lambda: {
            offsets.AREA_COLD_PLAINS: "waypoint.tab_act1",
            offsets.AREA_ROGUE_ENCAMPMENT: "waypoint.tab_act1",
            offsets.AREA_BLACK_MARSH: "waypoint.tab_act1",
            offsets.AREA_ARCANE_SANCTUARY: "waypoint.tab_act2",
            offsets.AREA_HALLS_OF_PAIN: "waypoint.tab_act5",
        }
    )
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
        interact: TownLayer,
        config: WaypointConfig | None = None,
        *,
        ui_array: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        # Named `interact` rather than `town` because nothing it does here is
        # town-specific — only its configured fallback positions are, and the
        # far-end waypoint is one we arrive standing on.
        self.interact = interact
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
        """Get to the waypoint and open its panel, attributably."""
        if self._panel_open():
            # The 0-side of the edge failed: either something else opened the
            # panel, or the slot is stuck at 1 (the M2 observation). Refuse —
            # a row click into an unverifiable panel is the M1 shape.
            raise WaypointError(
                "the waypoint panel already reads open before our click — "
                "cannot attribute the panel to ourselves; refusing to click "
                "rows (stuck-flag suspicion, see uistate.py)"
            )
        position = self.interact.open_object_panel(
            offsets.OBJ_WAYPOINT_A1, "waypoint", offsets.UI_WPMENU
        )
        report.clicks += 1
        report.log.append(f"panel edge 0->1 at waypoint object {position}")
        self.interact.runlog.event("waypoint.open", position=list(position))

    def select_tab(self, dest_area: int, report: TravelReport) -> None:
        """Click the destination's act tab (M6 P2). No-op for areas with
        no configured tab (none exist today — every destination names one).

        A tab click has no observable effect of its own (the list swaps
        inside the same panel), so its condition is only "the panel is
        still open" — one settled click, no blind retries. The real proof
        is downstream: the ROW click closes the panel and the ARRIVAL
        reads the area id, and a tab misclick that closed the panel makes
        the row click fail loudly instead of clicking into nothing.
        """
        tab_name = self.config.destination_tabs.get(dest_area)
        if tab_name is None:
            return
        tab = self.interact.point(tab_name)
        self.interact.click_point(tab, lambda: self._panel_open())
        report.clicks += 1
        report.log.append(f"act tab {tab.name} clicked, panel still open")
        self.interact.runlog.event("waypoint.tab", tab=tab.name)

    def click_destination(self, dest_area: int, report: TravelReport) -> None:
        point = self.interact.point(self._point_name(dest_area))
        # The row's immediate, observable effect is the list going away; the
        # area change follows a loading screen and is checked separately, so
        # a click that misses retries here rather than burning the travel
        # budget waiting for an arrival that was never coming.
        self.interact.click_point(point, lambda: not self._panel_open())
        report.log.append(f"destination row {point.name} clicked, panel closed")
        self.interact.runlog.event(
            "waypoint.select", row=point.name, dest_area=dest_area,
            dest_name=offsets.AREA_NAMES.get(dest_area, f"area {dest_area}"),
        )

    def await_arrival(self, dest_area: int, report: TravelReport) -> None:
        deadline = self._clock() + self.config.travel_timeout_s
        while self._clock() < deadline:
            self.interact._check_stop()
            try:
                area = read_area(self.session)
            except Exception:
                area = None  # mid-load reads tear; that is the normal path
            if area is not None and area.level_no == dest_area and not self._panel_open():
                report.arrived = True
                report.log.append(f"arrived: area {dest_area}")
                self.interact.runlog.event(
                    "waypoint.arrived", dest_area=dest_area,
                    dest_name=offsets.AREA_NAMES.get(
                        dest_area, f"area {dest_area}"
                    ),
                )
                return
            self._sleep(self.config.poll_s)
        where = "unreadable"
        try:
            current = read_area(self.session)
            if current is not None:
                where = str(current.level_no)
        except Exception:
            pass
        raise WaypointError(
            f"never observed arrival in area {dest_area} within "
            f"{self.config.travel_timeout_s:.0f}s of the row click — still "
            f"reading area {where}"
        )

    # -- the trip ---------------------------------------------------------------

    def _point_name(self, dest_area: int) -> str:
        name = self.config.destination_points.get(dest_area)
        if name is None:
            known = ", ".join(
                f"{a} ({offsets.AREA_NAMES.get(a, '?')})"
                for a in sorted(self.config.destination_points)
            )
            raise WaypointError(
                f"area {dest_area} is not a configured waypoint destination "
                f"(have: {known})"
            )
        return name

    def take(self, dest_area: int) -> TravelReport:
        """Travel to `dest_area` via the waypoint. Raises WaypointError with
        the failed step; InputRefused propagates (the cycle owns focus
        policy, not this module)."""
        report = TravelReport(dest_area=dest_area)
        # Resolve the row BEFORE any movement: an unknown or uncalibrated
        # destination can only fail, and walking to the waypoint first would
        # strand the bot there having learned nothing.
        self.interact.point(self._point_name(dest_area))
        # Start from a state where walking is legal — a panel left open by
        # whatever ran before makes the very first click illegal (T13).
        self.interact.close_panels()
        try:
            self.open_panel(report)
            self.select_tab(dest_area, report)
            self.click_destination(dest_area, report)
            self.await_arrival(dest_area, report)
        except InputRefused:
            raise
        return report
