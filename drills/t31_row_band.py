"""T31 — measure the trade/repair row's vertical BAND, not a point (R100).

T30 scored the NPC-anchored offset 4/5 on strict single clicks. The miss is
the interesting part: the menu stayed OPEN afterwards, so the click landed
off every row rather than on Cancel, and it was the highest prediction of
the five — y=171 against successes at 181..271.

That is the signature of a systematic bias, not noise. The -211 offset was
averaged from three hovers, and a hover lands wherever the hand happens to
be along the row's text band. If those three all sat toward the TOP of the
band, the average aims high, and the geometry that puts the row highest on
screen is the one that falls off the top edge first. Every failure being at
the top end is exactly what that would look like.

An average of point samples cannot detect that; only the band can. So:

    hover the TOP edge of the trade/repair text     -> band top
    hover the BOTTOM edge of it                     -> band bottom

which gives the row height, its centre, and — for the first time — the
MARGIN we are working with. Then the offset targets the centre, and we can
say how far a prediction may drift before it hits nothing (or, worse, the
row below: Cancel sits 180 px down, T28).

One dialog, two hovers. The bot opens the dialog and then stays silent
(chat presses Enter into an open dialog, R89) and sends nothing further.

Honest caveat, worth keeping in view while reading the result: if the
measured centre comes out within a few px of the current -211, the bias
theory is WRONG and the 4/5 has another cause entirely. This drill is as
much a test of that explanation as a calibration.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t31_row_band
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.input.screen import projection_for  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

POINT = "charsi.trade_repair"
ROW_PITCH_PX = 180  # trade/repair -> cancel, measured in T28

T31 = Drill(
    test_id="T31",
    title="Measure the trade/repair row's vertical band",
    kind="human calibration",
    instructions=(
        "SETUP: in town, all panels closed, hands off.",
        "Bot opens Charsi's dialog. Then TWO hovers, no clicking.",
        "1. TOP edge of the trade/repair text. Hold still 3s.",
        "2. BOTTOM edge of the same line. Hold still 3s.",
        "Aim at the edges, not the middle. NEVER CLICK.",
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


def t31_body(run: DrillRun) -> str:
    config = TownConfig()
    point = config.ui_points[POINT]
    stored_offset = point.npc_offset

    town = build_town(run)
    town.close_panels()
    town.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
    run.sleep(town.config.panel_settle_s)

    player = read_player(run.session)
    charsi = town._find_ally(offsets.NPC_CHARSI)
    if player is None or charsi is None:
        raise DrillAborted("player or Charsi unreadable with the dialog open")
    npc_screen = projection_for(
        player.position, run.window.client_rect()
    ).world_to_screen(*charsi)
    print(f"dialog open; Charsi {charsi} -> screen {npc_screen}; "
          f"stored offset {stored_offset}", flush=True)
    print("hover the TOP edge of the trade/repair text", flush=True)

    top = run.capture_hover(
        required_panel=offsets.UI_NPCMENU, last_point=None,
        still_samples=30, timeout_s=240,
    )
    if top is None:
        raise DrillAborted("no hover captured for the top edge")
    print(f"  top ({top[0]}, {top[1]}) — now the BOTTOM edge", flush=True)

    bottom = run.capture_hover(
        required_panel=offsets.UI_NPCMENU, last_point=(top[0], top[1]),
        still_samples=30, timeout_s=240,
    )
    if bottom is None:
        raise DrillAborted("no hover captured for the bottom edge")
    print(f"  bottom ({bottom[0]}, {bottom[1]})", flush=True)
    town.close_panels()

    top_y, bottom_y = sorted((top[1], bottom[1]))
    height = bottom_y - top_y
    centre_y = (top_y + bottom_y) // 2
    centre_offset_y = centre_y - npc_screen[1]
    drift = centre_offset_y - stored_offset[1] if stored_offset else None
    half = height // 2

    print(f"\nband y {top_y}..{bottom_y} ({height} px tall); centre {centre_y}",
          flush=True)
    print(f"centre offset from Charsi: {centre_offset_y} px "
          f"(stored {stored_offset[1] if stored_offset else '?'})", flush=True)

    if height <= 0:
        raise DrillAborted(
            f"the two hovers gave a {height} px band — they were probably "
            "both on the same edge; re-run and aim at top and bottom"
        )
    if drift is not None and abs(drift) <= 3:
        verdict = (
            f"BIAS THEORY WRONG: the band centre is {centre_offset_y}, within "
            f"{abs(drift)} px of the stored {stored_offset[1]}. The offset was "
            "already aimed at the centre, so T30's miss has another cause — "
            "do not trust this step unattended until that is found"
        )
    else:
        verdict = (
            f"AIM LOWER BY {drift} px: stored {stored_offset[1]}, band centre "
            f"{centre_offset_y}. Margin becomes +/-{half} px before leaving "
            f"the row, and {ROW_PITCH_PX - half} px before reaching Cancel "
            "below"
        )
    return (
        f"band {height} px tall (y {top_y}..{bottom_y}), centre offset "
        f"({stored_offset[0] if stored_offset else '?'}, {centre_offset_y}); "
        f"{verdict}"
    )


SUITE = {"T31": (T31, t31_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T31"], run=shared)
    print(f"\nsuite: T31 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
