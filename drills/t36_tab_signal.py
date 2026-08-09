"""T36 — is there a DIRECT stash-tab signal? (user request, R109)

Today the bot infers the tab instead of reading it:

    stash lists items   -> definitely REGULAR
    stash lists nothing -> materials, OR a regular stash that is empty

so an ambiguous case has to be resolved by toggling and looking. That works,
but it needs a non-empty stash and a click that lands — and a single lost
click already turned a perfectly readable stash into "unreadable" once
(R108). A signal that says which tab is up, read straight from memory,
would remove the toggle, the ambiguity and the click from the question
entirely.

T22 established that the STORE ARRAY moves on every toggle (`Inventory.
pStores`: each store is a grid with its own width, height and item chain).
What it did not record is WHICH field moved, and that is the whole question:
a differently-shaped store, or a different store count, is a direct signal;
an item-chain head going null is just the same content-dependent inference
in another costume.

Read-only: the bot sends nothing. The user toggles; this watches the store
array and reports what differs between the two states.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t36_tab_signal
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import player_unit  # noqa: E402

MAX_STORES = 16
SAMPLE_S = 0.2

T36 = Drill(
    test_id="T36",
    title="Direct stash-tab signal: what moves in the store array?",
    kind="perception",
    instructions=(
        "Read-only: the bot sends nothing and clicks nothing.",
        "1. Open the STASH and leave it open throughout.",
        "2. Toggle between the REGULAR and MATERIALS tabs, 4 times.",
        "3. Pause ~2s on each tab so the reading settles.",
        "4. Close the stash when done.",
    ),
)


def read_stores(session) -> tuple:
    """Every InventoryStore the player's Inventory lists (T22's reader)."""
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
                    bool(session.u32(base + offsets.STORE_FIRST_ITEM)),
                )
            )
        except Exception:
            stores.append((index, None, None, None))
    return tuple(stores)


def signature(run: DrillRun) -> tuple:
    """What we might read the tab from, all at once."""
    stores = read_stores(run.session)
    listed = len(read_carried_items(run.session).stash)
    return (stores, listed)


def describe(sig: tuple) -> str:
    stores, listed = sig
    rows = [
        f"      store {i}: {w}x{h} items={'yes' if first else 'no'}"
        for i, w, h, first in stores
    ]
    return f"    stash lists {listed}; {len(stores)} stores\n" + "\n".join(rows)


def t36_body(run: DrillRun) -> str:
    if not run.wait_until(
        lambda: run.panel_open(offsets.UI_STASH), timeout_s=300
    ):
        raise DrillAborted("the stash never opened")
    run.sleep(1.0)

    seen: list[tuple] = []
    last = None
    print("watching the store array — toggle the tabs now", flush=True)
    deadline = run.clock() + 240
    while run.clock() < deadline and run.panel_open(offsets.UI_STASH):
        run.check_cancel()
        sig = signature(run)
        if sig != last:
            last = sig
            if sig not in seen:
                seen.append(sig)
                print(f"\n  state {len(seen)}:\n{describe(sig)}", flush=True)
        run.sleep(SAMPLE_S)
        if len(seen) >= 6:
            break

    if len(seen) < 2:
        raise DrillAborted(
            f"only {len(seen)} distinct state(s) seen — the tabs were not "
            "toggled, or nothing observable changes between them"
        )

    # Which channels actually separate the states, ignoring item counts:
    # a shape change is a DIRECT signal, an item-chain flag is the same
    # content-dependent inference we already have.
    shapes = {tuple((i, w, h) for i, w, h, _ in stores) for stores, _ in seen}
    chains = {tuple(first for _, _, _, first in stores) for stores, _ in seen}
    counts = {len(stores) for stores, _ in seen}
    listings = {listed for _, listed in seen}

    findings = []
    if len(counts) > 1:
        findings.append(f"STORE COUNT differs {sorted(counts)} — direct signal")
    if len(shapes) > 1:
        findings.append("STORE SHAPE (width x height) differs — direct signal")
    if len(chains) > 1:
        findings.append("item-chain heads differ — content-dependent, like today")
    if len(listings) > 1:
        findings.append(f"listed count differs {sorted(listings)} — what we use now")
    return (
        f"{len(seen)} distinct states; "
        + ("; ".join(findings) if findings else "nothing separated them")
    )


SUITE = {"T36": (T36, t36_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T36"], run=shared)
    print(f"\nsuite: T36 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
