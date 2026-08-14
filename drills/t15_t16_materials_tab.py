"""T15-T16 — the stash's materials tab: find its state signal, then toggle it.

User request (R63): PD2's stash has a materials tab, reached by an X button
on the stash screen, holding many more items. Before the bot can use it for
anything it must be able to (a) tell which tab is showing and (b) switch
tabs on purpose — and (a) has to come first, because a toggle we cannot
verify is a click we are not allowed to make (the standing rule since M4's
difficulty guard).

    T15  discovery + calibration   the user toggles the tab by hand while
                                   the bot diffs everything it can read,
                                   then hovers the X button for its position
    T16  bot control               the bot clicks X, verifies the signal
                                   moved, clicks back, verifies it returned

T15 watches three channels at once, because it is not obvious in advance
which one carries the tab state: the raw UI-panel array (a tab might set its
own flag), the set of visible stash item ids (a different page shows
different items), and their storage bytes. Whichever moves in lockstep with
the user's toggles becomes T16's verification.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t15_t16_materials_tab
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.perception import uistate  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402

# Filled by T15, consumed by T16 (same process, sequential by construction).
FINDINGS: dict = {}


def stash_signature(run: DrillRun) -> tuple:
    """Everything readable that might differ between tabs."""
    carried = read_carried_items(run.session)
    stash = carried.stash
    return (
        uistate.read_ui_raw(run.session, run.ui_array),
        frozenset(i.unit_id for i in stash),
        frozenset((i.game_location, i.node_page) for i in stash),
        len(stash),
    )


def describe_change(before: tuple, after: tuple) -> list[str]:
    notes = []
    if before[0] != after[0]:
        moved = [
            f"slot {i:#04x} {a}->{b}"
            for i, (a, b) in enumerate(zip(before[0], after[0], strict=True))
            if a != b
        ]
        notes.append("UI array: " + ", ".join(moved))
    if before[1] != after[1]:
        notes.append(
            f"stash item ids: {len(before[1])} -> {len(after[1])} "
            f"({len(before[1] - after[1])} gone, {len(after[1] - before[1])} new)"
        )
    if before[2] != after[2]:
        notes.append(f"storage bytes: {sorted(before[2])} -> {sorted(after[2])}")
    return notes


# ------------------------------------------------- T15: discovery + calibration

T15 = Drill(
    test_id="T15",
    title="Materials tab: find the state signal, calibrate the X button",
    kind="human calibration",
    instructions=(
        "Open the STASH and leave it open for the whole test.",
        "First I watch: toggle to the MATERIALS tab and back, twice, pausing "
        "about 2s on each tab so I can see what changes.",
        "Then I will ask you to hover the X button so I can learn where it is.",
    ),
)


def t15_body(run: DrillRun) -> str:
    if not run.announce_until(
        "Open the STASH now (I need it open to watch the tabs).",
        lambda: run.panel_open(offsets.UI_STASH),
        timeout_s=180,
    ):
        raise DrillAborted("the stash never opened")

    run.say("Watching. Toggle to MATERIALS and back, twice, ~2s on each tab.")
    baseline = stash_signature(run)
    transitions = []
    current = baseline
    deadline = time.time() + 120
    while time.time() < deadline and len(transitions) < 4:
        if not run.panel_open(offsets.UI_STASH):
            time.sleep(0.2)
            continue
        now = stash_signature(run)
        if now != current:
            notes = describe_change(current, now)
            if notes:
                transitions.append(notes)
                print(f"transition {len(transitions)}: {'; '.join(notes)}", flush=True)
            current = now
        time.sleep(0.15)

    if not transitions:
        raise DrillAborted(
            "nothing observable changed between tabs — the materials tab is "
            "invisible to every channel we can read; it needs a different "
            "approach before the bot may click it"
        )

    ui_moved = any(any(n.startswith("UI array") for n in t) for t in transitions)
    items_moved = any(any(n.startswith("stash item ids") for n in t) for t in transitions)
    FINDINGS["signal"] = "ui_array" if ui_moved else ("stash_items" if items_moved else None)
    FINDINGS["transitions"] = transitions

    # -- calibrate the X button ---------------------------------------------------
    run.say("Got it. Now rest the cursor on the X button (tab toggle) and hold still 3s.")
    got = run.capture_hover(
        required_panel=offsets.UI_STASH,
        last_point=None,
        still_samples=30,
        timeout_s=120,
    )
    if got is None:
        raise DrillAborted("no hover captured for the X button")
    x, y, fx, fy = got
    FINDINGS["x_button"] = (fx, fy)
    print(f"X button at ({x}, {y}) -> fraction ({fx:.4f}, {fy:.4f})", flush=True)

    return (
        f"{len(transitions)} tab transitions seen; signal = {FINDINGS['signal']}; "
        f"X button fraction ({fx:.4f}, {fy:.4f}); "
        f"first transition: {'; '.join(transitions[0])}"
    )


# ------------------------------------------------------------ T16: bot toggle

T16 = Drill(
    test_id="T16",
    title="Materials tab: bot toggles and verifies",
    kind="bot control",
    instructions=(
        "Keep the STASH open and leave the mouse alone.",
        "The bot will click the X button, confirm the tab actually changed, "
        "then click back and confirm it returned.",
    ),
    sends_input=True,
)


def t16_body(run: DrillRun) -> str:
    if "x_button" not in FINDINGS:
        raise DrillAborted("T15 did not calibrate the X button; nothing to click")
    if FINDINGS.get("signal") is None:
        raise DrillAborted("T15 found no verifiable signal; refusing to click blind")

    if not run.announce_until(
        "Open the STASH for the toggle test.",
        lambda: run.panel_open(offsets.UI_STASH),
        timeout_s=120,
    ):
        raise DrillAborted("the stash never opened")

    panel = PanelInput(run.session, ui_array=run.ui_array)
    rect = run.window.client_rect()
    fx, fy = FINDINGS["x_button"]
    sx = rect.left + round(fx * rect.width)
    sy = rect.top + round(fy * rect.height)

    results = []
    for label in ("switch", "switch back"):
        before = stash_signature(run)
        panel.click(offsets.UI_STASH, sx, sy)
        changed = False
        deadline = time.time() + 5
        while time.time() < deadline:
            after = stash_signature(run)
            if after != before:
                changed = True
                break
            time.sleep(0.1)
        if not changed:
            raise DrillAborted(
                f"{label}: clicked ({sx}, {sy}) but nothing changed — the "
                "calibration may be off; not clicking again"
            )
        notes = describe_change(before, after)
        print(f"{label}: {'; '.join(notes)}", flush=True)
        results.append(f"{label} OK")
        time.sleep(1.0)

    return f"toggled twice via ({sx}, {sy}); {', '.join(results)}"


SUITE = {"T15": (T15, t15_body), "T16": (T16, t16_body)}

if __name__ == "__main__":
    wanted = [a.upper() for a in sys.argv[1:]] or list(SUITE)
    unknown = [w for w in wanted if w not in SUITE]
    if unknown:
        raise SystemExit(f"unknown drill(s): {', '.join(unknown)}; have {list(SUITE)}")
    shared = DrillRun(GameSession())
    statuses = [run_drill(*SUITE[name], run=shared) for name in wanted]
    summary = ", ".join(f"{n} {s}" for n, s in zip(wanted, statuses, strict=True))
    print(f"\nsuite: {summary}")
    raise SystemExit(0 if all(s == "PASS" for s in statuses) else 1)
