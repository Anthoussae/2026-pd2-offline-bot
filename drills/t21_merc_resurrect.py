"""T21 — the bot resurrects the mercenary at Kashya (bot control).

Calibration moved to T25's `kashya` battery (R87), so this file only drives
the bot. The state coupling is unchanged and still the hard part: Kashya's
"Resurrect <name>: <price>" row appears ONLY while the hireling is dead,
and its presence shifts the rows around it (R56). Both the measurement and
the use therefore have to happen inside the same dead-merc window, and this
drill re-confirms the merc is dead before trusting the stored row.

Two proofs rather than one, because either alone lies: a merc that was
never dead reads "alive" without a click, and gold moves for reasons other
than resurrection. Together they mean the transaction happened.

Setup the user must arrange: the mercenary actually dead. That is all — PD2
pays for services out of the shared stash regardless of what is on the
person (R76), so no gold needs withdrawing, and the step's floor is checked
against carried PLUS stashed.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t21_merc_resurrect
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
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import PreambleReport, TownConfig, TownLayer  # noqa: E402


def merc_alive(run: DrillRun) -> bool:
    return Perception(run.session).snapshot().merc is not None


def available_gold(run: DrillRun) -> int:
    """Carried plus stashed: PD2 pays for services from the shared stash
    regardless of what is on the person (R76)."""
    player = read_player(run.session)
    return (player.gold + player.gold_stash) if player is not None else 0


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
        # A stop request must reach the retry ladders inside the town
        # layer, not just the harness's own waits (R80).
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


T21 = Drill(
    test_id="T21",
    title="Bot resurrects the mercenary",
    kind="bot control",
    instructions=(
        "SETUP: the mercenary must be DEAD, and stay dead until this ends.",
        "Close Kashya's dialog, stand anywhere in town, and go hands off.",
        "The bot will walk to Kashya, click the resurrect line, and confirm "
        "BOTH that the merc is alive and that gold was spent.",
    ),
    sends_input=True,
)


def t21_body(run: DrillRun) -> str:
    config = TownConfig()
    point = config.ui_points["kashya.resurrect"]
    if not point.calibrated:
        raise DrillAborted(
            "kashya.resurrect is not calibrated — run T25's kashya battery "
            f"first, in this same dead-merc window. {point.note}"
        )
    if merc_alive(run):
        raise DrillAborted(
            "the merc is alive again — the resurrect row belongs to the "
            "dead-merc menu and must not be clicked in this state (R56)"
        )

    gold_before = available_gold(run)
    print(f"before: merc dead, {gold_before} gold available", flush=True)

    report = PreambleReport()
    build_town(run, config).resurrect_merc_if_dead(report)

    gold_after = available_gold(run)
    merc = Perception(run.session).snapshot().merc
    return (
        f"action={report.merc_action}; merc "
        f"{'alive (' + (merc.merc_kind or 'summon') + ')' if merc else 'STILL DEAD'}; "
        f"gold {gold_before} -> {gold_after} (spent {gold_before - gold_after}); "
        f"{'; '.join(report.log)}"
    )


SUITE = {"T21": (T21, t21_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T21"], run=shared)
    print(f"\nsuite: T21 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
