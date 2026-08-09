"""T29 — is an NPC dialog row a fixed OFFSET from the NPC? (R97)

The user's diagnosis, which resolves everything that came before it: NPC
dialog boxes are drawn relative to the NPC, and NPCs wander. So a row's
position in an NPC dialog is not a property of the screen at all, and no
client-rect fraction can ever locate one. Every value we stored for
`charsi.trade_repair` was a snapshot of one accidental arrangement — which
is exactly why each new number worked once and then failed, and why three
different points have all opened the shop while one of them also hit
Cancel.

The proposal this tests: store the row as an **offset from the NPC's
projected screen position** instead. We can compute where Charsi is on
screen at any moment — `screen.projection_for(player, rect).world_to_screen`
— from the M3 projection that the acceptance walk proved. If

    row_screen - npc_screen

is the same across openings from different standing positions, that
constant IS the fix, and it is a property of the UI rather than of one
lucky arrangement.

Three rounds, because two points always fit a line and three can disagree.
Each round: the bot walks somewhere different, opens the dialog, records
where Charsi projects to, and waits SILENTLY (chat would press Enter into
the dialog, R89) for the user to hover the real trade/repair line.

Reading the result:

    offsets agree      the model holds; T30 then confirms it bot-only
    offsets scatter    the dialog is not NPC-anchored either, and the row
                       has to be found at click time rather than predicted

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t29_row_repeatability
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.input.screen import projection_for  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

# Where to stand for each round, as a subtile offset from Charsi. Different
# sides, so the NPC lands in a genuinely different part of the screen — the
# whole point is to make the dialog move.
STANDING_SPOTS = [(-11, -4), (10, 6), (-3, 11)]
AGREEMENT_PX = 12  # hover precision is a few px; this is comfortably above it

T29 = Drill(
    test_id="T29",
    title="Is an NPC dialog row a fixed offset from the NPC?",
    kind="human calibration",
    # Terse on purpose (user, R98): these are delivered once, before the
    # first dialog opens, and after that the drill is silent — so they have
    # to be recallable from memory, not merely correct.
    instructions=(
        "SETUP: in town, all panels closed, hands off.",
        "3 ROUNDS, all identical. Bot drives. You only hover.",
        "Dialog opens -> HOVER trade/repair. Hold still 3s.",
        "NEVER CLICK.",
        "Dialog closes = captured. Wait for the next round.",
    ),
    sends_input=True,
)


def build_town(run: DrillRun) -> TownLayer:
    session = run.session
    navigator = live_navigator(session, MapStore(), offsets.DIFFICULTY_HELL)
    return TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=navigator.walk_to,
        snapshot=Perception(session).snapshot,
        config=TownConfig(),
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def charsi_screen(run: DrillRun, town: TownLayer) -> tuple[tuple[int, int], tuple[int, int]]:
    """Where Charsi is in the world, and where that projects on screen NOW.

    Read fresh at the moment the dialog is up: the camera follows the player
    and NPCs pace, so a stale reading of either would move the answer.
    """
    player = read_player(run.session)
    if player is None:
        raise DrillAborted("player unreadable")
    world = town._find_ally(offsets.NPC_CHARSI)
    if world is None:
        raise DrillAborted(
            "Charsi is not in perception range with her dialog open — cannot "
            "anchor the row to an NPC we cannot locate"
        )
    projection = projection_for(player.position, run.window.client_rect())
    return world, projection.world_to_screen(*world)


def t29_body(run: DrillRun) -> str:
    town = build_town(run)
    charsi_home = TownConfig().npc_positions[offsets.NPC_CHARSI]
    samples = []

    for index, (dx, dy) in enumerate(STANDING_SPOTS, start=1):
        run.check_cancel()
        town.close_panels()
        try:
            town._walk_guarded((charsi_home[0] + dx, charsi_home[1] + dy))
        except Exception as exc:  # noqa: BLE001 - a failed move is not the test
            print(f"round {index}: could not reposition ({exc}) — "
                  "measuring from where we are", flush=True)
        town.close_panels()
        town.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
        run.sleep(town.config.panel_settle_s)

        world, npc_px = charsi_screen(run, town)
        player = read_player(run.session)
        print(f"\nround {index}: stood {player.position if player else '?'}, "
              f"Charsi at {world} -> screen {npc_px}; hover TRADE/REPAIR",
              flush=True)

        got = run.capture_hover(
            required_panel=offsets.UI_NPCMENU,
            last_point=None,
            still_samples=30,
            timeout_s=240,
        )
        if got is None:
            raise DrillAborted(f"round {index}: no hover captured")
        rx, ry, _, _ = got
        offset = (rx - npc_px[0], ry - npc_px[1])
        samples.append(offset)
        print(f"  row at ({rx}, {ry}); offset from Charsi {offset}", flush=True)
        town.close_panels()

    xs = [o[0] for o in samples]
    ys = [o[1] for o in samples]
    spread = (max(xs) - min(xs), max(ys) - min(ys))
    mean = (round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
    # Judge the axes SEPARATELY. A combined test conflates a real signal
    # with measurement noise, and did on this drill's first run (R98): Y
    # agreed to 5 px while X spread 84, and a max() over both called the
    # whole thing a failure. X *should* scatter — a dialog row is a wide
    # line of text and the human hovers anywhere along it — while Y is the
    # axis that decides WHICH row, since rows stack 180 px apart (T28).
    y_agrees = spread[1] <= AGREEMENT_PX
    x_agrees = spread[0] <= AGREEMENT_PX

    print(f"\noffsets: {samples}", flush=True)
    print(f"spread {spread} px, mean {mean}", flush=True)
    if y_agrees:
        verdict = (
            f"Y IS A FIXED OFFSET ({mean[1]} px, spread {spread[1]} px) — the "
            f"row is NPC-anchored vertically, which is the axis that picks "
            f"the row. X spread {spread[0]} px is hover placement along a "
            f"wide line, not layout"
            if not x_agrees
            else f"BOTH AXES FIXED at {mean} (spread {spread} px)"
        )
    else:
        verdict = (
            f"Y DOES NOT AGREE (spread {spread[1]} px) — the dialog is not "
            "NPC-anchored vertically, so the row must be located at click "
            "time rather than predicted"
        )
    return f"offsets {samples}; spread {spread} px; mean offset {mean}; {verdict}"


SUITE = {"T29": (T29, t29_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T29"], run=shared)
    print(f"\nsuite: T29 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
