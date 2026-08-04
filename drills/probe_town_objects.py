"""Why did `_approach_object` not find the Act 1 waypoint? (stage B, run 2)

Read-only. Sends nothing, not even chat.

Stage B's second attempt completed the preamble and then died with

    waypoint still not visible after walking to (5884, 5709)

which is `TownLayer._approach_object` walking to its configured position
and finding no object of kind 119 in the snapshot. That should be
impossible at a 10-subtile standoff against an 80-subtile perception
radius, and the position itself is not in doubt — a live dump earlier in
the same session reported `waypoint at (5884, 5709)`.

So the interesting question is WHICH of two very different things happened,
and one read separates them:

  * the waypoint is in the client's unit table but the snapshot dropped it
    -> a perception/locality problem, and `raw` below will show it
  * the waypoint is not in the unit table at all
    -> the object was never loaded, and the walk is the suspect

The locality filter is the whole difference: `scan_units` enforces it
because the hash table lists units from other levels and expired summons
(R23). This prints both sides of that filter, so the answer is not a
matter of opinion.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig  # noqa: E402
from pd2bot.units import (  # noqa: E402
    PERCEPTION_RADIUS,
    iter_units_of_type,
    player_unit,
    unit_position,
)


def main() -> int:
    session = GameSession()
    player = player_unit(session)
    if player is None:
        print("not in a game — enter one first")
        return 1
    origin = unit_position(session, player, offsets.UNIT_TYPE_PLAYER)
    config = TownConfig()
    wanted = config.object_positions[offsets.OBJ_WAYPOINT_A1]
    print(f"player at {origin}; perception radius {PERCEPTION_RADIUS}")
    print(f"configured waypoint position: {wanted}")
    print(f"distance player -> configured: "
          f"{max(abs(origin[0] - wanted[0]), abs(origin[1] - wanted[1]))}")

    snap = Perception(session).snapshot()
    print(f"\nsnapshot objects ({len(snap.objects)}):")
    for obj in sorted(
        snap.objects,
        key=lambda o: max(abs(o.position[0] - origin[0]),
                          abs(o.position[1] - origin[1])),
    ):
        distance = max(abs(obj.position[0] - origin[0]),
                       abs(obj.position[1] - origin[1]))
        mark = "  <== WAYPOINT" if obj.kind == offsets.OBJ_WAYPOINT_A1 else ""
        print(f"  kind {obj.kind:5} {str(obj.name or ''):10} at {obj.position} "
              f"d={distance}{mark}")

    # The unfiltered side: every type-2 unit the client knows about, with no
    # locality applied. A waypoint that appears HERE but not above is a
    # filtering story; one that appears in neither was never loaded.
    print("\nraw type-2 units with kind 119 (no locality filter):")
    found = 0
    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_OBJECT):
        try:
            if session.u32(unit + offsets.UNIT_TXT_FILE_NO) != offsets.OBJ_WAYPOINT_A1:
                continue
            position = unit_position(session, unit, offsets.UNIT_TYPE_OBJECT)
            distance = (
                "unknown" if position is None
                else max(abs(position[0] - origin[0]), abs(position[1] - origin[1]))
            )
            print(f"  unit {unit:#x} at {position} d={distance}")
            found += 1
        except Exception as exc:
            print(f"  unit {unit:#x}: unreadable ({exc})")
    if not found:
        print("  none — the waypoint is not in the unit table at all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
