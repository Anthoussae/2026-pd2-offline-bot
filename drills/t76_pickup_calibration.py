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
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    label_display_on,
    player_unit,
    unit_position,
)
from pd2bot.pickit import load_item_codes  # noqa: E402

GO_WORDS = frozenset({"go", "go!"})
DONE_WORDS = frozenset({"done", "stop", "finish", "finished"})
# Run 1 (2026-08-06) staged items the census could not see and reported
# "saw 1" with no way to tell whether that meant "not dropped" or "out of
# range". 15 was borrowed from T63, where the operator dropped at their
# feet; here they walk between rounds. Widened, and everything just
# outside is now REPORTED rather than silently excluded.
NEAR_SUBTILES = 40
CLICK_PACE_S = 1.2
ARRIVAL_WAIT_S = 0.9
# How close two items must be to count as crowding each other. Matches
# the `neighbours` field the run log now carries, so the drill's
# arrangements and the live measurement speak the same units.
CROWD_SUBTILES = 2

# Two staging rounds, not three arrangements with exact counts.
#
# Run 1 demanded "drop exactly 2" / "drop exactly 4" and skipped both
# rounds when the census disagreed with the operator. The arrangement is
# not something the operator should have to hit precisely — it is a
# property of the floor, which the drill can MEASURE. So: two loose
# rounds, and every target is labelled by its own live crowding.
STAGING = (
    ("spread", "several items SPREAD OUT — a step or two between each"),
    ("packed", "several items PACKED TOGETHER — dropped on the same spot"),
)


def arrangement_of(crowd: int) -> str:
    """Label a target by what the floor actually looks like around it."""
    if crowd == 0:
        return "solo"
    if crowd == 1:
        return "pair"
    return "pile"


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
    # PD2 carries PARALLEL records for runes and gems: `r05` and `r05s`,
    # `gzv` and `gzvs` — and R126 measured which one matters: "it is the
    # `s` family that actually drops". Run 2 filed an Eth rune (r05s), an
    # Eld rune (r02s) and a flawless amethyst (gzvs) as "other" for want
    # of these four characters, which buried the two most interesting
    # results in the run under a generic label.
    stem = code[:-1] if len(code) == 4 and code.endswith("s") else code
    if stem.startswith(("hp", "mp", "rv")):
        return "potion"
    if len(stem) == 3 and stem[0] == "r" and stem[1:].isdigit():
        return "rune"
    if stem.startswith("cm"):
        return "charm"
    if stem.startswith("sk") or (len(stem) == 3 and stem[0] == "g"):
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
            # Run 1's silent exit. If the target vanished before we aimed
            # at it, SAY so — it is either a neighbour's click having
            # taken it (data) or the census losing sight of it (a defect),
            # and those must never look alike again.
            print(f"    ({dx:>3}, {dy:>3}): target {target_id} no longer on "
                  "the floor — stopping this target", flush=True)
            trail.append({"offset": [dx, dy], "result": "target vanished"})
            break
        try:
            base = gated.project_world(*position)
            gated.click_screen(base[0] + dx, base[1] + dy)
        except InputRefused as exc:
            # THE silent branch of run 1: eight refusals in a row produced
            # a target that "never came up" and not one line saying why.
            print(f"    ({dx:>3}, {dy:>3}): REFUSED — {exc}", flush=True)
            trail.append({"offset": [dx, dy], "result": f"refused: {exc}"})
            run.sleep(CLICK_PACE_S)
            continue
        except Exception as exc:  # noqa: BLE001 - a probe explains itself
            print(f"    ({dx:>3}, {dy:>3}): ERROR — "
                  f"{type(exc).__name__}: {exc}", flush=True)
            trail.append({"offset": [dx, dy], "result": f"error: {exc}"})
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
            "TWO ROUNDS, staged by you, standing STILL in a safe spot",
            "(town is fine — stay put so the item census can see them).",
            "  ROUND 1 'spread': drop several items a step or two apart.",
            "  ROUND 2 'packed': drop several ON THE SAME SPOT.",
            "Exact counts do not matter — I measure how crowded each item",
            "actually is. What DOES matter is variety: include potions",
            "AND at least one small item (rune, gem or charm) in each",
            "round, because the item-class question is half of this.",
            "After each drop, type GO and hands off. I click a schedule",
            "of offsets around each item and record which one works and",
            "WHICH item came up. Type 'done' to finish early.",
            "ENDS ON ITS OWN. Abort: 'abort', drill-cancel, ESC, mouse.",
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
        for name, description in STAGING:
            before = set(_floor(run))
            run.say(f"ROUND '{name}': drop {description}, then type GO.")
            if _await_word(run, GO_WORDS) != "heard":
                skipped.append(f"{name} (no GO — stopped early or timed out)")
                break
            floor = _floor(run)
            fresh = {uid: info for uid, info in floor.items() if uid not in before}
            # The census, printed. Run 1 said "saw 1" and left no way to
            # tell "not dropped" from "out of the census radius".
            print(f"\n--- round '{name}' ---", flush=True)
            print(f"  player at {_origin(run)}; census radius {NEAR_SUBTILES}",
                  flush=True)
            print(f"  floor: {len(floor)} item(s), {len(fresh)} new this round",
                  flush=True)
            for uid, (kind, position) in floor.items():
                mark = "NEW" if uid in fresh else "   "
                print(f"    {mark} {uid} kind {kind} "
                      f"({classify(kind, codes_by_kind)}) at {position}",
                      flush=True)
            if not fresh:
                message = f"{name} (GO heard but no new items in the census)"
                skipped.append(message)
                run.say(f"SKIPPING {message}")
                continue

            # Every item on the floor crowds every other, not just the
            # ones dropped this round — crowding is a property of the
            # floor, and the leftovers from an earlier round are part of
            # it. This is also what makes exact counts unnecessary.
            everything = [pos for _, pos in floor.values()]
            for target_id, (kind, position) in list(fresh.items()):
                if target_id not in _floor(run):
                    print(f"  target {target_id} left the floor before we "
                          "aimed at it — skipping", flush=True)
                    continue
                others = [p for p in everything if p != position]
                crowd = crowding(position, others)
                item_class = classify(kind, codes_by_kind)
                print(
                    f"  target {target_id} kind {kind} ({item_class}) at "
                    f"{position}, crowded by {crowd} "
                    f"-> arrangement '{arrangement_of(crowd)}'",
                    flush=True,
                )
                winner, trail = _click_schedule(run, gated, target_id, position)
                print(f"    => winner {winner}, {len(trail)} attempt(s)",
                      flush=True)
                results.append({
                    "arrangement": arrangement_of(crowd),
                    "staging": name,
                    "unit_id": target_id,
                    "kind": kind,
                    "item_class": item_class,
                    "position": list(position),
                    "crowding": crowd,
                    "winning_offset": list(winner) if winner else None,
                    "clicks": len(trail),
                    "trail": trail,
                })

        # Round 0 was designed to run first and found an empty floor
        # (run 1). It needs items to look at, so it runs HERE too, on
        # whatever is still lying around.
        print("\n--- label geometry probe, re-run with items present ---",
              flush=True)
        for line in probe_label_geometry(run, gated):
            print(line, flush=True)

        print("\n=== EVERY ATTEMPT ===", flush=True)
        for row in results:
            print(
                f"  {row['unit_id']} {row['item_class']} "
                f"({row['arrangement']}, crowd {row['crowding']}): "
                f"{[(t['offset'], t['result']) for t in row['trail']]}",
                flush=True,
            )

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
