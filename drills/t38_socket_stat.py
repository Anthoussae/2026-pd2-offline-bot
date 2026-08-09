"""T38 — verify the socket-count stat, carried and on the ground.

The R117 pickit needs "3-socket archon plate", which means reading socket
counts off ground items. kolbot says stat index 194 (NumSockets), and a
read-only probe (bridge 061) found 194 present on exactly the items you
would expect it on, holding small integers. That is *plausible*, which is
the dangerous state: T18 produced a confident, precise, wrong calibration
and nothing downstream could tell (R86). So this drill makes the user the
oracle and an ACTION the answer.

The protocol, in two halves:

1. **Identification.** The drill reads every carried item, states its
   socket predictions in chat, and asks the user to DROP the one
   inventory item it believes is socketed. Dropping is the confirmation
   signal; cancelling is the denial. The drill cannot receive a typed
   reply, so one bit of ground truth arrives as a game-state change —
   the same shape as T17's proximity drill.
2. **The ground read.** The pickit reads sockets off GROUND items, a
   different code path from carried ones, so the dropped item is read
   again where it lies and the two values must agree.

A mismatch at either half leaves `STAT_NUM_SOCKETS` unverified and the
socket-conditioned pickit rules disarmed — which is the fail-safe
direction (items not picked, never mis-picked).

Read-only: the drill sends no input beyond its own chat messages.

Run from the repo root (bridge, elevated):
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t38_socket_stat
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.items import _iter_carried_units, read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import read_stats, scan_units  # noqa: E402

DROP_TIMEOUT_S = 300.0


T38 = Drill(
    test_id="T38",
    title="Socket-count stat, carried and on the ground",
    kind="perception",
    instructions=(
        "READ-ONLY - the bot sends nothing but these chat messages.",
        "1) I will read your gear and tell you how many sockets I think "
        "each socketed item has.",
        "2) If EVERY number I state is right: drop the socketed INVENTORY "
        "item on the ground. That drop is your 'yes'.",
        "3) If ANY number is wrong: leave everything alone and run "
        "tools\\drill-cancel.ps1. That is your 'no'.",
        "4) After I read it off the ground you can pick it back up.",
    ),
)


def socketed_items(session):
    """(item, sockets, container) for everything carrying stat 194."""
    carried = read_carried_items(session)
    by_id = {i.unit_id: i for i in carried.items}
    rows = []
    for unit in _iter_carried_units(session):
        try:
            unit_id = session.u32(unit + offsets.UNIT_ID)
        except Exception:
            continue
        item = by_id.get(unit_id)
        if item is None:
            continue
        try:
            stats = read_stats(session, unit)
        except Exception:
            continue
        sockets = stats.get(offsets.STAT_NUM_SOCKETS)
        if sockets:
            rows.append((item, sockets, item.container))
    return rows


def t38_body(run: DrillRun) -> str:
    session = run.session

    rows = socketed_items(session)
    if not rows:
        raise DrillAborted(
            "no carried item reads stat 194 at all — nothing to verify; "
            "put a socketed item in the inventory and re-run"
        )

    in_inventory = [
        (item, sockets) for item, sockets, container in rows
        if item.in_main_inventory
    ]
    equipped = [
        (item, sockets) for item, sockets, container in rows
        if container == "equipped"
    ]

    print("== what stat 194 says ==", flush=True)
    for item, sockets, container in rows:
        print(
            f"  {container:10} kind {item.kind:4} quality {item.quality} "
            f"cell {item.position} -> {sockets} socket(s)",
            flush=True,
        )

    if len(in_inventory) != 1:
        raise DrillAborted(
            f"expected exactly ONE socketed item in the main inventory grid, "
            f"found {len(in_inventory)} — the drop signal needs to be "
            "unambiguous; adjust the inventory and re-run"
        )
    target, target_sockets = in_inventory[0]

    # State every prediction, so the user's "yes" covers all of them.
    run.say(
        f"I read {len(rows)} socketed item(s). Equipped: "
        + ", ".join(f"{s} sockets" for _, s in equipped)
        + "."
    )
    column, row_index = target.position
    run.say(
        f"In your inventory, column {column + 1} row {row_index + 1} "
        f"(kind {target.kind}): I read {target_sockets} SOCKETS."
    )
    run.say(
        "If all of that is correct, DROP that inventory item on the ground "
        "now. If anything is wrong, cancel instead."
    )

    def dropped():
        try:
            found = scan_units(session).ground_items
        except Exception:
            return []
        return [g for g in found if g.kind == target.kind]

    if not run.wait_until(lambda: bool(dropped()), timeout_s=DROP_TIMEOUT_S):
        raise DrillAborted(
            "the item was never dropped — treating that as 'not confirmed'; "
            "stat 194 stays unverified and socket rules stay disarmed"
        )

    ground = dropped()[0]
    print(
        f"\nground read: unit {ground.unit_id} kind {ground.kind} "
        f"sockets={ground.sockets}",
        flush=True,
    )
    run.say(f"Ground read: {ground.sockets} sockets. You can pick it up.")

    if ground.sockets != target_sockets:
        raise DrillAborted(
            f"the SAME item read {target_sockets} sockets carried but "
            f"{ground.sockets} on the ground — the ground path is the one "
            "the pickit uses, so socket rules stay disarmed"
        )

    equipped_note = (
        ", equipped: " + "/".join(str(s) for _, s in equipped)
        if equipped else ""
    )
    return (
        f"stat 194 CONFIRMED by the user: inventory kind {target.kind} = "
        f"{target_sockets} sockets, same value read off the ground"
        f"{equipped_note}"
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T38, t38_body, session=GameSession()) == "PASS" else 1)
