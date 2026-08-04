"""T32 — sweep for the row's CLICKABLE band, bot-only (R101).

T31 asked the user to hover the top and bottom edges of the trade/repair
text. The two hovers came out 4 px apart vertically and 60 px apart
horizontally: they landed along the line, not on its edges. That was a bad
drill design — the edges of a text row are not reliably visible, and asking
a person to eyeball them produces a number that looks like a measurement and
is not one.

The bot can do this properly, and without a human at all. What we actually
need is not where the text *looks* like it ends but where a click *works*,
and that is directly testable: try a click at a series of vertical offsets
and record which ones open the shop. The clickable band is exactly the set
that works, its centre is what the offset should be, and its half-height is
the margin — a number we have never had, and whose absence is why a one-row
error stayed invisible through four failed live runs.

**The menu is three tight rows, not three distant ones** (user, R102):

    TALK
    TRADE/REPAIR
    CANCEL

in a font about 14 px tall. T28's capture put Cancel 180 px below
trade/repair and 83 px to its left, which cannot be right for stacked rows —
that measurement was wrong, and the reasoning built on it was wrong with it,
including an earlier version of this drill that swept +/-60 px in 10 px
steps and claimed no probe could reach Cancel. At a ~20-30 px pitch, a 10 px
step could step clean over the target row, and +/-60 px crosses the whole
menu. So: fine steps, and no pretence that neighbouring rows are out of
reach. Probes WILL land on TALK and CANCEL, which costs nothing — Cancel
closes the dialog, Talk opens gossip — and the drill reopens as needed.

A narrow band also reframes T30's 4/5. On a ~14 px row, an offset 4 px off
centre is already marginal, and there is a second suspect: **Charsi paces.**
Her position is read, projected, and clicked ~50 ms later, so a step taken
in between moves the target out from under the click. That would look
exactly like what we saw — mostly working, occasionally hitting nothing, no
pattern in where the bot stood. So every probe here records whether she
moved between the read and the click, and misses are reported with that
alongside.

    a miss does NOTHING     T30 round 2 left the menu open after a missed
                            click, so a failed probe costs no state and
                            several fit in one opening

Reading the result: a contiguous run of hits is the band. Its centre becomes
the stored offset, and the distance to the "closed" band below is the true
row pitch — the number T28 got wrong. If the hits are scattered rather than
contiguous, or cluster with the she-was-still probes, the anchor is not the
whole story.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t32_band_sweep
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.player import read_player  # noqa: E402
from pd2bot.screen import projection_for  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

POINT = "charsi.trade_repair"
# Sized for a ~14 px row in a three-row menu (R102): far enough to cross
# into TALK above and CANCEL below — which maps the whole menu and yields
# the real row pitch — and stepped finely enough that a 14 px band cannot
# be stepped over.
SWEEP_PX = 36
STEP_PX = 3

T32 = Drill(
    test_id="T32",
    title="Sweep for the trade/repair row's clickable band",
    kind="bot control",
    instructions=(
        "SETUP: in town, all panels closed, hands off throughout.",
        "The bot probes clicks above and below the stored row position.",
        "No gold is spent - it never clicks inside the shop screen.",
        "Expect the dialog to open and close repeatedly. That is the test.",
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


def npc_screen_now(run: DrillRun, town: TownLayer) -> tuple[int, int]:
    """Where Charsi projects RIGHT NOW — she paces, so every probe re-reads."""
    player = read_player(run.session)
    charsi = town._find_ally(offsets.NPC_CHARSI)
    if player is None or charsi is None:
        raise DrillAborted("player or Charsi unreadable with the dialog open")
    return projection_for(
        player.position, run.window.client_rect()
    ).world_to_screen(*charsi)


def ensure_dialog(run: DrillRun, town: TownLayer) -> None:
    if not run.panel_open(offsets.UI_NPCMENU) or run.panel_open(offsets.UI_NPCSHOP):
        town.close_panels()
        town.open_npc_dialog(offsets.NPC_CHARSI, "Charsi")
        run.sleep(town.config.panel_settle_s)


def t32_body(run: DrillRun) -> str:
    config = TownConfig()
    point = config.ui_points[POINT]
    if not point.npc_anchored or point.npc_offset is None:
        raise DrillAborted(f"{POINT} is not an anchored, calibrated point")
    dx, centre = point.npc_offset
    candidates = list(range(centre - SWEEP_PX, centre + SWEEP_PX + 1, STEP_PX))
    print(f"{POINT}: anchor offset ({dx}, {centre}); sweeping {candidates}",
          flush=True)

    town = build_town(run)
    outcomes: dict[int, str] = {}

    moved_during: list[int] = []
    for dy in candidates:
        run.check_cancel()
        ensure_dialog(run, town)
        before = town._find_ally(offsets.NPC_CHARSI)
        npc = npc_screen_now(run, town)
        sx, sy = npc[0] + dx, npc[1] + dy
        town.panel.click(offsets.UI_NPCMENU, sx, sy)
        # Did she move out from under the click? On a ~14 px row a single
        # step is enough to miss, and this is the difference between "the
        # offset is wrong" and "the target moved" (R102).
        after = town._find_ally(offsets.NPC_CHARSI)
        moved = before != after
        if moved:
            moved_during.append(dy)

        opened = town._await(
            lambda: run.panel_open(offsets.UI_NPCSHOP),
            town.config.interact_timeout_s,
        )
        if opened:
            outcomes[dy] = "hit"
        elif not run.panel_open(offsets.UI_NPCMENU):
            # The dialog went away without the shop appearing: this probe
            # landed on a row that dismisses it. Worth distinguishing from a
            # probe that hit nothing at all.
            outcomes[dy] = "closed"
        else:
            outcomes[dy] = "miss"
        print(f"  dy {dy:+5d} -> click ({sx}, {sy}) [Charsi {npc}] "
              f"= {outcomes[dy]}{' (SHE MOVED)' if moved else ''}", flush=True)

    town.close_panels()

    hits = [dy for dy in candidates if outcomes[dy] == "hit"]
    closed = [dy for dy in candidates if outcomes[dy] == "closed"]
    pattern = "".join(
        {"hit": "H", "miss": ".", "closed": "X"}[outcomes[dy]] for dy in candidates
    )
    print(f"\npattern {pattern} over {candidates[0]}..{candidates[-1]}", flush=True)

    if not hits:
        return (
            f"NO OFFSET WORKED across {candidates[0]}..{candidates[-1]} "
            f"(pattern {pattern}); the anchor model does not locate this row"
        )
    contiguous = hits == list(range(hits[0], hits[-1] + 1, STEP_PX))
    band_centre = (hits[0] + hits[-1]) // 2
    half = (hits[-1] - hits[0]) // 2
    # The gap to the dismissing row IS the row pitch — the number T28 got
    # wrong at 180 px, and the reason a one-row error looked impossible.
    pitch = (
        min(abs(c - band_centre) for c in closed) if closed else None
    )
    return (
        f"band {hits[0]}..{hits[-1]} ({hits[-1] - hits[0] + STEP_PX} px tall, "
        f"centre {band_centre}, margin +/-{half} px, stored {centre})"
        + (f"; row pitch to the dismissing row {pitch} px" if pitch else "")
        + (f"; dialog dismissed at {closed}" if closed else "")
        + (f"; Charsi moved during {len(moved_during)} probe(s)" if moved_during else "")
        + f"; pattern {pattern}"
        + (
            ""
            if contiguous
            else " — HITS NOT CONTIGUOUS, so the anchor is not the whole "
            "story and no single offset will fix this"
        )
    )


SUITE = {"T32": (T32, t32_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T32"], run=shared)
    print(f"\nsuite: T32 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
