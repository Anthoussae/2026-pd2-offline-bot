"""T59 — sprite-aim pickup, live: the bot takes potions off the floor.

**Run 1 (the hover era) failed 1/3 and started the investigation; this is
the rematch on the T63 answer.** Position clicks DO pick items — the
whole failure was aim: the clickable sprite draws ~16-40 px ABOVE the
projected ground tile (T63 measured (0, -28) bare and (-16, -40) with
labels). `PickUpItem` now aims each attempt at the next point of the
measured offset schedule; no hover reads, no label dependence.

## Protocol

1. Census: belt and inventory potions, by kind.
2. You DROP 2-3 potions on open ground AT THE CHARACTER'S FEET (within a
   couple of steps — the drill does not walk), then type **GO** in chat.
3. The bot picks them up one at a time — up to 6 paced sprite-aimed
   clicks each — reporting per potion which attempt (= which offset)
   landed it.
4. Final census. PASS = every dropped potion arrived.

**This test SENDS INPUT** — clicks only.

## How it ends

On its own after the last dropped potion is resolved (a few minutes).
Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take the mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.behavior.actions import PickUpItem  # noqa: E402
from pd2bot.behavior.execute import _PICKUP_OFFSETS, GameActionExecutor  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput, InputRefused  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
# Run 2 (1/3, all drops in a row AT the feet) suggested the character's
# own sprite occludes close items — the winning click was the westmost
# potion, T63's clean pickups were all steps away. Run 3 measures it:
# drops go 3-5 steps out in DIFFERENT directions, and the ledger carries
# each potion's direction from the player.
NEAR_SUBTILES = 15
CLICK_PACE_S = 1.2
ARRIVAL_WAIT_S = 1.0

T59 = Drill(
    test_id="T59",
    title="sprite-aim pickup — the bot takes potions off the floor",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "THE BOT CLICKS potions you drop 3-5 STEPS from the character,",
        "spread in DIFFERENT directions (one above the character, one",
        "below, one to a side). Drop 2-3 that way, then type GO.",
        "Each attempt aims at a different point of the potion's sprite",
        "(the T63 calibration). IT ENDS ON ITS OWN after the last one.",
        "Abort: 'abort' in chat, drill-cancel, ESC, or take the mouse.",
    ),
)


def _origin(run: DrillRun) -> tuple[int, int]:
    unit = player_unit(run.session)
    position = (
        unit_position(run.session, unit, offsets.UNIT_TYPE_PLAYER)
        if unit is not None
        else None
    )
    if position is None:
        raise RuntimeError("player position unreadable — not in a game?")
    return position


def _floor_potions(run: DrillRun) -> dict[int, tuple[int, tuple[int, int]]]:
    origin = _origin(run)
    found: dict[int, tuple[int, tuple[int, int]]] = {}
    for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_ITEM):
        item = _read_ground_item(run.session, unit)
        if item is None or item.kind not in offsets.POTION_KINDS:
            continue
        if (
            abs(item.position[0] - origin[0]) <= NEAR_SUBTILES
            and abs(item.position[1] - origin[1]) <= NEAR_SUBTILES
        ):
            found[item.unit_id] = (item.kind, item.position)
    return found


def _census(run: DrillRun) -> str:
    carried = read_carried_items(run.session)
    belt = sorted(i.kind for i in carried.belt)
    inventory = sorted(
        i.kind for i in carried.main_inventory if i.kind in offsets.POTION_KINDS
    )
    return f"belt {belt}; inventory potions {inventory}"


def t59_body(run: DrillRun) -> str:
    session = run.session
    print(f"census before: {_census(run)}", flush=True)

    before = set(_floor_potions(run))
    run.say(
        "Drop 2-3 potions 3-5 steps out, in DIFFERENT directions, "
        "then type GO in chat."
    )
    deadline = run.clock() + 300.0
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            break
        run.sleep(0.2)
    else:
        raise RuntimeError("no GO heard within 5 minutes")

    targets = {
        unit_id: info
        for unit_id, info in _floor_potions(run).items()
        if unit_id not in before
    }
    if not targets:
        raise RuntimeError(
            "GO heard, but no new potion is on the floor within "
            f"{NEAR_SUBTILES} subtiles of the character"
        )
    run.say(f"Saw {len(targets)} potion(s). Picking them up — hands off.")

    executor = GameActionExecutor(
        session=session,
        gated=GatedInput(session),
        walk_to=lambda target: None,  # never needed: the drill clicks in reach
        hotkeys={},
    )

    origin = _origin(run)
    print(f"player at {origin}", flush=True)

    ledger: list[str] = []
    arrived = 0
    for unit_id, (kind, position) in targets.items():
        # World y grows roughly screen-down-right; the direction label is
        # what lets the run-3 ledger separate occluded from clear drops.
        rel = (position[0] - origin[0], position[1] - origin[1])
        outcome = "never left the ground"
        for attempt in range(len(_PICKUP_OFFSETS)):
            run.check_cancel()
            try:
                executor.execute(PickUpItem(unit_id, position, attempt=attempt))
            except InputRefused as exc:
                outcome = f"refused ({exc})"
                break
            waited = time.monotonic()
            gone = False
            while time.monotonic() - waited < ARRIVAL_WAIT_S:
                if unit_id not in _floor_potions(run):
                    gone = True
                    break
                run.sleep(0.15)
            if gone:
                arrived += 1
                offset = _PICKUP_OFFSETS[attempt]
                outcome = f"ARRIVED on attempt {attempt + 1} at offset {offset}"
                break
            run.sleep(max(0.0, CLICK_PACE_S - ARRIVAL_WAIT_S))
        ledger.append(f"kind {kind} at {position} (rel {rel}): {outcome}")
        print(f"  {ledger[-1]}", flush=True)

    after = _census(run)
    print(f"census after: {after}", flush=True)
    summary = (
        f"{arrived}/{len(targets)} arrived; {'; '.join(ledger)}; after: {after}"
    )
    if arrived < len(targets):
        run.say(
            f"TEST T59 FAILED — {arrived}/{len(targets)} arrived. "
            "Hands back to you.",
            patience_s=15.0,
        )
        raise RuntimeError(summary)
    run.say(
        f"TEST T59 COMPLETE — {arrived}/{len(targets)} arrived. "
        "Hands back to you.",
        patience_s=15.0,
    )
    return summary


if __name__ == "__main__":
    status = run_drill(T59, t59_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
