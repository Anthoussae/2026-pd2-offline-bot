"""T53 — the patrol acceptance run, as a formal test (R177 run 3).

**This test SENDS INPUT: the bot plays.** After the OK gate the bot owns
the character for one full game — it may leave the game you are standing
in, create a fresh Hell game, run the town preamble, waypoint to Cold
Plains, clear the patrol circle, sweep it, and leave. Hands off unless
you are taking over.

## What one run validates (all landed this session, none live-proven)

- **Cleanse drop hygiene** (P1): junk is dropped clear of wanted items,
  the bot steps off the pile, and no drop-and-scoop loop can form.
- **The reposition rung** (P2): sustained chip damage while standing
  still produces a sidestep, not a slow burn to chicken.
- **Full-atlas pathing**: the first fighting run since Cold Plains hit
  frontier-zero — walks should plan around walls from the start, and an
  unreachable monster should be written off on the FIRST failed walk.
- **The click audit** rides along, priced against the R167 baseline
  (31/39 accidental exemptions then; ~0 expected now).

## How it ends

On its own, after one game (several minutes): the cycle leaves the game
and the drill reports the run summary. Stopping early: type **abort** in
chat (checked between bot actions — best effort), run
`tools\\drill-cancel.ps1`, or simply take the mouse / press ESC — the
foreground guard stops every send instantly, always.
"""

import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot.drill import (  # noqa: E402
    ABORT_WORDS,
    CANCEL_FILE,
    Drill,
    DrillAborted,
    DrillRun,
    run_drill,
)
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.wiring import BotPaths, build_bot, describe  # noqa: E402

T53 = Drill(
    test_id="T53",
    title="patrol acceptance — cleanse hygiene, reposition, full-atlas pathing",
    kind="bot control",
    sends_input=True,
    instructions=(
        "THE BOT PLAYS one full game: preamble, waypoint, patrol clearance,",
        "sweep, leave. It may leave THIS game and create its own.",
        "IT ENDS ON ITS OWN after one game (several minutes).",
        "Stop early: 'abort' in chat, tools\\drill-cancel.ps1, or just",
        "take the mouse / press ESC — your hands always win.",
    ),
)


def t53_body(run: DrillRun) -> str:
    aborted = [False]

    def stop_requested() -> bool:
        """The drill's stop channels, offered to the bot as `should_stop`.

        Returns rather than raises: the bot's own layers decide how to
        wind down. Best-effort by nature — the foreground guard (take
        the mouse) is the always-works stop, and the instructions say so.
        """
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
        paths=replace(BotPaths(), run=REPO / "runs" / "cold-plains-patrol.toml"),
        chicken_life_pct=50.0,  # the P6 stage-B setting, as every run tonight
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

    if aborted[0]:
        raise DrillAborted("stopped by request mid-run")
    cycle_summary = report.summary() if hasattr(report, "summary") else str(report)
    result = (
        f"{duration:.0f}s; {cycle_summary}; "
        + "; ".join(f"game {i + 1}: {s}" for i, s in enumerate(game_lines))
    )
    # An acceptance run that did not run to plan is a FAILED test, not a
    # PASS with sad prose. Run 1 of this very drill logged PASS around a
    # "LEFT EARLY: healing short 2" — the harness cannot see inside the
    # cycle report, so the body must say it out loud.
    if getattr(report, "completed", None) == 0:
        raise RuntimeError(f"no clean cycle: {result}")
    return result


if __name__ == "__main__":
    status = run_drill(T53, t53_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
