"""T76 — pickup calibration: does the clickable point MOVE when items crowd?

P2 of the pickup-reliability plan
(`docs/plans/2026-08-06-pickup-reliability/02-calibration-drill.md`).

**The question.** `actions.PICKUP_AIM_POINTS` is 8 FIXED screen offsets
from an item's projected ground tile. T71 run 4 lost 13 of 31 wanted
items, and the shape of the loss points at one hypothesis:

> PD2 displaces item labels vertically when items are close together —
> that is how a human picks one potion out of a pile — so the clickable
> point for a given item DEPENDS ON ITS NEIGHBOURS, and a fixed
> schedule cannot find it.

It predicts everything the run showed: failure is bimodal (1-2 clicks or
all 8, nothing between), misses cluster where items are dense (26.3 on
screen vs 15.1), the click lands on a neighbour ("clicked A, got B" in 9
of 13), and label-only classes fail hardest — T65 run 4 put **245 probes
into kind 619 with zero hits**, and 619 is `cm2`, a charm.

**Falsifiable, which is the point**: if the winning offset for an item is
the SAME alone as it is in a pile, the hypothesis is dead and the cause
is elsewhere (draw-order occlusion, stand-off geometry, item class).

## What it does

**Round 0 is READ-ONLY** and runs first: for every ground item nearby it
prints the world position, the projected screen point, and scans the
unit's own memory for anything that looks like screen geometry. If label
rectangles are readable, the fix stops being a guess schedule and
becomes a read — the highest-value five minutes in the plan.

**Then the click rounds.** For each arrangement the operator stages
(solo -> pair -> pile), the drill walks the aim schedule against one
target at a time and records, per offset, whether anything left the
ground and WHICH unit it was. The neighbour-stealing case is data, not
noise.

**This test SENDS INPUT**: paced clicks around items you drop. Misses are
move commands, so the character wanders a little; every click
re-projects, so that costs nothing.

## How it ends

On its own after the last stageable arrangement, or when you type
`done`. An arrangement that cannot be staged is SKIPPED OUT LOUD, never
silently. Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take
the mouse.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t76_pickup_calibration
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.behavior.actions import PICKUP_AIM_POINTS  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput, InputRefused  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.pickit import load_item_codes  # noqa: E402
from pd2bot.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    label_display_on,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
DONE_WORDS = frozenset({"done", "stop", "finish", "finished"})
NEAR_SUBTILES = 15
CLICK_PACE_S = 1.2
ARRIVAL_WAIT_S = 0.9
# How close two items must be to count as crowding each other. Matches
# the `neighbours` field the run log now carries, so the drill's
# arrangements and the live measurement speak the same units.
CROWD_SUBTILES = 2

# The arrangements, in order. Each is (name, how many items, what to say).
ARRANGEMENTS = (
    ("solo", 1, "ONE item on clear ground, nothing else within ~5 steps"),
    ("pair", 2, f"TWO items within {CROWD_SUBTILES} subtiles of each other"),
    ("pile", 4, f"FOUR OR MORE items packed within {CROWD_SUBTILES} subtiles"),
)


# -- pure helpers (unit-tested; no game required) --------------------------------


def classify(kind: int, codes_by_kind: dict[int, str]) -> str:
    """The item's CLASS, anchored to the game's own item code (R144).

    Never a guess from the numeric kind: kinds are renumbered between
    seasons, which is the defect that had the bot picking up a Wire
    Fleece believing it was a Kraken Shell. `config/item_codes.toml` is
    generated from the live game by T42.

    The classes are the ones the aim schedule might plausibly need to
    differ between — a potion's sprite is fat, a rune's is a sliver, and
    T65 measured a charm (`cm2`, kind 619) surviving 245 direct probes.
    """
    code = codes_by_kind.get(kind)
    if not code:
        return "unknown"
    if code.startswith(("hp", "mp")) or code.startswith("rv"):
        return "potion"
    if len(code) == 3 and code[0] == "r" and code[1:].isdigit():
        return "rune"
    if code.startswith("cm"):
        return "charm"
    if code.startswith("sk") or (len(code) == 3 and code[0] == "g"):
        return "gem"
    return "other"


def crowding(
    target: tuple[int, int], others: list[tuple[int, int]], within: int = CROWD_SUBTILES
) -> int:
    """How many other items sit within `within` subtiles of the target."""
    return sum(
        1
        for position in others
        if max(abs(position[0] - target[0]), abs(position[1] - target[1])) <= within
    )


def attribute(before: dict, after: dict, target_id: int) -> tuple[str, int | None]:
    """What one click actually achieved.

    Returns one of ("target", id) / ("neighbour", id) / ("nothing", None).
    The neighbour case is the whole reason this drill exists: a click
    that picks the wrong item looks identical to a click that worked,
    unless something checks WHICH unit left the ground.
    """
    gone = [uid for uid in before if uid not in after]
    if not gone:
        return "nothing", None
    if target_id in gone:
        return "target", target_id
    return "neighbour", gone[0]


def compare_offsets(results: list[dict]) -> list[str]:
    """The verdict lines: does the winning offset shift with crowding?

    This is the drill's actual output. A calibration that printed raw
    rounds and left the comparison to a human reading a transcript would
    be answering a different, easier question.
    """
    lines: list[str] = []
    by_class: dict[str, dict[str, list]] = {}
    for row in results:
        by_class.setdefault(row["item_class"], {}).setdefault(
            row["arrangement"], []
        ).append(row)
    for item_class, arrangements in sorted(by_class.items()):
        lines.append(f"  {item_class}:")
        winners: dict[str, set] = {}
        for name, rows in arrangements.items():
            won = {tuple(r["winning_offset"]) for r in rows if r["winning_offset"]}
            missed = sum(1 for r in rows if not r["winning_offset"])
            winners[name] = won
            lines.append(
                f"    {name:<6} winning offsets {sorted(won) or 'NONE'}"
                + (f", {missed} target(s) never came up" if missed else "")
            )
        solo, pile = winners.get("solo"), winners.get("pile")
        if solo and pile:
            if solo & pile:
                lines.append(
                    "    -> STABLE across crowding (hypothesis WEAKENED for "
                    f"{item_class}): {sorted(solo & pile)} works in both"
                )
            else:
                lines.append(
                    "    -> SHIFTED with crowding (hypothesis SUPPORTED for "
                    f"{item_class}): solo {sorted(solo)} vs pile {sorted(pile)}"
                )
        else:
            lines.append(
                "    -> inconclusive: need both a solo and a pile round "
                f"for {item_class}"
            )
    return lines


def sufficient(results: list[dict]) -> tuple[bool, str]:
    """Did this run measure enough to license a fix? (The T72 lesson.)

    A drill that passed on the easy case only would license exactly the
    wrong change — review 001's shape, and the reason T71 run 4's own
    criteria were re-checked before it launched. PASS needs the solo AND
    pile arrangements for at least two classes.
    """
    seen: dict[str, set] = {}
    for row in results:
        seen.setdefault(row["item_class"], set()).add(row["arrangement"])
    complete = [c for c, names in seen.items() if {"solo", "pile"} <= names]
    if len(complete) >= 2:
        return True, f"solo+pile measured for {len(complete)} class(es): {complete}"
    return False, (
        "INCOMPLETE — needs solo AND pile for at least two item classes; "
        f"got {({c: sorted(n) for c, n in seen.items()} or 'nothing')}"
    )


# -- live plumbing ---------------------------------------------------------------


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


def _floor(run: DrillRun) -> dict[int, tuple[int, tuple[int, int]]]:
    """Every ground item near the player: id -> (kind, position)."""
    origin = _origin(run)
    found: dict[int, tuple[int, tuple[int, int]]] = {}
    for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_ITEM):
        item = _read_ground_item(run.session, unit)
        if item is None:
            continue
        if (
            abs(item.position[0] - origin[0]) <= NEAR_SUBTILES
            and abs(item.position[1] - origin[1]) <= NEAR_SUBTILES
        ):
            found[item.unit_id] = (item.kind, item.position)
    return found


def _await_word(run: DrillRun, words, timeout_s: float = 300.0) -> str | None:
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(words):
            return "heard"
        if run.heard(DONE_WORDS):
            return "done"
        run.sleep(0.2)
    return None


def probe_label_geometry(run: DrillRun, gated: GatedInput) -> list[str]:
    """Round 0, READ-ONLY: is an item's on-screen geometry readable?

    If it is, P3 becomes "aim where the game says the label is" and this
    entire class of failure disappears. Scans each nearby item's unit
    block for an int pair plausibly close to the projected point — the
    T58/T66 hunt shape, which is how the hover pointer and the ALT flag
    were both found.

    Sends nothing. Reports candidates; proves nothing on its own.
    """
    lines = ["--- round 0: label geometry probe (read-only) ---"]
    labels = label_display_on(run.session)
    lines.append(f"  label display (ALT): {labels}")
    floor = _floor(run)
    if not floor:
        lines.append("  no ground items nearby — drop a few and re-run round 0")
        return lines
    for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_ITEM):
        item = _read_ground_item(run.session, unit)
        if item is None or item.unit_id not in floor:
            continue
        try:
            projected = gated.project_world(*item.position)
        except Exception as exc:  # noqa: BLE001 - a probe never breaks a run
            lines.append(f"  item {item.unit_id}: projection failed ({exc})")
            continue
        lines.append(
            f"  item {item.unit_id} kind {item.kind} at {item.position} "
            f"projects to {projected}"
        )
        hits = []
        for step in range(0, 0x140, 4):
            try:
                x = run.session.u32(unit + step)
                y = run.session.u32(unit + step + 4)
            except Exception:  # noqa: BLE001
                continue
            if (
                abs(x - projected[0]) <= 120
                and abs(y - projected[1]) <= 120
                and x < 4000
                and y < 4000
            ):
                hits.append((hex(step), x, y))
        lines.append(
            f"    screen-like pairs in the unit block: {hits or 'none'}"
        )
    lines.append(
        "  NOTE: candidates here are LEADS, not offsets. Anything durable "
        "needs the T58 treatment — change the state, read again, keep only "
        "what tracks."
    )
    return lines


def _click_schedule(
    run: DrillRun,
    gated: GatedInput,
    target_id: int,
    position: tuple[int, int],
) -> tuple[tuple[int, int] | None, list[dict]]:
    """Walk the aim schedule against one target. Returns (winner, trail)."""
    trail: list[dict] = []
    for dx, dy in PICKUP_AIM_POINTS:
        run.check_cancel()
        before = _floor(run)
        if target_id not in before:
            break  # already gone (a neighbour's click took it)
        try:
            base = gated.project_world(*position)
            gated.click_screen(base[0] + dx, base[1] + dy)
        except InputRefused as exc:
            trail.append({"offset": [dx, dy], "result": f"refused: {exc}"})
            continue
        waited = time.monotonic()
        outcome, who = "nothing", None
        while time.monotonic() - waited < ARRIVAL_WAIT_S:
            outcome, who = attribute(before, _floor(run), target_id)
            if outcome != "nothing":
                break
            run.sleep(0.1)
        trail.append({"offset": [dx, dy], "result": outcome, "unit": who})
        print(f"    ({dx:>3}, {dy:>3}): {outcome}"
              + (f" -> unit {who}" if who is not None else ""), flush=True)
        if outcome == "target":
            return (dx, dy), trail
        run.sleep(max(0.0, CLICK_PACE_S - ARRIVAL_WAIT_S))
    return None, trail


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T76",
        title="pickup calibration — does the clickable point move in a pile?",
        kind="hybrid",
        sends_input=True,
        instructions=(
            "THREE ARRANGEMENTS, staged by you, in a SAFE spot (town is",
            "fine). For each one I will say what to drop; drop it, then",
            "type GO and hands off.",
            "  1. solo — ONE item on clear ground",
            "  2. pair — TWO items within 2 subtiles of each other",
            "  3. pile — FOUR OR MORE items packed together",
            "Vary the CLASS between rounds if you can (potions, then a",
            "rune or a gem or a charm) — the class question is half of",
            "what this measures.",
            "I click a schedule of offsets around each item and record",
            "which one works and WHAT came up. Type 'done' any time to",
            "finish early. ENDS ON ITS OWN. Abort: 'abort', drill-cancel,",
            "ESC, or take the mouse.",
        ),
    )

    def body(run: DrillRun) -> str:
        gated = GatedInput(run.session)
        codes_by_kind = {
            kind: code
            for code, kinds in load_item_codes(REPO / "config" / "item_codes.toml").items()
            for kind in kinds
        }

        for line in probe_label_geometry(run, gated):
            print(line, flush=True)

        results: list[dict] = []
        skipped: list[str] = []
        for name, wanted, description in ARRANGEMENTS:
            before = set(_floor(run))
            run.say(f"ARRANGEMENT '{name}': drop {description}, then type GO.")
            if _await_word(run, GO_WORDS) != "heard":
                skipped.append(f"{name} (no GO — stopped early or timed out)")
                break
            fresh = {
                uid: info for uid, info in _floor(run).items() if uid not in before
            }
            if len(fresh) < wanted:
                # Said out loud, never silently: a skipped arrangement
                # changes what the run is allowed to conclude.
                message = f"{name} (needed {wanted} items, saw {len(fresh)})"
                skipped.append(message)
                run.say(f"SKIPPING {message}")
                continue

            positions = [pos for _, pos in fresh.values()]
            print(f"\n--- arrangement '{name}': {len(fresh)} item(s) ---", flush=True)
            for target_id, (kind, position) in list(fresh.items()):
                if target_id not in _floor(run):
                    continue
                others = [p for p in positions if p != position]
                item_class = classify(kind, codes_by_kind)
                print(
                    f"  target {target_id} kind {kind} ({item_class}) at "
                    f"{position}, crowded by {crowding(position, others)}",
                    flush=True,
                )
                winner, trail = _click_schedule(run, gated, target_id, position)
                results.append({
                    "arrangement": name,
                    "unit_id": target_id,
                    "kind": kind,
                    "item_class": item_class,
                    "position": list(position),
                    "crowding": crowding(position, others),
                    "winning_offset": list(winner) if winner else None,
                    "clicks": len(trail),
                    "trail": trail,
                })

        print("\n=== WHAT THE OFFSETS DID ===", flush=True)
        for line in compare_offsets(results):
            print(line, flush=True)

        stolen = [
            (r["unit_id"], t)
            for r in results
            for t in r["trail"]
            if t.get("result") == "neighbour"
        ]
        print(
            f"\nclicked-the-neighbour events: {len(stolen)}"
            + (f" -> {stolen}" if stolen else ""),
            flush=True,
        )

        ok, verdict = sufficient(results)
        summary = (
            f"{len(results)} target(s) across "
            f"{len({r['arrangement'] for r in results})} arrangement(s); "
            f"{len(stolen)} neighbour-steal(s); {verdict}"
        )
        if skipped:
            summary += f"; SKIPPED: {'; '.join(skipped)}"
        if not ok:
            raise RuntimeError(summary)
        return summary

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
