"""T30 — does the NPC-anchored row actually work, five times running? (R99)

T29 measured the model: an NPC dialog row sits a fixed vertical offset from
the NPC (-211 px, holding to 5 px while the NPC's screen position moved 60+).
This confirms it the only way that counts — the bot predicting the position
from scratch, clicking it, and the shop opening.

It exists because the three attempts before it were each "a better number"
that passed once and failed live. A single successful click proves nothing
here; that is exactly what every discarded calibration also had. So: five
openings from five different standing positions, and the click is judged
STRICTLY.

**One click per round, no retries.** Production keeps its retry ladder, and
should — but a ladder measures whether the bot eventually copes, and the
question here is whether the model is right. A first click that misses and a
second that lands would report as success and hide the thing being tested.

Nothing spends gold: it clicks only the trade/repair row, never inside the
shop screen. A miss lands on another of Charsi's dialog rows (Talk, Cancel),
all harmless, and the round is recorded as a failure.

Reading the result:

    5/5   the model holds; the repair step can be trusted and T27 re-run
    4/5   better than any fraction ever managed, but the offset needs
          refining before this runs unattended every game
    worse the anchor is not the whole story; do not build on it

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t30_anchored_row_confirm
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets, uistate  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.player import read_player  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

POINT = "charsi.trade_repair"
# Five sides, so the NPC lands in a genuinely different part of the screen
# each time. If the offset only works from one approach, this finds out.
STANDING_SPOTS = [(-11, -4), (10, 6), (-3, 11), (9, -8), (-12, 5)]

T30 = Drill(
    test_id="T30",
    title="NPC-anchored row: five predicted clicks, no retries",
    kind="bot control",
    instructions=(
        "SETUP: in town, all panels closed, hands off throughout.",
        "5 ROUNDS. Bot moves, opens Charsi, clicks the PREDICTED row once.",
        "No gold is spent - it never clicks inside the shop screen.",
        "Watch for it hitting Cancel instead; that is the failure we expect.",
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


def t30_body(run: DrillRun) -> str:
    config = TownConfig()
    point = config.ui_points[POINT]
    if not point.npc_anchored:
        raise DrillAborted(
            f"{POINT} is not NPC-anchored — this drill confirms the anchor "
            "model, and there is nothing to confirm"
        )
    if not point.calibrated:
        raise DrillAborted(f"{POINT} has no measured offset; run T29 first")
    print(f"{POINT}: anchor NPC {point.anchor_npc}, offset {point.npc_offset}",
          flush=True)

    town = build_town(run)
    charsi_home = config.npc_positions[offsets.NPC_CHARSI]
    results = []

    for index, (dx, dy) in enumerate(STANDING_SPOTS, start=1):
        run.check_cancel()
        town.close_panels()
        try:
            town._walk_guarded((charsi_home[0] + dx, charsi_home[1] + dy))
        except Exception as exc:  # noqa: BLE001 - a failed move is not the test
            print(f"round {index}: reposition failed ({exc})", flush=True)
        town.close_panels()
        town.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
        run.sleep(town.config.panel_settle_s)

        predicted = town.point_pixel(point)
        player = read_player(run.session)
        charsi = town._find_ally(offsets.NPC_CHARSI)

        # ONE click, deliberately. See the module docstring.
        town.panel.click(offsets.UI_NPCMENU, *predicted)
        opened = town._await(
            lambda: run.panel_open(offsets.UI_NPCSHOP),
            town.config.interact_timeout_s,
        )
        results.append(opened)
        print(
            f"round {index}: stood {player.position if player else '?'}, "
            f"Charsi {charsi}, predicted {predicted} -> shop "
            f"{'OPENED' if opened else 'did NOT open'}; panels {panels(run)}",
            flush=True,
        )
        town.close_panels()

    hits = sum(results)
    total = len(results)
    pattern = "".join("H" if r else "." for r in results)
    if hits == total:
        verdict = (
            "MODEL CONFIRMED — every predicted click landed, first time, "
            "from five different positions. No stored fraction ever managed "
            "better than one"
        )
    elif hits >= total - 1:
        verdict = (
            "MOSTLY — better than any fraction achieved, but a miss every "
            "few games is a halt every few games; refine the offset before "
            "this runs unattended"
        )
    else:
        verdict = (
            "MODEL NOT CONFIRMED — the NPC anchor is not the whole story, "
            "and the row needs locating at click time rather than predicting"
        )
    return f"{hits}/{total} predicted clicks opened the shop; pattern {pattern}; {verdict}"


SUITE = {"T30": (T30, t30_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T30"], run=shared)
    print(f"\nsuite: T30 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
