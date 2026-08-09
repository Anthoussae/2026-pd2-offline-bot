"""T64 — pickit accuracy: mixed drops, only the wanted taken.

**The user's peace-of-mind test (2026-08-03):** they drop a MIX of junk
and whitelisted items, say GO, and the bot must scan the drops, decide
each one with the SHIPPED pickit (config/pickit.toml, loaded exactly the
way the wiring loads it), announce its plan, take only what the rules
want, and leave the junk lying. Accuracy is assessed on both sides:

- every WANTED item must arrive (leave the ground, via the T63
  sprite-aim schedule, up to 6 clicks each);
- every JUNK item must still be on the ground at the end — an
  accidental pickup is a failure even if everything wanted arrived.

The decision ledger names the RULE behind every verdict, so a
disagreement between the user's intent and the config reads as exactly
that — a config conversation, not a mystery.

**This test SENDS INPUT** — aimed clicks at the wanted items only.
Anything the pickit wants WILL be taken (keeps go to the inventory,
potions to the belt/reserve, gold to the purse); junk stays on the
ground for you to retrieve.

## How it ends

On its own once every wanted item is resolved and the junk re-scanned
(a few minutes). Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC,
or take the mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.behavior.actions import PickUpItem  # noqa: E402
from pd2bot.behavior.execute import _PICKUP_OFFSETS, GameActionExecutor  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput, InputRefused  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import (  # noqa: E402
    GroundItem,
    _read_ground_item,
    iter_units_of_type,
    player_unit,
    unit_position,
)
from pd2bot.pickit import load_item_table, load_pickit  # noqa: E402
from pd2bot.wiring import BotPaths, belt_capacity, load_class_config  # noqa: E402

GO_WORDS = frozenset({"go", "go!"})
NEAR_SUBTILES = 15
CLICK_PACE_S = 1.2
ARRIVAL_WAIT_S = 1.0

T64 = Drill(
    test_id="T64",
    title="pickit accuracy — mixed drops, only the wanted taken",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "Drop a MIX of junk and whitelisted items 2-6 steps from the",
        "character (spread them a little), then type GO. The bot decides",
        "each drop with the real pickit, says its plan, takes ONLY what",
        "the rules want, and leaves the junk for you to retrieve.",
        "Judge it on both sides: wanted taken, junk untouched.",
        "IT ENDS ON ITS OWN. Abort: 'abort', drill-cancel, ESC, mouse.",
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


def _floor_items(run: DrillRun) -> dict[int, GroundItem]:
    """ALL ground items near the player — junk judging needs every kind."""
    origin = _origin(run)
    found: dict[int, GroundItem] = {}
    for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_ITEM):
        item = _read_ground_item(run.session, unit)
        if item is None:
            continue
        if (
            abs(item.position[0] - origin[0]) <= NEAR_SUBTILES
            and abs(item.position[1] - origin[1]) <= NEAR_SUBTILES
        ):
            found[item.unit_id] = item
    return found


def _await_go(run: DrillRun, timeout_s: float = 300.0) -> None:
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            return
        run.sleep(0.2)
    raise RuntimeError("no GO within the wait window")


def t64_body(run: DrillRun) -> str:
    session = run.session
    paths = BotPaths()
    class_config = load_class_config(paths.class_config)
    pickit = load_pickit(
        paths.pickit,
        item_table=load_item_table(paths.item_table),
        belt_capacity=belt_capacity(class_config),
    )
    inventory_before = len(read_carried_items(session).main_inventory)

    # The baseline is taken NOW, so items dropped before the OK gate read
    # as pre-existing (run 1 failed on exactly that). The loop gives the
    # drop-first user a second (and third) GO instead of a failure.
    before = set(_floor_items(run))
    fresh: dict[int, GroundItem] = {}
    for round_no in range(3):
        run.say(
            "Drop a MIX of junk and whitelisted items 2-6 steps out "
            "— AFTER this message — then type GO."
            if round_no == 0
            else "I see no NEW drops since the test began. Drop them NOW, "
            "then type GO again."
        )
        _await_go(run)
        fresh = {
            uid: item
            for uid, item in _floor_items(run).items()
            if uid not in before
        }
        if fresh:
            break
    if not fresh:
        raise RuntimeError("three GOs and never a new item on the floor")

    carried = read_carried_items(session)
    wanted: list[tuple[int, GroundItem, str, str]] = []
    junk: list[tuple[int, GroundItem, str]] = []
    for uid, item in fresh.items():
        action, rule = pickit.decide(item, carried)
        line = (
            f"kind {item.kind} quality {item.quality} sockets {item.sockets} "
            f"at {item.position} -> {action} ({rule})"
        )
        print(f"  decision: {line}", flush=True)
        if action == "skip":
            junk.append((uid, item, rule))
        else:
            wanted.append((uid, item, action, rule))
    run.say(
        f"Saw {len(fresh)} drop(s): {len(wanted)} wanted, {len(junk)} junk. "
        "Taking the wanted — hands off."
    )

    executor = GameActionExecutor(
        session=session,
        gated=GatedInput(session),
        walk_to=lambda target: None,
        hotkeys={},
    )

    ledger: list[str] = []
    arrived = 0
    for uid, item, _action, rule in wanted:
        outcome = "never left the ground"
        for attempt in range(len(_PICKUP_OFFSETS)):
            run.check_cancel()
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
                outcome = f"ARRIVED on attempt {attempt + 1}"
                break
            run.sleep(max(0.0, CLICK_PACE_S - ARRIVAL_WAIT_S))
        ledger.append(f"WANTED kind {item.kind} ({rule}): {outcome}")
        print(f"  {ledger[-1]}", flush=True)

    # The other half of accuracy: the junk must still be lying there.
    run.sleep(0.5)
    remaining = _floor_items(run)
    junk_taken = [
        f"kind {item.kind} ({rule})"
        for uid, item, rule in junk
        if uid not in remaining
    ]
    junk_left = len(junk) - len(junk_taken)
    inventory_after = len(read_carried_items(session).main_inventory)

    summary = (
        f"wanted: {arrived}/{len(wanted)} taken; junk: {junk_left}/{len(junk)} "
        f"left lying"
        + (f"; JUNK TAKEN: {', '.join(junk_taken)}" if junk_taken else "")
        + f"; inventory {inventory_before} -> {inventory_after}; "
        + "; ".join(ledger)
    )
    ok = arrived == len(wanted) and not junk_taken
    run.say(
        f"TEST T64 {'COMPLETE' if ok else 'FAILED'} — {arrived}/{len(wanted)} "
        f"wanted taken, {junk_left}/{len(junk)} junk left. Hands back to you.",
        patience_s=15.0,
    )
    if not ok:
        raise RuntimeError(summary)
    return summary


if __name__ == "__main__":
    status = run_drill(T64, t64_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
