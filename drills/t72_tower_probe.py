"""T72 — the Forgotten Tower probe: the first run under the new event log.

**Sends input: the bot plays.** Town chores, waypoint to Black Marsh,
into the Forgotten Tower, and then the one transition that has never been
explained — Tower -> Cellar 1 — after which the run stops.

Two things come out of one short run:

1. **The log's shape**, for the operator to judge. Every tick, every
   decision, every action with world / area-local / character-relative
   coordinates, and where each tick's time went.
2. **The Forgotten Tower answer.** T71 run 1 spent 144 s in that room —
   an empty 19x19-subtile box with the staircase eleven subtiles from the
   arrival point — made five staircase clicks, and gave up. The atlas and
   A* are proven innocent (one-leg route, both ends walkable); the room
   contains no monsters and never has. So ~26 s per click-cycle went
   somewhere nothing could name. This run names it.

Deliberately short. The Countess is not involved; nothing here needs to
survive a whole descent first, and a two-minute run that reaches the room
beats a five-minute one that might not.

Read the result afterwards with:

    python -m pd2bot.runlog
    python -m pd2bot.runlog --kind step.decision

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t72_tower_probe
"""

import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets, runlog  # noqa: E402
from pd2bot.drill import (  # noqa: E402
    ABORT_WORDS,
    CANCEL_FILE,
    Drill,
    DrillAborted,
    DrillRun,
    run_drill,
)
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.wiring import BotPaths, build_bot, describe  # noqa: E402

TOWER = offsets.AREA_FORGOTTEN_TOWER
CELLAR_1 = 21


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T72",
        title="Forgotten Tower probe — the first run under the event log",
        kind="bot control",
        sends_input=True,
        instructions=(
            "THE BOT PLAYS: it may leave THIS game and make its own, do",
            "the town chores, waypoint to Black Marsh, walk into the",
            "Forgotten Tower, and try to take the stairs down to Cellar 1.",
            "IT STOPS THERE — the Countess is not involved.",
            "This is the SHORT diagnostic run: the tower stairs are the",
            "transition that failed at T71, and this run is instrumented",
            "to say exactly why. Chicken 50.",
            "IT ENDS ON ITS OWN. Stop early: 'abort' in chat, ESC/Enter in",
            "the field, tools\\drill-cancel.ps1, or take the mouse.",
        ),
    )

    def body(run: DrillRun) -> str:
        aborted = [False]

        def stop_requested() -> bool:
            if aborted[0]:
                return True
            try:
                if CANCEL_FILE.exists():
                    aborted[0] = True
                    return True
            except OSError:
                pass
            if run.heard(ABORT_WORDS):
                aborted[0] = True
                return True
            return False

        bot = build_bot(
            paths=replace(BotPaths(), run=REPO / "runs" / "m6-tower-probe.toml"),
            chicken_life_pct=50.0,  # a cellar drill, not a proper run (R212 Q8)
            should_stop=stop_requested,
        )
        for line in describe(bot):
            print(line, flush=True)

        started = time.monotonic()
        report = bot.cycle().run_games(bot.runner(), max_games=1)
        duration = time.monotonic() - started

        print(f"\n{report.summary() if hasattr(report, 'summary') else report}")
        game_lines = []
        for index, engine in enumerate(bot.engines(), start=1):
            summary = engine.report.summary()
            print(f"\n--- game {index}: {summary} ---")
            for line in engine.report.log:
                print(f"  {line}")
            game_lines.append(summary)

        # THE ARTIFACT. Printed in full: this run exists to be read.
        events = "none written"
        tower_ticks = 0
        try:
            opened = getattr(bot, "_runlogs", [])
            if opened:
                directory = opened[-1].directory
                events = str(directory.relative_to(REPO))
                entries = runlog.load(directory)
                print(f"\n=== EVENT LOG: {events} ({len(entries)} events) ===")
                for line in runlog.render(entries):
                    print(f"  {line}")
                for line in runlog.summarize(entries):
                    print(f"  {line}")
                # The question this run was launched to answer, counted
                # rather than eyeballed.
                tower_ticks = sum(
                    1 for e in entries
                    if e.get("kind") == "tick" and e.get("area") == TOWER
                )
                print(f"\n  ticks spent in the Forgotten Tower: {tower_ticks}")
        except Exception as exc:  # noqa: BLE001 - reporting must not raise
            events = f"unreadable: {type(exc).__name__}"

        landed = "not in a game (the run left, as designed)"
        try:
            snap = Perception(run.session).snapshot()
            if snap.area is not None:
                landed = (
                    f"area {snap.area.level_no} "
                    f"({offsets.AREA_NAMES.get(snap.area.level_no, '?')})"
                )
        except Exception as exc:  # noqa: BLE001
            landed = f"post-run read failed: {type(exc).__name__}"

        if aborted[0]:
            raise DrillAborted("stopped by request mid-run")

        cycle_summary = (
            report.summary() if hasattr(report, "summary") else str(report)
        )
        done_steps = [
            s for engine in bot.engines() for s in engine.report.steps_completed
        ]
        traverses = sum(1 for s in done_steps if s == "traverse")
        result = (
            f"{duration:.0f}s; {cycle_summary}; "
            + "; ".join(f"game {i + 1}: {s}" for i, s in enumerate(game_lines))
            + f"; traverses {traverses}/2; tower ticks {tower_ticks}"
            + f"; ended: {landed}; events: {events}"
        )
        if traverses < 1:
            raise RuntimeError(f"never reached the Forgotten Tower: {result}")
        # Both transitions REQUIRED (review 001, 2026-08-06). This drill
        # once passed on a reproduced failure, which was right while the
        # event log was the deliverable — a failure WITH a log was the
        # outcome it existed to produce. The fix has since landed and been
        # verified live (run 2: 4.3 s, 2/2, clean), so a failed crossing is
        # now a REGRESSION. A drill that can pass without doing the thing
        # it tests is the shape this repo keeps paying for.
        if traverses < 2:
            raise RuntimeError(
                "the tower-stairs transition FAILED — fixed on 2026-08-06 "
                "(T72 run 2: 4.3 s, 16 ticks, 2/2), so this is a "
                f"REGRESSION; the event log has the detail: {result}"
            )
        return result

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
