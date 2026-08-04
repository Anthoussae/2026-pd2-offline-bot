"""T55 — the timed patrol: does the dilly-dally work actually pay?

**This test SENDS INPUT: the bot plays** one full patrol game, exactly
T53's flow (it may leave your game, create a fresh Hell game, run the
preamble, waypoint, clear, sweep, leave). What is new is the QUESTION:
run 4 of T54 took 1032 s, of which ~600 s was upkeep churn, ~60 s an
unconditional sweep re-walk, and ~60 s NPC trips for slivers. After
R185 A+B+C and R186 T1-T4 the same run should land around 4-6 minutes.

The verdict stays on CORRECTNESS (a clean [CVRL] cycle = PASS); the
timings are REPORTED against the run-4 baseline, not asserted — a
monster-dense map can honestly cost minutes, and a flaky time assertion
would teach nothing. The result line carries: total duration, per-step
durations from the run's own narrative log, any churn-narration lines
(there should be none in a quiet field now), and whether the sweep
walked its ring or skipped it on a clean memo.

## How it ends

On its own, after one game. Stopping early ALWAYS works: type **abort**
in chat — the engine now polls the stop channel every tick, and the
panel-recovery leaves a lone chat console alone while you type — or run
`tools\\drill-cancel.ps1`, or take the mouse / press ESC.
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
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.wiring import BotPaths, build_bot, describe  # noqa: E402

BASELINE_S = 1032  # T54 run 4, before the R185/R186 work

T55 = Drill(
    test_id="T55",
    title="timed patrol — the churn and dilly-dally fixes, priced live",
    kind="bot control",
    sends_input=True,
    instructions=(
        "THE BOT PLAYS one full patrol game like T53. The question is",
        "TIME: run 4 took 17 minutes; expect roughly 4-6 now. PASS is a",
        "clean cycle; the timings are reported, not asserted.",
        "IT ENDS ON ITS OWN after one game.",
        "Stop any time: 'abort' in chat (now heard everywhere, and the",
        "bot will not fight you for the chat box), tools\\drill-cancel.ps1,",
        "or take the mouse / press ESC - your hands always win.",
    ),
)


def t55_body(run: DrillRun) -> str:
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
        chicken_life_pct=50.0,  # the P6 stage-B setting
        should_stop=stop_requested,
    )
    for line in describe(bot):
        print(line, flush=True)

    started = time.monotonic()
    report = bot.cycle().run_games(bot.runner(), max_games=1)
    duration = time.monotonic() - started

    game_lines = []
    for index, engine in enumerate(bot.engines(), start=1):
        summary = engine.report.summary()
        print(f"\n--- game {index}: {summary} ---")
        for line in engine.report.log:
            print(f"  {line}")
        game_lines.append(summary)

    if aborted[0]:
        run.say("TEST T55 ABORTED — hands back to you.")
        raise DrillAborted("stopped by request mid-run")
    cycle_summary = report.summary() if hasattr(report, "summary") else str(report)
    if getattr(report, "completed", None) == 0:
        run.say("TEST T55 FAILED — no clean cycle. Hands back to you.", patience_s=15.0)
        raise RuntimeError(f"no clean cycle: {cycle_summary}")

    # The timings, from the run's own narrative log.
    logs = sorted(
        (REPO / "logs").glob("run-*.log"), key=lambda p: p.stat().st_mtime
    )
    steps, churn, sweep_note = [], [], ""
    if logs:
        for line in logs[-1].read_text(encoding="utf-8").splitlines():
            done = re.search(r"(\w+): done after (\d+)s", line)
            if done:
                steps.append(f"{done.group(1)} {done.group(2)}s")
            if "has fired" in line:
                churn.append(line.split("  ", 1)[-1])
            if "ring walk skipped" in line:
                sweep_note = "sweep skipped its ring (memo clean)"
            elif "circle walked" in line:
                sweep_note = "sweep walked its ring (sightings pending)"
        print(f"\nnarrative: {logs[-1].name}")

    verdict = (
        f"{duration:.0f}s vs the {BASELINE_S}s baseline "
        f"({100 * duration / BASELINE_S:.0f}%)"
    )
    run.say(f"TEST T55 COMPLETE — {verdict}. Hands back to you.", patience_s=15.0)
    return (
        f"{verdict}; {cycle_summary}; steps: {', '.join(steps) or 'n/a'}"
        + (f"; {sweep_note}" if sweep_note else "")
        + (f"; CHURN: {' | '.join(churn)}" if churn else "; no churn narration")
        + "; " + "; ".join(f"game {i + 1}: {s}" for i, s in enumerate(game_lines))
    )


if __name__ == "__main__":
    status = run_drill(T55, t55_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
