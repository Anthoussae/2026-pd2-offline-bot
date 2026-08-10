"""T85b — survey Akara's shop (READ-ONLY pre-test for the restock chore).

The point of this drill is UNDERSTANDING, not calibration: it shows the
real layout of Akara's trade screen before any hover/click design is
attempted. It answers three things, all read-only, no clicking:

  1. What does Akara stock, and at which grid cell does each item sit
     (read straight from her unit's item chain)? -> the actual layout.
  2. Does the game's hovered-item slot update when the OPERATOR (real
     hand) rests the cursor on a SHOP item? (It does for ground items,
     T58; unknown for shop items.) If yes, calibration needs no cell
     naming at all — the bot pairs cursor pixel with the hovered item's
     known cell automatically.
  3. Live cursor-pixel vs hovered-item, so the pairing can be seen.

Protocol: type OK; walk to Akara; open TRADE; then just move the cursor
slowly over the potions for ~30 s. The drill prints what it sees to the
bridge transcript; the agent reads it and reports the layout back.
"""

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.items import read_vendor_stock  # noqa: E402
from pd2bot.perception.uistate import read_ui_state  # noqa: E402
from pd2bot.perception.units import (  # noqa: E402
    hovered_item_id,
    iter_units_of_type,
)

SURVEY_S = 40.0
POLL_S = 0.5

T85B = Drill(
    test_id="T85b",
    title="survey Akara's shop — read-only layout + hover pre-test",
    kind="human calibration",
    sends_input=False,
    instructions=(
        "Walk to Akara and open TRADE.",
        "Then move the cursor SLOWLY over the potions for ~40 seconds.",
        "The bot only READS — it maps the shop and tests hover; no clicks.",
        "Cancel any time: 'abort' in chat, or tools\\drill-cancel.ps1",
    ),
)


def t85b_body(run: DrillRun) -> str:
    session = run.session
    akara = _await_shop(run)

    # 1) The layout, straight from memory.
    stock = read_vendor_stock(session, akara)
    by_cell = {(p.cell): p.potion_type for p in stock}
    print("\n  === Akara's potion stock (type @ cell col,row) ===", flush=True)
    for potion in sorted(stock, key=lambda p: (p.cell[1], p.cell[0])):
        print(f"    {potion.potion_type:8s} @ col {potion.cell[0]}, "
              f"row {potion.cell[1]}  (kind {potion.kind})", flush=True)
    cols = sorted({c for c, _ in by_cell}) if by_cell else []
    rows = sorted({r for _, r in by_cell}) if by_cell else []
    print(f"  columns seen: {cols}   rows seen: {rows}", flush=True)

    stock_by_id = {p.unit_id: p for p in stock}

    # 2+3) Live hover pre-test: cursor pixel vs hovered item, dedup'd.
    print("\n  === live hover (move slowly over the potions) ===", flush=True)
    hover_worked = False
    started = time.monotonic()
    last_line = None
    while time.monotonic() - started < SURVEY_S:
        run.check_cancel()
        pos = run.cursor()
        hid = hovered_item_id(session)
        matched = stock_by_id.get(hid) if hid is not None else None
        cell = matched.cell if matched is not None else None
        if hid is not None and matched is not None:
            hover_worked = True
        line = f"    cursor {pos}  hovered_id={hid}  cell={cell}"
        if line != last_line:
            print(line, flush=True)
            last_line = line
        time.sleep(POLL_S)

    verdict = (
        "hover-read WORKS for shop items — calibration can pair "
        "pixel<->cell automatically"
        if hover_worked else
        "hover-read did NOT resolve a shop item — calibration will need "
        "geometry from known cells instead"
    )
    print(f"\n  {verdict}", flush=True)
    return f"stock: {len(stock)} potions, cols {cols} rows {rows}; {verdict}"


def _await_shop(run: DrillRun, timeout_s: float = 300.0) -> int:
    started = time.monotonic()
    last_nag = 0.0
    while time.monotonic() - started < timeout_s:
        run.check_cancel()
        akara = _find_akara(run)
        shop_open = False
        try:
            ui = read_ui_state(run.session)
            shop_open = ui is not None and ui.is_open(offsets.UI_NPCSHOP)
        except Exception:
            pass
        if akara is not None and shop_open:
            return akara
        now = time.monotonic()
        if now - last_nag >= 20.0:
            last_nag = now
            run.say(
                "Waiting for Akara's TRADE screen to open.", patience_s=2.5
            )
        time.sleep(1.0)
    raise RuntimeError("the shop never opened — T85b backstop expired")


def _find_akara(run: DrillRun) -> int | None:
    try:
        for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_MONSTER):
            if run.session.u32(
                unit + offsets.UNIT_TXT_FILE_NO
            ) == offsets.NPC_AKARA:
                return unit
    except Exception:
        return None
    return None


if __name__ == "__main__":
    argparse.ArgumentParser(description=T85B.title).parse_args()
    run_drill(T85B, t85b_body)
