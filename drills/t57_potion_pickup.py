"""T57 — potion pickup: every tier identified, belted, mid-combat.

**This test SENDS INPUT: the bot plays** one patrol game (T55's flow,
radius 96, chicken 50). The question is the POTION SUPPLY CHAIN, end to
end, after the T56 findings: only one healing tier (hp5/606) was in the
kind table, a click miss was diagnosed as "belt full for the type", and
the type write-off never expired when drinking made room. All three are
fixed; this drill is the live proof.

The setup is the user's: ONE healing potion staged in the inventory,
the rest to come off fallen enemies. The chain under test:

1. **Town**: the preamble's belt refill sees the staged potion as
   loadable stock (whatever its tier) and moves it to the belt.
2. **Field**: ground healing potions of EVERY tier are wanted, walked
   to, clicked, and CONFIRMED arriving — the new narrative line
   ("came up — belt healing n/8, ...") is the receipt, including
   during the clearance, which is where mid-combat pickups live.
3. **Diagnosis**: any "belt full" alert now means the counts agreed;
   a miss says "click misses suspected" and leaves the type wanted.

PASS = a clean cycle AND the staged potion loaded in town AND at least
one ground healing potion confirmed into the belt in the field. The
result line carries the whole potion ledger either way.

## How it ends

On its own, after one game. Stopping early ALWAYS works: type **abort**
in chat, press ESC or Enter in the field (the kill switch), run
`tools\\drill-cancel.ps1`, or take the mouse. Any death: the latch
holds and the milestone stops for a conversation.
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
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.pickit import potion_type_of  # noqa: E402
from pd2bot.wiring import BotPaths, build_bot, describe  # noqa: E402

T57 = Drill(
    test_id="T57",
    title="potion pickup — every tier identified, belted, mid-combat",
    kind="bot control",
    sends_input=True,
    instructions=(
        "SETUP FIRST: exactly 1 healing potion in the INVENTORY, belt",
        "healing drained/low. The bot plays ONE patrol game (radius 96):",
        "town refill should belt your staged potion; field drops off",
        "fallen enemies should be picked up and CONFIRMED, any tier.",
        "IT ENDS ON ITS OWN after one game (~4-6 minutes).",
        "Stop any time: 'abort' in chat, ESC or Enter in the field,",
        "tools\\drill-cancel.ps1, or take the mouse.",
    ),
)


def _census(session: GameSession) -> str:
    """One line: potions in belt and main inventory, by kind."""
    carried = read_carried_items(session)
    belt = [i.kind for i in carried.belt if potion_type_of(i) is not None]
    inv = [
        i.kind for i in carried.main_inventory if potion_type_of(i) is not None
    ]
    return (
        f"belt potions by kind {sorted(belt)}; "
        f"inventory potions by kind {sorted(inv)}"
    )


def t57_body(run: DrillRun) -> str:
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

    baseline = _census(run.session)
    print(f"baseline: {baseline}", flush=True)
    run.say(f"Baseline read: {baseline}"[:180], patience_s=15.0)

    bot = build_bot(
        paths=replace(BotPaths(), run=REPO / "runs" / "cold-plains-patrol.toml"),
        chicken_life_pct=50.0,  # the P6 stage setting until stage D decides
        should_stop=stop_requested,
    )
    for line in describe(bot):
        print(line, flush=True)

    logs_before = set((REPO / "logs").glob("run-*.log"))
    started = time.monotonic()
    report = bot.cycle().run_games(bot.runner(), max_games=1)
    duration = time.monotonic() - started

    for index, engine in enumerate(bot.engines(), start=1):
        print(f"\n--- game {index}: {engine.report.summary()} ---")
        for line in engine.report.log:
            print(f"  {line}")

    if aborted[0]:
        run.say("TEST T57 ABORTED — hands back to you.")
        raise DrillAborted("stopped by request mid-run")

    # The potion ledger, from the run's own narrative log.
    new_logs = sorted(
        set((REPO / "logs").glob("run-*.log")) - logs_before,
        key=lambda p: p.stat().st_mtime,
    )
    loaded_in_town = 0
    picked: list[str] = []
    confirmed: list[str] = []
    confirmed_mid_clearance = 0
    misses: list[str] = []
    belt_full_alerts: list[str] = []
    foreign_drinks = 0
    in_clearance = False
    for log in new_logs:
        for line in log.read_text(encoding="utf-8").splitlines():
            if "waypoint: done" in line:
                in_clearance = True
            if "clear_radius: done" in line:
                in_clearance = False
            moved = re.search(r"belt: (\d+) moved", line)
            if moved and "town_preamble" not in line:
                loaded_in_town = max(loaded_in_town, int(moved.group(1)))
            if re.search(r"pickup: kind \d+ at", line) and "came up" not in line:
                picked.append(line.split("  ", 1)[-1])
            if "came up" in line:
                confirmed.append(line.split("  ", 1)[-1])
                if in_clearance:
                    confirmed_mid_clearance += 1
            if "click misses suspected" in line:
                misses.append(line.split("  ", 1)[-1])
            if "belt full for" in line:
                belt_full_alerts.append(line.split("  ", 1)[-1])
            if "foreign potion" in line:
                foreign_drinks += 1

    healing_confirmed = [
        c for c in confirmed
        if re.search(r"kind 60[2-6] ", c)
    ]
    cycle_summary = report.summary() if hasattr(report, "summary") else str(report)
    clean = getattr(report, "completed", 0) >= 1

    ledger = (
        f"town loaded {loaded_in_town}; picked {len(picked)}; "
        f"confirmed {len(confirmed)} ({len(healing_confirmed)} healing, "
        f"{confirmed_mid_clearance} mid-clearance); "
        f"misses {len(misses)}; belt-full alerts {len(belt_full_alerts)}; "
        f"foreign drinks {foreign_drinks}"
    )
    detail = "; ".join(confirmed[:6])

    failures = []
    if not clean:
        failures.append("no clean cycle")
    if loaded_in_town < 1:
        failures.append("the staged inventory potion was not belted in town")
    if not healing_confirmed:
        failures.append("no ground healing potion confirmed into the belt")
    if failures:
        run.say(
            f"TEST T57 FAILED — {'; '.join(failures)}. Hands back to you.",
            patience_s=15.0,
        )
        raise RuntimeError(
            f"{'; '.join(failures)}; {ledger}; {cycle_summary}"
            + (f"; confirmations: {detail}" if detail else "")
        )

    run.say(
        f"TEST T57 COMPLETE — {ledger}. Hands back to you.", patience_s=15.0
    )
    return (
        f"{duration:.0f}s; {ledger}; {cycle_summary}"
        + (f"; confirmations: {detail}" if detail else "")
        + (f"; MISSES: {' | '.join(misses[:3])}" if misses else "")
    )


if __name__ == "__main__":
    status = run_drill(T57, t57_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
