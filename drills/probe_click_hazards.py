"""What is the navigator refusing to click near, and is any of it real?

Read-only. Sends nothing, not even chat.

Stage B's third attempt reached Cold Plains — preamble and waypoint both
worked — and then could not walk 12 subtiles:

    click nudged off interactive unit at (5219, 5661)
    click nudged off interactive unit at (5214, 5664)
    click nudged off interactive unit at (5222, 5668)
    stuck at (5216, 5676) toward (5218, 5664)

`clickable_hazards` avoids EVERY object and EVERY living ally, and the
nudges apply one after another without re-checking, so each push lands the
click near the next hazard and the last nudge wins. With enough hazards in
a small area the click ends up back where the character stands.

Two candidate causes, and they want different fixes, so this classifies
every hazard instead of assuming:

  * ALLIES — a poison necro is permanently surrounded by 7 summons and a
    merc. None of them opens anything on click; only town NPCs do. If the
    hazards are mostly allies, the rule "avoid allies" is simply wrong
    outside town.
  * OBJECTS — most are decorative scenery (kind 37 was 15 of the 22 objects
    in town) which cannot be clicked at all. The waypoint and stash can.
    If scenery dominates, avoiding every object is the wrong rule.

Run it standing where the Cold Plains waypoint drops you.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.navigate import AVOID_RADIUS  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402


def main() -> int:
    session = GameSession()
    snap = Perception(session).snapshot()
    if snap.player is None:
        print("not in a game — enter one first")
        return 1
    origin = snap.player.position
    area = snap.area.level_no if snap.area else "?"
    print(f"player at {origin}, area {area}, in_town={snap.in_town}")
    print(f"AVOID_RADIUS={AVOID_RADIUS} (a click within this is pushed away)\n")

    def near(position):
        return max(abs(position[0] - origin[0]), abs(position[1] - origin[1]))

    rows = []
    for obj in snap.objects:
        rows.append(("object", obj.kind, obj.name or "", obj.position, near(obj.position)))
    for ally in snap.allies:
        if ally.is_alive:
            label = ally.merc_kind or "summon"
            rows.append(("ally", ally.kind, label, ally.position, near(ally.position)))

    rows.sort(key=lambda r: r[4])
    print(f"clickable_hazards would return {len(rows)} points:")
    for kind_of, kind, name, position, distance in rows:
        flag = "  <== within avoid radius" if distance <= AVOID_RADIUS else ""
        print(f"  {kind_of:7} kind {kind:5} {name:10} at {position} d={distance}{flag}")

    close = [r for r in rows if r[4] <= 12]
    print(f"\nwithin 12 subtiles (the failed walk's whole distance): {len(close)}")
    print("  by category:", Counter(r[0] for r in close))
    print("  object kinds:", Counter(r[1] for r in close if r[0] == "object"))
    named = [r for r in close if r[0] == "object" and r[2]]
    print(f"  NAMED (genuinely interactive) objects close by: {len(named)}")
    for row in named:
        print(f"    kind {row[1]} {row[2]} at {row[3]} d={row[4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
