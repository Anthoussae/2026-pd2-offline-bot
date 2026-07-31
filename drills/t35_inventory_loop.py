"""T35 — the R75 inventory-management loop, end to end (bot control).

The loop the user designed and this drill exercises:

    potions to belt (stash CLOSED - shift-click means "to belt" there)
    -> drink excess healing/mana out of the inventory
    -> open the stash, ensure the MATERIALS tab
    -> attempt EVERY movable item; keep whatever the tab accepts
    -> switch to REGULAR
    -> attempt the rest; anything still there is a fault
    -> close

The idea worth protecting is that **the game does the classification**.
Attempting everything into materials and keeping what it takes means the bot
needs no item taxonomy — the kind of knowledge that goes stale every patch.
Potions are the single category it must recognise, and it already does.

**Coverage is reported, not assumed**, for the same reason as T27: nearly
every phase is conditional, and a green run over an empty inventory proves
almost nothing while looking like proof of everything. So this reads the
world before and after and says what each phase actually did.

Setup for a run that exercises the lot:

    belt + drink   spare potions in the usable grid, belt below minimums
    materials      at least one item the tab will take (a rejuvenation is
                   the reliable one - rejuvs are materials, R75)
    regular        at least one ordinary item it will not take
    tab reading    the REGULAR stash must hold something. With it empty the
                   stash lists nothing on either tab, the tab is genuinely
                   unreadable, and the loop refuses by design rather than
                   guessing - which is a correct outcome but not a useful test

Everything must sit in the USABLE grid, rows 0-3. Charm space (y>=4) shares
the same container and is deliberately untouchable (R60); this drill hard
fails if the charm count moves at all.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t35_inventory_loop
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402
from pd2bot.town import PreambleReport, TownConfig, TownLayer  # noqa: E402

T35 = Drill(
    test_id="T35",
    title="Inventory-management loop: belt, drink, materials, regular",
    kind="bot control",
    instructions=(
        "SETUP: in town, all panels closed, hands off throughout.",
        "Items to deposit must be in the USABLE grid (top 4 rows), not "
        "charm space.",
        "The bot fills the belt, drinks leftovers, then deposits into "
        "materials and regular in turn.",
        "It reports what each phase actually did - a phase with nothing to "
        "do proves nothing.",
    ),
    sends_input=True,
)


@dataclass
class WorldState:
    main: int
    charms: int
    potions: int
    belt_healing: int
    belt_mana: int
    belt_rejuv: int
    stash_visible: int

    def line(self) -> str:
        return (
            f"inventory {self.main} usable (+{self.charms} charms, "
            f"{self.potions} potions); belt h{self.belt_healing}/"
            f"m{self.belt_mana}/r{self.belt_rejuv}; "
            f"stash lists {self.stash_visible}"
        )


def read_world(run: DrillRun) -> WorldState:
    carried = read_carried_items(run.session)
    return WorldState(
        main=len(carried.main_inventory),
        charms=len(carried.charm_inventory),
        potions=sum(1 for i in carried.main_inventory if i.potion_name is not None),
        belt_healing=sum(1 for i in carried.belt if i.is_healing_potion),
        belt_mana=sum(1 for i in carried.belt if i.is_mana_potion),
        belt_rejuv=carried.belt_rejuv_count,
        stash_visible=len(carried.stash),
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


def coverage(before: WorldState, after: WorldState, report: PreambleReport) -> list[str]:
    """What each phase did, judged from the world and the report together."""
    lines = []
    lines.append(
        f"belt    {'EXERCISED' if report.refilled else 'SKIPPED'} - "
        f"{report.refilled} moved; h{before.belt_healing}/m{before.belt_mana}"
        f" -> h{after.belt_healing}/m{after.belt_mana}"
    )
    drank = [line for line in report.log if line.startswith("drink:")]
    lines.append(
        f"drink   {'EXERCISED' if drank else 'SKIPPED'} - "
        + (drank[0] if drank else "no excess healing/mana left over")
    )
    for phase in ("materials", "regular"):
        moved = [line for line in report.log if f"into {phase}" in line]
        got = moved[0].split()[1] if moved else "0"
        lines.append(
            f"{phase:8}{'EXERCISED' if got != '0' else 'NO-OP'} - "
            f"{got} deposited"
        )
    lines.append(
        f"totals  inventory {before.main} -> {after.main}; "
        f"deposited {report.deposited}; charms {before.charms} -> "
        f"{after.charms} (must not move)"
    )
    return lines


def t35_body(run: DrillRun) -> str:
    area = Perception(run.session).snapshot().area
    if area is None or area.level_no != offsets.AREA_ROGUE_ENCAMPMENT:
        raise DrillAborted(
            f"start in town: this reads area {area.level_no if area else '?'}"
        )

    before = read_world(run)
    print(f"BEFORE: {before.line()}", flush=True)
    if before.main == 0:
        raise DrillAborted(
            "the usable inventory is empty — there is nothing for the loop "
            "to do, and a green run would prove nothing. Put some items in "
            "the top four rows and re-run"
        )

    town = build_town(run)
    report = PreambleReport()
    town.manage_inventory(report)

    after = read_world(run)
    print(f"AFTER:  {after.line()}", flush=True)
    lines = coverage(before, after, report)
    print("\n--- phase coverage ---", flush=True)
    for line in lines:
        print(f"  {line}", flush=True)

    if after.charms != before.charms:
        raise DrillAborted(
            f"CHARM SPACE CHANGED: {before.charms} -> {after.charms}. The "
            "usable-grid guard (R60) failed and the bot moved charms."
        )
    exercised = sum(1 for line in lines if "EXERCISED" in line)
    print(f"\n{exercised} of 4 phases did real work", flush=True)
    return (
        f"{exercised}/4 phases exercised; "
        + "; ".join(" ".join(line.split()) for line in lines)
        + f"; report: {'; '.join(report.log)}"
    )


SUITE = {"T35": (T35, t35_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T35"], run=shared)
    print(f"\nsuite: T35 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
