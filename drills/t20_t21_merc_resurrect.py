"""T20-T21 — resurrecting the mercenary at Kashya.

This pair exists because the thing it calibrates cannot be calibrated any
other way: Kashya's "Resurrect <name>: <price>" row appears ONLY while the
hireling is dead, and its presence shifts the rows around it (user note,
R56). So the measurement and the use both have to happen inside the same
dead-merc window, which is why T20 and T21 run back to back and T21
re-confirms the merc is still dead before trusting T20's numbers.

    T20  calibration   with the merc dead, the user opens Kashya's dialog
                       and hovers the resurrect row
    T21  bot control   the bot walks to Kashya, clicks that row, and
                       verifies BOTH that the merc lives and that gold was
                       spent

Two proofs rather than one, because either alone lies: a merc that was
never dead reads "alive" without a click, and gold moves for reasons other
than resurrection. Together they mean the transaction happened.

Setup the user must arrange: the mercenary actually dead. That is all —
PD2 pays for services out of the shared stash regardless of what is on the
person (user, R76), so no gold needs withdrawing, and the step's floor is
checked against carried PLUS stashed.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t20_t21_merc_resurrect
"""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.player import read_player  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import PreambleReport, TownConfig, TownLayer  # noqa: E402

FINDINGS: dict = {}


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


# ------------------------------------------------------------- T20: calibration

T20 = Drill(
    test_id="T20",
    title="Merc resurrect row calibration (dead-merc state only)",
    kind="human calibration",
    instructions=(
        "SETUP: the mercenary must be DEAD. No gold withdrawal needed - "
        "services are paid from the shared stash.",
        "Walk to KASHYA and click her so the dialog opens.",
        "Rest the cursor on the 'Resurrect <name>: <price>' line, hold still 3s.",
        "Do NOT click it - T21 does that.",
    ),
)


def t20_body(run: DrillRun) -> str:
    gold = available_gold(run)
    if merc_alive(run):
        raise DrillAborted(
            "the merc is alive — the resurrect row does not exist in this "
            "state, so there is nothing to calibrate (R56)"
        )
    if gold <= TownConfig().resurrect_gold_floor:
        raise DrillAborted(
            f"only {gold} gold available (carried + stashed); the step needs "
            f"more than {TownConfig().resurrect_gold_floor}"
        )
    run.say(f"Merc is dead, {gold} gold available. Open Kashya's dialog.")

    if not run.announce_until(
        "Click KASHYA, then hover the 'Resurrect' line (do not click it).",
        lambda: run.panel_open(offsets.UI_NPCMENU),
        timeout_s=180,
    ):
        raise DrillAborted("Kashya's dialog never opened")

    got = run.capture_hover(
        required_panel=offsets.UI_NPCMENU,
        last_point=None,
        still_samples=30,
        timeout_s=120,
    )
    if got is None:
        raise DrillAborted("no hover captured for the resurrect row")
    x, y, fx, fy = got
    FINDINGS["resurrect_row"] = (fx, fy)
    FINDINGS["gold_at_calibration"] = gold
    print(f"resurrect row at ({x}, {y}) -> fraction ({fx:.4f}, {fy:.4f})", flush=True)

    run.say("Captured. Close the dialog; leave the merc dead for the next test.")
    return (
        f"resurrect row ({fx:.4f}, {fy:.4f}); merc dead; {gold} gold available"
    )


# ---------------------------------------------------------- T21: bot resurrects

T21 = Drill(
    test_id="T21",
    title="Bot resurrects the mercenary",
    kind="bot control",
    instructions=(
        "Close Kashya's dialog, stand anywhere in town, and go hands off.",
        "The bot will walk to Kashya, click the resurrect line, and confirm "
        "BOTH that the merc is alive and that gold was spent.",
    ),
    sends_input=True,
)


def t21_body(run: DrillRun) -> str:
    # T20's capture is baked into TownConfig, so T21 runs standalone; a
    # T20 in this same process overrides it after a re-calibration.
    defaults = TownConfig()
    row = FINDINGS.get("resurrect_row", defaults.resurrect_row)
    if row is None:
        raise DrillAborted("the resurrect row is not calibrated; run T20 first")
    if merc_alive(run):
        raise DrillAborted(
            "the merc is alive again — T20's row position belongs to the "
            "dead-merc menu and must not be clicked in this state (R56)"
        )

    gold_before = available_gold(run)
    print(f"before: merc dead, {gold_before} gold available", flush=True)

    config = replace(defaults, resurrect_row=row)
    town = build_town(run, config)
    report = PreambleReport()
    town.resurrect_merc_if_dead(report)

    gold_after = available_gold(run)
    snapshot = Perception(run.session).snapshot()
    merc = snapshot.merc
    return (
        f"action={report.merc_action}; merc "
        f"{'alive (' + (merc.merc_kind or 'summon') + ')' if merc else 'STILL DEAD'}; "
        f"gold {gold_before} -> {gold_after} (spent {gold_before - gold_after}); "
        f"{'; '.join(report.log)}"
    )


SUITE = {"T20": (T20, t20_body), "T21": (T21, t21_body)}

if __name__ == "__main__":
    wanted = [a.upper() for a in sys.argv[1:]] or list(SUITE)
    unknown = [w for w in wanted if w not in SUITE]
    if unknown:
        raise SystemExit(f"unknown drill(s): {', '.join(unknown)}; have {list(SUITE)}")
    shared = DrillRun(GameSession())
    statuses = [run_drill(*SUITE[name], run=shared) for name in wanted]
    summary = ", ".join(f"{n} {s}" for n, s in zip(wanted, statuses, strict=True))
    print(f"\nsuite: {summary}")
    raise SystemExit(0 if all(s == "PASS" for s in statuses) else 1)
