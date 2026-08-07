"""T77 — what IS a PD2 map, to the bot? A read-only identity probe.

The operator drops maps; this reads them off the floor and says what
memory calls them. **Sends no input.** The character does not move.

## Why

PD2 maps have a right-click effect (they open a portal / consume), which
puts them in the same family as the Tome of Town Portal — items whose
plain right-click does something that outlives the click. The inventory
cleanse aims a ctrl+right-click at junk, and a dropped modifier on one of
those is how R112/R113 armed an identify cursor that ate every retry.

We cannot protect what we cannot name, and **a numeric guess is not
allowed here** (R144): reviewing kind ids by eye once approved six wrong
elite armours and the bot picked up a Wire Fleece believing it was a
Kraken Shell. Maps appear under no code this repo knows —
`config/item_codes.toml` (generated live by T42) has no `map`-like entry
— so the id has to be *read*, which is what this does.

## The question it must actually answer

Not just "what kind is a map", but **are all maps ONE kind or many?**
That decides the shape of the fix: one entry in an exception registry,
or a whole id range. Drop several DIFFERENT maps and this reports the
distinct kinds among them.

## How it ends

On its own, seconds after you type GO. Abort: 'abort' in chat,
tools\\drill-cancel.ps1, ESC, or take the mouse.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t77_map_identity
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.pickit import load_item_codes  # noqa: E402
from pd2bot.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
# Generous on purpose: the operator drops ten things and will shuffle
# about doing it. T76 run 1 lost items to a 15-subtile census.
NEAR_SUBTILES = 60


def _await_go(run: DrillRun, timeout_s: float = 600.0) -> bool:
    """Wait for GO, honouring every abort path via `check_cancel`."""
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            return True
        run.sleep(0.2)
    return False


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


def _floor(run: DrillRun) -> dict[int, object]:
    """Every readable ground item near the player, by unit id."""
    origin = _origin(run)
    found: dict[int, object] = {}
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


def describe(items: list, codes_by_kind: dict[int, str]) -> list[str]:
    """One line per item, plus the verdict on how many kinds there are.

    Pure: takes the items and the code table, returns the report. The
    distinct-kind count is the point — see the module docstring.
    """
    lines: list[str] = []
    for item in sorted(items, key=lambda i: (i.kind, i.unit_id)):
        code = codes_by_kind.get(item.kind)
        lines.append(
            f"  unit {item.unit_id:>7}  kind {item.kind:>4}  "
            f"code {code or 'NOT IN THE CODE TABLE':<22} "
            f"quality {item.quality} ({item.quality_name})  "
            f"sockets {item.sockets}  at {item.position}"
        )
    kinds = sorted({i.kind for i in items})
    unknown = sorted({i.kind for i in items if i.kind not in codes_by_kind})
    lines.append("")
    lines.append(f"  DISTINCT KINDS: {len(kinds)} -> {kinds}")
    if len(kinds) == 1:
        lines.append(
            "  -> every map read as ONE kind: a single registry entry "
            "protects them all."
        )
    elif kinds:
        lines.append(
            "  -> maps span SEVERAL kinds: the exception registry needs "
            "the whole set (or a range), not one entry."
        )
    lines.append(
        f"  kinds absent from config/item_codes.toml: {unknown or 'none'}"
    )
    if unknown:
        lines.append(
            "  -> the T42 code table predates these; re-run T42 to bind "
            "them to the game's own codes rather than to bare numbers."
        )
    qualities = sorted({i.quality for i in items})
    lines.append(f"  qualities seen: {qualities}")
    return lines


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T77",
        title="PD2 map identity — what does memory call a map?",
        kind="perception",
        sends_input=False,
        instructions=(
            "READ-ONLY: I send nothing, your character does not move.",
            "Stand somewhere safe (town is fine) and drop the maps on the",
            "ground near you — ideally TEN DIFFERENT ones, since the",
            "question is whether they share one item kind or span many.",
            "Anything else already lying there is fine; I diff against a",
            "census taken before you start.",
            "Then type GO. It answers in a few seconds.",
            "Abort: 'abort' in chat, drill-cancel, ESC, or take the mouse.",
        ),
    )

    def body(run: DrillRun) -> str:
        codes_by_kind = {
            kind: code
            for code, kinds in load_item_codes(
                REPO / "config" / "item_codes.toml"
            ).items()
            for kind in kinds
        }
        before = _floor(run)
        print(f"floor before: {len(before)} item(s)", flush=True)
        run.say("Drop the maps now, then type GO.")
        if not _await_go(run):
            raise RuntimeError("no GO — nothing was measured")

        after = _floor(run)
        fresh = [item for uid, item in after.items() if uid not in before]
        print(f"\n--- {len(fresh)} NEW item(s) on the floor ---", flush=True)
        report = describe(fresh, codes_by_kind)
        for line in report:
            print(line, flush=True)

        # Everything present, for context — a map that was already lying
        # there would otherwise read as "nothing new" and look like a
        # failure of the drop rather than of the diff.
        if not fresh:
            print("\n--- everything the census CAN see ---", flush=True)
            for line in describe(list(after.values()), codes_by_kind):
                print(line, flush=True)
            raise RuntimeError(
                f"GO heard but no new items in the census (player at "
                f"{_origin(run)}, radius {NEAR_SUBTILES}); "
                f"{len(after)} item(s) visible in total"
            )

        kinds = sorted({i.kind for i in fresh})
        unknown = sorted({i.kind for i in fresh if i.kind not in codes_by_kind})
        return (
            f"{len(fresh)} new item(s); DISTINCT KINDS {len(kinds)} -> {kinds}; "
            f"codes: "
            + ", ".join(
                f"{k}={codes_by_kind.get(k) or 'UNKNOWN'}" for k in kinds
            )
            + f"; not in the code table: {unknown or 'none'}"
        )

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
