"""How much room does a travel click actually need around a town NPC?

Written 2026-08-08. The NPC misclick had two causes stacked on each other.
The first is fixed and proven: town NPCs were being filed as decorative
scenery, so `clickable_hazards` had nothing to avoid (perception reported
1 ally in the Rogue Encampment; it now reports 11). The walk still died on
`npc_menu` — the character stopped 4 subtiles from Kashya, who stands
directly on the line from the spawn to Akara.

So `AVOID_RADIUS` (4, Chebyshev, WORLD space) is now the binding rule, and
the suspicion is that it cannot express the thing it is guarding against:
the client's hit test is against a SPRITE, in SCREEN space, and a sprite is
tall. Screen-x moves 20 px per (dx - dy) and screen-y 10 px per (dx + dy)
(measured, `screen.py`), so a click 6 subtiles up-screen of an NPC — world
delta (-6, -6), Chebyshev 6 — lands 120 px above her feet, which is her
body, while a click the same Chebyshev distance sideways is nowhere near
her. A world-space radius covers those two cases equally and the game does
not.

That is a hypothesis, and picking a bigger number to satisfy it is exactly
the guess this repo keeps paying for. So: walk the failing route, record
EVERY travel click with its clearance to every nearby ally in both world
and screen terms, and report the click that actually opened a dialog. The
answer is one row of that table.

Town only. No combat, no pickup, no vitals. Travel clicks are the only
input, and the game is left in a `finally`.

    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.town_click_clearance
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.behavior.town import TownConfig  # noqa: E402
from pd2bot.cycle import GameCycle  # noqa: E402
from pd2bot.input import screen  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.nav.mapstore import MapStore  # noqa: E402
from pd2bot.nav.navigate import live_navigator  # noqa: E402
from pd2bot.perception import uistate  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402

MAX_LEGS = 15
# Only allies this close to a click are worth a row; further ones cannot
# plausibly own the sprite that was hit.
REPORT_RADIUS = 14


def _cheb(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _screen_offset(frm, to) -> tuple[int, int]:
    """Where `to` is drawn relative to `frm`, in window pixels.

    The same arithmetic `screen.py` uses, without needing a window: only
    the DIFFERENCE matters here, and the camera cancels out of it.
    """
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    return (
        (dx - dy) * screen.PX_PER_SUBTILE_X,
        (dx + dy) * screen.PX_PER_SUBTILE_Y,
    )


class ClickRecorder:
    """Every travel click, with who was standing near it."""

    def __init__(self, session) -> None:
        self.session = session
        self.rows: list[dict] = []

    def __call__(self, point, goal, nudges) -> None:
        try:
            snap = Perception(self.session).snapshot()
        except Exception:  # noqa: BLE001 - measurement must never break a walk
            return
        near = []
        for ally in snap.allies:
            gap = _cheb(point, ally.position)
            if gap <= REPORT_RADIUS:
                sx, sy = _screen_offset(ally.position, point)
                near.append(
                    {
                        "kind": ally.kind,
                        "position": ally.position,
                        "world_gap": gap,
                        "screen_dx": sx,
                        "screen_dy": sy,
                    }
                )
        near.sort(key=lambda row: row["world_gap"])
        self.rows.append(
            {
                "n": len(self.rows) + 1,
                "click": point,
                "goal": goal,
                "nudges": nudges,
                "near": near,
            }
        )

    def summarise(self) -> None:
        """Was the rule under test actually exercised?

        A clean walk proves nothing on its own: the NPCs pace, so a run
        where nobody stood on the line would pass without the sprite
        escape ever firing. Review 001 of the event-log work was exactly
        this shape — a drill that could pass without doing the thing it
        tests — so the count is reported, not assumed.
        """
        nudged = [row for row in self.rows if row["nudges"]]
        closest = min(
            (n["world_gap"] for row in self.rows for n in row["near"]),
            default=None,
        )
        print(
            f"\nclicks sent: {len(self.rows)}; nudged: {len(nudged)}; "
            f"closest approach of any click to an ally: "
            f"{closest if closest is not None else 'n/a'} subtiles"
        )
        if not nudged:
            print(
                "  NOTE: no click needed adjusting, so this run did not "
                "exercise the sprite escape — it shows the route is clean "
                "with the NPCs standing where they stood, nothing more."
            )

    def report(self, last: int | None = None) -> None:
        rows = self.rows if last is None else self.rows[-last:]
        print(f"\n--- {len(rows)} travel click(s) ---")
        for row in rows:
            print(
                f"  click {row['n']:>3} at {row['click']} "
                f"(goal {row['goal']}, {row['nudges']} nudge(s))"
            )
            if not row["near"]:
                print(f"      no ally within {REPORT_RADIUS} subtiles")
            for near in row["near"]:
                print(
                    f"      ally kind {near['kind']:>5} at {near['position']}: "
                    f"world gap {near['world_gap']:>2}, "
                    f"drawn {abs(near['screen_dx']):>3} px "
                    f"{'right' if near['screen_dx'] >= 0 else 'left'} / "
                    f"{abs(near['screen_dy']):>3} px "
                    f"{'BELOW' if near['screen_dy'] >= 0 else 'ABOVE'} her feet"
                )


def _blocking(session, ui_array) -> list[str]:
    state = uistate.read_ui_state(session, ui_array)
    return list(state.names) if state.blocks_input else []


def main() -> int:
    session = GameSession()
    menu = MenuInput(session)
    cycle = GameCycle(session, menu)
    target = TownConfig().npc_positions[offsets.NPC_AKARA]

    if not menu.window.bring_to_foreground():
        print("could not focus the game window — refusing to send anything")
        return 1

    created = False
    recorder = ClickRecorder(session)
    try:
        print("creating a game...", flush=True)
        cycle.create_game()
        created = True
        player = read_player(session)
        here = player.position if player else None
        print(f"spawned at {here}; walking toward Akara at {target}")

        nav = live_navigator(session, MapStore())
        # The whole point of the drill: replace the ground-item audit with
        # one that measures ALLY clearance instead.
        nav._audit = recorder

        opened: list[str] = []
        for leg in range(1, MAX_LEGS + 1):
            began = time.monotonic()
            try:
                result = nav.walk_to(target)
                capped = result.capped
            except Exception as exc:  # noqa: BLE001 - the failure IS the data
                print(f"  leg {leg:>2}: FAILED: {exc}")
                capped = True
            here = read_player(session).position
            opened = _blocking(session, menu.ui_array)
            print(
                f"  leg {leg:>2}: {time.monotonic() - began:.2f}s at {here} "
                f"dist {_cheb(here, target):>3}"
                + (f"  PANEL OPEN: {', '.join(opened)}" if opened else "")
            )
            if opened:
                print("    a travel click interacted — stopping to report")
                break
            if not capped:
                print("    (arrived)")
                break

        recorder.report()
        recorder.summarise()
        if opened:
            print(
                "\nVERDICT: the click above with the SMALLEST world gap is the "
                "clearance `AVOID_RADIUS` must beat. Compare the screen offsets: "
                "if the offending clicks are drawn ABOVE the NPC's feet while "
                "clicks the same world distance to the side are harmless, the "
                "rule needs to be a screen-space box, not a world-space radius."
            )
        else:
            print("\nVERDICT: no dialog opened — the route was clean this time.")
    except Exception as exc:  # noqa: BLE001 - a drill reports, never explodes
        print(f"\nDRILL FAILED: {type(exc).__name__}: {exc}")
        recorder.report()
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
