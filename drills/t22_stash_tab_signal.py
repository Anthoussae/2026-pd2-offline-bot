"""T22 — find a reliable signal for WHICH stash tab is showing.

T15 established that the ordinary stash reads empty while the materials tab
is up, which is a signal but not a usable one: an empty stash reads exactly
the same. Depositing into the wrong tab is not a cosmetic error — materials
would fill the small regular stash — so the loop needs to KNOW (user
decision, R75 Q5).

T15 also ruled out the obvious candidate: the raw UI-panel array did not
move across four toggles. So this probe reads deeper, and reads everything
plausible at once rather than guessing again:

  * the INVENTORY STORE ARRAY (Inventory.pStores / dwStoresCount) — each
    store is a grid with its own width, height and item chain, so a tab
    that is a different grid should show up here
  * the stash items themselves, with their storage bytes
  * the raw UI array again, as a control

The user toggles; whatever moves in lockstep is the answer. If nothing
does, that is worth knowing too — it means tab state is not readable and
the loop must be built to be correct without it.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t22_stash_tab_signal
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets, uistate  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.units import player_unit  # noqa: E402

MAX_STORES = 16  # a sanity bound; D2 has a handful


def read_stores(session) -> tuple:
    """Every InventoryStore the player's Inventory lists."""
    player = player_unit(session)
    if player is None:
        return ()
    inventory = session.ptr(player + offsets.UNIT_INVENTORY)
    if inventory is None:
        return ()
    try:
        array = session.ptr(inventory + offsets.INVENTORY_STORES)
        count = session.u32(inventory + offsets.INVENTORY_STORES_COUNT)
    except Exception:
        return ()
    if array is None or not 0 < count <= MAX_STORES:
        return ()
    stores = []
    for index in range(count):
        base = array + index * offsets.STORE_SIZE
        try:
            stores.append(
                (
                    index,
                    session.u8(base + offsets.STORE_WIDTH),
                    session.u8(base + offsets.STORE_HEIGHT),
                    session.u32(base + offsets.STORE_FIRST_ITEM),
                    session.u32(base + offsets.STORE_GRID),
                )
            )
        except Exception:
            stores.append((index, None, None, None, None))
    return tuple(stores)


def signature(run: DrillRun) -> dict:
    carried = read_carried_items(run.session)
    return {
        "ui": uistate.read_ui_raw(run.session, run.ui_array),
        "stores": read_stores(run.session),
        "stash_ids": frozenset(i.unit_id for i in carried.stash),
        "stash_bytes": frozenset(
            (i.game_location, i.node_page) for i in carried.stash
        ),
        "all_locations": frozenset(
            (i.game_location, i.node_page) for i in carried.items
        ),
    }


def diff(before: dict, after: dict) -> list[str]:
    notes = []
    if before["ui"] != after["ui"]:
        moved = [
            f"slot {i:#04x} {a}->{b}"
            for i, (a, b) in enumerate(zip(before["ui"], after["ui"], strict=True))
            if a != b
        ]
        notes.append("UI ARRAY: " + ", ".join(moved))
    if before["stores"] != after["stores"]:
        for old, new in zip(before["stores"], after["stores"], strict=False):
            if old != new:
                notes.append(
                    f"STORE {old[0]}: {old[1]}x{old[2]} first=0x{(old[3] or 0):08X} "
                    f"grid=0x{(old[4] or 0):08X}  ->  {new[1]}x{new[2]} "
                    f"first=0x{(new[3] or 0):08X} grid=0x{(new[4] or 0):08X}"
                )
        if len(before["stores"]) != len(after["stores"]):
            notes.append(
                f"STORE COUNT: {len(before['stores'])} -> {len(after['stores'])}"
            )
    if before["stash_ids"] != after["stash_ids"]:
        notes.append(
            f"stash items: {len(before['stash_ids'])} -> {len(after['stash_ids'])}"
        )
    if before["all_locations"] != after["all_locations"]:
        notes.append(
            f"location bytes anywhere: {sorted(before['all_locations'])} -> "
            f"{sorted(after['all_locations'])}"
        )
    return notes


T22 = Drill(
    test_id="T22",
    title="Find a reliable stash-tab signal",
    kind="perception",
    instructions=(
        "Open the STASH and leave it open.",
        "IMPORTANT setup: first put at least one item INTO the materials tab "
        "(a rejuv works) so the tab is not empty - an empty tab is what made "
        "the last attempt ambiguous.",
        "Then toggle materials <-> regular three times, ~2s on each tab.",
    ),
)


def t22_body(run: DrillRun) -> str:
    if not run.announce_until(
        "Open the STASH, put an item in the MATERIALS tab, then toggle tabs.",
        lambda: run.panel_open(offsets.UI_STASH),
        timeout_s=240,
    ):
        raise DrillAborted("the stash never opened")

    baseline = signature(run)
    print(f"stores at start ({len(baseline['stores'])}):", flush=True)
    for index, width, height, first, grid in baseline["stores"]:
        print(
            f"  store {index}: {width}x{height}  first=0x{(first or 0):08X}  "
            f"grid=0x{(grid or 0):08X}",
            flush=True,
        )
    print(f"stash items: {len(baseline['stash_ids'])}", flush=True)
    print(f"location bytes anywhere: {sorted(baseline['all_locations'])}", flush=True)

    run.say("Recorded. Now toggle materials <-> regular, ~2s each, three times.")
    transitions = []
    current = baseline
    deadline = time.time() + 150
    while time.time() < deadline and len(transitions) < 6:
        if not run.panel_open(offsets.UI_STASH):
            time.sleep(0.2)
            continue
        now = signature(run)
        notes = diff(current, now)
        if notes:
            transitions.append(notes)
            print(f"\ntransition {len(transitions)}:", flush=True)
            for note in notes:
                print(f"    {note}", flush=True)
            current = now
        time.sleep(0.15)

    if not transitions:
        raise DrillAborted("nothing changed at all — was the tab actually toggled?")

    channels = {
        "UI array": sum(1 for t in transitions if any(n.startswith("UI ARRAY") for n in t)),
        "store array": sum(1 for t in transitions if any(n.startswith("STORE") for n in t)),
        "stash items": sum(1 for t in transitions if any(n.startswith("stash items") for n in t)),
        "location bytes": sum(
            1 for t in transitions if any(n.startswith("location bytes") for n in t)
        ),
    }
    print("\n== which channels moved, and how often ==", flush=True)
    for name, count in channels.items():
        verdict = "EVERY toggle" if count == len(transitions) else f"{count}/{len(transitions)}"
        print(f"  {name:16} {verdict}")
    reliable = [n for n, c in channels.items() if c == len(transitions)]
    print(
        f"\nusable as a tab signal: {reliable or 'NOTHING — tab state is not readable'}",
        flush=True,
    )

    run.say("Done - thanks. You can close the stash.")
    return (
        f"{len(transitions)} toggles; channels moving every time: "
        f"{', '.join(reliable) if reliable else 'none'}"
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T22, t22_body, session=GameSession()) == "PASS" else 1)
