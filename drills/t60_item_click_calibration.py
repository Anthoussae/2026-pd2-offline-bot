"""T60 — item-click calibration: WHERE is a ground item actually clickable?

**The user watched T59 and named it (2026-08-03):** the bot's clicks were
close but OFF — a systematic aim error on ground items. That one error
explains T59's misses, T57's ~1-in-30 arrival rate, whitelisted runes
clicked-near-but-never-taken, and likely some "dither loops" (T55 run 2's
seam item included). The movement projection is calibrated and fine
(R6: error (0,1) px); what has never been measured is where an ITEM's
clickable region sits relative to the projection of its ground tile.

The hover pointer (T58, player unit + 0xE8) is ground truth for exactly
that question. So this drill MAPS it: sweep the cursor over a grid
around the projected point of a dropped potion, read after every move
whether the game says the cursor is on it, and report the confirming
region — its bounds and its centroid's offset from the projection. Then
prove it end to end: one click at the measured centroid, and the belt
census before/after says where the potion actually went (auto-belt or
cursor). Two rounds at different spots separate a constant offset from a
direction-dependent one.

**This test SENDS INPUT**: cursor sweeps, and ONE verification click per
round, aimed at a potion you dropped for exactly that purpose.

## How it ends

On its own, after two rounds (about a minute of sweeping each plus the
clicks). Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take
the mouse.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput, InputRefused  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.units import (  # noqa: E402
    _read_ground_item,
    hovered_item_id,
    iter_units_of_type,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
NEAR_SUBTILES = 15
ROUNDS = 3
# The sweep. Run 2 taught the protocol (2026-08-03): the pointer SETS
# crisply when the cursor first crosses the item and then clears LAZILY,
# so confirmations trail the cursor and a region centroid means nothing
# (run 2's "regions" were retention smears; the click at their centroid
# found the hover already lost). The honest gesture is TRANSITION-CLICK:
# sweep until the pointer FIRST flips to the target, and click right
# there, immediately — which is also exactly the executor's pickup
# protocol, so each round validates the real path end to end.
SWEEP_STEP = 8
SWEEP_HALF = 56
WIDE_STEP = 16
WIDE_HALF = 104
HOVER_SETTLE_S = 0.05
ARRIVAL_WAIT_S = 2.5
# Where the cursor parks to prove the pointer is NOT already latched on
# the target before the sweep is believed (the user's own drop latches
# it — run 1 round 2 read all 225 cells "confirmed" from exactly that).
NEUTRAL_PARKS = ((-120, 100), (120, 100), (0, 130))

T60 = Drill(
    test_id="T60",
    title="item-click calibration — where is a ground item clickable?",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "THREE ROUNDS. Each: drop ONE potion a few steps from the",
        "character (2-4 steps, clear of NPCs and the merc), then type GO.",
        "The bot sweeps the cursor until the game FIRST says 'on it' and",
        "clicks that instant — watch the potion vanish into the belt.",
        "Between rounds, walk somewhere else and repeat on my mark.",
        "IT ENDS ON ITS OWN after round 3. Abort: 'abort', ESC, mouse.",
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


def _await_go_and_drop(run: DrillRun, round_no: int) -> tuple[int, int, tuple[int, int]]:
    before = set(_floor_potions(run))
    run.say(
        f"ROUND {round_no}: drop ONE potion 2-4 steps from the character, "
        "clear of NPCs, then type GO."
    )
    deadline = run.clock() + 300.0
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            break
        run.sleep(0.2)
    else:
        raise RuntimeError(f"round {round_no}: no GO within 5 minutes")
    fresh = {
        unit_id: info
        for unit_id, info in _floor_potions(run).items()
        if unit_id not in before
    }
    if not fresh:
        raise RuntimeError(f"round {round_no}: GO heard but no new potion on the floor")
    unit_id, (kind, position) = next(iter(fresh.items()))
    return unit_id, kind, position


def _clear_pointer(
    run: DrillRun, gated: GatedInput, base: tuple[int, int], unit_id: int
) -> bool:
    """Park off the item until the pointer does NOT read the target."""
    for ndx, ndy in NEUTRAL_PARKS:
        try:
            gated.hover_screen(base[0] + ndx, base[1] + ndy)
        except InputRefused:
            continue
        run.sleep(HOVER_SETTLE_S * 2)
        if hovered_item_id(run.session) != unit_id:
            return True
    return False


def _sweep_to_transition(
    run: DrillRun,
    gated: GatedInput,
    base: tuple[int, int],
    unit_id: int,
    *,
    half: int,
    step: int,
) -> tuple[int, int] | None:
    """The first (dx, dy) at which the pointer FLIPS to the target — the
    cursor is provably on the item at that instant — or None."""
    probes = refused = 0
    for dy in range(-half, half + 1, step):
        run.check_cancel()
        for dx in range(-half, half + 1, step):
            try:
                gated.hover_screen(base[0] + dx, base[1] + dy)
            except InputRefused:
                refused += 1
                continue
            run.sleep(HOVER_SETTLE_S)
            probes += 1
            if hovered_item_id(run.session) == unit_id:
                print(
                    f"  transition at ({dx}, {dy}) after {probes} probes "
                    f"({refused} refused)",
                    flush=True,
                )
                return (dx, dy)
    print(
        f"  no transition: {probes} probes ({refused} refused) at half {half}",
        flush=True,
    )
    return None


def _round(run: DrillRun, gated: GatedInput, round_no: int) -> dict:
    unit_id, kind, position = _await_go_and_drop(run, round_no)
    base = gated.project_world(*position)
    origin = _origin(run)
    print(
        f"round {round_no}: potion kind {kind} unit {unit_id} at {position} "
        f"(player at {origin}); projection {base}",
        flush=True,
    )
    run.say(f"Saw it (kind {kind}). Sweeping — hands off.")

    if not _clear_pointer(run, gated, base, unit_id):
        return {
            "round": round_no, "kind": kind, "position": position,
            "delta": None, "note": "pointer never cleared at the parks",
            "arrived": False,
        }
    delta = _sweep_to_transition(
        run, gated, base, unit_id, half=SWEEP_HALF, step=SWEEP_STEP
    )
    if delta is None:
        delta = _sweep_to_transition(
            run, gated, base, unit_id, half=WIDE_HALF, step=WIDE_STEP
        )
    if delta is None:
        return {
            "round": round_no, "kind": kind, "position": position,
            "delta": None, "note": "no transition — never confirmed",
            "arrived": False,
        }

    # -- click AT the transition, immediately — the executor's protocol --
    belt_before = _belt_kinds(run)
    arrived = False
    where = "never left the ground"
    try:
        gated.click_screen(base[0] + delta[0], base[1] + delta[1])
        waited = time.monotonic()
        while time.monotonic() - waited < ARRIVAL_WAIT_S:
            if unit_id not in _floor_potions(run):
                arrived = True
                break
            run.sleep(0.15)
        if arrived:
            run.sleep(0.3)  # let the belt read settle
            belt_after = _belt_kinds(run)
            where = (
                f"ARRIVED; belt {belt_before} -> {belt_after}"
                if belt_after != belt_before
                else f"LEFT THE GROUND but belt unchanged {belt_before} "
                "— check the cursor/inventory"
            )
    except InputRefused as exc:
        where = f"refused: {exc}"
    print(f"  transition {delta}; verification: {where}", flush=True)
    run.say(f"Round {round_no}: {'ARRIVED' if arrived else where}.")
    return {
        "round": round_no, "kind": kind, "position": position,
        "delta": delta, "arrived": arrived, "where": where,
    }


def t60_body(run: DrillRun) -> str:
    gated = GatedInput(run.session)
    results = [_round(run, gated, n) for n in range(1, ROUNDS + 1)]

    pieces = []
    for r in results:
        pieces.append(
            f"round {r['round']} (kind {r['kind']} at {r['position']}): "
            + (
                f"transition {r['delta']}, {r.get('where', '')}"
                if r["delta"] is not None
                else r["note"]
            )
        )
    summary = "; ".join(pieces)
    ok = all(r["delta"] is not None and r["arrived"] for r in results)
    if not ok:
        run.say("TEST T60 FAILED — see the transcript. Hands back to you.", patience_s=15.0)
        raise RuntimeError(summary)
    deltas = [r["delta"] for r in results]
    spread = (
        max(d[0] for d in deltas) - min(d[0] for d in deltas),
        max(d[1] for d in deltas) - min(d[1] for d in deltas),
    )
    run.say(
        f"TEST T60 COMPLETE — deltas {deltas}, spread {spread}. "
        "Hands back to you.",
        patience_s=15.0,
    )
    return f"{summary}; deltas {deltas}, spread {spread} px"


if __name__ == "__main__":
    status = run_drill(T60, t60_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
