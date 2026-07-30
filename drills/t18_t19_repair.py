"""T18-T19 — repairing at Charsi (user request, R70).

    T18  calibration   the user opens Charsi's dialog and hovers the
                       TRADE/REPAIR row, then opens it and hovers the
                       REPAIR ALL button
    T19  bot control   the bot walks to Charsi, opens the dialog, picks
                       trade/repair, clicks repair-all, and verifies from
                       memory that the gear stopped being worn

Repair is two clicks deep into NPC UI, and NPC menus shift with state (the
R56 lesson: Kashya's resurrect row exists only while the merc is dead). So
neither click is trusted: both positions are hover-calibrated, and the
proof of success is durability read back off the worn items rather than
"the button was clicked". A mis-aimed row leaves the gear worn and says so.

T18 also prints the panel flags in each state, which confirms the shop
screen really is UI_NPCSHOP rather than something that merely looks like it.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t18_t19_repair
"""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets, uistate  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.items import read_equipped_durability  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import PreambleReport, TownConfig, TownLayer  # noqa: E402

FINDINGS: dict = {}


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
        # A stop request must reach the retry ladders inside the town
        # layer, not just the harness's own waits (R80).
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


# ------------------------------------------------------------- T18: calibration

T18 = Drill(
    test_id="T18",
    title="Repair UI calibration at Charsi",
    kind="human calibration",
    instructions=(
        "Walk to CHARSI and click her so her dialog opens.",
        "Rest the cursor on the TRADE/REPAIR line and hold still 3s.",
        "Then open it, and rest on the REPAIR ALL EQUIPMENT button; hold still.",
    ),
)


def t18_body(run: DrillRun) -> str:
    print(f"wear before: {wear_report(run.session)}", flush=True)

    if not run.announce_until(
        "Click CHARSI so her dialog is open, then hover the TRADE/REPAIR line.",
        lambda: run.panel_open(offsets.UI_NPCMENU),
        timeout_s=180,
    ):
        raise DrillAborted("Charsi's dialog never opened")
    print(f"dialog panels: {uistate.read_ui_state(run.session, run.ui_array).names}",
          flush=True)

    row = run.capture_hover(
        required_panel=offsets.UI_NPCMENU, last_point=None,
        still_samples=30, timeout_s=120,
    )
    if row is None:
        raise DrillAborted("no hover captured for the trade/repair row")
    FINDINGS["trade_repair_row"] = (row[2], row[3])
    print(f"trade/repair row at ({row[0]}, {row[1]}) -> ({row[2]:.4f}, {row[3]:.4f})",
          flush=True)

    if not run.announce_until(
        "Now open trade/repair, then hover the REPAIR ALL EQUIPMENT button.",
        lambda: run.panel_open(offsets.UI_NPCSHOP),
        timeout_s=180,
    ):
        raise DrillAborted(
            "the shop screen never registered as UI_NPCSHOP — the panel id may "
            "differ in PD2; nothing may be clicked there until it is known"
        )
    print(f"shop panels: {uistate.read_ui_state(run.session, run.ui_array).names}",
          flush=True)

    button = run.capture_hover(
        required_panel=offsets.UI_NPCSHOP, last_point=(row[0], row[1]),
        still_samples=30, timeout_s=120,
    )
    if button is None:
        raise DrillAborted("no hover captured for the repair-all button")
    FINDINGS["repair_all_button"] = (button[2], button[3])
    print(
        f"repair-all button at ({button[0]}, {button[1]}) -> "
        f"({button[2]:.4f}, {button[3]:.4f})",
        flush=True,
    )

    run.say("Calibrated - close the shop when ready.")
    return (
        f"trade row ({row[2]:.4f}, {row[3]:.4f}); "
        f"repair-all ({button[2]:.4f}, {button[3]:.4f}); {wear_report(run.session)}"
    )


# --------------------------------------------------------------- T19: bot repair

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


def t19_body(run: DrillRun) -> str:
    # T18's measurements are baked into TownConfig defaults, so a standalone
    # T19 run uses those; a T18 in this same process overrides them, which is
    # what you want after a re-calibration.
    defaults = TownConfig()
    row = FINDINGS.get("trade_repair_row", defaults.trade_repair_row)
    button = FINDINGS.get("repair_all_button", defaults.repair_all_button)
    if row is None or button is None:
        raise DrillAborted("the repair UI is not calibrated; run T18 first")

    worn = read_equipped_durability(run.session)
    if not any(d.missing for d in worn):
        raise DrillAborted(
            "nothing is worn — go take some durability damage and re-run "
            "(a repair with nothing to repair proves nothing)"
        )
    before = wear_report(run.session)
    print(f"wear before: {before}", flush=True)

    config = replace(defaults, trade_repair_row=row, repair_all_button=button)
    town = build_town(run, config)
    report = PreambleReport()
    town.repair_at_charsi(report)

    return f"before: {before}; after: {wear_report(run.session)}; {'; '.join(report.log)}"


SUITE = {"T18": (T18, t18_body), "T19": (T19, t19_body)}

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
