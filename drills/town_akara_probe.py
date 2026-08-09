"""Where is Akara, really? A read-mostly probe of the Act 1 town approach.

Written 2026-08-08 because `heal` failed twice with "Akara still not
visible after walking to (5922, 5714)" and the honest answer was "we do
not know why" — the configured point is a MEASURED one (T17/R68), so
either the character is not where we think, or the walk is not arriving,
or she is not where she was.

Guessing between those three is exactly what this repo's method note
forbids. So: create a game, say where we are, walk toward the configured
point in capped legs printing position as it goes, and list every ally
in perception with its distance. Then leave.

Town only. Nothing is fought, nothing is picked up, no vitals are armed
beyond the bot's own defaults. The only input is travel clicks.

    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.town_akara_probe
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import mapframe, offsets  # noqa: E402
from pd2bot.cycle import GameCycle  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.perception.world import read_area  # noqa: E402
from pd2bot.town import TownConfig  # noqa: E402

MAX_LEGS = 15


def _dist(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _report_panels(session, ui_array) -> None:
    """What is open right now. The 2026-08-08 stall was an NPC dialog and
    the probe could not see it — the operator had to say so by eye."""
    from pd2bot.perception import uistate

    state = uistate.read_ui_state(session, ui_array)
    names = ", ".join(state.names) if state.names else "none"
    print(f"    panels open: {names} (blocks_input={state.blocks_input})")


def _report_allies(session, here) -> None:
    snap = Perception(session).snapshot()
    print(f"    allies in perception: {len(snap.allies)}")
    for ally in sorted(snap.allies, key=lambda a: _dist(a.position, here)):
        mark = "  <-- AKARA" if ally.kind == offsets.NPC_AKARA else ""
        print(
            f"      kind {ally.kind:>5} at {ally.position} "
            f"dist {_dist(ally.position, here):>4} alive={ally.is_alive}{mark}"
        )


def main() -> int:
    session = GameSession()
    menu = MenuInput(session)
    cycle = GameCycle(session, menu)
    target = TownConfig().npc_positions[offsets.NPC_AKARA]
    print(f"configured Akara approach: {target}")

    if not menu.window.bring_to_foreground():
        print("could not focus the game window — refusing to send anything")
        return 1

    created = False
    try:
        print("creating a game...", flush=True)
        cycle.create_game()
        created = True
        player = read_player(session)
        area = read_area(session)
        here = player.position if player else None
        print(
            f"spawned: {player.name if player else '?'} act={player.act if player else '?'} "
            f"at {here}"
        )
        if area is not None:
            print(
                f"area: {area.level_no} ({mapframe.area_name(area.level_no)}), "
                f"town={area.level_no in offsets.TOWN_AREAS}"
            )
        if here is None:
            print("no player — cannot probe")
            return 1
        print(f"distance from spawn to the configured point: {_dist(here, target)}")
        print("\n--- allies at spawn ---")
        _report_allies(session, here)
        _report_panels(session, menu.ui_array)

        # The decisive question: is the stall MY 2 s cap starving the
        # navigator's own unstick ladder (which needs ~1.5 s just to
        # NOTICE it is stuck, then more to re-click and shake loose), or
        # is this town walk stuck regardless? One uncapped walk answers
        # it, and answering it is the difference between fixing a
        # regression and tuning a number that was never the problem.
        store = MapStore()
        print(f"\n--- walk 1: UNCAPPED toward {target} ---", flush=True)
        uncapped = live_navigator(session, store)
        uncapped._walk_budget_s = None
        began = time.monotonic()
        try:
            result = uncapped.walk_to(target)
            here = read_player(session).position
            print(
                f"  {time.monotonic() - began:.2f}s -> {here}, "
                f"dist-to-target {_dist(here, target)}, capped={result.capped}"
            )
            print(f"  trail: {'; '.join(result.log[-6:])}")
        except Exception as exc:  # noqa: BLE001
            here = read_player(session).position
            print(f"  FAILED after {time.monotonic() - began:.2f}s at {here}: {exc}")

        print(f"\n--- walk 2: CAPPED legs toward {target} ---", flush=True)
        nav = live_navigator(session, store)
        for leg in range(1, MAX_LEGS + 1):
            began = time.monotonic()
            try:
                result = nav.walk_to(target)
            except Exception as exc:  # noqa: BLE001
                print(f"  leg {leg:>2}: FAILED: {exc}")
                break
            here = read_player(session).position
            print(
                f"  leg {leg:>2}: {time.monotonic() - began:.2f}s "
                f"capped={result.capped} at {here} "
                f"dist-to-target {_dist(here, target)}"
            )
            if not result.capped:
                print("    (walk_to reports it is done)")
                break
        print("\n--- allies after walking ---")
        _report_allies(session, here)
        _report_panels(session, menu.ui_array)
    except Exception as exc:  # noqa: BLE001 - a probe reports, never explodes
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
    finally:
        if created:
            try:
                print("\nleaving the game...", flush=True)
                cycle.leave_game()
                print("left cleanly")
            except Exception as exc:  # noqa: BLE001
                print(f"leave failed ({exc}) — a human should look")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
