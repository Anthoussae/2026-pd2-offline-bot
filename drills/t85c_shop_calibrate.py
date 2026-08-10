"""T85c — calibrate Akara's two potion spots (R241 item 5).

The survey (T85b) settled the reality: Akara stocks exactly two potions
the restock needs — a healing potion and a mana potion, stacked in one
column — and the game's hover slot does NOT report shop items, so we
pair by ORDER, not by hover. Two hovers, two real items the operator
can see (the red healing potion, then the blue mana potion), captured
as client-rect fractions the buy chore clicks.

READ-ONLY: reads the cursor and Akara's stock; sends nothing.

Protocol (the order is relayed out of band — the trade screen blocks
in-game chat): open Akara's TRADE, then hover the HEALING potion and
hold still, move off, hover the MANA potion and hold still. The drill
captures the two distinct still-cursor pixels and writes the
calibration for the chore.
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.items import read_vendor_stock  # noqa: E402
from pd2bot.perception.uistate import read_ui_state  # noqa: E402
from pd2bot.perception.units import iter_units_of_type  # noqa: E402

CALIBRATION_PATH = REPO / "config" / "shop_calibration.json"
STILL_SAMPLES = 30
STILL_POLL_S = 0.1
MIN_MOVE_PX = 12  # the second hover must sit this far from the first

T85C = Drill(
    test_id="T85c",
    title="calibrate Akara's potion spots — hover healing, then mana",
    kind="human calibration",
    sends_input=False,
    instructions=(
        "Open Akara's TRADE screen.",
        "Hover the HEALING potion, hold still ~3s; move off;",
        "hover the MANA potion, hold still ~3s. That's it.",
        "Cancel any time: 'abort' in chat, or tools\\drill-cancel.ps1",
    ),
)


def t85c_body(run: DrillRun) -> str:
    session = run.session
    akara = _await_shop(run)
    stock = read_vendor_stock(session, akara)
    healing = next((p for p in stock if p.potion_type == "healing"), None)
    mana = next((p for p in stock if p.potion_type == "mana"), None)
    if healing is None:
        raise RuntimeError(
            "Akara is not stocking a healing potion this read — the chore "
            "needs one; re-open the shop and retry"
        )
    print(
        "  HOVER ORDER (relayed out of band): (1) the HEALING potion, "
        "(2) the MANA potion. Hold still ~3s on each; move off between.",
        flush=True,
    )

    rect = run.window.client_rect()
    healing_px = _await_distinct_still(run, None)
    print(f"  healing potion cursor {healing_px} (cell {healing.cell})", flush=True)
    mana_px = _await_distinct_still(run, healing_px) if mana is not None else None
    if mana_px is not None:
        print(f"  mana potion cursor {mana_px} (cell {mana.cell})", flush=True)

    calibration = {
        "window": [rect.width, rect.height],
        "healing": {
            "cell": list(healing.cell),
            "fraction": [healing_px[0] / rect.width, healing_px[1] / rect.height],
        },
    }
    if mana is not None and mana_px is not None:
        calibration["mana"] = {
            "cell": list(mana.cell),
            "fraction": [mana_px[0] / rect.width, mana_px[1] / rect.height],
        }
        # Sanity: the two spots must differ (a repeated capture is a
        # miscalibration, not two potions).
        if (
            abs(mana_px[0] - healing_px[0]) < MIN_MOVE_PX
            and abs(mana_px[1] - healing_px[1]) < MIN_MOVE_PX
        ):
            raise RuntimeError(
                "the healing and mana captures coincide — hover TWO "
                "different potions"
            )

    CALIBRATION_PATH.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    summary = (
        f"healing @ px {healing_px} cell {healing.cell}"
        + (f"; mana @ px {mana_px} cell {mana.cell}" if mana_px else "; no mana")
        + f" -> {CALIBRATION_PATH.name}"
    )
    print(f"\n  {summary}", flush=True)
    return summary


def _await_distinct_still(run: DrillRun, previous):
    last = None
    held = 0
    while True:
        run.check_cancel()
        pos = run.cursor()
        held = held + 1 if pos == last else 0
        last = pos
        if held >= STILL_SAMPLES:
            if previous is None or (
                abs(pos[0] - previous[0]) >= MIN_MOVE_PX
                or abs(pos[1] - previous[1]) >= MIN_MOVE_PX
            ):
                return pos
            held = 0
        time.sleep(STILL_POLL_S)


def _await_shop(run: DrillRun, timeout_s: float = 300.0) -> int:
    started = time.monotonic()
    last_nag = 0.0
    while time.monotonic() - started < timeout_s:
        run.check_cancel()
        akara = _find_akara(run)
        try:
            ui = read_ui_state(run.session)
            shop_open = ui is not None and ui.is_open(offsets.UI_NPCSHOP)
        except Exception:
            shop_open = False
        if akara is not None and shop_open:
            return akara
        now = time.monotonic()
        if now - last_nag >= 20.0:
            last_nag = now
            run.say("Waiting for Akara's TRADE screen.", patience_s=2.5)
        time.sleep(1.0)
    raise RuntimeError("the shop never opened — T85c backstop expired")


def _find_akara(run: DrillRun) -> int | None:
    try:
        for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_MONSTER):
            if run.session.u32(unit + offsets.UNIT_TXT_FILE_NO) == offsets.NPC_AKARA:
                return unit
    except Exception:
        return None
    return None


if __name__ == "__main__":
    argparse.ArgumentParser(description=T85C.title).parse_args()
    run_drill(T85C, t85c_body)
