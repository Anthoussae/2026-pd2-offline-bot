"""T79 — the controlled label-state experiment: does labels-OFF pick a pile?

T76 run 2 (labels **ON**) failed 7 of 8 in a dense pile; run 3 (labels
**OFF**) swept a comparable pile at the first offset. But those two runs
differed in more than the label flag — items and positions moved too.
This drill controls the one variable: it **sets** the label display
itself (an ALT press, verified against `units.label_display_on`, exactly
as the executor does), and measures a pile in each state.

If labels-OFF genuinely picks a pile that labels-ON cannot, that is a
large finding — the executor currently *ensures labels ON*, which would
then be a contributor to the Countess chamber's pickup failures — and it
is a clean P2 lever. If the two states pick the same, the run-2/run-3
gap was noise and the label lead dies here. Either is worth knowing.

**This test SENDS INPUT**: two ALT presses to set state, then a paced
schedule of clicks per item. Misses are move orders, so the character
wanders a little; each click re-projects.

## How it ends

On its own after both label states are measured, or when you type
`done`. Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or the
mouse.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t79_label_state
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Reuse the MEASURED helpers rather than a second copy that could drift —
# the same reason the codebase shares `_PickupMixin`.
from drills.t76_pickup_calibration import (  # noqa: E402
    GO_WORDS,
    _await_word,
    _click_schedule,
    _floor,
    _origin,
    classify,
    crowding,
)
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import VK_MENU, GatedInput, InputRefused  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.pickit import load_item_codes  # noqa: E402
from pd2bot.units import label_display_on  # noqa: E402

# A "pile" worth the name — below this the label question is moot because
# nothing is occluding anything.
MIN_PILE_CROWD = 3


def _set_labels(run: DrillRun, gated: GatedInput, target: bool) -> bool | None:
    """Drive the ALT label display to `target`, verified. Returns the
    achieved state, or None if the flag cannot be read (never guess it).

    The mechanism is the executor's own (T66): read the flag, press ALT
    only when it disagrees, re-read. A press that does not move the flag
    after a few tries is reported, not pretended away.
    """
    for _ in range(4):
        run.check_cancel()
        state = label_display_on(run.session)
        if state is None:
            return None
        if state == target:
            return state
        try:
            gated.press_key(VK_MENU)
        except InputRefused:
            pass
        run.sleep(0.2)
    return label_display_on(run.session)


def verdict(results: list[dict]) -> list[str]:
    """The controlled comparison: pile pick-rate by label state.

    `results` rows carry `labels` (bool, the VERIFIED state), `picked`,
    `crowding`. Only genuine piles (crowd >= MIN_PILE_CROWD) speak to the
    question; solo items are reported but excluded from the verdict.
    """
    lines: list[str] = []
    for state in (True, False):
        rows = [r for r in results if r["labels"] is state]
        pile = [r for r in rows if r["crowding"] >= MIN_PILE_CROWD]
        if not rows:
            lines.append(f"  labels {'ON' if state else 'OFF'}: not measured")
            continue
        picked = sum(1 for r in pile if r["picked"])
        lines.append(
            f"  labels {'ON' if state else 'OFF'}: "
            f"pile {picked}/{len(pile)} lifted"
            + (f" (crowd>={MIN_PILE_CROWD})" if pile else " — no pile staged")
            + f"; all arrangements {sum(1 for r in rows if r['picked'])}/{len(rows)}"
        )
    on = [r for r in results if r["labels"] is True and r["crowding"] >= MIN_PILE_CROWD]
    off = [r for r in results if r["labels"] is False and r["crowding"] >= MIN_PILE_CROWD]
    if on and off:
        on_rate = sum(1 for r in on if r["picked"]) / len(on)
        off_rate = sum(1 for r in off if r["picked"]) / len(off)
        if off_rate - on_rate >= 0.25:
            lines.append(
                "  -> labels OFF picks the pile markedly better "
                "(run-2/run-3 gap CONFIRMED under control): the executor's "
                "ensure-ON policy is a pile liability."
            )
        elif on_rate - off_rate >= 0.25:
            lines.append("  -> labels ON is better; the run-3 result was the outlier.")
        else:
            lines.append(
                "  -> no meaningful label-state difference on the pile; "
                "the run-2/run-3 gap was not the label flag."
            )
    else:
        lines.append(
            "  -> inconclusive: need a genuine pile "
            f"(crowd>={MIN_PILE_CROWD}) measured in BOTH label states."
        )
    return lines


def sufficient(results: list[dict]) -> tuple[bool, str]:
    """PASS needs a real pile measured in BOTH verified label states (the
    T72 lesson: do not pass on the easy half)."""
    on = [r for r in results if r["labels"] is True and r["crowding"] >= MIN_PILE_CROWD]
    off = [r for r in results if r["labels"] is False and r["crowding"] >= MIN_PILE_CROWD]
    if on and off:
        return True, f"pile measured labels-ON ({len(on)}) and labels-OFF ({len(off)})"
    return False, (
        "INCOMPLETE — need a pile "
        f"(crowd>={MIN_PILE_CROWD}) in BOTH label states; got "
        f"ON={len(on)}, OFF={len(off)}"
    )


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T79",
        title="label-state experiment — does labels-OFF pick a pile?",
        kind="hybrid",
        sends_input=True,
        instructions=(
            "TWO ROUNDS, same shape, one variable: the ALT label display,",
            "which I set and verify myself before each round.",
            "  ROUND 1: labels ON.  ROUND 2: labels OFF.",
            "Each round: I confirm the label state, then you drop a PILE",
            "(several items PACKED on one spot — include a small item if",
            "you can), stand still, and type GO. I click the schedule and",
            "record what came up. Type 'done' to finish early.",
            "ENDS ON ITS OWN. Abort: 'abort', drill-cancel, ESC, mouse.",
        ),
    )

    def body(run: DrillRun) -> str:
        gated = GatedInput(run.session)
        codes_by_kind = {
            kind: code
            for code, kinds in load_item_codes(
                REPO / "config" / "item_codes.toml"
            ).items()
            for kind in kinds
        }

        results: list[dict] = []
        skipped: list[str] = []
        for target in (True, False):
            name = "ON" if target else "OFF"
            achieved = _set_labels(run, gated, target)
            if achieved is None:
                skipped.append(f"labels {name} (flag unreadable — not set)")
                run.say(f"SKIPPING labels {name}: cannot read the label flag.")
                continue
            if achieved != target:
                skipped.append(f"labels {name} (press did not move the flag)")
                run.say(f"SKIPPING labels {name}: ALT did not change the display.")
                continue
            print(f"\n--- round: labels {name} (verified {achieved}) ---", flush=True)

            before = set(_floor(run))
            run.say(
                f"Labels are {name}. Drop a PILE (several packed on one "
                "spot), stand still, then type GO."
            )
            if _await_word(run, GO_WORDS) != "heard":
                skipped.append(f"labels {name} (no GO)")
                break
            floor = _floor(run)
            fresh = {uid: info for uid, info in floor.items() if uid not in before}
            print(f"  player {_origin(run)}; {len(fresh)} new item(s)", flush=True)
            for uid, (kind, pos) in floor.items():
                mark = "NEW" if uid in fresh else "   "
                print(f"    {mark} {uid} kind {kind} "
                      f"({classify(kind, codes_by_kind)}) at {pos}", flush=True)
            if not fresh:
                skipped.append(f"labels {name} (no new items in census)")
                run.say(f"SKIPPING labels {name}: saw no new items.")
                continue

            everything = [p for _, p in floor.values()]
            for gid, (kind, pos) in list(fresh.items()):
                # Re-verify the flag did not drift mid-round (a stray ALT,
                # a UI event): the label state on THIS item is the datum.
                here = label_display_on(run.session)
                if gid not in _floor(run):
                    print(f"  {gid} left before we aimed — skipping", flush=True)
                    continue
                others = [p for p in everything if p != pos]
                crowd = crowding(pos, others)
                item_class = classify(kind, codes_by_kind)
                print(f"  target {gid} kind {kind} ({item_class}) crowd {crowd} "
                      f"labels={here}", flush=True)
                winner, trail = _click_schedule(run, gated, gid, pos)
                results.append({
                    "labels": bool(here) if here is not None else target,
                    "unit_id": gid, "kind": kind, "item_class": item_class,
                    "crowding": crowd, "winning_offset": list(winner) if winner else None,
                    "picked": winner is not None, "clicks": len(trail), "trail": trail,
                })

        print("\n=== LABEL-STATE VERDICT ===", flush=True)
        for line in verdict(results):
            print(line, flush=True)

        ok, why = sufficient(results)
        summary = f"{len(results)} target(s); {why}"
        if skipped:
            summary += f"; SKIPPED: {'; '.join(skipped)}"
        if not ok:
            raise RuntimeError(summary)
        return summary

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
