"""T19 — the bot repairs at Charsi (bot control).

Calibration lives in T25 now (R87): this file only ever drives the bot, so
"human calibration" and "bot control" are separate runs with separate log
rows rather than two halves of one file. T18, the calibration that used to
sit here, is gone — and its measurement with it, since T24 proved the row
it captured was Charsi's portrait rather than the trade/repair line (R86).

What this proves, when it passes, is the whole step: walk to Charsi, open
the dialog, click the trade/repair row, click repair-all, and read the
durability back off the gear. The proof is the durability, never the click.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t19_repair
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.perception.items import read_equipped_durability  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import PreambleReport, TownConfig, TownLayer  # noqa: E402

T19 = Drill(
    test_id="T19",
    title="Bot repairs at Charsi",
    kind="bot control",
    instructions=(
        "Close any open panels and stand anywhere in town; hands off.",
        "The bot will walk to Charsi, open trade/repair, click repair-all, and "
        "verify from memory that nothing is worn any more.",
    ),
    sends_input=True,
)


def wear_report(session) -> str:
    worn = read_equipped_durability(session)
    if not worn:
        return "no repairable gear detected"
    short = [d for d in worn if d.missing]
    return (
        f"{len(worn)} repairable items, {len(short)} worn, "
        f"{sum(d.missing for d in worn)} durability missing; "
        f"lowest {min(d.fraction for d in worn):.0%}"
    )


def build_town(run: DrillRun, config: TownConfig) -> TownLayer:
    session = run.session
    navigator = live_navigator(session, MapStore(), offsets.DIFFICULTY_HELL)
    return TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=navigator.walk_to,
        snapshot=Perception(session).snapshot,
        config=config,
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def t19_body(run: DrillRun) -> str:
    config = TownConfig()
    for name in ("charsi.trade_repair", "charsi.repair_all"):
        point = config.ui_points[name]
        if not point.calibrated:
            raise DrillAborted(
                f"{name} is not calibrated — run T25's charsi battery first. "
                f"{point.note}"
            )

    worn = read_equipped_durability(run.session)
    if not any(d.missing for d in worn):
        raise DrillAborted(
            "nothing is worn — go take some durability damage and re-run "
            "(a repair with nothing to repair proves nothing)"
        )
    before = wear_report(run.session)
    print(f"wear before: {before}", flush=True)

    report = PreambleReport()
    build_town(run, config).repair_at_charsi(report)
    return f"before: {before}; after: {wear_report(run.session)}; {'; '.join(report.log)}"


SUITE = {"T19": (T19, t19_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T19"], run=shared)
    print(f"\nsuite: T19 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
