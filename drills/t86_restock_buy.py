"""T86 — prove the buy mechanic (R241 item 5, the risky half).

Does right-clicking the calibrated healing-potion spot actually BUY a
potion, and can the belt-count delta verify it? That is the one live
unknown the offline planning could not settle. The operator opens the
shop; this drill buys healing potions up to a small test target,
verifying each purchase by the belt's healing count rising. Autonomous
trade-opening is the real chore's job (built on open_npc_dialog once
this mechanic is proven); this isolates the mechanic.

Sends input (right-clicks in the shop) — supervised, hands near ESC.
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
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.uistate import read_ui_state  # noqa: E402

CALIBRATION = REPO / "config" / "shop_calibration.json"
BUY_TARGET = 3  # buy this many healing potions in the test (bounded spend)
MAX_ATTEMPTS = 10
VERIFY_S = 1.5
PACE_S = 0.4

T86 = Drill(
    test_id="T86",
    title="prove the buy mechanic — right-click buys, belt-count verifies",
    kind="supervised live",
    sends_input=True,
    instructions=(
        "Open Akara's TRADE screen and leave it open.",
        "The bot buys up to 3 healing potions, verifying each by belt count.",
        "SUPERVISED: hands near ESC. Cancel: 'abort' in chat.",
    ),
)


def _belt_healing(session) -> int:
    carried = read_carried_items(session, with_sockets=False)
    return sum(1 for i in carried.belt if i.is_healing_potion)


def t86_body(run: DrillRun) -> str:
    session = run.session
    calib = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    rect = run.window.client_rect()
    fx, fy = calib["healing"]["fraction"]
    px, py = round(fx * rect.width), round(fy * rect.height)

    _await_shop(run)
    panel = PanelInput(session)

    before = _belt_healing(session)
    gold_before = _player_gold(session)
    print(f"  belt healing before: {before}; gold: {gold_before}; "
          f"healing spot px ({px}, {py})", flush=True)

    bought = 0
    attempts = 0
    while bought < BUY_TARGET and attempts < MAX_ATTEMPTS:
        run.check_cancel()
        attempts += 1
        want = before + bought + 1
        try:
            panel.click(offsets.UI_NPCSHOP, px, py, button="right")
        except Exception as exc:  # noqa: BLE001
            print(f"  attempt {attempts}: click refused ({exc})", flush=True)
            time.sleep(PACE_S)
            continue
        # Verify by effect: the belt's healing count reaches `want`.
        deadline = time.monotonic() + VERIFY_S
        landed = False
        while time.monotonic() < deadline:
            if _belt_healing(session) >= want:
                landed = True
                break
            time.sleep(0.1)
        if landed:
            bought += 1
            print(f"  attempt {attempts}: bought #{bought} "
                  f"(belt healing now {before + bought})", flush=True)
        else:
            print(f"  attempt {attempts}: no belt change "
                  f"(still {_belt_healing(session)})", flush=True)
        time.sleep(PACE_S)

    after = _belt_healing(session)
    gold_after = _player_gold(session)
    verdict = "PASS" if bought >= 1 else "FAIL (no purchase verified)"
    summary = (
        f"{verdict}: bought {bought}/{BUY_TARGET} in {attempts} attempts; "
        f"belt healing {before}->{after}; gold {gold_before}->{gold_after}"
    )
    print(f"\n  {summary}", flush=True)
    if bought == 0:
        raise RuntimeError(summary)
    return summary


def _player_gold(session) -> int | None:
    p = read_player(session)
    return p.gold if p is not None else None


def _await_shop(run: DrillRun, timeout_s: float = 300.0) -> None:
    started = time.monotonic()
    last_nag = 0.0
    while time.monotonic() - started < timeout_s:
        run.check_cancel()
        try:
            ui = read_ui_state(run.session)
            if ui is not None and ui.is_open(offsets.UI_NPCSHOP):
                return
        except Exception:
            pass
        now = time.monotonic()
        if now - last_nag >= 20.0:
            last_nag = now
            run.say("Open Akara's TRADE screen to begin.", patience_s=2.5)
        time.sleep(1.0)
    raise RuntimeError("the shop never opened — T86 backstop expired")


if __name__ == "__main__":
    argparse.ArgumentParser(description=T86.title).parse_args()
    run_drill(T86, t86_body)
