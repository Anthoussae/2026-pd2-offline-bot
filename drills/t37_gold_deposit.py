"""T37 — depositing gold: what the dialog is, and whether Enter confirms it.

Supersedes T23, which was written before three things we have since learned
and never run. It chatted while the stash was open, which `Chat` now refuses
outright (R89), so its prompts could not have arrived. It assumed the
confirm was a button to hover — but NPC dialogs turned out to be
keyboard-driven (R104), and if the amount dialog takes Enter there is
nothing to calibrate. And it moved no gold, so it could not have proved the
flow either way.

Gold is the one stash transfer with no item to watch, which makes it the
easiest to VERIFY and the fiddliest to DRIVE: carried gold falling and
stashed gold rising by the same amount is unambiguous proof (both readable
since M1), but getting there goes through a dialog rather than a
shift-click.

Three questions, one run:

    1. where is the gold button        (human hovers it; the stash is fixed
                                        furniture, so a client-rect fraction
                                        is legitimate here — unlike an NPC
                                        dialog row, which has no position)
    2. what does the dialog raise      (bot clicks, then reads the settled
                                        panel flags — if it raises nothing,
                                        `PanelInput` has nothing to gate on
                                        inside it and the approach changes)
    3. does ENTER confirm it           (bot tries; gold moving is the proof)

If Enter does not work, the run says so and a follow-up can calibrate a
confirm button — but it is worth asking first, because a keyboard confirm
needs no calibration and cannot drift.

**This moves real gold**, deliberately: a calibration that proves nothing is
what T23 was. The amount is whatever the dialog defaults to, into your own
stash, and services are paid from the shared stash anyway (R76), so nothing
is lost.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t37_gold_deposit
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import VK_RETURN  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.perception import uistate  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402

SETTLE_S = 1.2
SAMPLE_S = 0.15

T37 = Drill(
    test_id="T37",
    title="Gold deposit: dialog flags, and whether Enter confirms",
    kind="human calibration",
    instructions=(
        "SETUP: carry some gold. Read this now - it goes silent once the "
        "stash is open.",
        "1. Open the STASH.",
        "2. HOVER the gold-deposit button. Hold still 3s. Do NOT click.",
        "3. Hands off. The bot clicks it and tries ENTER to confirm.",
        "4. This DOES move gold, into your own stash.",
    ),
    sends_input=True,
)


def gold(run: DrillRun) -> tuple[int, int]:
    player = read_player(run.session)
    return (player.gold, player.gold_stash) if player else (0, 0)


def panels(run: DrillRun) -> list[str]:
    return uistate.read_ui_state(run.session, run.ui_array).names


def settled_panels(run: DrillRun, timeout_s: float) -> list[str]:
    """The panel set once it stops moving — a dialog animating in looks like
    a change that has not finished (T15/R86)."""
    last: list[str] | None = None
    stable_since = 0.0
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        now = panels(run)
        if now != last:
            last, stable_since = now, run.clock()
        elif run.clock() - stable_since >= SETTLE_S:
            return now
        run.sleep(SAMPLE_S)
    return panels(run)


def t37_body(run: DrillRun) -> str:
    if not run.wait_until(
        lambda: run.panel_open(offsets.UI_STASH), timeout_s=300
    ):
        raise DrillAborted("the stash never opened")
    run.sleep(1.0)

    carried, stashed = gold(run)
    print(f"gold: {carried} carried, {stashed} stashed", flush=True)
    print(f"stash panels: {panels(run)}", flush=True)
    if carried == 0:
        raise DrillAborted(
            "you carry 0 gold — a deposit of nothing proves nothing. Withdraw "
            "some or pick some up, then re-run"
        )
    print("hover the gold-deposit button", flush=True)

    got = run.capture_hover(
        required_panel=offsets.UI_STASH,
        last_point=None,
        still_samples=30,
        timeout_s=240,
    )
    if got is None:
        raise DrillAborted("no hover captured for the gold button")
    bx, by, bfx, bfy = got
    print(f"gold button ({bx}, {by}) -> ({bfx:.4f}, {bfy:.4f}); clicking it",
          flush=True)

    panel = PanelInput(run.session, ui_array=run.ui_array)
    before_click = panels(run)
    panel.click(offsets.UI_STASH, bx, by)
    dialog = settled_panels(run, timeout_s=8)
    raised = [p for p in dialog if p not in before_click]
    print(f"panels after the click: {dialog}"
          f"{' — new: ' + ', '.join(raised) if raised else ' — NOTHING NEW'}",
          flush=True)

    # Enter, gated on the stash, which stays open behind the dialog. If the
    # dialog raised its own flag we would rather gate on that, but it has to
    # exist first — which is question 2.
    gate = offsets.UI_STASH
    panel.press_key(gate, VK_RETURN)
    moved = run.wait_until(
        lambda: gold(run)[0] != carried, timeout_s=6, poll_s=0.2
    )
    after_carried, after_stashed = gold(run)
    print(f"after ENTER: {after_carried} carried, {after_stashed} stashed",
          flush=True)

    verdict = (
        f"ENTER CONFIRMS — gold {carried} -> {after_carried} carried, "
        f"{stashed} -> {after_stashed} stashed (moved "
        f"{carried - after_carried}). No confirm button needs calibrating"
        if moved
        else "ENTER DID NOT CONFIRM — the dialog needs a confirm control "
        "hover-calibrated in a follow-up run"
    )
    raised_note = (
        ", ".join(raised)
        if raised
        else (
            "NO NEW PANEL FLAG — ungateable, so PanelInput can only ever "
            "gate on the stash behind it"
        )
    )
    return f"gold button ({bfx:.4f}, {bfy:.4f}); dialog raised {raised_note}; {verdict}"


SUITE = {"T37": (T37, t37_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T37"], run=shared)
    print(f"\nsuite: T37 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
