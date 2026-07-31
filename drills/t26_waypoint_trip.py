"""T26 — the bot takes the waypoint round trip (bot control).

The human half of this was T25's waypoint battery: the user travelled both
ways and both rows are calibrated by arrival. This is the same journey with
the bot driving, and it is the last P3 capability the trial run needs —
after this, everything between "in town" and "at the Cold Plains waypoint"
is machine-driven.

    town -> open the waypoint panel (0->1 edge, attributable)
         -> click COLD PLAINS, verified by the area id
    Cold Plains -> open the panel again (we arrive standing on it)
         -> click ROGUE ENCAMPMENT, verified by the area id

Danger note, deliberately kept in view: the bot has no combat, no reflexes
and no chicken behaviour in this drill — those are P4/P5. Hell Cold Plains
can kill an idle character (user assessment, R47), so the return leg is
taken IMMEDIATELY on arrival, with no pause, and the whole exposure is a
few seconds standing on the waypoint. If anything goes wrong the trip is
stoppable from outside like any other (`tools/drill-cancel.ps1`), and the
death latch remains inviolable: after a death the bot sends nothing, ever.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t26_waypoint_trip
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402
from pd2bot.waypoint import WaypointTravel  # noqa: E402

T26 = Drill(
    test_id="T26",
    title="Bot takes the waypoint round trip (town <-> Cold Plains)",
    kind="bot control",
    instructions=(
        "SETUP: stand in town with all panels closed; hands off throughout.",
        "The bot will waypoint to Cold Plains and come straight back.",
        "It has NO combat: it returns immediately on arrival. Cancel with "
        "drill-cancel if anything looks wrong.",
    ),
    sends_input=True,
)


def build_travel(run: DrillRun) -> WaypointTravel:
    session = run.session
    navigator = live_navigator(session, MapStore(), offsets.DIFFICULTY_HELL)
    interact = TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=navigator.walk_to,
        snapshot=Perception(session).snapshot,
        config=TownConfig(),
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )
    return WaypointTravel(session=session, interact=interact, ui_array=run.ui_array)


def area_of(run: DrillRun) -> int | None:
    area = Perception(run.session).snapshot().area
    return area.level_no if area is not None else None


def t26_body(run: DrillRun) -> str:
    travel = build_travel(run)
    start = area_of(run)
    if start != offsets.AREA_ROGUE_ENCAMPMENT:
        raise DrillAborted(
            f"start in town: this reads area {start} "
            f"({offsets.AREA_NAMES.get(start, '?')}), not the Rogue Encampment"
        )

    out = travel.take(offsets.AREA_COLD_PLAINS)
    print(f"outbound: {'; '.join(out.log)}", flush=True)
    # Straight back — no pause, because standing still in Hell is the risk
    # this drill is deliberately minimising.
    home = travel.take(offsets.AREA_ROGUE_ENCAMPMENT)
    print(f"return: {'; '.join(home.log)}", flush=True)

    end = area_of(run)
    if end != offsets.AREA_ROGUE_ENCAMPMENT:
        raise DrillAborted(f"ended in area {end}, not back in town")
    return (
        f"round trip OK: area {start} -> {out.dest_area} -> {end}; "
        f"{out.clicks + home.clicks} object clicks; "
        f"out [{'; '.join(out.log)}]; back [{'; '.join(home.log)}]"
    )


SUITE = {"T26": (T26, t26_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T26"], run=shared)
    print(f"\nsuite: T26 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
