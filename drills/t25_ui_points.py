"""T25 — UI point calibration: briefed up front, then measured in silence
(user design, R87 and R89).

The bot sends NOTHING here. The user drives every step from memory, having
been given the whole script before anything is opened, and this only
watches. Both halves of that are load-bearing:

*Sends nothing* was the first requirement (R87): a calibration contaminated
by the bot's own clicks is one you cannot trust, and it keeps "human
calibration" and "bot control" separate runs with separate log rows.

*In silence* is the second (R89), and it came from the user diagnosing three
confusing live runs. Chat opens with Enter, and Enter into an open panel is
not a chat key — an NPC dialog takes it as choosing an option. So a drill
that prompts step-by-step through a dialog is editing the very state it is
trying to measure, and when the console fails to open the harness retries
once a second and does it again. `Chat` now refuses outright while a panel
is up; this drill goes further and says nothing at all between the briefing
and the end, because a message that cannot be delivered is not instructions
either. Everything after "TEST LIVE" is detected by watching:

    a panel opens          -> you have reached the screen
    the cursor holds still -> that is the target, captured (re-armed, R86)
    the panels settle      -> your click landed, and this is what it did

Transferability was the other requirement. Nothing here knows what Charsi
is: a target is data, and which panel it needs and what it should raise come
from `uipoints.py`. A new battery is a new list, not new code — the waypoint
destination rows calibrate through this same drill.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t25_ui_points charsi
    ... -m drills.t25_ui_points kashya      # dead-merc state only (R56)
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.perception import uistate  # noqa: E402
from pd2bot.perception.items import read_equipped_durability  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.uipoints import default_points  # noqa: E402

SETTLE_S = 1.2  # a transition counts only once the panel set stops moving
SAMPLE_S = 0.15
STILL_SAMPLES = 30  # ~3s of a held cursor


@dataclass
class Target:
    """One thing to measure. Everything panel-specific comes from the point."""

    point: str  # a name in uipoints.default_points()
    reach: str  # how the user gets to the screen it lives on
    hover_hint: str  # what to put the cursor on
    observe: object = None  # optional extra reading, e.g. durability
    # What proves the click landed. "panels": the panel set changes and
    # settles (rows, buttons — the default). "none": nothing observable
    # changes (a waypoint ACT TAB swaps the list inside the same panel,
    # M6 T69) — the capture is the hover alone, and the real proof is the
    # travel on the row clicked right after it.
    proof: str = "panels"


@dataclass
class Measured:
    point: str
    fraction: tuple[float, float]
    pixel: tuple[int, int]
    panels_before: list[str] = field(default_factory=list)
    panels_after: list[str] = field(default_factory=list)
    extra: str = ""


def durability_note(run: DrillRun) -> str:
    worn = read_equipped_durability(run.session)
    return f"{sum(d.missing for d in worn)} durability missing"


def merc_note(run: DrillRun) -> str:
    merc = Perception(run.session).snapshot().merc
    return f"merc {'alive' if merc else 'dead'}"


def area_note(run: DrillRun) -> str:
    """Where the click actually put us — the whole proof of a waypoint row.

    Read rather than assumed: the area ids in offsets are classic D2's
    numbering and have never been verified against this client.
    """
    area = Perception(run.session).snapshot().area
    if area is None:
        return "area unreadable"
    known = offsets.AREA_NAMES.get(area.level_no, "?")
    return f"arrived in area {area.level_no} ({known})"


BATTERIES: dict[str, tuple[str, tuple[Target, ...]]] = {
    "charsi": (
        "Charsi: trade/repair row, then the repair-all button",
        (
            Target(
                "charsi.trade_repair",
                "walk to CHARSI and click her so the dialog opens",
                "the TRADE/REPAIR line",
            ),
            Target(
                "charsi.repair_all",
                "the trade/repair screen is now open",
                "the REPAIR ALL EQUIPMENT button",
                observe=durability_note,
            ),
        ),
    ),
    # This battery IS the supervised round trip P3 wants: each row is proved
    # by travelling on it, so the calibration and the trip are one sitting
    # rather than two (and area ids get verified as a side effect).
    "waypoint": (
        "Waypoint: Cold Plains out, Rogue Encampment home",
        (
            Target(
                "waypoint.cold_plains",
                "click the TOWN WAYPOINT so the destination list opens",
                "the COLD PLAINS row",
                observe=area_note,
            ),
            Target(
                "waypoint.rogue_encampment",
                "now in Cold Plains, click that waypoint to reopen the list",
                "the ROGUE ENCAMPMENT row",
                observe=area_note,
            ),
        ),
    ),
    "kashya": (
        "Kashya: the resurrect row (exists only while the merc is dead, R56)",
        (
            Target(
                "kashya.resurrect",
                "with the merc DEAD, click KASHYA so the dialog opens",
                "the 'Resurrect <name>: <price>' line",
                observe=merc_note,
            ),
        ),
    ),
}


def panel_name(panel_id: int) -> str:
    return offsets.UI_NAMES.get(panel_id, f"ui_{panel_id:#x}")


def open_panels(run: DrillRun) -> frozenset[int]:
    return frozenset(uistate.read_ui_state(run.session, run.ui_array).open_panels)


def names(panels) -> list[str]:
    return sorted(panel_name(p) for p in panels)


def settled_panels(run: DrillRun, before: frozenset[int], timeout_s: float) -> list[str]:
    """Report the panel set once it has changed AND stopped moving.

    First-change reporting lies in both directions: a panel swap passes
    through a frame with neither panel up, and an animating panel raises its
    flag before it can be clicked. Only stillness separates "the click did
    nothing" from "the click is still happening" (R86).
    """
    last: frozenset[int] | None = None
    stable_since = 0.0
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        now = open_panels(run)
        if now != last:
            last, stable_since = now, run.clock()
        elif now != before and run.clock() - stable_since >= SETTLE_S:
            return names(now)
        run.sleep(SAMPLE_S)
    raise DrillAborted(
        "the panel set never changed and settled after the click — either "
        "nothing was clicked, or the click had no effect at all"
    )


def measure(run: DrillRun, target: Target) -> Measured:
    """Measure one target, saying nothing. Progress goes to stdout only."""
    point = default_points().get(target.point)
    if point is None:
        raise DrillAborted(f"unknown UI point {target.point!r}")

    print(f"\n[{target.point}] waiting for {panel_name(point.panel)} "
          f"({target.reach})", flush=True)
    if not run.wait_until(lambda: run.panel_open(point.panel), timeout_s=300):
        raise DrillAborted(
            f"{panel_name(point.panel)} never opened for {target.point}"
        )
    before = open_panels(run)
    print(f"[{target.point}] on screen with {names(before)}; "
          f"hover {target.hover_hint}", flush=True)

    got = run.capture_hover(
        required_panel=point.panel,
        last_point=None,  # arms against the live cursor (R86)
        still_samples=STILL_SAMPLES,
        timeout_s=300,
    )
    if got is None:
        raise DrillAborted(f"no hover captured for {target.point}")
    x, y, fx, fy = got
    print(f"[{target.point}] captured ({x}, {y}) -> ({fx:.4f}, {fy:.4f}) "
          f"— now click it", flush=True)

    if target.proof == "none":
        # A tab click changes no panel; the next target's travel is the
        # proof. Record the capture and move straight on.
        return Measured(
            point=target.point,
            fraction=(round(fx, 4), round(fy, 4)),
            pixel=(x, y),
            panels_before=names(before),
            panels_after=names(before),
            extra="(no panel change expected)",
        )

    after = settled_panels(run, before, timeout_s=300)
    extra = target.observe(run) if target.observe else ""
    print(f"[{target.point}] click settled to {after}"
          f"{' — ' + extra if extra else ''}", flush=True)
    return Measured(
        point=target.point,
        fraction=(round(fx, 4), round(fy, 4)),
        pixel=(x, y),
        panels_before=names(before),
        panels_after=after,
        extra=extra,
    )


def briefing(battery: str) -> tuple[str, ...]:
    """The WHOLE script, delivered before anything is open.

    This is the only chat the drill sends. It has to carry every step,
    because once the first panel is up nothing more can be said safely.
    """
    _, targets = BATTERIES[battery]
    lines = [
        "Read this ONCE - after it, the bot goes SILENT and only watches.",
        "No further prompts will appear. Work through the steps from memory.",
    ]
    for index, target in enumerate(targets, start=1):
        # Only the first letter — `.capitalize()` would lowercase CHARSI.
        reach = target.reach[:1].upper() + target.reach[1:]
        lines.append(
            f"{index}. {reach}; HOVER {target.hover_hint}, "
            "hold still 3s, THEN click it."
        )
    lines.append(
        f"{len(targets) + 1}. Close all panels when done - the bot speaks "
        "again only then."
    )
    return tuple(lines)


def make_drill(battery: str) -> tuple[Drill, object]:
    title, targets = BATTERIES[battery]
    drill = Drill(
        test_id="T25",
        title=f"UI point calibration - {title}",
        kind="human calibration",
        instructions=briefing(battery),
        sends_input=False,
    )

    def body(run: DrillRun) -> str:
        if uistate.read_ui_state(run.session, run.ui_array).blocks_input:
            raise DrillAborted(
                "a panel is already open — close everything and re-run, so "
                "the briefing above was actually deliverable and the first "
                "measurement starts from a known state"
            )
        results = [measure(run, target) for target in targets]

        print("\n--- paste-ready ---", flush=True)
        for m in results:
            print(f"    {m.point}: fraction={m.fraction}"
                  f"  # {'+'.join(m.panels_before)} -> {'+'.join(m.panels_after)}"
                  f"{'; ' + m.extra if m.extra else ''}", flush=True)

        # Only now is talking safe again — and if the user leaves a panel up,
        # the concluding line simply will not deliver, which is the guard
        # doing its job rather than a failure (R89).
        run.wait_until(
            lambda: not uistate.read_ui_state(run.session, run.ui_array).blocks_input,
            timeout_s=60,
        )
        return "; ".join(
            f"{m.point} {m.fraction} [{'+'.join(m.panels_before)} -> "
            f"{'+'.join(m.panels_after)}]{' ' + m.extra if m.extra else ''}"
            for m in results
        )

    return drill, body


if __name__ == "__main__":
    wanted = [a.lower() for a in sys.argv[1:]] or ["charsi"]
    unknown = [w for w in wanted if w not in BATTERIES]
    if unknown:
        raise SystemExit(
            f"unknown battery/batteries: {', '.join(unknown)}; "
            f"have {list(BATTERIES)}"
        )
    shared = DrillRun(GameSession())
    statuses = [run_drill(*make_drill(name), run=shared) for name in wanted]
    summary = ", ".join(f"{n} {s}" for n, s in zip(wanted, statuses, strict=True))
    print(f"\nsuite: {summary}")
    raise SystemExit(0 if all(s == "PASS" for s in statuses) else 1)
