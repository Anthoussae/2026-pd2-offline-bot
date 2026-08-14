"""T56 — Stage C: the supervised full run (radius 150, full pickit).

**This test SENDS INPUT: the bot plays** two full patrol games on the
T55 flow, with the circle widened from 96 to 150 subtiles — the Stage C
shape from the P6 plan (06-staged-acceptance-closeout.md): full pickit,
pickup sweep, and the NEXT-game stash deposit observed. Chicken stays at
50% (the Stage B setting) until the Stage D threshold decision; every
other number is the R49 config as shipped.

Two games rather than one, deliberately: the deposit of game 1's loot
happens in game 2's town preamble, so a single game can never show the
whole loop. The verdict stays on CORRECTNESS — two clean [CVRL] cycles =
PASS. Timings are REPORTED against T55's radius-96 steady state (~220 s
a game), not asserted: radius 150 covers ~2.4x the ground and is allowed
to cost what it costs. The result line carries, per game: duration by
step (from the run's own narrative log), pickup count, the stash lines
from the town preamble, any churn narration, and the sweep's
walked/skipped decision. If game 1 picked items up and game 2's preamble
deposited nothing, the result says DEPOSIT NOT SEEN — a flag for the
review, not an automatic failure (a potion picked to the belt is loot
that legitimately never reaches the stash).

## How it ends

On its own, after two games. Stopping early ALWAYS works: type **abort**
in chat, press ESC or Enter in the field (the R189 kill switch — opening
chat IS the abort), run `tools\\drill-cancel.ps1`, or take the mouse.
Any death: the latch holds and the milestone stops for a conversation.
"""

import re
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

STEADY_96_S = 220  # T55 runs 3-4: the radius-96 steady state, for context

T56 = Drill(
    test_id="T56",
    title="stage C — supervised full run: radius 150, deposit verified",
    kind="bot control",
    sends_input=True,
    instructions=(
        "THE BOT PLAYS TWO full patrol games, radius 150 (T55 ran 96).",
        "Watch, hands off: game 2's town preamble should DEPOSIT game 1's",
        "loot. Chicken stays at 50% until the stage-D decision.",
        "IT ENDS ON ITS OWN after two games; expect roughly 15-25 minutes.",
        "Stop any time: 'abort' in chat, ESC or Enter in the field (the",
        "kill switch), tools\\drill-cancel.ps1, or take the mouse.",
    ),
)


def _narrative(path: Path) -> tuple[list[str], list[str], str, int]:
    """(step timings, churn lines, sweep note, pickup count) of one log."""
    steps, churn, sweep_note, pickups = [], [], "", 0
    for line in path.read_text(encoding="utf-8").splitlines():
        done = re.search(r"(\w+): done after (\d+)s", line)
        if done:
            steps.append(f"{done.group(1)} {done.group(2)}s")
        if "has fired" in line:
            churn.append(line.split("  ", 1)[-1])
        if "ring walk skipped" in line:
            sweep_note = "sweep skipped (memo clean)"
        elif "circle walked" in line:
            sweep_note = "sweep walked its ring"
        if "pickup: kind" in line:
            pickups += 1
    return steps, churn, sweep_note, pickups


def t56_body(run: DrillRun) -> str:
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
        paths=replace(BotPaths(), run=REPO / "runs" / "cold-plains-patrol.toml"),
        chicken_life_pct=50.0,  # held at the stage-B setting until stage D
        radius_override=150,  # the stage-C circle; everything else is R49
        should_stop=stop_requested,
    )
    for line in describe(bot):
        print(line, flush=True)

    logs_before = set((REPO / "logs").glob("run-*.log"))
    started = time.monotonic()
    report = bot.cycle().run_games(bot.runner(), max_games=2)
    duration = time.monotonic() - started

    game_lines, stash_lines = [], []
    for index, engine in enumerate(bot.engines(), start=1):
        summary = engine.report.summary()
        print(f"\n--- game {index}: {summary} ---")
        for line in engine.report.log:
            print(f"  {line}")
            if index > 1 and "stash:" in line:
                stash_lines.append(line.strip())
        game_lines.append(summary)

    if aborted[0]:
        run.say("TEST T56 ABORTED — hands back to you.")
        raise DrillAborted("stopped by request mid-run")
    cycle_summary = report.summary() if hasattr(report, "summary") else str(report)
    completed = getattr(report, "completed", None)
    if completed is not None and completed < 2:
        run.say(
            f"TEST T56 FAILED — {completed} of 2 clean. Hands back to you.",
            patience_s=15.0,
        )
        raise RuntimeError(f"only {completed} of 2 clean cycles: {cycle_summary}")

    # Per-game evidence from each run's own narrative log (one file per run).
    new_logs = sorted(
        set((REPO / "logs").glob("run-*.log")) - logs_before,
        key=lambda p: p.stat().st_mtime,
    )
    pieces, pickups_g1 = [], 0
    for index, log in enumerate(new_logs, start=1):
        steps, churn, sweep_note, pickups = _narrative(log)
        if index == 1:
            pickups_g1 = pickups
        pieces.append(
            f"game {index} [{log.name}]: steps: {', '.join(steps) or 'n/a'}"
            f"; pickups {pickups}"
            + (f"; {sweep_note}" if sweep_note else "")
            + (f"; CHURN: {' | '.join(churn)}" if churn else "")
        )

    deposit = "; ".join(stash_lines) or "no stash lines in game 2's preamble"
    flag = (
        "; DEPOSIT NOT SEEN — review"
        if pickups_g1 > 0 and not any("deposited" in s for s in stash_lines)
        else ""
    )
    verdict = (
        f"{duration:.0f}s for 2 games at radius 150 "
        f"(radius-96 steady state was ~{STEADY_96_S}s a game)"
    )
    run.say(f"TEST T56 COMPLETE — {verdict}. Hands back to you.", patience_s=15.0)
    return (
        f"{verdict}; {cycle_summary}; deposit: {deposit}{flag}; "
        + "; ".join(pieces)
        + "; " + "; ".join(f"game {i + 1}: {s}" for i, s in enumerate(game_lines))
    )


if __name__ == "__main__":
    status = run_drill(T56, t56_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
