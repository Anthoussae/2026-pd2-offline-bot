"""T79 — the controlled label-state experiment, AUTOMATED and within-subjects.

The question, from T76 runs 2 and 3: a dense pile failed every offset
with the ALT label display **ON** and was swept cleanly with it **OFF**
— but those runs also moved the items, so the label flag was never the
sole variable. This drill removes every confound:

- **within-subjects** — one pile, measured labels-ON, then the SAME
  survivors measured labels-OFF. Same items, same positions, one flag.
- **automated** — the bot drops the pile itself from inventory (operator
  licence 2026-08-06: inventory items may be used for testing, EXCEPT
  the two tomes and the Horadric Cube), so no manual staging. The
  exclusion is `UNMOVABLE_KINDS | RIGHT_CLICK_HAZARD_KINDS` — cube,
  tomes AND potions, because a dropped ctrl on a potion drinks it.
- **self-recovering** — the labels-OFF pass is also the recovery pass
  (OFF picks piles well), and anything still down at the end is reported
  loudly for the operator to grab.

The executor currently *ensures labels ON* (T66, for small-class
clickability). If OFF genuinely picks a pile that ON cannot, that policy
is a pile liability and a clean P2 lever. Command-by-GID (P4) sidesteps
the whole question — no labels, no aim.

**This test SENDS INPUT**: drops items from inventory, presses ALT to
set the label state, and clicks a schedule per item.

## How it ends

On its own once both states are measured and recovery is attempted, or
on `done`. Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, mouse.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t79_label_state
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from drills.t76_pickup_calibration import (  # noqa: E402
    _click_schedule,
    _floor,
    classify,
    crowding,
)
from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import VK_I, VK_MENU, GatedInput, InputRefused  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.pickit import load_item_codes  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import TownLayer  # noqa: E402
from pd2bot.uistate import find_ui_array, read_ui_state  # noqa: E402
from pd2bot.units import label_display_on  # noqa: E402

MIN_PILE_CROWD = 3
MAX_DROP = 8   # a manageable pile; bounds the items ever at risk on the floor

# Never dropped: the operator's exclusion (tomes 533/534, cube 564) plus
# potions, whose bare right-click drinks them if the ctrl modifier slips.
SAFE_EXCLUDE = offsets.UNMOVABLE_KINDS | offsets.RIGHT_CLICK_HAZARD_KINDS


# -- pure logic (unit-tested; no game) -------------------------------------------


def droppable(carried, exclude=SAFE_EXCLUDE, limit=MAX_DROP) -> list:
    """The inventory items safe to drop for testing, capped."""
    return [
        item
        for item in carried.main_inventory
        if item.kind not in exclude
    ][:limit]


def verdict(results: list[dict]) -> list[str]:
    """The controlled comparison: pile pick-rate by label state.

    Rows carry `labels` (the VERIFIED state), `picked`, `crowding`. Only
    genuine piles (crowd >= MIN_PILE_CROWD) speak to the question.
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
            f"  labels {'ON' if state else 'OFF'}: pile {picked}/{len(pile)} lifted"
            + (f" (crowd>={MIN_PILE_CROWD})" if pile else " — no pile")
            + f"; all {sum(1 for r in rows if r['picked'])}/{len(rows)}"
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
                "  -> no meaningful label-state difference on the pile."
            )
    else:
        lines.append(
            "  -> inconclusive: need a genuine pile "
            f"(crowd>={MIN_PILE_CROWD}) in BOTH label states."
        )
    return lines


def sufficient(results: list[dict], min_per_state: int = 3) -> tuple[bool, str]:
    """PASS needs a real pile measured in BOTH verified states, with at
    least `min_per_state` items each (the T72 lesson AND run 1's n=1 trap:
    do not conclude from a single OFF item)."""
    on = [r for r in results if r["labels"] is True and r["crowding"] >= MIN_PILE_CROWD]
    off = [r for r in results if r["labels"] is False and r["crowding"] >= MIN_PILE_CROWD]
    if len(on) >= min_per_state and len(off) >= min_per_state:
        return True, f"pile measured ON ({len(on)}) and OFF ({len(off)})"
    return False, (
        f"INCOMPLETE — need a pile (crowd>={MIN_PILE_CROWD}) of >= "
        f"{min_per_state} in BOTH states; got ON={len(on)}, OFF={len(off)}"
    )


# -- live plumbing ---------------------------------------------------------------


def _set_labels(run: DrillRun, gated: GatedInput, target: bool) -> bool | None:
    """Drive the ALT label display to `target`, verified (the executor's
    own mechanism, T66). None if the flag cannot be read (never guessed)."""
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


def _build_town(run: DrillRun, gated: GatedInput) -> TownLayer:
    ui_array = find_ui_array(run.session)
    return TownLayer(
        run.session,
        gated,
        PanelInput(run.session, ui_array=ui_array),
        MenuInput(run.session, ui_array=ui_array),
        walk_to=lambda pos: None,   # drop_item never walks
        snapshot=Perception(run.session).snapshot,
    )


def _inventory_open(run: DrillRun) -> bool:
    return offsets.UI_INVENTORY in read_ui_state(run.session).open_panels


def _stage_pile(run: DrillRun, gated: GatedInput, town: TownLayer) -> list[int]:
    """Drop up to MAX_DROP safe inventory items onto the floor. Returns the
    gids seen on the floor afterwards. Leaves the inventory CLOSED."""
    before = set(_floor(run))
    town.press_inventory_open()
    carried = read_carried_items(run.session)
    candidates = droppable(carried)
    print(f"  {len(candidates)} safe drop candidate(s) "
          f"(excluding tomes/cube/potions)", flush=True)
    dropped = 0
    for item in candidates:
        run.check_cancel()
        try:
            if town.drop_item(item):
                dropped += 1
        except Exception as exc:  # noqa: BLE001 - a stuck drop is not fatal
            print(f"    drop of unit {item.unit_id} kind {item.kind} "
                  f"failed: {exc}", flush=True)
    # Close the inventory (clicks are refused while a panel is open).
    for _ in range(6):
        if not _inventory_open(run):
            break
        try:
            gated.press_key(VK_I)
        except InputRefused:
            pass
        run.sleep(0.2)
    fresh = [uid for uid in _floor(run) if uid not in before]
    print(f"  dropped {dropped} item(s); {len(fresh)} new on the floor",
          flush=True)
    return fresh


def _measure(run, gated, codes, staged: list[int], labels: bool) -> list[dict]:
    """Click-schedule every staged item still on the floor, in the current
    (verified `labels`) state."""
    rows = []
    for gid in list(staged):
        run.check_cancel()
        floor = _floor(run)
        if gid not in floor:
            continue
        kind, pos = floor[gid]
        here = label_display_on(run.session)
        others = [p for u, (_, p) in floor.items() if u != gid]
        crowd = crowding(pos, others)
        item_class = classify(kind, codes)
        print(f"  target {gid} kind {kind} ({item_class}) crowd {crowd} "
              f"labels={here}", flush=True)
        winner, trail = _click_schedule(run, gated, gid, pos)
        rows.append({
            "labels": bool(here) if here is not None else labels,
            "unit_id": gid, "kind": kind, "item_class": item_class,
            "crowding": crowd, "picked": winner is not None,
            "winning_offset": list(winner) if winner else None,
            "clicks": len(trail),
        })
    return rows


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T79",
        title="label-state experiment — automated, within-subjects",
        kind="bot control",
        sends_input=True,
        instructions=(
            "AUTOMATED: I drop a pile from your inventory (NEVER the two",
            "tomes or the Horadric Cube, and never potions), then measure",
            "the SAME pile with labels ON and again with labels OFF — one",
            "variable, same items. The labels-OFF pass also recovers the",
            "pile; anything still on the floor at the end I call out.",
            "Stand somewhere safe and clear (town). Type OK to begin.",
            "Abort: 'abort', drill-cancel, ESC, or take the mouse.",
        ),
    )

    def body(run: DrillRun) -> str:
        gated = GatedInput(run.session)
        codes = {
            kind: code
            for code, kinds in load_item_codes(
                REPO / "config" / "item_codes.toml"
            ).items()
            for kind in kinds
        }
        town = _build_town(run, gated)

        print("\n--- staging a pile from inventory ---", flush=True)
        staged = _stage_pile(run, gated, town)
        if len(staged) < MIN_PILE_CROWD + 1:
            raise RuntimeError(
                f"staged only {len(staged)} item(s) — need > {MIN_PILE_CROWD} "
                "for a pile; inventory may be short of droppable items"
            )

        results: list[dict] = []
        for target in (True, False):
            name = "ON" if target else "OFF"
            achieved = _set_labels(run, gated, target)
            if achieved != target:
                run.say(f"labels {name}: could not set (got {achieved}) — "
                        "measuring skipped for this state")
                continue
            print(f"\n--- labels {name} (verified) ---", flush=True)
            results += _measure(run, gated, codes, staged, target)

        # Recovery: whatever is still down, sweep it with labels OFF (which
        # the experiment expects to work) so nothing valuable is abandoned.
        _set_labels(run, gated, False)
        left = [uid for uid in staged if uid in _floor(run)]
        for _ in range(2):
            if not left:
                break
            print(f"\n--- recovery pass: {len(left)} item(s) still down ---",
                  flush=True)
            _measure(run, gated, codes, left, False)
            left = [uid for uid in staged if uid in _floor(run)]

        print("\n=== LABEL-STATE VERDICT ===", flush=True)
        for line in verdict(results):
            print(line, flush=True)
        if left:
            floor = _floor(run)
            leftover = [(u, floor[u][0], floor[u][1]) for u in left if u in floor]
            run.say(f"HEADS UP: {len(left)} test item(s) still on the floor — "
                    "please grab them.")
            print(f"  LEFTOVER (please collect): {leftover}", flush=True)

        ok, why = sufficient(results)
        summary = f"{len(results)} measured; {why}"
        if left:
            summary += f"; {len(left)} left on floor (reported)"
        if not ok:
            raise RuntimeError(summary)
        return summary

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
