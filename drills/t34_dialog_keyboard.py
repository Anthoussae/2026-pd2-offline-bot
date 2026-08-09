"""T34 — can the NPC dialog be driven by keyboard? (user discovery, R104)

The user found that arrows move the highlight in an NPC dialog and Enter
selects. If that is reliable it retires the entire problem this milestone
has been stuck on: no fractions, no NPC anchor, no offset, no band, no
sweep. "Choose the 2nd option" is then the literal instruction, identical at
every NPC, and it survives the thing that broke every other approach —
Kashya's menu growing a row when the merc dies (R56) only changes WHICH
index you want, not how you get there.

It also fits evidence we already paid for: chat's Enter was selecting dialog
options by accident (R89). That was a bug from chat's side and a
demonstration from this side — Enter really does choose.

What this measures, bot-only:

    how many DOWNs before ENTER opens the shop, if any

Trying k = 0, 1, 2, 3 answers two things at once — whether the keyboard
works at all, and where the highlight starts. A menu with nothing
pre-highlighted needs one DOWN to reach the first row; a menu that opens
with row 1 selected needs none. Both are plausible and the difference
matters, so it is measured rather than assumed.

Safe at Charsi specifically: her options are Talk, Trade/Repair and Cancel,
and choosing the wrong one costs nothing — Talk opens gossip, Cancel closes
the dialog. That is why this is being learned HERE and not at Kashya, where
a wrong choice spends 50,000 gold.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t34_dialog_keyboard
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import VK_DOWN, VK_RETURN, GatedInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.perception import uistate  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

MAX_DOWNS = 3

T34 = Drill(
    test_id="T34",
    title="Driving Charsi's dialog by keyboard (arrows + Enter)",
    kind="bot control",
    instructions=(
        "SETUP: in town, all panels closed, hands off throughout.",
        "Bot opens Charsi and tries ENTER after 0, 1, 2, 3 DOWN presses.",
        "No gold is spent - Charsi's options are Talk, Trade/Repair, Cancel.",
        "Watch which press count opens the trade screen.",
    ),
    sends_input=True,
)


def build_town(run: DrillRun) -> TownLayer:
    session = run.session
    navigator = live_navigator(session, MapStore(), offsets.DIFFICULTY_HELL)
    return TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=navigator.walk_to,
        snapshot=Perception(session).snapshot,
        config=TownConfig(),
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def panels(run: DrillRun) -> str:
    return "+".join(uistate.read_ui_state(run.session, run.ui_array).names) or "none"


def t34_body(run: DrillRun) -> str:
    town = build_town(run)
    results: dict[int, str] = {}

    for downs in range(MAX_DOWNS + 1):
        run.check_cancel()
        town.close_panels()
        town.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
        run.sleep(town.config.panel_settle_s)

        for _ in range(downs):
            town.panel.press_key(offsets.UI_NPCMENU, VK_DOWN)
            run.sleep(0.15)
        town.panel.press_key(offsets.UI_NPCMENU, VK_RETURN)

        opened = town._await(
            lambda: run.panel_open(offsets.UI_NPCSHOP),
            town.config.interact_timeout_s,
        )
        if opened:
            results[downs] = "TRADE"
        elif not run.panel_open(offsets.UI_NPCMENU):
            results[downs] = "dialog closed"
        else:
            results[downs] = "no effect"
        print(f"  {downs} down + enter -> {results[downs]}; panels {panels(run)}",
              flush=True)
        town.close_panels()

    working = [k for k, v in results.items() if v == "TRADE"]
    summary = "; ".join(f"{k} down={v}" for k, v in sorted(results.items()))
    if not working:
        return (
            f"KEYBOARD DOES NOT DRIVE THIS DIALOG — {summary}. Arrows and "
            "Enter had no useful effect from the bot, so selection stays a "
            "clicking problem"
        )
    return (
        f"KEYBOARD WORKS — {working[0]} DOWN press(es) then ENTER opens the "
        f"trade screen ({summary}). Selection by ordinal needs no screen "
        "position at all"
    )


SUITE = {"T34": (T34, t34_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T34"], run=shared)
    print(f"\nsuite: T34 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
