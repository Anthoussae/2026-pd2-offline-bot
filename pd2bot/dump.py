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

    lines.append(f"  items on the ground: {len(snap.ground_items)}")
    for item in snap.ground_items[: 40 if verbose else 8]:
        lines.append(f"    type {item.kind:<5} at {item.position}  {item.quality_name}")

    if snap.skipped_units:
        lines.append(f"  ({snap.skipped_units} units skipped as unreadable)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="keep printing at ~5 Hz")
    parser.add_argument("-v", "--verbose", action="store_true", help="show more of everything")
    args = parser.parse_args(argv)

    try:
        session = GameSession()
        perception = Perception(session)
    except (GameNotRunning, NeedsAdministrator, UIArrayNotFound) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"attached to pid {session.process_id}, D2Client at 0x{session.client_base:08X}")

    if not args.watch:
        print(format_snapshot(perception.snapshot(), args.verbose))
        return 0

    print("watching — Ctrl+C to stop\n")
    try:
        while True:
            print(format_snapshot(perception.snapshot(), args.verbose))
            print("-" * 60)
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
