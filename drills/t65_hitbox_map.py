"""T65 — hitbox mapping: WHERE exactly is each item class clickable?

**Autonomous** (user mandate, 2026-08-03): the user has tabbed in and
waived the OK gate for the accuracy campaign; this drill starts the
moment its banner lands. It probes JUNK items lying in town — never
whitelisted ones — clicking one offset at a time with arrival checks,
walking back to a standoff between probes, and rotating each item's
probe order so that, across items, hits and misses together map the
clickable region per item class (a rune sprite is a sliver; an armor
sprite is a slab; T63's single offset cannot serve both).

Each probed item ends up in the inventory the moment a probe hits (it
is junk by the shipped pickit's own verdict; the next cleanse deals
with it). Every probe BEFORE the hit is a confirmed miss at that
offset. The output is the raw ledger the aim refinement is built from.

## How it ends

On its own: after every eligible junk item is probed (or 10 items,
whichever first). Abort: 'abort' in chat, drill-cancel, ESC, mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import VK_I, VK_MENU, GatedInput, InputRefused  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import (  # noqa: E402
    GroundItem,
    _read_ground_item,
    iter_units_of_type,
    label_display_on,
    player_unit,
    unit_position,
)
from pd2bot.pickit import load_item_table, load_pickit  # noqa: E402
from pd2bot.wiring import (  # noqa: E402
    BotPaths,
    belt_capacity,
    build_bot,
    load_class_config,
)

NEAR_SUBTILES = 25
NEIGHBOR_CLEAR = 8  # probe only items with no other item this close (world)
MAX_ITEMS = 10
PROBE_PACE_S = 1.2  # covers instant picks; standoff sits INSIDE reach
STANDOFF = (3, 3)  # inside pickup reach 4: hits register instantly, no walk-pick
# The probe grid, covering everything the night's data suggested plus
# margin: x -32..32, y -52..4, 8 px pitch.
GRID = [
    (dx, dy)
    for dy in range(-48, 1, 8)
    for dx in range(-24, 25, 8)
]
TIME_BUDGET_S = 600.0  # the bridge kills at 1200; self-limit and report partials

T65 = Drill(
    test_id="T65",
    title="hitbox mapping — where each item class is clickable",
    kind="bot control",
    sends_input=True,
    menu_ok=True,  # autonomous: the user waived the gate for this campaign
    instructions=(
        "AUTONOMOUS calibration — starts immediately, no OK needed.",
        "The bot probes JUNK items lying in town with single clicks,",
        "mapping where each item class is clickable. Probed junk lands",
        "in the inventory (the cleanse deals with it later).",
        "Stay tabbed in; hands off. ENDS ON ITS OWN after <=10 items.",
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


def _floor_items(run: DrillRun) -> dict[int, GroundItem]:
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


def _walk_near(run: DrillRun, gated: GatedInput, target: tuple[int, int]) -> bool:
    """Best-effort short town walk: click toward `target` until within 2."""
    for _ in range(4):
        run.check_cancel()
        origin = _origin(run)
        if max(abs(origin[0] - target[0]), abs(origin[1] - target[1])) <= 2:
            return True
        try:
            gated.click_world(*target)
        except InputRefused:
            return False
        deadline = time.monotonic() + 3.0
        while time.monotonic() - deadline < 0:
            here = _origin(run)
            if max(abs(here[0] - target[0]), abs(here[1] - target[1])) <= 2:
                return True
            run.sleep(0.2)
    return False


def _self_drop(run: DrillRun, gated: GatedInput, town, pickit, count: int = 6) -> int:
    """Drop up to `count` pickit-junk items from the inventory at the feet.

    The user sanctioned the inventory (minus the Cube) as test material.
    Right-click hazards (potions, tomes) are never dropped — the gesture
    is ctrl+RIGHT-click, and a settle failure on those DRINKS them.
    """
    carried = read_carried_items(run.session)
    junk = [
        i for i in carried.main_inventory
        if i.kind not in offsets.UNMOVABLE_KINDS
        and i.kind not in offsets.RIGHT_CLICK_HAZARD_KINDS
    ][:count]  # junk AND wanted alike: the user stocked both for testing
    if not junk:
        return 0
    gated.press_key(VK_I)
    run.sleep(0.6)
    if not run.panel_open(offsets.UI_INVENTORY):
        raise RuntimeError("the inventory panel did not open for the self-drop")
    dropped = 0
    for item in junk:
        run.check_cancel()
        if town.drop_item(item):
            dropped += 1
    town.close_panels()
    run.sleep(0.4)
    return dropped


def t65_body(run: DrillRun) -> str:
    session = run.session
    paths = BotPaths()
    pickit = load_pickit(
        paths.pickit,
        item_table=load_item_table(paths.item_table),
        belt_capacity=belt_capacity(load_class_config(paths.class_config)),
    )
    bot = build_bot(session)
    gated = GatedInput(session)
    # Label policy for the probe: ON, verified via the T66 flag — the first
    # time the bot KNOWS the toggle state instead of assuming it.
    for _ in range(2):
        state = label_display_on(session)
        print(f"label display: {state}", flush=True)
        if state:
            break
        gated.press_key(VK_MENU)
        run.sleep(0.3)

    def junk_on_floor() -> dict[int, GroundItem]:
        return dict(_floor_items(run))  # both classes probed since v4

    targets = junk_on_floor()
    if len(targets) < 3:
        made = _self_drop(run, gated, bot.town, pickit)
        print(f"self-drop: {made} junk item(s) put on the floor", flush=True)
        run.sleep(0.5)
        targets = junk_on_floor()
    if not targets:
        raise RuntimeError("no junk to probe: floor empty and nothing droppable")
    run.say(f"T65: probing {len(targets)} junk item(s). Hands off.", patience_s=10.0)

    # Step away so the pile is clear of the character sprite.
    origin = _origin(run)
    _walk_near(run, gated, (origin[0] + 6, origin[1] + 6))

    hits: list[str] = []
    misses: dict[int, list[tuple[int, int]]] = {}
    # Vary the first offset per RUN too, or every rerun re-tests the
    # same corner (run 4: two first-probe hits, zero information).
    rotation = int(time.time()) % len(GRID)
    probes = 0
    started = time.monotonic()
    while targets and probes < 200 and time.monotonic() - started < TIME_BUDGET_S:
        run.check_cancel()
        origin = _origin(run)
        uid, item = min(
            targets.items(),
            key=lambda kv: max(
                abs(kv[1].position[0] - origin[0]),
                abs(kv[1].position[1] - origin[1]),
            ),
        )
        order = GRID[rotation:] + GRID[:rotation]
        rotation = (rotation + 7) % len(GRID)
        standoff = (item.position[0] + STANDOFF[0], item.position[1] + STANDOFF[1])
        _walk_near(run, gated, standoff)
        for dx, dy in order:
            run.check_cancel()
            floor_before = _floor_items(run)
            if uid not in floor_before:
                break
            projections = {
                u: gated.project_world(*it.position)
                for u, it in floor_before.items()
            }
            try:
                aim = (projections[uid][0] + dx, projections[uid][1] + dy)
                gated.click_screen(*aim)
            except InputRefused:
                continue
            probes += 1
            run.sleep(PROBE_PACE_S)
            floor_after = _floor_items(run)
            vanished = [u for u in floor_before if u not in floor_after]
            if vanished:
                for gone in vanished:
                    px, py = projections[gone]
                    rel = (aim[0] - px, aim[1] - py)
                    kind = floor_before[gone].kind
                    hits.append(f"kind {kind} HIT at {rel}")
                    print(f"  kind {kind} HIT at {rel} (aimed at {uid})", flush=True)
                break
            misses.setdefault(item.kind, []).append((dx, dy))
            here = _origin(run)
            if max(abs(here[0] - standoff[0]), abs(here[1] - standoff[1])) > 2:
                _walk_near(run, gated, standoff)
        targets = junk_on_floor()

    miss_lines = [
        f"kind {k}: {len(v)} misses {v[:12]}" for k, v in misses.items()
    ]
    summary = (
        f"{probes} probes; {len(hits)} hit sample(s): "
        + "; ".join(hits)
        + " || misses: "
        + "; ".join(miss_lines)
    )
    run.say(f"TEST T65 done — {len(hits)} hits in {probes} probes.", patience_s=15.0)
    return summary  # partial data is still data; the analysis judges it


if __name__ == "__main__":
    status = run_drill(T65, t65_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
