"""T62 — the glide lawnmower: can continuous relative motion set the hover
slot, and what does a click obey?

**Why T61 answered nothing (2026-08-03, probe `probe-hover-slots`):** the
slot at player+0xE8 is alive and general — it currently holds a TYPE-1
unit (the merc), same game as T58 — but T61 filtered reads to items
(a slot holding the merc printed as None), told the user they could move
their hand after the control hover (real motion REPLACES the slot), and
aimed every strategy at the raw projection point, which T60 measured as
up to ~50 px off the sprite. Three self-inflicted blindfolds.

This drill removes all three:

**Stage A — the lawnmower.** A continuous glide (small relative deltas,
the physical mouse's dialect) sweeps row by row across the whole ±64 px
area around the projection, polling the RAW slot at every step. The
instant it flips to the potion: CLICK, right there — mechanism, aim
delta and end-to-end pickup proven in one gesture.

**Stage B — only if A never flips.** The by-hand control done right:
you hover the potion and HOLD STILL (no typing — the bot watches the
slot itself to know your hand is there), then the bot clicks 100 px
away on empty ground. The potion coming up = clicks resolve against
the SLOT; staying down = clicks resolve against position.

**This test SENDS INPUT**: cursor glides, and one click per stage.

## How it ends

On its own after stage A (if the click lands) or stage B (2-4 minutes).
Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take the mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import (  # noqa: E402
    GatedInput,
    InputRefused,
    _cursor_pos,
    _send_mouse_move_relative,
)
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
NEAR_SUBTILES = 15
MOW_HALF = 64
MOW_ROW_STEP = 6  # vertical distance between rows — under a sprite's height
MOW_DELTA = 5  # horizontal px per relative move — continuous, hand-like
MOW_POLL_S = 0.004
ARRIVAL_WAIT_S = 2.5
FAR_CLICK_OFFSET = (0, 100)

T62 = Drill(
    test_id="T62",
    title="glide lawnmower — continuous relative motion vs the hover slot",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "Drop ONE potion a few steps from the character, then type GO and",
        "take your hand OFF the mouse. The bot mows the area around the",
        "potion with a continuous cursor glide; if the game's hover flips,",
        "it clicks that instant — watch for the pickup. If the mow never",
        "flips it, I will ask you to hover the potion BY HAND and HOLD",
        "STILL — no typing, I detect your hand from memory — then the bot",
        "clicks 100px away to see what a click obeys.",
        "ENDS ON ITS OWN. Abort: 'abort', drill-cancel, ESC, take mouse.",
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


def _belt_kinds(run: DrillRun) -> list[int]:
    return sorted(i.kind for i in read_carried_items(run.session).belt)


def _slot_raw(run: DrillRun) -> tuple[int, str]:
    """The raw hover-slot value and a human description of what it holds."""
    player = player_unit(run.session)
    if player is None:
        return 0, "no player unit"
    try:
        value = run.session.u32(player + offsets.PLAYER_HOVER_ITEM)
    except Exception as exc:
        return 0, f"unreadable ({exc})"
    if not value:
        return 0, "null"
    try:
        t = run.session.u32(value + offsets.UNIT_TYPE)
        i = run.session.u32(value + offsets.UNIT_ID)
        k = run.session.u32(value + offsets.UNIT_TXT_FILE_NO)
        return value, f"unit type {t} id {i} kind {k}"
    except Exception:
        return value, "not readable as a unit"


def _slot_holds_item(run: DrillRun, unit_id: int) -> bool:
    player = player_unit(run.session)
    if player is None:
        return False
    try:
        value = run.session.u32(player + offsets.PLAYER_HOVER_ITEM)
        if not value:
            return False
        return (
            run.session.u32(value + offsets.UNIT_TYPE) == offsets.UNIT_TYPE_ITEM
            and run.session.u32(value + offsets.UNIT_ID) == unit_id
        )
    except Exception:
        return False


def _await_go(run: DrillRun, timeout_s: float = 300.0) -> None:
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            return
        run.sleep(0.2)
    raise RuntimeError("no GO within the wait window")


def _mow(
    run: DrillRun, gated: GatedInput, base: tuple[int, int], unit_id: int
) -> tuple[int, int] | None:
    """Sweep the area in continuous relative-delta rows, polling the raw
    slot at every step. Returns the CURSOR point at the first flip."""
    steps = flips_checked = 0
    for row, dy in enumerate(range(-MOW_HALF, MOW_HALF + 1, MOW_ROW_STEP)):
        run.check_cancel()
        # Park at the row's start with a real glide (never a teleport —
        # the whole point is that the game must HEAR the motion).
        row_x = base[0] - MOW_HALF if row % 2 == 0 else base[0] + MOW_HALF
        try:
            gated.glide_screen(row_x, base[1] + dy)
        except InputRefused:
            continue  # row start off the safe region: skip the row
        direction = 1 if row % 2 == 0 else -1
        travelled = 0
        while travelled < 2 * MOW_HALF:
            _send_mouse_move_relative(direction * MOW_DELTA, 0)
            time.sleep(MOW_POLL_S)
            travelled += MOW_DELTA
            steps += 1
            if _slot_holds_item(run, unit_id):
                cx, cy = _cursor_pos()
                print(
                    f"  FLIP at cursor ({cx}, {cy}) = delta "
                    f"({cx - base[0]}, {cy - base[1]}) after {steps} steps",
                    flush=True,
                )
                return (cx, cy)
            flips_checked += 1
    print(f"  no flip: {steps} steps, {flips_checked} polls", flush=True)
    return None


def t62_body(run: DrillRun) -> str:
    gated = GatedInput(run.session)
    value, described = _slot_raw(run)
    print(f"slot at start: {hex(value)} ({described})", flush=True)

    before = set(_floor_potions(run))
    run.say("Drop ONE potion a few steps away, type GO, then hand OFF the mouse.")
    _await_go(run)
    fresh = {
        uid: info for uid, info in _floor_potions(run).items() if uid not in before
    }
    if not fresh:
        raise RuntimeError("GO heard but no new potion on the floor")
    unit_id, (kind, position) = next(iter(fresh.items()))
    base = gated.project_world(*position)
    print(
        f"target: kind {kind} unit {unit_id} at {position}, projection {base}",
        flush=True,
    )
    run.say(f"Saw it (kind {kind}). Mowing — hands off.")

    # -- stage A: the lawnmower -------------------------------------------
    belt_before = _belt_kinds(run)
    flip_point = _mow(run, gated, base, unit_id)
    if flip_point is not None:
        gated.click_screen(*flip_point)
        arrived = False
        waited = time.monotonic()
        while time.monotonic() - waited < ARRIVAL_WAIT_S:
            if unit_id not in _floor_potions(run):
                arrived = True
                break
            run.sleep(0.15)
        belt_after = _belt_kinds(run)
        delta = (flip_point[0] - base[0], flip_point[1] - base[1])
        if arrived:
            run.say(
                "TEST T62: STAGE A PICKED IT UP — glide steering works. "
                "Hands back to you.",
                patience_s=15.0,
            )
            return (
                f"STAGE A: relative glide STEERS the slot; flip at delta "
                f"{delta}; click there ARRIVED; belt {belt_before} -> "
                f"{belt_after}"
            )
        run.say("Stage A: flip but the click took nothing. Stage B next.")
        stage_a = (
            f"STAGE A: flip at delta {delta} but the click did NOT pick up "
            f"(belt {belt_before} -> {belt_after})"
        )
    else:
        run.say("Stage A: the mow never flipped the slot. Stage B next.")
        stage_a = "STAGE A: no flip — relative deltas are not heard either"

    # -- stage B: by-hand control + the far click --------------------------
    run.say(
        "STAGE B: hover the potion with your HAND and HOLD STILL on it. "
        "No typing — I will see it in memory."
    )
    if not run.wait_until(
        lambda: _slot_holds_item(run, unit_id), timeout_s=120.0, poll_s=0.1
    ):
        raise RuntimeError(
            f"{stage_a}; STAGE B: the slot never showed your hand on the "
            "potion within 2 minutes — the slot may not track this game"
        )
    run.say("Seen. Keep the hand still — clicking far away now.")
    belt_before_b = _belt_kinds(run)
    still_held = _slot_holds_item(run, unit_id)
    far = (base[0] + FAR_CLICK_OFFSET[0], base[1] + FAR_CLICK_OFFSET[1])
    gated.click_screen(*far)
    arrived = False
    waited = time.monotonic()
    while time.monotonic() - waited < ARRIVAL_WAIT_S:
        if unit_id not in _floor_potions(run):
            arrived = True
            break
        run.sleep(0.15)
    belt_after_b = _belt_kinds(run)
    verdict = (
        "CLICK OBEYS THE SLOT — the potion came up from 100px away"
        if arrived
        else "click obeys POSITION — 100px away took nothing"
    )
    run.say(f"TEST T62 done: {verdict}. Hands back to you.", patience_s=15.0)
    return (
        f"{stage_a}; STAGE B: slot-held-at-click {still_held}; {verdict}; "
        f"belt {belt_before_b} -> {belt_after_b}"
    )


if __name__ == "__main__":
    status = run_drill(T62, t62_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
