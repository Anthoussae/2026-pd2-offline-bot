"""T67 — sparse melange: the accuracy validation, fully self-staged.

**Autonomous** (R207). The bot stages its own field-realistic test: five
single-item drops at spread stops (no pile-label displacement), labels
verified ON via the T66 flag, then the T64 protocol — decide each drop
with the shipped pickit, take ONLY the wanted with the label-band-aware
offset schedule, leave the junk, re-scan, and judge both sides.

PASS = every wanted item arrived AND zero junk taken. The ledger also
reports attempts-per-arrival — the speed metric the campaign optimizes.

Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take the mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drills.t65_hitbox_map import (  # noqa: E402
    _floor_items,
    _origin,
    _self_drop,
    _walk_near,
)
from pd2bot.behavior.actions import PickUpItem  # noqa: E402
from pd2bot.behavior.execute import _PICKUP_OFFSETS, GameActionExecutor  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import VK_MENU, GatedInput, InputRefused  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.pickit import load_item_table, load_pickit  # noqa: E402
from pd2bot.units import label_display_on  # noqa: E402
from pd2bot.wiring import (  # noqa: E402
    BotPaths,
    belt_capacity,
    build_bot,
    load_class_config,
)

STOPS = [(0, 0), (7, 0), (0, 7), (-7, 7), (7, 7)]
CLICK_PACE_S = 1.2
ARRIVAL_WAIT_S = 1.0

T67 = Drill(
    test_id="T67",
    title="sparse melange — self-staged accuracy validation",
    kind="bot control",
    sends_input=True,
    menu_ok=True,
    instructions=(
        "AUTONOMOUS: the bot drops five inventory items at spread stops,",
        "then takes ONLY what the pickit wants and leaves the junk.",
        "Hands off. ENDS ON ITS OWN. Abort: 'abort', ESC, take the mouse.",
    ),
)


def t67_body(run: DrillRun) -> str:
    session = run.session
    paths = BotPaths()
    pickit = load_pickit(
        paths.pickit,
        item_table=load_item_table(paths.item_table),
        belt_capacity=belt_capacity(load_class_config(paths.class_config)),
    )
    bot = build_bot(session)
    gated = GatedInput(session)
    for _ in range(2):
        if label_display_on(session):
            break
        gated.press_key(VK_MENU)
        run.sleep(0.3)
    print(f"label display: {label_display_on(session)}", flush=True)

    before = set(_floor_items(run))
    base = _origin(run)
    staged = 0
    for dx, dy in STOPS:
        run.check_cancel()
        _walk_near(run, gated, (base[0] + dx, base[1] + dy))
        staged += _self_drop(run, gated, bot.town, pickit, count=1)
    fresh = {
        uid: item for uid, item in _floor_items(run).items() if uid not in before
    }
    print(f"staged {staged}; fresh on floor {len(fresh)}", flush=True)
    if not fresh:
        raise RuntimeError("nothing staged — inventory empty of droppables?")

    carried = read_carried_items(session)
    wanted, junk = [], []
    for uid, item in fresh.items():
        action, rule = pickit.decide(item, carried)
        print(f"  decision: kind {item.kind} -> {action} ({rule})", flush=True)
        (junk if action == "skip" else wanted).append((uid, item, rule))
    run.say(
        f"T67: {len(wanted)} wanted, {len(junk)} junk. Taking the wanted.",
        patience_s=10.0,
    )

    executor = GameActionExecutor(
        session=session, gated=gated, walk_to=lambda t: None, hotkeys={}
    )
    ledger, arrived, total_attempts = [], 0, 0
    for uid, item, rule in wanted:
        run.check_cancel()
        _walk_near(run, gated, (item.position[0] + 3, item.position[1] + 3))
        outcome = "never left the ground"
        for attempt in range(len(_PICKUP_OFFSETS)):
            try:
                executor.execute(PickUpItem(uid, item.position, attempt=attempt))
            except InputRefused as exc:
                outcome = f"refused ({exc})"
                break
            waited = time.monotonic()
            gone = False
            while time.monotonic() - waited < ARRIVAL_WAIT_S:
                if uid not in _floor_items(run):
                    gone = True
                    break
                run.sleep(0.15)
            if gone:
                arrived += 1
                total_attempts += attempt + 1
                outcome = f"ARRIVED on attempt {attempt + 1}"
                break
            run.sleep(max(0.0, CLICK_PACE_S - ARRIVAL_WAIT_S))
        ledger.append(f"WANTED kind {item.kind} ({rule}): {outcome}")
        print(f"  {ledger[-1]}", flush=True)

    run.sleep(0.5)
    remaining = _floor_items(run)
    junk_taken = [f"kind {i.kind}" for uid, i, _ in junk if uid not in remaining]
    ok = arrived == len(wanted) and not junk_taken
    mean = f"{total_attempts / arrived:.1f}" if arrived else "n/a"
    summary = (
        f"wanted {arrived}/{len(wanted)} taken (mean attempts {mean}); "
        f"junk taken {len(junk_taken)}/{len(junk)}"
        + (f" ({', '.join(junk_taken)})" if junk_taken else "")
        + "; " + "; ".join(ledger)
    )
    run.say(
        f"TEST T67 {'COMPLETE' if ok else 'FAILED'} — {arrived}/{len(wanted)} "
        f"wanted, {len(junk_taken)} junk taken. Hands back.",
        patience_s=15.0,
    )
    if not ok:
        raise RuntimeError(summary)
    return summary


if __name__ == "__main__":
    status = run_drill(T67, t67_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
