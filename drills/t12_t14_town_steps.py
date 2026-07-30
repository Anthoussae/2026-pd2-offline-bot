"""T12-T14 — the town preamble steps, driven by the bot for the first time.

Three drills in one run so the user sets up once and stays in the game:

    T12  heal at Akara      walk, click, ESC out, verify vitals full
    T13  stash deposit      walk, open stash, shift+right-click each
                            planted item, verify each left the grid
    T14  belt refill        open inventory, shift-click potions into the
                            belt, verify counts, check minimums

Every step is the real `pd2bot.town.TownLayer` wired to the real gates and
the live navigator — nothing here reimplements behaviour, so a PASS is
evidence about the shipping code, not about the drill.

Each body checks its own setup first and aborts with a plain sentence if
the world is not in the state the drill needs; a confusing failure three
steps later helps nobody. InputRefused gets a bounded retry, since a
momentary alt-tab should cost a pause rather than the run.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t12_t14_town_steps
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput, InputRefused  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import PreambleReport, TownConfig, TownLayer  # noqa: E402


def build_town(run: DrillRun) -> TownLayer:
    """The shipping TownLayer, wired to the live game."""
    session = run.session
    gated = GatedInput(session, ui_array=run.ui_array)
    navigator = live_navigator(session, MapStore(), offsets.DIFFICULTY_HELL)
    perception = Perception(session)
    return TownLayer(
        session=session,
        gated=gated,
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=navigator.walk_to,
        snapshot=perception.snapshot,
        config=TownConfig(),
        # A stop request must reach the retry ladders inside the town
        # layer, not just the harness's own waits (R80).
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def with_focus_retries(run: DrillRun, action, attempts: int = 3):
    """Run `action`, pausing for the human if the gate refuses for focus."""
    for attempt in range(attempts):
        try:
            return action()
        except InputRefused as exc:
            if attempt == attempts - 1:
                raise
            run.say(f"Input refused ({exc}) - bring PD2 to the front; retrying in 10s.")
            time.sleep(10)
    return None


# ---------------------------------------------------------------- T12: heal

T12 = Drill(
    test_id="T12",
    title="Heal at Akara",
    kind="bot control",
    instructions=(
        "SETUP: spend some mana or life first (cast Bone Armor a few times) so "
        "the heal has something to prove, and stand anywhere in town.",
        "The bot will walk to Akara, click her, close the dialog, and verify "
        "your vitals read FULL from memory.",
    ),
    sends_input=True,
)


def t12_body(run: DrillRun) -> str:
    town = build_town(run)
    player = town._read_player(run.session)
    if player is None:
        raise DrillAborted("player unreadable - are you in a game?")
    if player.hp == player.max_hp and player.mana == player.max_mana:
        raise DrillAborted(
            "already at full hp AND mana - nothing for the heal to prove; "
            "spend some mana and re-run"
        )
    before = f"{player.hp}/{player.max_hp} hp, {player.mana}/{player.max_mana} mana"
    run.say(f"Starting at {before}. Walking to Akara.")

    report = PreambleReport()
    with_focus_retries(run, lambda: town.heal_at_akara(report))

    after = town._read_player(run.session)
    return (
        f"{before} -> {after.hp}/{after.max_hp} hp, {after.mana}/{after.max_mana} mana; "
        f"{'; '.join(report.log)}"
    )


# -------------------------------------------------------- T13: stash deposit

T13 = Drill(
    test_id="T13",
    title="Stash deposit with verification",
    kind="bot control",
    instructions=(
        "SETUP: put 2-3 JUNK non-potion items into the usable inventory grid "
        "(the top 4 rows) - things you do not mind being stashed.",
        "Keep any potions you want for the next test in the grid too; the bot "
        "deposits non-potions only.",
        "The bot will walk to the stash, open it, and shift+right-click each "
        "junk item across, verifying each one leaves the grid.",
    ),
    sends_input=True,
)


def t13_body(run: DrillRun) -> str:
    town = build_town(run)
    carried = read_carried_items(run.session)
    junk = [i for i in carried.main_inventory if i.potion_name is None]
    if not junk:
        raise DrillAborted(
            "no non-potion items in the usable grid - nothing to deposit; "
            "plant 2-3 junk items and re-run"
        )
    run.say(f"Found {len(junk)} junk item(s) to deposit. Walking to the stash.")

    report = PreambleReport()
    with_focus_retries(
        run, lambda: town.deposit_to_stash(lambda i: i.potion_name is None, report)
    )

    after = read_carried_items(run.session)
    left = [i for i in after.main_inventory if i.potion_name is None]
    charm_untouched = len(after.charm_inventory)
    return (
        f"deposited {report.deposited} of {len(junk)}; {len(left)} junk left in grid; "
        f"charm space untouched at {charm_untouched} items; {'; '.join(report.log)}"
    )


# ---------------------------------------------------------- T14: belt refill

T14 = Drill(
    test_id="T14",
    title="Belt refill from inventory",
    kind="bot control",
    instructions=(
        "SETUP: make sure the belt is SHORT of its minimums (drink or remove a "
        "few) and put several potions into the usable inventory grid.",
        "The bot will open the inventory and shift-click potions into the belt "
        "until the minimums hold, verifying the belt count after each one.",
        "If the inventory runs dry first, the bot halts loudly - that is the "
        "manual-restock path working, not a failure.",
    ),
    sends_input=True,
)


def t14_body(run: DrillRun) -> str:
    town = build_town(run)
    before = read_carried_items(run.session)
    pool = [i for i in before.main_inventory if i.potion_name is not None]
    shortfall = town._belt_shortfall()
    if not any(shortfall.values()):
        raise DrillAborted(
            f"belt already at minimums ({dict(shortfall)}) - nothing to refill; "
            "remove a couple of potions and re-run"
        )
    if not pool:
        raise DrillAborted(
            "no potions in the usable inventory grid to refill from; "
            "move some out of the stash and re-run"
        )
    run.say(
        f"Belt short {dict(shortfall)}, {len(pool)} potion(s) available. Refilling."
    )

    report = PreambleReport()
    with_focus_retries(run, lambda: town.refill_belt(report))

    after = read_carried_items(run.session)
    counts = {c: after.belt_count(c) for c in range(offsets.BELT_COLUMNS)}
    return (
        f"moved {report.refilled}; belt columns now {counts}; "
        f"rejuvs {after.belt_rejuv_count}; {'; '.join(report.log)}"
    )


SUITE = {"T12": (T12, t12_body), "T13": (T13, t13_body), "T14": (T14, t14_body)}

if __name__ == "__main__":
    # Optional id arguments select a subset, so a re-run after a fix does not
    # drag already-passing drills through a pointless ABORTED row.
    wanted = [a.upper() for a in sys.argv[1:]] or list(SUITE)
    unknown = [w for w in wanted if w not in SUITE]
    if unknown:
        raise SystemExit(f"unknown drill(s): {', '.join(unknown)}; have {list(SUITE)}")

    session = GameSession()
    shared = DrillRun(session)  # one run: only the first header waits for the user
    statuses = [run_drill(*SUITE[name], run=shared) for name in wanted]
    summary = ", ".join(f"{n} {s}" for n, s in zip(wanted, statuses, strict=True))
    print(f"\nsuite: {summary}")
    raise SystemExit(0 if all(s == "PASS" for s in statuses) else 1)
