"""T84 — record a route line: you walk the route, the bot remembers it.

Map-agnostic by design (R241 Q2/the user's request): run it in ANY
area — Cold Plains today, Blood Raven or the Arcane Sanctuary when
those runs are planned — and it records the core path for the area you
are standing in, keyed by (map seed, difficulty, area), stored beside
the atlas as `line-<area>.json`.

READ-ONLY: samples your position once a second; sends nothing.

Protocol: walk the route you want the bot to treat as its core path,
start to finish, at your own pace (fighting along the way is fine — the
recorder samples POSITIONS, and detours are thinned out only if they
stay within the tolerance; big detours become part of the line, so
prefer a reasonably direct walk). Type END in chat when you reach the
route's end. Crossing into a NEW area ends the current area's line and
starts recording the next — one walk can lay down a whole descent.
"""

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.nav.routeline import RouteLine, save_line, thin  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.world import read_area, read_map_seed  # noqa: E402

DIFFICULTY = 2  # Hell — the only difficulty this character runs
POLL_S = 1.0
SAY_PATIENCE_S = 2.5
END_WORDS = frozenset({"end", "end test", "done"})
DEFAULT_SECONDS = 1800.0
THIN_TOLERANCE = 3.0  # subtiles of wobble collapsed out of the walk
MIN_POINTS = 2  # a shorter trace than this is a non-walk, not a line

T84 = Drill(
    test_id="T84",
    title="record a route line — you walk, the bot remembers the path",
    kind="human calibration",
    sends_input=False,
    instructions=(
        "WALK the route you want as the run's core path, start to end.",
        "Reasonably direct: big detours become part of the line.",
        "Crossing into a new area starts that area's line automatically.",
        "TYPE 'END' IN CHAT at the route's end (or 'done').",
        "Cancel any time: 'abort' in chat, or tools\\drill-cancel.ps1",
    ),
)


def t84_body(run: DrillRun, seconds: float = DEFAULT_SECONDS) -> str:
    session = run.session
    started = time.monotonic()
    # area_id -> ordered trace of positions walked in that area, in the
    # order areas were entered (dict preserves insertion order).
    traces: dict[int, list[tuple[int, int]]] = {}
    seed_seen: int | None = None
    ending = f"the {seconds:.0f}s backstop"

    while time.monotonic() - started < seconds:
        run.check_cancel()
        if run.heard(END_WORDS):
            ending = "the user typed END"
            break
        time.sleep(POLL_S)

        area = read_area(session)
        seed = read_map_seed(session)
        player = read_player(session)
        if area is None or seed is None or player is None:
            continue  # mid-transition; keep walking
        if seed_seen is None:
            seed_seen = seed
        elif seed != seed_seen:
            raise RuntimeError(
                f"the map seed changed mid-recording ({seed_seen:#x} -> "
                f"{seed:#x}) — a new game was created; record in ONE game"
            )
        trace = traces.setdefault(area.level_no, [])
        if not trace and len(traces) > 1:
            run.say(
                f"area {area.level_no}: recording its line now.",
                patience_s=SAY_PATIENCE_S,
            )
        if not trace or trace[-1] != player.position:
            trace.append(player.position)

    if seed_seen is None or not traces:
        raise RuntimeError(
            "never saw a readable position — was a game running the whole time?"
        )

    parts = []
    for area_id, trace in traces.items():
        if len(trace) < MIN_POINTS:
            parts.append(f"area {area_id}: trace too short, NOT saved")
            continue
        points = thin(trace, THIN_TOLERANCE)
        line = RouteLine(seed_seen, DIFFICULTY, area_id, points)
        path = save_line(line, REPO / "maps")
        parts.append(
            f"area {area_id}: {len(trace)} samples -> {len(points)} "
            f"waypoints, {line.length:.0f} subtiles ({path.name})"
        )
    summary = "; ".join(parts)
    print(f"\n  {summary}", flush=True)
    run.say(f"T84 DONE — {summary}", patience_s=10.0)
    return f"stopped on {ending}; {summary}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=T84.title)
    parser.add_argument(
        "--seconds", type=float, default=DEFAULT_SECONDS,
        help="backstop duration before the recorder gives up",
    )
    args = parser.parse_args()
    run_drill(T84, lambda run: t84_body(run, seconds=args.seconds))
