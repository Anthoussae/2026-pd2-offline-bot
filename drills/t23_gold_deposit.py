"""T23 — calibrate depositing gold into the stash (user request, R75).

Gold is the one stash transfer with no item to watch: the proof is that
carried gold falls and stashed gold rises by the same amount, both of
which are already readable (STAT_GOLD / STAT_GOLD_BANK, live since M1).
That makes it the easiest transfer to verify and the fiddliest to drive,
since it goes through a dialog rather than a shift-click.

The drill captures whatever the flow needs — the gold button on the stash
panel, and the confirm control in whatever dialog it raises — and reports
the panel flags at each step, so we learn whether the amount dialog even
registers as a panel we can gate on. If it does not, the deposit cannot be
driven safely by PanelInput and we will need a different approach; better
to discover that here than mid-run.

Deliberately calibration-only: no gold is moved. T24 (the bot doing it,
with the before/after proof) comes once we know the shape of the dialog.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t23_gold_deposit
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets, uistate  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.player import read_player  # noqa: E402

FINDINGS: dict = {}


def gold(run: DrillRun) -> tuple[int, int]:
    player = read_player(run.session)
    return (player.gold, player.gold_stash) if player else (0, 0)


def panels(run: DrillRun) -> list[str]:
    return uistate.read_ui_state(run.session, run.ui_array).names


T23 = Drill(
    test_id="T23",
    title="Gold deposit calibration",
    kind="human calibration",
    instructions=(
        "Open the STASH. You need some gold ON YOUR PERSON for this to mean "
        "anything - pick some up or withdraw a little first.",
        "Rest the cursor on the GOLD button (the deposit-gold control on the "
        "stash panel) and hold still 3s.",
        "Then click it to raise the amount dialog, and hover the button that "
        "CONFIRMS the deposit; hold still. Do not complete it - I only need "
        "the positions.",
    ),
)


def t23_body(run: DrillRun) -> str:
    if not run.announce_until(
        "Open the STASH (with some gold carried), then hover the GOLD button.",
        lambda: run.panel_open(offsets.UI_STASH),
        timeout_s=240,
    ):
        raise DrillAborted("the stash never opened")

    carried, stashed = gold(run)
    print(f"gold at start: {carried} carried, {stashed} stashed", flush=True)
    print(f"stash panels: {panels(run)}", flush=True)
    if carried == 0:
        run.say("Note: you carry 0 gold - I can still calibrate, but T24 will need some.")

    button = run.capture_hover(
        required_panel=offsets.UI_STASH, last_point=None,
        still_samples=30, timeout_s=150,
    )
    if button is None:
        raise DrillAborted("no hover captured for the gold button")
    FINDINGS["gold_button"] = (button[2], button[3])
    print(
        f"gold button at ({button[0]}, {button[1]}) -> "
        f"({button[2]:.4f}, {button[3]:.4f})",
        flush=True,
    )

    run.say("Got it. Now click the gold button, and hover the CONFIRM control.")
    # Watch what the dialog does to the panel flags: if it raises nothing we
    # can gate on, PanelInput cannot guard clicks inside it.
    before_panels = set(panels(run))
    deadline = time.time() + 60
    dialog_panels: set[str] = set()
    while time.time() < deadline:
        now = set(panels(run))
        if now != before_panels:
            dialog_panels = now
            print(f"panels changed on opening the dialog: {sorted(now)}", flush=True)
            break
        time.sleep(0.2)
    if not dialog_panels:
        print(
            "!! the amount dialog raised NO new panel flag — PanelInput has "
            "nothing to verify against inside it (see the drill docstring)",
            flush=True,
        )
    FINDINGS["dialog_panels"] = sorted(dialog_panels)

    confirm = run.capture_hover(
        required_panel=offsets.UI_STASH,  # the stash stays up behind the dialog
        last_point=(button[0], button[1]),
        still_samples=30,
        timeout_s=150,
    )
    if confirm is None:
        raise DrillAborted("no hover captured for the confirm control")
    FINDINGS["confirm_button"] = (confirm[2], confirm[3])
    print(
        f"confirm at ({confirm[0]}, {confirm[1]}) -> "
        f"({confirm[2]:.4f}, {confirm[3]:.4f})",
        flush=True,
    )

    run.say("Calibrated - cancel the dialog, nothing was deposited.")
    return (
        f"gold button ({button[2]:.4f}, {button[3]:.4f}); "
        f"confirm ({confirm[2]:.4f}, {confirm[3]:.4f}); "
        f"dialog panels {FINDINGS['dialog_panels'] or 'NONE — ungateable'}; "
        f"gold {carried} carried / {stashed} stashed"
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T23, t23_body, session=GameSession()) == "PASS" else 1)
