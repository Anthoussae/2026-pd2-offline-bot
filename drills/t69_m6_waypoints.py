"""T69 — M6 waypoint calibration: act tabs + the three new rows.

T25's battery machinery verbatim (silent after each briefing, captures
by held cursor, rows proven by TRAVELLING on them); what is new is the
tab targets (`proof="none"` — a tab click swaps the list inside the
same panel, so the following row's travel is its proof) and the route:

    town (Act I list)      -> BLACK MARSH row          -> Black Marsh
    Black Marsh waypoint   -> ACT II tab, ARCANE row   -> Arcane Sanctuary
    Arcane waypoint        -> ACT V tab, HALLS row     -> Halls of Pain
    Halls waypoint         -> ACT I tab, ROGUE row     -> home

Four short batteries, one briefing each, panels closed between — so
every briefing is deliverable (the R89 rule). Area ids are read on
every arrival (Q1): Black Marsh expects 6; Arcane Sanctuary and Halls
of Pain record whatever the client says, which BECOMES the constant.

Run from the repo root (the whole chain in one command):
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t69_m6_waypoints
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drills.t25_ui_points import (  # noqa: E402
    Target,
    area_note,
    measure,
)
from pd2bot import uistate  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402

BATTERIES: dict[str, tuple[str, tuple[Target, ...]]] = {
    "black_marsh": (
        "Black Marsh row (Act I list)",
        (
            Target(
                "waypoint.black_marsh",
                "in town, click the TOWN WAYPOINT so the list opens",
                "the BLACK MARSH row",
                observe=area_note,
            ),
        ),
    ),
    "arcane": (
        "Act II tab, then the Arcane Sanctuary row",
        (
            Target(
                "waypoint.tab_act2",
                "in Black Marsh, click the WAYPOINT so the list opens",
                "the ACT II tab",
                proof="none",
            ),
            Target(
                "waypoint.arcane_sanctuary",
                "the Act II list is now showing",
                "the ARCANE SANCTUARY row",
                observe=area_note,
            ),
        ),
    ),
    "halls": (
        "Act V tab, then the Halls of Pain row",
        (
            Target(
                "waypoint.tab_act5",
                "in the Arcane Sanctuary, click the WAYPOINT so the list opens",
                "the ACT V tab",
                proof="none",
            ),
            Target(
                "waypoint.halls_of_pain",
                "the Act V list is now showing",
                "the HALLS OF PAIN row",
                observe=area_note,
            ),
        ),
    ),
    "home": (
        "Act I tab, then home to the Rogue Encampment",
        (
            Target(
                "waypoint.tab_act1",
                "in the Halls of Pain, click the WAYPOINT so the list opens",
                "the ACT I tab",
                proof="none",
            ),
            Target(
                "waypoint.rogue_encampment",
                "the Act I list is now showing",
                "the ROGUE ENCAMPMENT row",
                observe=area_note,
            ),
        ),
    ),
}


def make_drill(battery: str) -> tuple[Drill, object]:
    title, targets = BATTERIES[battery]
    drill = Drill(
        test_id="T69",
        title=f"M6 waypoint calibration - {title}",
        kind="human calibration",
        instructions=_briefing(battery),
        sends_input=False,
    )

    def body(run: DrillRun) -> str:
        if uistate.read_ui_state(run.session, run.ui_array).blocks_input:
            raise DrillAborted(
                "a panel is already open — close everything so the briefing "
                "was deliverable and measurement starts from a known state"
            )
        results = [measure(run, target) for target in targets]
        print("\n--- paste-ready ---", flush=True)
        for m in results:
            print(f"    {m.point}: fraction={m.fraction}"
                  f"{'; ' + m.extra if m.extra else ''}", flush=True)
        run.wait_until(
            lambda: not uistate.read_ui_state(
                run.session, run.ui_array
            ).blocks_input,
            timeout_s=120,
        )
        return "; ".join(
            f"{m.point} {m.fraction}"
            f"{' ' + m.extra if m.extra else ''}"
            for m in results
        )

    return drill, body


def _briefing(battery: str) -> tuple[str, ...]:
    _, targets = BATTERIES[battery]
    lines = [
        "Read ONCE - the bot then goes SILENT and only watches.",
    ]
    for index, target in enumerate(targets, start=1):
        reach = target.reach[:1].upper() + target.reach[1:]
        lines.append(
            f"{index}. {reach}; HOVER {target.hover_hint}, "
            "hold still 3s, THEN click it."
        )
    lines.append("Then close any panels - the next briefing follows.")
    return tuple(lines)


if __name__ == "__main__":
    order = ["black_marsh", "arcane", "halls", "home"]
    shared = DrillRun(GameSession())
    statuses = []
    for name in order:
        status = run_drill(*make_drill(name), run=shared)
        statuses.append(status)
        if status != "PASS":
            break  # a broken chain cannot reach the next battery's start
    summary = ", ".join(
        f"{n} {s}" for n, s in zip(order, statuses, strict=False)
    )
    print(f"\nsuite: {summary}")
    raise SystemExit(0 if all(s == "PASS" for s in statuses) else 1)
