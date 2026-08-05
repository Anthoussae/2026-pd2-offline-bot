"""Print what the bot currently perceives.

    python -m pd2bot.dump            one snapshot
    python -m pd2bot.dump --watch    keep printing at ~5 Hz

This is the tool for checking perception against the game with your own eyes:
run it, look at the screen, and confirm the numbers match. Every later milestone
leans on it, so its output is meant to be read by a human, not parsed.

Requires Administrator (the PD2 client runs elevated).
"""

from __future__ import annotations

import argparse
import sys
import time

from pd2bot.memory import GameNotRunning, GameSession, NeedsAdministrator
from pd2bot.snapshot import GameSnapshot, Perception
from pd2bot.uistate import UIArrayNotFound


def format_snapshot(snap: GameSnapshot, verbose: bool = False) -> str:
    if not snap.in_game:
        return "not in a game (client is in the menus)"

    lines = []
    player = snap.player
    if player is None:
        lines.append("in a game, but the player is not readable yet (loading?)")
    else:
        lines.append(
            f"{player.name}  level {player.level}  act {player.act}  at {player.position}"
        )
        lines.append(
            f"  hp {player.hp}/{player.max_hp}"
            f"   mana {player.mana}/{player.max_mana}"
            f"   stamina {player.stamina}/{player.max_stamina}"
        )
        if verbose:
            lines.append(
                f"  str {player.strength}  dex {player.dexterity}"
                f"  vit {player.vitality}  eng {player.energy}"
            )
            lines.append(
                f"  gold {player.gold} carried, {player.gold_stash} stashed"
                f"   exp {player.experience}"
            )

    if snap.area is not None:
        lines.append(
            f"  area {snap.area.level_no} at {snap.area.position} size {snap.area.size}"
            f"   map seed 0x{snap.map_seed:08X}"
        )

    panels = snap.ui.names if snap.ui else []
    lines.append(f"  ui: {', '.join(panels) if panels else 'nothing open'}"
                 f"   can act: {'yes' if snap.can_act else 'NO'}")

    if snap.skills is not None:
        lines.append(
            f"  skills: left {snap.skills.left_id}  right {snap.skills.right_id}"
        )

    live = snap.live_monsters
    lines.append(f"  monsters: {len(live)} alive of {len(snap.monsters)} nearby")
    for monster in sorted(live, key=lambda m: m.position)[: 40 if verbose else 8]:
        tags = "".join(
            tag
            for tag, on in (
                (" boss", monster.is_boss),
                (" champion", monster.is_champion),
                (" minion", monster.is_minion),
            )
            if on
        )
        fraction = monster.hp_fraction
        health = f"{fraction:.0%}" if fraction is not None else "?"
        lines.append(f"    type {monster.kind:<5} at {monster.position}  hp {health}{tags}")

    if snap.allies:
        alive = [a for a in snap.allies if a.is_alive]
        names = []
        for ally in alive:
            # life_pct, not hp/max_hp: an ally's current hp is on the
            # 0-128 client scale (the full merc used to print "8%" here).
            names.append(
                f"{ally.merc_kind or f'summon {ally.kind}'} {ally.life_pct:.0f}%"
            )
        lines.append(f"  yours: {len(alive)} — {', '.join(names) or 'none alive'}")
        if not snap.in_town:
            lines.append(
                f"    merc: {'alive' if snap.merc else 'ABSENT'}"
                f"   revives: {len(snap.revives)}"
            )

    if snap.corpses:
        lines.append(f"  corpses: {len(snap.corpses)}")
        if verbose:
            for corpse in snap.corpses[:12]:
                lines.append(
                    f"    type {corpse.kind:<5} at {corpse.position}  mode {corpse.mode}"
                )

    interesting = [o for o in snap.objects if o.name is not None]
    if interesting or verbose:
        lines.append(
            f"  objects: {len(snap.objects)} nearby"
            + (f" — {', '.join(f'{o.name} at {o.position}' for o in interesting)}"
               if interesting else "")
        )
        if verbose:
            for obj in snap.objects[:20]:
                lines.append(
                    f"    kind {obj.kind:<5} at {obj.position}  mode {obj.mode}"
                    f"{f'  ({obj.name})' if obj.name else ''}"
                )

    lines.append(f"  items on the ground: {len(snap.ground_items)}")
    for item in snap.ground_items[: 40 if verbose else 8]:
        lines.append(f"    type {item.kind:<5} at {item.position}  {item.quality_name}")

    if snap.skipped_units:
        lines.append(f"  ({snap.skipped_units} units skipped as unreadable)")
    return "\n".join(lines)


def dump_item_units(session) -> str:
    """Every item unit the client knows about, with the fields that might
    distinguish 'on the floor' from 'carried'.

    Written because two guesses at that distinction failed live
    (instruction log R17, R19) — and the diagnostic then revealed the real
    problem (R20): items were not in the room unit lists at all. Now it
    enumerates via the unit hash table and shows both enumerations, so the
    raw fields decide rather than another assumption.
    """
    from pd2bot import offsets
    from pd2bot.units import iter_units, iter_units_of_type, nearby_rooms

    lines = []

    # Two enumerations, side by side: the hash table (authoritative) and the
    # room walk (which R20 showed is incomplete). Keeping both makes a
    # regression in either one visible.
    table_counts: dict[int, int] = {}
    for unit_type in range(offsets.UNIT_TYPE_COUNT):
        table_counts[unit_type] = sum(1 for _ in iter_units_of_type(session, unit_type))
    room_counts: dict[int, int] = {}
    for room in nearby_rooms(session):
        for unit in iter_units(session, room):
            try:
                room_counts[session.u32(unit + offsets.UNIT_TYPE)] = (
                    room_counts.get(session.u32(unit + offsets.UNIT_TYPE), 0) + 1
                )
            except Exception:
                continue

    lines.append(
        "unit counts — hash table: "
        + ", ".join(f"type {t}: {c}" for t, c in sorted(table_counts.items()) if c)
        + "\n                 room walk: "
        + (
            ", ".join(f"type {t}: {c}" for t, c in sorted(room_counts.items()) if c)
            or "(nothing)"
        )
    )

    found = 0
    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_ITEM):
        found += 1
        try:
            data = session.ptr(unit + offsets.UNIT_DATA)
            path = session.ptr(unit + offsets.UNIT_PATH)
            fields = {
                "id": session.u32(unit + offsets.UNIT_ID),
                "txt": session.u32(unit + offsets.UNIT_TXT_FILE_NO),
                "mode": session.u32(unit + offsets.UNIT_MODE),
                "loc@0x45": session.u8(data + offsets.ITEM_LOCATION) if data else None,
                "quality": session.u32(data + offsets.ITEM_QUALITY) if data else None,
            }
            as_item_path = (
                (
                    session.u32(path + offsets.ITEM_PATH_X),
                    session.u32(path + offsets.ITEM_PATH_Y),
                )
                if path
                else None
            )
            as_unit_path = (
                (session.u16(path + offsets.PATH_X), session.u16(path + offsets.PATH_Y))
                if path
                else None
            )
        except Exception as exc:
            lines.append(f"  unit 0x{unit:08X}: unreadable ({exc})")
            continue
        lines.append(f"  unit 0x{unit:08X} " + "  ".join(f"{k}={v}" for k, v in fields.items()))
        lines.append(f"      ItemPath(dword)={as_item_path}   Path(word)={as_unit_path}")

    if not found:
        lines.append("  (no item units at all — not even carried ones)")
    lines.append(
        "\nmode key: 0 in-storage, 1 equipped, 2 in-belt, 3 ON GROUND, "
        "4 on-cursor, 5 dropping, 6 socketed"
    )
    return "\n".join(lines)


def dump_carried_items(session) -> str:
    """Every item the character owns, with all three location bytes raw.

    This is the M5 P1 potion-shuffle instrument: the user moves one potion
    between inventory, belt and stash while this dump runs, and every field
    must match the screen before items.py's classification is trusted —
    the ItemData location byte has lied before (instruction log R17).
    """
    from pd2bot import offsets
    from pd2bot.items import read_carried_items

    carried = read_carried_items(session)
    lines = [f"{len(carried.items)} carried items ({carried.skipped} skipped)"]
    lines.append(
        "  kind   quality  mode  loc  node  position    container   note"
    )
    for item in carried.items:
        note = item.potion_name or ""
        if item.belt_slot is not None:
            note += f"  belt col {item.belt_column} slot {item.belt_slot}"
        lines.append(
            f"  {item.kind:<6} {item.quality:<8} {item.mode:<5} "
            f"{item.game_location:<4} {item.node_page:<5} "
            f"{str(item.position):<11} {item.container:<11} {note}"
        )
    belt = carried.belt
    lines.append(
        f"\nbelt: {len(belt)} potions — columns "
        + ", ".join(
            f"{c}: {carried.belt_count(c)}" for c in range(offsets.BELT_COLUMNS)
        )
        + f"   rejuvs: {carried.belt_rejuv_count}"
    )
    lines.append(
        f"inventory: {len(carried.main_inventory)} usable"
        f" + {len(carried.charm_inventory)} in CHARM space (off limits)"
        f"   stash: {len(carried.stash)}"
        f"   cursor: {'yes' if carried.cursor_item else 'no'}"
    )
    lines.append(
        "\nmode key: 0 in-storage, 1 equipped, 2 in-belt, 4 on-cursor, "
        "6 socketed | loc key: 1 equip, 2 belt, 3 inven, 6 cube, 7 stash"
    )
    return "\n".join(lines)


def dump_monster_units(session) -> str:
    """Every type-1 unit with the fields that classify it.

    Mercenaries, summons and hostiles share a unit type; alignment and
    distance decide what each one is to us. Printed raw so a
    misclassification is diagnosable rather than guessable.
    """
    from pd2bot import offsets
    from pd2bot.units import (
        PERCEPTION_RADIUS,
        iter_units_of_type,
        player_unit,
        read_stats,
        unit_position,
    )

    player = player_unit(session)
    origin = (
        unit_position(session, player, offsets.UNIT_TYPE_PLAYER) if player is not None else None
    )
    lines = [f"player at {origin}; perception radius {PERCEPTION_RADIUS} subtiles"]
    lines.append("  kind  align  hp/max      position        dist  note")

    total = positionless = 0
    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_MONSTER):
        total += 1
        try:
            kind = session.u32(unit + offsets.UNIT_TXT_FILE_NO)
            position = unit_position(session, unit, offsets.UNIT_TYPE_MONSTER)
            stats = read_stats(session, unit)
        except Exception as exc:
            lines.append(f"  unit 0x{unit:08X}: unreadable ({exc})")
            continue
        if position is None:
            positionless += 1
            continue
        distance = (
            max(abs(position[0] - origin[0]), abs(position[1] - origin[1]))
            if origin
            else -1
        )
        note = []
        if kind in offsets.MERC_CLASS_IDS:
            note.append(f"MERC {offsets.MERC_CLASS_IDS[kind]}")
        if stats.get(offsets.STAT_ALIGNMENT, 0) == offsets.ALIGNMENT_FRIENDLY:
            note.append("ally")
        if distance > PERCEPTION_RADIUS:
            note.append("out of range")
        if stats.get(offsets.STAT_HP, 0) == 0:
            note.append("dead")
        lines.append(
            f"  {kind:<5} {stats.get(offsets.STAT_ALIGNMENT, 0):<6} "
            f"{stats.get(offsets.STAT_HP, 0):>5}/{stats.get(offsets.STAT_MAX_HP, 0):<7} "
            f"{str(position):<16} {distance:>5}  {', '.join(note)}"
        )

    lines.append(
        f"\n{total} type-1 units in the hash table; {positionless} had no readable position"
    )
    return "\n".join(lines)


def dump_level_exits(session: GameSession) -> str:
    """The current area's warp exits + any boss-flagged monsters in range.

    The M6 P1 probe (and the standing re-verification tool): run it, look
    at the map, and confirm the staircases are where it says. The boss
    table is the Countess-id capture surface — the P2 descent drill reads
    its (unique_no, name) pairs off this same code path.
    """
    from pd2bot import offsets
    from pd2bot.exits import read_level_exits
    from pd2bot.player import read_player
    from pd2bot.units import _read_monster, iter_units_of_type

    scan = read_level_exits(session)
    if scan is None:
        return "not in a game (or mid-load): no level to read exits from"
    player = read_player(session)
    origin = player.position if player is not None else None

    lines = [
        f"area {scan.area} ({offsets.AREA_NAMES.get(scan.area, 'unnamed')}), "
        f"{scan.rooms_walked} static room(s) walked, {scan.skipped} skipped"
    ]
    if not scan.exits:
        lines.append("  no warp exits found (edge-seam areas connect without warps)")
    for one in scan.exits:
        distance = (
            max(abs(one.position[0] - origin[0]), abs(one.position[1] - origin[1]))
            if origin
            else -1
        )
        lines.append(
            f"  -> {one.dest_name:<24} (area {one.dest_area:>3}) at "
            f"{str(one.position):<16} distance {distance}"
        )

    boss_lines = []
    for unit in iter_units_of_type(session, offsets.UNIT_TYPE_MONSTER):
        try:
            monster = _read_monster(session, unit)
        except Exception:  # noqa: BLE001 - diagnostic: skip what tears
            continue
        if monster is None or not monster.is_boss:
            continue
        boss_lines.append(
            # ascii(): a torn or garbage wName must not crash the probe on
            # a console codepage that cannot print it (cp1252 did, live).
            f"  kind {monster.kind:<5} unique_no {monster.unique_no!s:<6} "
            f"name {ascii(monster.name):<30} at {monster.position}"
            f"{'  SUPER-UNIQUE' if monster.is_super_unique else ''}"
        )
    lines.append(
        f"\nboss-flagged monsters in the hash table: {len(boss_lines)}"
    )
    lines.extend(boss_lines)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="keep printing at ~5 Hz")
    parser.add_argument("-v", "--verbose", action="store_true", help="show more of everything")
    parser.add_argument(
        "--items",
        action="store_true",
        help="dump raw fields of every item unit (diagnostic)",
    )
    parser.add_argument(
        "--monsters",
        action="store_true",
        help="dump every type-1 unit with alignment and distance (diagnostic)",
    )
    parser.add_argument(
        "--carried",
        action="store_true",
        help="dump every carried item with raw location bytes (diagnostic)",
    )
    parser.add_argument(
        "--exits",
        action="store_true",
        help="dump the current area's warp exits and boss-flagged monsters (M6)",
    )
    args = parser.parse_args(argv)

    try:
        session = GameSession()
        perception = Perception(session)
    except (GameNotRunning, NeedsAdministrator, UIArrayNotFound) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"attached to pid {session.process_id}, D2Client at 0x{session.client_base:08X}")

    if args.items:
        print(dump_item_units(session))
        return 0

    if args.monsters:
        print(dump_monster_units(session))
        return 0

    if args.carried and not args.watch:
        print(dump_carried_items(session))
        return 0

    if args.exits:
        print(dump_level_exits(session))
        return 0

    if not args.watch:
        print(format_snapshot(perception.snapshot(), args.verbose))
        return 0

    print("watching — Ctrl+C to stop\n")
    try:
        while True:
            if args.carried:
                print(dump_carried_items(session))
            else:
                print(format_snapshot(perception.snapshot(), args.verbose))
            print("-" * 60)
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
