"""T71 — the Countess run: the flagship, end to end, for real.

**Sends input: the bot plays.** Town chores, waypoint to Black Marsh,
the seven-transition descent to Tower Cellar Level 5 (warm now — the
staircases were banked by T70 run 5), then the P4 endgame: clear the
arrival neighborhood, stage north of her chamber, advance behind the
revive wall, kill her, prove it, and sweep the chamber for the drop.

Chicken **35** — this is a proper run, not a cellar drill (R212 Q8).

Two artifacts come out of one run, by design:

1. **The kill**, proven the way the step proves it — her pinned identity
   (kind 734 / unique_no 6) dead on the ground, or provably absent after
   the budgeted chamber sweep. The drill re-reads the blackboard
   afterwards so the staging point, the anchor and the drop zone are in
   the record next to what the user watched.
2. **The warm-descent timing** (P5's first live act, riding along): the
   narrative log is stamped per act, so the run file it writes IS the
   measurement against the 5-6 minute target. The drill prints its path
   and the per-step wall-clock stamps it can recover.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t71_countess
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


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T71",
        title="the Countess run — the flagship, end to end",
        kind="bot control",
        sends_input=True,
        instructions=(
            "THE BOT PLAYS THE WHOLE RUN: it may leave THIS game and make",
            "its own, do the town chores, waypoint to Black Marsh, walk",
            "the seven staircases down to Cellar 5, and FIGHT THE",
            "COUNTESS. Chicken is 35% for this one.",
            "Two things to watch and judge afterwards (R219 item 2):",
            "  - the NORTH STAGING point it walks to before closing in",
            "    (derived at (12531, 11036) — the chamber's NW band);",
            "  - whether the approach reads right to you on the map.",
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
            paths=replace(BotPaths(), run=REPO / "runs" / "countess.toml"),
            chicken_life_pct=35.0,  # R212 Q8: a proper run, not a drill
            should_stop=stop_requested,
        )
        for line in describe(bot):
            print(line, flush=True)

        started = time.monotonic()
        report = bot.cycle().run_games(bot.runner(), max_games=1)
        duration = time.monotonic() - started

        print(f"\n{report.summary() if hasattr(report, 'summary') else report}")
        game_lines = []
        endgame: dict = {}
        for index, engine in enumerate(bot.engines(), start=1):
            summary = engine.report.summary()
            print(f"\n--- game {index}: {summary} ---")
            for line in engine.report.log:
                print(f"  {line}")
            game_lines.append(summary)
            # The blackboard the endgame wrote: staging derivation and
            # drop zone, read back rather than inferred from the log.
            notes = getattr(engine, "ctx", None)
            notes = getattr(notes, "notes", {}) if notes is not None else {}
            for key in ("countess", "cleared", "arrival"):
                if key in notes:
                    endgame[key] = notes[key]

        # The narrative file IS the warm-descent measurement (stamped per
        # act, R179). Name it so the timing pass has something to read.
        narrative = "none written"
        try:
            logs = sorted((REPO / "logs").glob("run-*.log"))
            if logs:
                narrative = str(logs[-1].relative_to(REPO))
                print(f"\n--- narrative log: {narrative} ---")
                for line in logs[-1].read_text(encoding="utf-8").splitlines():
                    print(f"  {line}")
        except Exception as exc:  # noqa: BLE001 - reporting must not raise
            narrative = f"unreadable: {type(exc).__name__}"

        # The EVENT log (the run-event-log plan): the structured record.
        # Rendered here so the drill transcript carries the timeline, and
        # named so it can be re-read later without hunting.
        events = "none written"
        try:
            opened = getattr(bot, "_runlogs", [])
            if opened:
                directory = opened[-1].directory
                events = str(directory.relative_to(REPO))
                entries = runlog.load(directory)
                print(f"\n--- event log: {events} ({len(entries)} events) ---")
                for line in runlog.render(entries):
                    print(f"  {line}")
                for line in runlog.summarize(entries):
                    print(f"  {line}")
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
        staging = endgame.get("countess") or "endgame never staged"
        drop_zone = endgame.get("cleared") or "no drop zone published"
        result = (
            f"{duration:.0f}s; {cycle_summary}; "
            + "; ".join(f"game {i + 1}: {s}" for i, s in enumerate(game_lines))
            + f"; endgame: staging {staging}, drop zone {drop_zone}"
            + f"; ended: {landed}; narrative: {narrative}; events: {events}"
        )
        if getattr(report, "completed", None) == 0:
            raise RuntimeError(f"no clean cycle: {result}")
        # The run's whole objective, checked out loud (the T53 run 1
        # lesson): a cycle can report clean while the endgame never ran —
        # a chicken, an abort, a step that gave up short. `clear_countess`
        # completing is what says she was resolved.
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
        result += f"; traverses {traverses}/{wanted}"
        if traverses < wanted:
            raise RuntimeError(f"the descent stopped short: {result}")
        if "clear_countess" not in done_steps:
            raise RuntimeError(f"the endgame never completed: {result}")
        return result

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
