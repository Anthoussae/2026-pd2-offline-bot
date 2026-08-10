"""T85 — calibrate the vendor shop grid (R241 item 5).

The shop's item cells are FURNITURE: the panel's grid origin and cell
size are fixed even though WHICH potion sits in WHICH cell is not (that
is read fresh from memory each visit — the user's Q4 point). This drill
measures the fixed part: open Akara's shop, hover the cells it names,
and it records origin + cell size as client-rect fractions (the
uipoints convention), cross-checking each prediction against the live
cursor to catch a bad measurement before any buy click trusts it.

READ-ONLY: it reads the cursor and the vendor's stock; it sends
nothing. The operator does the hovering.

Protocol: talk to Akara, open Trade; then hover the cells the drill
names on each chat prompt and hold still. It prints the derived grid
and the ±px agreement per sample; >~4 px on any sample means re-measure.
"""

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.items import read_vendor_stock  # noqa: E402

STILL_SAMPLES = 30  # ~3 s of a held cursor (the T25 idiom)
STILL_POLL_S = 0.1

# The cells to hover, chosen at the grid's corners so the derived origin
# and cell size are least sensitive to a shaky hand.
SAMPLE_CELLS = ((0, 0), (3, 0), (0, 4))
TOLERANCE_PX = 4.0

T85 = Drill(
    test_id="T85",
    title="calibrate the vendor shop grid — you hover, the bot measures",
    kind="human calibration",
    sends_input=False,
    instructions=(
        "Talk to Akara and open TRADE so the shop grid is visible.",
        "On each prompt, hover the named cell's CENTRE and hold still.",
        "The drill prints the grid it derived and the ±px agreement.",
        "Cancel any time: 'abort' in chat, or tools\\drill-cancel.ps1",
    ),
)


def t85_body(run: DrillRun) -> str:
    session = run.session
    # R243: chatting is allowed while the TRADE screen is open — the
    # operator's call, and the whole point of this drill is prompting
    # them while they look at that screen.
    from pd2bot import offsets
    from pd2bot.input.chat import Chat

    run.chat = Chat(session, allow_panels=frozenset({offsets.UI_NPCSHOP}))
    # WAIT for the operator to reach Akara and open the shop — the first
    # run of this drill read instantly on OK and failed while the
    # operator was still walking (the announcement-vs-reality gap the
    # T70 run 1 lesson already named).
    akara = _await_shop_open(run)
    # Read the stock once so the write-up records what Akara had — proof
    # the vendor-stock read works against the live NPC, independent of
    # the geometry the operator hovers.
    stock = read_vendor_stock(session, akara)
    kinds = ", ".join(sorted({p.potion_type for p in stock})) or "none read"
    run.say(f"Akara stocks: {len(stock)} potion(s) [{kinds}].", patience_s=2.5)

    samples: dict[tuple[int, int], tuple[int, int]] = {}
    for cell in SAMPLE_CELLS:
        run.say(
            f"Hover cell (col {cell[0]}, row {cell[1]}) centre; hold still.",
            patience_s=3.0,
        )
        pos = _await_still_cursor(run)
        samples[cell] = pos
        print(f"  cell {cell}: cursor at {pos}", flush=True)

    origin, cell_size = _derive_grid(samples)
    worst = _cross_check(samples, origin, cell_size)
    verdict = "PASS" if worst <= TOLERANCE_PX else "RE-MEASURE"
    rect = run.window.client_rect()
    fo = (origin[0] / rect.width, origin[1] / rect.height)
    fs = (cell_size[0] / rect.width, cell_size[1] / rect.height)
    summary = (
        f"grid origin px {origin} ~ fraction ({fo[0]:.4f}, {fo[1]:.4f}); "
        f"cell size px {cell_size} ~ ({fs[0]:.4f}, {fs[1]:.4f}); "
        f"worst cross-check {worst:.1f}px -> {verdict}"
    )
    print(f"\n  {summary}", flush=True)
    run.say(f"T85 {verdict} — {summary}", patience_s=10.0)
    return summary


def _await_shop_open(run: DrillRun, timeout_s: float = 300.0) -> int:
    """Block until Akara is in perception AND her shop panel is open;
    returns her unit id. Announces progress; the drill's backstop is the
    timeout."""
    from pd2bot import offsets
    from pd2bot.perception.uistate import read_ui_state

    started = time.monotonic()
    last_nag = 0.0
    while time.monotonic() - started < timeout_s:
        run.check_cancel()
        akara = _find_akara(run)
        shop_open = False
        try:
            ui = read_ui_state(run.session)
            shop_open = ui is not None and offsets.UI_NPCSHOP in ui.open_panels
        except Exception:
            pass
        if akara is not None and shop_open:
            return akara
        now = time.monotonic()
        if now - last_nag >= 20.0:
            last_nag = now
            missing = "walk to Akara" if akara is None else "open TRADE"
            run.say(f"Waiting: {missing} (the drill reads when the shop is open).",
                    patience_s=2.5)
        time.sleep(1.0)
    raise RuntimeError("the shop never opened — T85 backstop expired")


def _find_akara(run: DrillRun) -> int | None:
    """Akara's unit ADDRESS (what the inventory walk dereferences) —
    the first T85b run passed her unit ID here and read address ~110."""
    from pd2bot import offsets
    from pd2bot.perception.units import iter_units_of_type

    try:
        for unit in iter_units_of_type(
            run.session, offsets.UNIT_TYPE_MONSTER
        ):
            if run.session.u32(
                unit + offsets.UNIT_TXT_FILE_NO
            ) == offsets.NPC_AKARA:
                return unit
    except Exception:
        return None
    return None


def _await_still_cursor(run: DrillRun) -> tuple[int, int]:
    """Block until the cursor holds one spot for STILL_SAMPLES polls,
    then return it (the T25 hover-capture idiom, inline)."""
    last = None
    held = 0
    while held < STILL_SAMPLES:
        run.check_cancel()
        pos = run.cursor()
        held = held + 1 if pos == last else 0
        last = pos
        time.sleep(STILL_POLL_S)
    return last


def _akara_unit(run: DrillRun) -> int:  # kept for reference; superseded by _await_shop_open
    from pd2bot import offsets
    from pd2bot.perception.units import scan_units

    scan = scan_units(run.session)
    for ally in scan.allies:
        if ally.kind == offsets.NPC_AKARA:
            return ally.unit_id
    raise RuntimeError("Akara is not in perception range — stand at her shop")


def _derive_grid(samples):
    """Origin (cell 0,0 centre) and per-cell pixel deltas from the corners."""
    o = samples[(0, 0)]
    dx = (samples[(3, 0)][0] - o[0]) / 3
    dy = (samples[(0, 4)][1] - o[1]) / 4
    return o, (round(dx), round(dy))


def _cross_check(samples, origin, cell_size) -> float:
    worst = 0.0
    for (cx, cy), pos in samples.items():
        pred = (origin[0] + cx * cell_size[0], origin[1] + cy * cell_size[1])
        worst = max(worst, abs(pred[0] - pos[0]), abs(pred[1] - pos[1]))
    return worst


if __name__ == "__main__":
    argparse.ArgumentParser(description=T85.title).parse_args()
    run_drill(T85, t85_body)
