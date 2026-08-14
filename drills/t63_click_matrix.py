"""T63 — the click matrix: do POSITION clicks pick items, and do labels
(the ALT toggle) change the answer?

**Where the investigation stands (2026-08-03):** kolbot never solved
screen clicking (it sends engine packets); our projection and item
coordinates are proven; the open question is what the game requires of a
click. The label lighting under a teleported cursor proves a
position-based hit-test runs off the POLLED cursor — so the cheapest
live question is pure geometry: click a paced grid of offsets around
the projection and watch what arrives. No hover reads anywhere.

**The user's insight (this drill's stage 0):** ALT TOGGLES the item
label display. Labels are ~100x16 px click targets — the way humans and
every pixel bot pick items — where the sprite is a sliver. If clicks
hit-test by position, labels-ON should make the matrix connect early
and often; labels-OFF measures the bare sprite. The toggle itself is
verified live before anything trusts it (Drill Kit rule 4), and the
long-term protocol it enables is: labels ON to pick, OFF to travel
(so travel clicks cannot scoop junk).

**This test SENDS INPUT**: two ALT presses, and up to ~15 paced clicks
per round aimed around a potion you dropped. Clicks that miss are MOVE
commands — the character will wander a little; each click re-projects,
so that costs nothing.

## How it ends

On its own after round 2 (both rounds stop early on first arrival).
Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take the mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import VK_MENU, GatedInput, InputRefused  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
NEAR_SUBTILES = 15
CLICK_PACE_S = 1.2
ARRIVAL_WAIT_S = 0.9
# The matrix, ordered most-likely-first: labels draw ABOVE the sprite and
# the sprite draws above its ground tile, so the y sweep leans upward.
MATRIX = [
    (0, -16), (0, -28), (0, -4), (0, -40), (0, 8),
    (-16, -16), (16, -16), (-16, -28), (16, -28), (-16, -4),
    (16, -4), (-16, -40), (16, -40), (-16, 8), (16, 8),
]

T63 = Drill(
    test_id="T63",
    title="click matrix — position clicks vs items, labels on and off",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "Before OK: make sure item labels are HIDDEN (press Alt if they",
        "are showing). TWO ROUNDS. Each: drop ONE potion a few steps",
        "away, type GO, hands off. Round 1 first VERIFIES the Alt toggle:",
        "I press Alt and ask you to confirm labels appeared (type OK).",
        "Then a paced grid of clicks around the potion, stopping the",
        "moment one picks it up. Round 2 repeats with labels OFF.",
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


def _await_go(run: DrillRun, timeout_s: float = 300.0) -> None:
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            return
        run.sleep(0.2)
    raise RuntimeError("no GO within the wait window")


def _await_fresh_potion(
    run: DrillRun, round_no: int
) -> tuple[int, int, tuple[int, int]]:
    before = set(_floor_potions(run))
    run.say(
        f"ROUND {round_no}: drop ONE potion a few steps away, then type GO."
    )
    _await_go(run)
    fresh = {
        uid: info for uid, info in _floor_potions(run).items() if uid not in before
    }
    if not fresh:
        raise RuntimeError(f"round {round_no}: GO heard but no new potion")
    unit_id, (kind, position) = next(iter(fresh.items()))
    return unit_id, kind, position


def _matrix_round(
    run: DrillRun, gated: GatedInput, unit_id: int, position: tuple[int, int]
) -> tuple[tuple[int, int] | None, int, list[int]]:
    """Click the matrix until the item arrives. Returns (winning offset,
    clicks spent, belt after)."""
    clicks = 0
    for dx, dy in MATRIX:
        run.check_cancel()
        # Re-project EVERY click: misses are move commands and the
        # character wanders, which moves the projection with it.
        try:
            base = gated.project_world(*position)
            gated.click_screen(base[0] + dx, base[1] + dy)
        except InputRefused as exc:
            print(f"  ({dx}, {dy}): refused ({exc})", flush=True)
            continue
        clicks += 1
        waited = time.monotonic()
        arrived = False
        while time.monotonic() - waited < ARRIVAL_WAIT_S:
            if unit_id not in _floor_potions(run):
                arrived = True
                break
            run.sleep(0.1)
        if arrived:
            print(f"  ({dx}, {dy}): ARRIVED after {clicks} click(s)", flush=True)
            return (dx, dy), clicks, _belt_kinds(run)
        print(f"  ({dx}, {dy}): no pickup", flush=True)
        run.sleep(max(0.0, CLICK_PACE_S - ARRIVAL_WAIT_S))
    return None, clicks, _belt_kinds(run)


def t63_body(run: DrillRun) -> str:
    gated = GatedInput(run.session)

    # -- round 1: verify the ALT toggle, then the matrix with labels ON ----
    unit_id, kind, position = _await_fresh_potion(run, 1)
    run.say("Pressing Alt now — labels should APPEAR on the potion.")
    gated.press_key(VK_MENU)
    run.say("If labels are now SHOWING, type OK. If nothing changed, type abort.")
    if not run.await_ok(timeout_s=120.0):
        raise RuntimeError("the Alt toggle was never confirmed — no OK")
    belt_before = _belt_kinds(run)
    run.say("Labels ON confirmed. Clicking the matrix — hands off.")
    won_on, clicks_on, belt_after_on = _matrix_round(run, gated, unit_id, position)
    print(
        f"round 1 (labels ON): {won_on} in {clicks_on} clicks; "
        f"belt {belt_before} -> {belt_after_on}",
        flush=True,
    )
    run.say(
        f"Round 1: {'PICKED at offset ' + str(won_on) if won_on else 'no offset picked'}."
    )

    # -- round 2: labels OFF, same matrix ----------------------------------
    unit_id2, kind2, position2 = _await_fresh_potion(run, 2)
    run.say("Pressing Alt again — labels should HIDE.")
    gated.press_key(VK_MENU)
    run.say("If labels are now HIDDEN, type OK. If not, type abort.")
    if not run.await_ok(timeout_s=120.0):
        raise RuntimeError("the Alt un-toggle was never confirmed — no OK")
    belt_before2 = _belt_kinds(run)
    run.say("Labels OFF confirmed. Clicking the matrix — hands off.")
    won_off, clicks_off, belt_after_off = _matrix_round(
        run, gated, unit_id2, position2
    )
    print(
        f"round 2 (labels OFF): {won_off} in {clicks_off} clicks; "
        f"belt {belt_before2} -> {belt_after_off}",
        flush=True,
    )

    verdict_on = (
        f"labels ON: "
        f"{'PICKED at ' + str(won_on) if won_on else 'NOTHING picked'} "
        f"({clicks_on} clicks)"
    )
    verdict_off = (
        f"labels OFF: "
        f"{'PICKED at ' + str(won_off) if won_off else 'NOTHING picked'} "
        f"({clicks_off} clicks)"
    )
    run.say(
        f"TEST T63 done — {verdict_on}; {verdict_off}. Hands back to you.",
        patience_s=15.0,
    )
    if won_on is None and won_off is None:
        raise RuntimeError(
            f"{verdict_on}; {verdict_off} — position clicks do not pick items; "
            "the mechanism (T62, bookmarked) is the remaining road"
        )
    return (
        f"{verdict_on}; {verdict_off}; alt toggle verified both ways; "
        f"belt {belt_before} -> {belt_after_on} then {belt_before2} -> "
        f"{belt_after_off}"
    )


if __name__ == "__main__":
    status = run_drill(T63, t63_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
