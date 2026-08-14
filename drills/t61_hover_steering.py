"""T61 — hover steering and click resolution: the two questions that decide
how synthetic pickup can work at all.

**Where T60 left it (2026-08-03):** the hover pointer tracks a REAL hand
(T58) and ignores BOTH synthetic move flavors — SetCursorPos teleports
and absolute SendInput jumps (T60 run 3: 421 probes across the potion,
label visibly highlighting, zero pointer flips). Labels poll the cursor
position; the pointer listens to MOTION, and the motion dialect it might
still accept is the physical mouse's own: relative deltas.

Two questions, one drill:

**Q1 — can relative-delta motion steer the pointer?** Strategies, in
order, each read back: (a) absolute jump (the control — expected dead),
(b) a GLIDE of small relative moves walking onto the potion,
(c) SetCursorPos onto it plus a 2 px relative jiggle. First one that
flips the pointer to the target wins and becomes the pickup's hover
mechanism.

**Q2 — does a CLICK resolve against the pointer or the position?** The
record already hints pointer (T59's only arrival and T60 run 1's
centroid click both happened with the pointer latched by the user's
hand). Proof: with the pointer holding the potion, click ~100 px away
on empty ground. If the potion comes up anyway, cursor accuracy was
never the requirement — pointer state is — and pickup becomes
"set the pointer by any working means, then click".

Setup uses TWO potions: the second drop latches the pointer, so
potion 1 starts provably UN-latched and any flip to it is a real
steering success, not retention.

**This test SENDS INPUT**: cursor moves, and up to two clicks.

## How it ends

On its own after Q2 (2-3 minutes). If no strategy works, it asks for
ONE by-hand hover before Q2, then ends. Abort: 'abort' in chat,
tools\\drill-cancel.ps1, ESC, or take the mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput, InputRefused, _send_mouse_move_relative  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import (  # noqa: E402
    _read_ground_item,
    hovered_item_id,
    iter_units_of_type,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
NEAR_SUBTILES = 15
SETTLE_S = 0.08
FAR_CLICK_OFFSET = (0, 100)
ARRIVAL_WAIT_S = 2.5

T61 = Drill(
    test_id="T61",
    title="hover steering + click resolution — what can set the pointer, "
    "and what does a click obey?",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "Drop TWO potions a few steps from the character, a couple of",
        "steps APART from each other, then type GO. Hands off after that.",
        "The bot tries three ways of steering the game's hover onto the",
        "FIRST potion, then one click 100px AWAY from it — watching",
        "whether the potion comes up anyway. It may ask for ONE by-hand",
        "hover if no strategy works. ENDS ON ITS OWN. Abort: 'abort', ESC.",
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


def _await_go(run: DrillRun, timeout_s: float = 300.0) -> None:
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            return
        run.sleep(0.2)
    raise RuntimeError("no GO within the wait window")


def t61_body(run: DrillRun) -> str:
    gated = GatedInput(run.session)
    before = set(_floor_potions(run))
    run.say(
        "Drop TWO potions a few steps away, a couple of steps apart, "
        "then type GO."
    )
    _await_go(run)
    fresh = {
        unit_id: info
        for unit_id, info in _floor_potions(run).items()
        if unit_id not in before
    }
    if len(fresh) < 2:
        raise RuntimeError(f"need two fresh potions on the floor, saw {len(fresh)}")
    # Potion 1 = target; the LAST-dropped one holds the latch, and we cannot
    # know drop order — so pick as target whichever the pointer does NOT
    # currently read, which is exactly the property Q1 needs.
    latched = hovered_item_id(run.session)
    target_id = next(
        (uid for uid in fresh if uid != latched), next(iter(fresh))
    )
    kind, position = fresh[target_id]
    base = gated.project_world(*position)
    print(
        f"target: kind {kind} unit {target_id} at {position}, projection "
        f"{base}; pointer currently holds {latched}",
        flush=True,
    )
    if latched == target_id:
        raise RuntimeError(
            "the pointer already holds the target — cannot measure steering"
        )
    run.say(f"Target: the kind-{kind} potion. Hands off — steering rounds.")

    # -- Q1: which motion dialect can steer the pointer? -------------------
    def read_after(label: str) -> bool:
        run.sleep(SETTLE_S)
        got = hovered_item_id(run.session)
        hit = got == target_id
        print(f"  {label}: pointer -> {got} ({'TARGET' if hit else 'no'})", flush=True)
        return hit

    winner = None
    try:
        gated.hover_screen(*base)
        if read_after("(a) absolute jump"):
            winner = "absolute"
    except InputRefused as exc:
        print(f"  (a) refused: {exc}", flush=True)
    if winner is None:
        try:
            # Start the glide from a definite elsewhere so the walk crosses
            # onto the item the way a hand would.
            gated.hover_screen(base[0] - 120, base[1] - 90)
            run.sleep(0.05)
            gated.glide_screen(*base)
            if read_after("(b) relative glide"):
                winner = "glide"
        except InputRefused as exc:
            print(f"  (b) refused: {exc}", flush=True)
    if winner is None:
        try:
            gated.hover_screen(*base)
            run.sleep(0.02)
            _send_mouse_move_relative(2, 2)
            run.sleep(0.02)
            _send_mouse_move_relative(-2, -2)
            if read_after("(c) teleport + jiggle"):
                winner = "jiggle"
        except InputRefused as exc:
            print(f"  (c) refused: {exc}", flush=True)

    by_hand = False
    if winner is None:
        run.say(
            "No strategy worked. Hover the TARGET potion with your hand, "
            "then type GO (leave the cursor wherever you like after)."
        )
        _await_go(run)
        if hovered_item_id(run.session) != target_id:
            raise RuntimeError(
                "even the by-hand hover did not leave the pointer on the "
                "target — Q2 cannot run"
            )
        by_hand = True

    # -- Q2: does the click obey the pointer or the position? --------------
    belt_before = _belt_kinds(run)
    far = (base[0] + FAR_CLICK_OFFSET[0], base[1] + FAR_CLICK_OFFSET[1])
    still_held = hovered_item_id(run.session) == target_id
    print(f"far click at {far}; pointer on target: {still_held}", flush=True)
    gated.click_screen(*far)
    arrived = False
    waited = time.monotonic()
    while time.monotonic() - waited < ARRIVAL_WAIT_S:
        if target_id not in _floor_potions(run):
            arrived = True
            break
        run.sleep(0.15)
    belt_after = _belt_kinds(run)
    q2 = (
        "CLICK OBEYS THE POINTER — the potion came up from a click 100px away"
        if arrived
        else "click obeys the POSITION — 100px away took nothing"
    )
    print(f"Q2: {q2}; belt {belt_before} -> {belt_after}", flush=True)

    run.say("TEST T61 measurements complete. Hands back to you.", patience_s=15.0)
    return (
        f"Q1 steering: {winner or 'NONE of absolute/glide/jiggle'}"
        + (" (pointer set by hand for Q2)" if by_hand else "")
        + f"; Q2: {q2}; pointer-on-target at click time: {still_held}; "
        f"belt {belt_before} -> {belt_after}"
    )


if __name__ == "__main__":
    status = run_drill(T61, t61_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
