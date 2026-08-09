"""T27 — the whole town routine, end to end (bot control).

Asked for at the P3 review gate (user, 2026-07-30): before advancing, prove
the town chores work together and are bot-ready, not just individually.

The individual town steps have each been drilled, but never together and
never through the production orchestrator. This runs `TownLayer.run_preamble`
itself — heal -> repair -> inventory loop -> merc, the real order (R46 Q5 +
R70) — so what passes here is the code the game cycle will call, not a
drill's re-creation of it.

**Coverage is reported, not assumed.** Every step in the preamble is
conditional: a healthy character skips the heal, pristine gear skips the
repair, an empty inventory skips the deposit, a full belt skips the refill,
a live merc skips the resurrect. A green run where four of five steps
no-opped proves almost nothing, and would be easy to mistake for proof of
everything. So this captures the world before and after, decides per step
whether it did real work, and says so plainly — an EXERCISED count is the
actual result of this drill, and PASS on its own is not.

Setup, if you want full coverage (each independently optional):

    heal     be missing some hp or mana
    repair   have some durability missing
    stash    misc items in the USABLE grid, rows 0-3 — NOT the charm rows
             (y>=4), which share the container and are deliberately
             untouchable (R60)
    belt     spare potions, with room in a belt column
    merc     merc dead, and kashya.resurrect calibrated in that same
             dead-merc window (T25 kashya) — otherwise this step halts

The middle of the preamble is R75's inventory-management loop
(`manage_inventory`, drilled on its own as T35): belt, drink, cleanse,
stash. It takes no keep-predicate, because the GAME classifies the items —
everything is offered to the stash and routed by the game itself.

Since R134 that is ONE deposit pass, not the old materials-then-regular
pair: T45 established that a material self-routes from the regular tab, so
nothing needs to identify or switch tabs. A blind toggle and one retry
happen only if something refuses.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t27_full_preamble
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.nav.mapstore import MapStore  # noqa: E402
from pd2bot.nav.navigate import live_navigator  # noqa: E402
from pd2bot.perception.items import read_carried_items, read_equipped_durability  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import PreambleReport, TownConfig, TownLayer  # noqa: E402

# Which points the preamble may need. The merc row is listed separately
# because it is only REQUIRED when the merc is actually dead.
ALWAYS_NEEDED = ("charsi.trade_repair", "charsi.repair_all")
MERC_POINT = "kashya.resurrect"

T27 = Drill(
    test_id="T27",
    title="Full town preamble, end to end",
    kind="bot control",
    instructions=(
        "SETUP: stand in town, all panels closed, then hands off throughout.",
        "The bot runs the WHOLE routine: heal, repair, inventory loop, merc.",
        "It reports which steps did real work - a step with nothing to do "
        "proves nothing, and will be listed as skipped.",
        "Cancel with drill-cancel if anything looks wrong.",
    ),
    sends_input=True,
)


@dataclass
class WorldState:
    """Everything the preamble could change, read in one go."""

    hp: int
    max_hp: int
    mana: int
    max_mana: int
    durability_missing: int
    worn_items: int
    main_items: int
    charm_items: int
    belt_healing: int
    belt_mana: int
    belt_rejuv: int
    inventory_potions: int
    merc_alive: bool
    gold: int

    def line(self) -> str:
        return (
            f"hp {self.hp}/{self.max_hp}, mana {self.mana}/{self.max_mana}; "
            f"durability {self.durability_missing} missing over "
            f"{self.worn_items} worn; inventory {self.main_items} usable "
            f"(+{self.charm_items} charms, {self.inventory_potions} potions); "
            f"belt h{self.belt_healing}/m{self.belt_mana}/r{self.belt_rejuv}; "
            f"merc {'alive' if self.merc_alive else 'DEAD'}; gold {self.gold}"
        )


def read_world(run: DrillRun) -> WorldState:
    player = read_player(run.session)
    if player is None:
        raise DrillAborted("player unreadable")
    carried = read_carried_items(run.session)
    worn = read_equipped_durability(run.session)
    return WorldState(
        hp=player.hp,
        max_hp=player.max_hp,
        mana=player.mana,
        max_mana=player.max_mana,
        durability_missing=sum(d.missing for d in worn),
        worn_items=sum(1 for d in worn if d.missing),
        main_items=len(carried.main_inventory),
        charm_items=len(carried.charm_inventory),
        belt_healing=sum(1 for i in carried.belt if i.is_healing_potion),
        belt_mana=sum(1 for i in carried.belt if i.is_mana_potion),
        belt_rejuv=carried.belt_rejuv_count,
        inventory_potions=sum(
            1 for i in carried.main_inventory if i.potion_name is not None
        ),
        merc_alive=Perception(run.session).snapshot().merc is not None,
        gold=player.gold + player.gold_stash,
    )


def coverage(before: WorldState, after: WorldState, report: PreambleReport) -> list[str]:
    """Per step: did it do real work, or was there nothing to do?

    Judged from the world rather than from the report's own log, because a
    step that believes it succeeded is exactly the thing under test.
    """
    lines = []
    if before.hp == before.max_hp and before.mana == before.max_mana:
        lines.append("heal    SKIPPED - already at full vitals")
    else:
        healed = after.hp == after.max_hp and after.mana == after.max_mana
        lines.append(
            f"heal    {'EXERCISED' if healed else 'FAILED'} - "
            f"{before.hp}/{before.max_hp} hp, {before.mana}/{before.max_mana} "
            f"mana -> {after.hp}/{after.max_hp}, {after.mana}/{after.max_mana}"
        )
    if before.durability_missing == 0:
        lines.append("repair  SKIPPED - gear was pristine")
    else:
        fixed = after.durability_missing == 0
        lines.append(
            f"repair  {'EXERCISED' if fixed else 'FAILED'} - "
            f"{before.durability_missing} missing -> {after.durability_missing}"
        )
    # The middle is R75's loop now, not a deposit/refill pair, so its four
    # phases are reported separately — a battery that lumps them together
    # cannot tell you which of them actually ran.
    lines.append(
        f"belt    {'EXERCISED' if report.refilled else 'SKIPPED'} - "
        f"{report.refilled} moved; h{before.belt_healing}/m{before.belt_mana}"
        f"/r{before.belt_rejuv} -> h{after.belt_healing}/m{after.belt_mana}"
        f"/r{after.belt_rejuv}"
    )
    drank = [line for line in report.log if line.startswith("drink:")]
    lines.append(
        f"drink   {'EXERCISED' if drank else 'SKIPPED'} - "
        + (drank[0] if drank else "no excess healing/mana left over")
    )
    # One deposit pass, not two (R134): the materials/regular split went
    # with the tab inference. The first live run after that change still
    # reported "materials NO-OP / regular NO-OP" while 11 items had just
    # been deposited — a coverage line that reads the wrong log key is a
    # coverage line that lies, and this one lied in the safe-looking
    # direction.
    deposited = [line for line in report.log if "deposited on the" in line]
    got = deposited[0].split()[1] if deposited else "0"
    lines.append(
        f"stash   {'EXERCISED' if got != '0' else 'NO-OP'} - {got} deposited"
    )
    retried = [line for line in report.log if "after switching tab" in line]
    if retried:
        lines.append(f"tab     TOGGLED - {retried[0]}")
    gold_lines = [line for line in report.log if line.startswith("gold:")]
    banked = gold_lines and "none carried" not in gold_lines[0]
    lines.append(
        f"gold    {'EXERCISED' if banked else 'SKIPPED'} - "
        + (gold_lines[0] if gold_lines else "not reached")
    )
    lines.append(
        f"charms  {before.charm_items} -> {after.charm_items} (must not move); "
        f"inventory {before.main_items} -> {after.main_items}"
    )
    if before.merc_alive:
        lines.append("merc    SKIPPED - merc was alive")
    else:
        lines.append(
            f"merc    {'EXERCISED' if after.merc_alive else 'FAILED'} - "
            f"action={report.merc_action}; gold {before.gold} -> {after.gold} "
            f"(spent {before.gold - after.gold})"
        )
    return lines


def build_town(run: DrillRun, config: TownConfig) -> TownLayer:
    session = run.session
    navigator = live_navigator(session, MapStore(), offsets.DIFFICULTY_HELL)
    return TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=navigator.walk_to,
        snapshot=Perception(session).snapshot,
        config=config,
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def t27_body(run: DrillRun) -> str:
    config = TownConfig()
    area = Perception(run.session).snapshot().area
    if area is None or area.level_no != offsets.AREA_ROGUE_ENCAMPMENT:
        raise DrillAborted(
            f"start in town: this reads area "
            f"{area.level_no if area else 'unreadable'}"
        )

    before = read_world(run)
    print(f"BEFORE: {before.line()}", flush=True)

    # Refuse up front for anything the run will actually need — walking a
    # whole preamble to halt at the last step teaches nothing new.
    needed = list(ALWAYS_NEEDED) + ([] if before.merc_alive else [MERC_POINT])
    missing = [n for n in needed if not config.ui_points[n].calibrated]
    if missing:
        raise DrillAborted(
            f"uncalibrated points this run needs: {', '.join(missing)}. "
            + (
                "The merc is dead, so the resurrect row is required — "
                "calibrate it NOW with `t25_ui_points kashya`, in this same "
                "dead-merc window (R56)."
                if MERC_POINT in missing
                else "Run the matching T25 battery first."
            )
        )

    town = build_town(run, config)
    report = PreambleReport()
    # The production entry point, deliberately: order, conditionals and
    # error handling are all under test here, not just the steps.
    town.run_preamble(report=report)

    after = read_world(run)
    print(f"AFTER:  {after.line()}", flush=True)
    lines = coverage(before, after, report)
    print("\n--- step coverage ---", flush=True)
    for line in lines:
        print(f"  {line}", flush=True)

    exercised = sum(1 for line in lines if "EXERCISED" in line)
    skipped = sum(1 for line in lines if "SKIPPED" in line)
    phases = exercised + skipped + sum(1 for line in lines if "NO-OP" in line)
    print(f"\n{exercised} exercised, {skipped} skipped of {phases} phases",
          flush=True)
    if after.charm_items != before.charm_items:
        raise DrillAborted(
            f"CHARM SPACE CHANGED: {before.charm_items} -> {after.charm_items}. "
            "The usable-grid guard (R60) failed and the bot moved charms."
        )
    return (
        f"{exercised} exercised / {skipped} skipped; "
        + "; ".join(line.replace("  ", " ") for line in lines)
        + f"; report: {'; '.join(report.log)}"
    )


SUITE = {"T27": (T27, t27_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T27"], run=shared)
    print(f"\nsuite: T27 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
