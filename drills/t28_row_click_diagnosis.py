"""T28 — recalibrate Charsi's trade row IN THE BOT'S OWN DIALOG (R96).

T27 clicked (712, 216) and hit **Cancel**, the line directly beneath
trade/repair (user, watching). So the click was one row low — and that
pixel is exactly what T25 measured, where the user hovered it and it opened
the shop.

Both observations are true, and together they expose a blind spot in the
calibration procedure rather than a bad measurement: **T25 measured a menu
the human opened, and the bot uses a menu the bot opened.** Nothing had ever
checked those are the same menu. This drill measures in the state the value
is actually used in, and refuses to store anything the bot has not itself
proved.

    1. the BOT walks to Charsi and opens the dialog
    2. silently (chat would press Enter into the dialog, R89) the user
       hovers the real TRADE/REPAIR line
    3. and then the CANCEL line directly beneath it
    4. the BOT clicks the freshly measured row; the shop opening is the
       proof, and only then is the number worth keeping

Capturing Cancel as well is the durable part. It gives the row pitch, and
a one-row error has so far been invisible to us — a click landing on the
neighbouring row looks identical to a click that missed entirely. With the
pitch we can say whether a stored point sits safely inside its row or near
the boundary, and which direction is dangerous. Here, low is: Cancel is
directly below, and Cancel closes the dialog silently.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t28_row_click_diagnosis
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.perception import uistate  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

POINT = "charsi.trade_repair"

T28 = Drill(
    test_id="T28",
    title="Recalibrate Charsi's trade row in the bot's own dialog",
    kind="human calibration",
    instructions=(
        "SETUP: stand in town, all panels closed. Hands off at first.",
        "The BOT walks to Charsi and opens her dialog. Read the rest NOW - "
        "it goes silent once the dialog is up.",
        "1. HOVER the TRADE/REPAIR line, hold still 3s. Do NOT click.",
        "2. Then HOVER the CANCEL line directly beneath it, hold still 3s. "
        "Do NOT click.",
        "3. Hands off - the bot then clicks the line you measured first.",
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


def t28_body(run: DrillRun) -> str:
    config = TownConfig()
    stored = config.ui_points[POINT]
    rect = run.window.client_rect()
    stored_px = stored.pixel(rect) if stored.calibrated else None
    print(f"stored {POINT} = {stored.fraction} -> {stored_px}", flush=True)

    town = build_town(run)
    town.close_panels()
    town.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
    run.sleep(town.config.panel_settle_s)
    print(f"bot opened the dialog; panels {panels(run)} — hover the "
          "TRADE/REPAIR line", flush=True)

    trade = run.capture_hover(
        required_panel=offsets.UI_NPCMENU, last_point=None,
        still_samples=30, timeout_s=240,
    )
    if trade is None:
        raise DrillAborted("no hover captured for the trade/repair line")
    tx, ty, tfx, tfy = trade
    delta = (tx - stored_px[0], ty - stored_px[1]) if stored_px else (0, 0)
    print(f"  trade/repair ({tx}, {ty}) -> ({tfx:.4f}, {tfy:.4f}); "
          f"delta from stored {delta} px — now hover CANCEL", flush=True)

    cancel = run.capture_hover(
        required_panel=offsets.UI_NPCMENU, last_point=(tx, ty),
        still_samples=30, timeout_s=240,
    )
    if cancel is None:
        raise DrillAborted("no hover captured for the cancel line")
    cx, cy, _, _ = cancel
    pitch = abs(cy - ty)
    print(f"  cancel ({cx}, {cy}); row pitch {pitch} px", flush=True)

    # The bot proves the number before anyone stores it. If this fails the
    # measurement is not trustworthy either, and saying so is the point.
    sx, sy = tx, ty
    town.panel.click(offsets.UI_NPCMENU, sx, sy)
    opened = town._await(
        lambda: run.panel_open(offsets.UI_NPCSHOP), town.config.interact_timeout_s
    )
    print(f"  bot clicked ({sx}, {sy}): shop "
          f"{'OPENED' if opened else 'did NOT open'}; panels {panels(run)}",
          flush=True)
    town.close_panels()

    if not opened:
        raise DrillAborted(
            f"the freshly measured row ({tfx:.4f}, {tfy:.4f}) did not work "
            f"for the bot either — pitch {pitch} px, delta from stored "
            f"{delta} px. The position is not the whole story."
        )
    margin = pitch / 2
    return (
        f"VERIFIED {POINT} = ({tfx:.4f}, {tfy:.4f}) at ({tx}, {ty}); "
        f"stored was {stored_px}, delta {delta} px; row pitch {pitch} px "
        f"(so ~{margin:.0f} px of margin before the neighbouring row, and "
        f"CANCEL is the one below); bot's own click opened the shop"
    )


SUITE = {"T28": (T28, t28_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T28"], run=shared)
    print(f"\nsuite: T28 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
