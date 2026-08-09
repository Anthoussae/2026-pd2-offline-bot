"""T45 — does a material self-route to the materials tab? (R134)

The user's observation at the R134 gate: shift+right-click on a MATERIAL
sends it to the materials tab even when the REGULAR tab is displayed. If
that holds, the bot never needs to toggle tabs to deposit, and the tab
inference that killed stage B attempt 1 leaves the deposit path entirely.

**Why this character can answer it cleanly.** The very condition that broke
the preamble is the perfect instrument here: this character's regular stash
(`game_location 7`) holds ZERO items, and everything lives in PD2's expanded
stash (location 8, 350 items). So there is no background noise at all —

    item leaves the inventory AND location 7 stays 0  -> it went elsewhere
                                                          (materials)
    item leaves the inventory AND location 7 becomes 1 -> it went to regular

Two clicks, one of each kind, and the routing rule falls out of the counts.
No square-counting, no screenshots, no trusting a tooltip: the effect is the
proof (the standing rule since R86 and T44, where the instrument was wrong
and the game was fine both times).

The drill CANNOT check which tab is displayed — that is the whole problem —
so the human confirms it. That is the one thing a human is strictly better
at here, and it is a glance rather than a task.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t45_materials_autoroute
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.pickit import load_item_table  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

T45 = Drill(
    test_id="T45",
    title="materials self-route from the regular stash tab",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "Stand in town and OPEN THE STASH on the REGULAR tab (not materials).",
        "The drill needs one material (a rune or a gem) and one ordinary item",
        "  (a weapon, armour, a ring — anything that is not a rune/gem/potion)",
        "  loose in the main inventory grid. Move them there if they are not.",
        "The bot will shift+right-click each one ONCE and read where it went.",
        "Both items end up in the stash — that is the point, not a mistake.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)

# Kinds that PD2's materials tab accepts. Deliberately a SMALL, certain list
# rather than a taxonomy: the drill only has to find one item it is sure
# about, and the whole design being tested exists so the bot never needs to
# classify items itself.
MATERIAL_GROUPS = ("runes", "gems_flawless_perfect")


def _counts(run: DrillRun) -> tuple[int, int, set[int]]:
    """(regular-stash count, expanded-stash count, main-inventory ids)."""
    carried = read_carried_items(run.session)
    expanded = sum(1 for i in carried.items if i.game_location == 8)
    return (
        len(carried.stash),
        expanded,
        {i.unit_id for i in carried.main_inventory},
    )


def _town_layer(run: DrillRun) -> TownLayer:
    """A TownLayer built only for its calibrated grid geometry and its panel.

    Deliberately the REAL class rather than a reimplementation of the cell ->
    pixel arithmetic. A drill that computed its own pixel could click a
    different square than the bot does and still report a tidy pass, which
    would prove the wrong thing about the exact code path stage B runs.
    `walk_to` and `snapshot` are never reached from here — no step in this
    drill moves the character.
    """
    panel = PanelInput(run.session, ui_array=run.ui_array)
    return TownLayer(
        session=run.session,
        gated=GatedInput(run.session, ui_array=run.ui_array),
        panel=panel,
        menu=MenuInput(run.session, ui_array=run.ui_array),
        walk_to=lambda target: None,
        snapshot=Perception(run.session).snapshot,
        config=TownConfig(),
        # A predicate, not `run.check_cancel` — that one RAISES, and this
        # hook is documented as returning a bool (t27's form).
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def t45_body(run: DrillRun) -> str:
    if run.player_is_dead():
        raise DrillAborted("the character is dead — this drill sends nothing")

    # The human owns the one fact the bot cannot read.
    if not run.announce_until(
        "T45: open the STASH on the REGULAR tab, with a rune/gem and one "
        "ordinary item loose in your inventory. Waiting...",
        lambda: run.panel_open(offsets.UI_STASH),
        timeout_s=300.0,
    ):
        raise DrillAborted("the stash never opened")

    repo = Path(__file__).resolve().parent.parent
    table = load_item_table(repo / "config" / "item_ids.toml")
    material_kinds: set[int] = set()
    for group in MATERIAL_GROUPS:
        for member in table.groups.get(group, ()):
            material_kinds.update(table.ids.get(member, ()))

    carried = read_carried_items(run.session)
    pool = [i for i in carried.main_inventory if i.is_movable]
    material = next((i for i in pool if i.kind in material_kinds), None)
    ordinary = next(
        (
            i
            for i in pool
            if i.kind not in material_kinds
            and i.kind not in offsets.POTION_KINDS
        ),
        None,
    )
    if material is None:
        raise DrillAborted(
            "no rune or gem loose in the main inventory — put one there and "
            "re-run (the drill will not guess what counts as a material)"
        )
    if ordinary is None:
        raise DrillAborted(
            "no ordinary (non-material, non-potion) item loose in the main "
            "inventory — put one there and re-run"
        )

    town = _town_layer(run)
    lines: list[str] = []

    for label, item in (("material", material), ("ordinary", ordinary)):
        run.check_cancel()
        before_regular, before_expanded, _ = _counts(run)
        pixel = town._grid_pixel(item.position)
        town.panel.click(offsets.UI_STASH, *pixel, button="right", shift=True)

        left = run.wait_until(
            lambda uid=item.unit_id: uid not in _counts(run)[2], timeout_s=5.0
        )
        after_regular, after_expanded, _ = _counts(run)
        if not left:
            lines.append(
                f"{label} (kind {item.kind}): REFUSED — never left the "
                f"inventory (regular {after_regular}, expanded {after_expanded})"
            )
            continue
        if after_regular > before_regular:
            landed = "the REGULAR stash"
        elif after_expanded > before_expanded:
            landed = "the EXPANDED/materials container (location 8)"
        else:
            landed = "somewhere neither counter saw — investigate"
        lines.append(
            f"{label} (kind {item.kind}): left the inventory -> {landed} "
            f"(regular {before_regular}->{after_regular}, "
            f"expanded {before_expanded}->{after_expanded})"
        )

    for line in lines:
        print(f"  {line}", flush=True)
    run.make_chat_possible(may_send_input=True)
    run.say("T45 done — see the terminal for where each item landed.")
    return "; ".join(lines)


if __name__ == "__main__":
    status = run_drill(T45, t45_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
