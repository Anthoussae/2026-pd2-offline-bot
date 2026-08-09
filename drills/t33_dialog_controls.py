"""T33 — are an NPC dialog's rows readable from memory? (user idea, R103)

The user's proposal: detect how many rows an NPC's dialog has and select by
ORDINAL — trade/repair is the 2nd of Charsi's 3 — which transfers to every
NPC, and would explain a fact already on record. Kashya's rows shift when the
resurrect line appears (R56), and that is exactly what happens to a menu laid
out around a centre when a row is added or removed. No fixed offset survives
that; a row index does.

Before building geometry for it, this asks whether the geometry is needed at
all. M4 reads MENU screens through D2Win's control list — every button and
label is a struct with a position and, for buttons, its text (`oog.py`). If
an in-game NPC dialog populates that same list, then the rows can simply be
READ: how many there are, where each one is, and possibly what each says.
That would replace every calibrated fraction, offset and sweep in this whole
saga with a memory read, and it would make "the 2nd row" literal rather than
inferred.

Zero risk: the bot sends nothing and clicks nothing. The user opens the
dialog; we dump the control list with it open and again with it closed, and
diff. If nothing appears, we have lost two minutes and can build the ordinal
model on geometry instead — which is still the user's design, just measured
rather than read.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t33_dialog_controls
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.oog import read_controls  # noqa: E402

T33 = Drill(
    test_id="T33",
    title="Are an NPC dialog's rows readable from the control list?",
    kind="perception",
    instructions=(
        "Read-only: the bot sends nothing and clicks nothing.",
        "1. Walk to CHARSI and click her. Leave the dialog OPEN.",
        "2. Wait ~5s, then CLOSE it (Esc or Cancel).",
        "That is all. No hovering, no timing to get right.",
    ),
)


def describe(controls) -> str:
    if not controls:
        return "    (none)"
    lines = []
    for c in controls:
        text = f" text={c.text!r}" if c.text else ""
        lines.append(
            f"    type={c.ctype} state={c.state} "
            f"at ({c.x}, {c.y}) {c.width}x{c.height}{text}"
        )
    return "\n".join(lines)


def t33_body(run: DrillRun) -> str:
    closed_before = read_controls(run.session)
    print(f"dialog CLOSED: {len(closed_before)} controls", flush=True)
    print(describe(closed_before), flush=True)

    if not run.wait_until(
        lambda: run.panel_open(offsets.UI_NPCMENU), timeout_s=300
    ):
        raise DrillAborted("Charsi's dialog never opened")
    run.sleep(0.8)  # let it finish animating in before reading

    with_dialog = read_controls(run.session)
    print(f"\ndialog OPEN: {len(with_dialog)} controls", flush=True)
    print(describe(with_dialog), flush=True)

    if not run.wait_until(
        lambda: not run.panel_open(offsets.UI_NPCMENU), timeout_s=300
    ):
        raise DrillAborted("the dialog never closed")
    run.sleep(0.5)
    closed_after = read_controls(run.session)
    print(f"\ndialog CLOSED again: {len(closed_after)} controls", flush=True)
    print(describe(closed_after), flush=True)

    # What matters is what APPEARED with the dialog and went away with it —
    # anything present in all three reads is furniture, not dialog rows.
    def key(c):
        return (c.ctype, c.x, c.y, c.width, c.height)

    baseline = {key(c) for c in closed_before} | {key(c) for c in closed_after}
    appeared = [c for c in with_dialog if key(c) not in baseline]
    print(f"\nappeared only with the dialog open: {len(appeared)}", flush=True)
    print(describe(appeared), flush=True)

    if not appeared:
        return (
            f"NOT READABLE — the control list held {len(with_dialog)} entries "
            "with the dialog open and nothing new appeared, so in-game NPC "
            "dialogs do not use D2Win controls. The ordinal-row model has to "
            "be built on measured geometry instead."
        )
    ys = sorted({c.y for c in appeared})
    gaps = [b - a for a, b in zip(ys, ys[1:], strict=False)]
    return (
        f"READABLE — {len(appeared)} controls appear with the dialog "
        f"({len(ys)} distinct y positions: {ys}"
        + (f", gaps {gaps}" if gaps else "")
        + f"); texts {[c.text for c in appeared if c.text]}. Rows can be "
        "counted and located from memory instead of calibrated"
    )


SUITE = {"T33": (T33, t33_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T33"], run=shared)
    print(f"\nsuite: T33 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
