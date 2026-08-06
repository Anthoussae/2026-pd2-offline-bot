"""T70 — the traversal drills: the bot's first autonomous area changes.

**Sends input: the bot plays.** Two stages, run separately so a failure
names one thing:

    one      town -> Black Marsh -> Forgotten Tower   (ONE transition)
    descent  ... -> Tower Cellar 1..5                 (seven in a row)

Every transition is proven by the area id (nothing counts floors), so a
missed or mis-aimed staircase fails the step that expected it instead of
continuing one level out of place. Brisk posture throughout: fight only
what obstructs the corridor (R212 Q4/Q5). Chicken 50 for these drills —
the cellars are meaner than Cold Plains, and 35 comes back for proper
runs (R212 Q8).

The Countess is NOT engaged: the descent stops on arrival in Cellar 5.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t70_traverse one
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t70_traverse descent
"""

import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import (  # noqa: E402
    ABORT_WORDS,
    CANCEL_FILE,
    Drill,
    DrillAborted,
    DrillRun,
    run_drill,
)
from pd2bot.exits import read_level_exits  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.wiring import BotPaths, build_bot, describe  # noqa: E402

STAGES = {
    "one": (
        "one transition — town to the Forgotten Tower",
        "m6-traverse-one.toml",
        offsets.AREA_FORGOTTEN_TOWER,
    ),
    "descent": (
        "the full descent — town to Tower Cellar Level 5",
        "m6-descent.toml",
        offsets.AREA_TOWER_CELLAR_5,
    ),
}


def make_drill(stage: str) -> tuple[Drill, object]:
    title, run_file, expect_area = STAGES[stage]

    drill = Drill(
        test_id="T70",
        title=f"traversal — {title}",
        kind="bot control",
        sends_input=True,
        instructions=(
            "THE BOT PLAYS: it may leave THIS game and create its own,",
            "run the town chores, waypoint out, and walk into the "
            "staircases.",
            "Watch the transitions — each one is proven by the area id.",
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
            paths=replace(BotPaths(), run=REPO / "runs" / run_file),
            chicken_life_pct=50.0,  # R212 Q8: raised for the cellar drills
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

        # Where the character actually ended up, and what that area's
        # exits look like — the drill's own reading, independent of the
        # engine's opinion. (The run leaves the game at `done`, so this
        # is usually the menus; the ENGINE log carries the arrivals.)
        landed = "not in a game (the run left, as designed)"
        try:
            snap = Perception(run.session).snapshot()
            if snap.area is not None:
                scan = read_level_exits(run.session)
                exits = (
                    ", ".join(
                        f"{e.dest_area}@{e.position}" for e in scan.exits
                    )
                    if scan is not None
                    else "unreadable"
                )
                landed = (
                    f"area {snap.area.level_no} "
                    f"({offsets.AREA_NAMES.get(snap.area.level_no, '?')}); "
                    f"exits: {exits or 'none'}"
                )
        except Exception as exc:  # noqa: BLE001 - reporting must not raise
            landed = f"post-run read failed: {type(exc).__name__}"

        if aborted[0]:
            raise DrillAborted("stopped by request mid-run")
        cycle_summary = (
            report.summary() if hasattr(report, "summary") else str(report)
        )
        result = (
            f"{duration:.0f}s; {cycle_summary}; "
            + "; ".join(f"game {i + 1}: {s}" for i, s in enumerate(game_lines))
            + f"; ended: {landed}"
        )
        if getattr(report, "completed", None) == 0:
            raise RuntimeError(f"no clean cycle: {result}")
        # How far down it actually got: the engine's own completed-step
        # list, counted against the run file's traverse steps. A cycle
        # that reports clean while half the descent never happened is
        # exactly the shape T53 run 1 taught us to check for out loud.
        done_steps = [
            s for engine in bot.engines() for s in engine.report.steps_completed
        ]
        traverses = sum(1 for s in done_steps if s == "traverse")
        wanted = sum(
            1
            for engine in bot.engines()
            for s in engine.step_names
            if s == "traverse"
        )
        result += f"; traverses {traverses}/{wanted} (target area {expect_area})"
        if traverses < wanted:
            raise RuntimeError(f"the descent stopped short: {result}")
        return result

    return drill, body


if __name__ == "__main__":
    stage = (sys.argv[1] if len(sys.argv) > 1 else "one").lower()
    if stage not in STAGES:
        raise SystemExit(f"unknown stage {stage!r}; have {list(STAGES)}")
    status = run_drill(*make_drill(stage), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
