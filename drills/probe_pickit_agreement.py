"""Where do the pickup rule and the cleanse rule DISAGREE? (stage B run 4)

Read-only. Sends nothing, not even chat.

The user spectated run 4 and reported the bot clicking items up off the
ground and then cleansing them straight back out of the inventory. That
loop should be impossible by construction:

    pickup  asks the pickit in STRICT mode      ("should I take this?")
    cleanse asks the pickit in PERMISSIVE mode  ("might I have wanted it?")

and permissive is deliberately broader than strict, so anything strict
wants, permissive keeps. An item that is picked up AND dropped means the
two evaluations are seeing different DATA for the same item — not
different rules.

The prime suspect is sockets, which is also the user's third observation
(a 3-socket armour picked up that they say should not have been). Sockets
are read from the item's stat list, and the ground unit and the carried
unit are different units: if one read succeeds and the other does not, the
socket-conditioned rules answer differently on each side and the item
oscillates.

So this prints, for every carried item and every nearby ground item:

    kind, quality, sockets, STRICT decision, PERMISSIVE decision, cleanse

and flags every disagreement. A row where strict says keep and the cleanse
says drop IS the loop, named.

It also resolves the socket rules' item names to ids, because the other
explanation for an unwanted pickup is a rule matching a kind nobody meant.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.pickit import (  # noqa: E402
    cleanse_keep,
    load_item_table,
    load_pickit,
)

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    session = GameSession()
    table = load_item_table(REPO / "config" / "item_ids.toml")
    pickit = load_pickit(REPO / "config" / "pickit.toml", item_table=table)
    keep = cleanse_keep(pickit)

    print("socket-rule vocabulary (an unwanted pickup may just be a bad id):")
    for name in ("necro_heads", "archon_plate"):
        members = table.groups.get(name, (name,))
        for member in members:
            print(f"  {name}/{member} -> {sorted(table.ids.get(member, ()))}")
    print(f"\ncleanse enabled: {keep is not None}")

    carried = read_carried_items(session)  # with_sockets=True by default
    snap = Perception(session).snapshot()

    print(f"\n--- carried, main inventory ({len(carried.main_inventory)}) ---")
    print("  kind  qual sock  strict      permissive  cleanse")
    for item in carried.main_inventory:
        strict = pickit.decide(item, carried)
        loose = pickit.decide(item, carried, mode="permissive")
        kept = keep(item) if keep else None
        flag = ""
        if strict[0] != "skip" and kept is False:
            flag = "  <== PICKED UP BUT CLEANSED: the loop"
        print(
            f"  {item.kind:5} {item.quality:4} {str(item.sockets):5} "
            f"{strict[0]:11} {loose[0]:11} {kept}{flag}"
        )

    ground = [
        i for i in snap.ground_items
        if snap.player is None
        or max(abs(i.position[0] - snap.player.position[0]),
               abs(i.position[1] - snap.player.position[1])) <= 40
    ]
    print(f"\n--- on the ground within 40 ({len(ground)}) ---")
    print("  kind  qual sock  strict      rule")
    for item in ground:
        action, rule = pickit.decide(item, carried)
        potion = item.kind in offsets.POTION_KINDS
        note = "  <== POTION" if potion else ""
        print(
            f"  {item.kind:5} {item.quality:4} {str(item.sockets):5} "
            f"{action:11} {rule}{note}"
        )

    # The rejuv question: the reserve rule should keep wanting them while
    # the inventory holds fewer than the reserve.
    rejuv_belt = sum(1 for i in carried.belt if i.is_rejuv_potion)
    rejuv_inv = sum(1 for i in carried.main_inventory if i.is_rejuv_potion)
    print(
        f"\nrejuvs: belt {rejuv_belt}, inventory {rejuv_inv} "
        f"(the reserve rule wants more while inventory < 2)"
    )
    tomes = [i for i in carried.main_inventory if i.kind in (533, 534)]
    print(f"tomes carried (533 TP / 534 ID): {[i.kind for i in tomes]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
