"""T43 — P6 stage A: prove the ctrl+right-click drop, and audit the whitelist.

The inventory cleanse is the only feature in the bot whose input path has
never been sent to the game. Everything else — every click, every gated
key, every panel gesture — was proven live in P1-P3. Ctrl+right-click has
not, and the failure mode is not "nothing happens": shift and click in the
same frame once resolved as an UNMODIFIED click and CAST a Tome of Identify
instead of stashing it (R113). An unmodified right-click on a potion drinks
it. So this gets proven on one expendable item before it is ever pointed at
a real inventory.

Two halves, in this order on purpose:

**1. The audit (nothing is sent).** For every item currently carried, the
drill prints what the cleanse whitelist WOULD decide. This is the honest
way to meet a whitelist: read its verdicts on your real inventory before
letting it act. Magic charms, tomes and unnamed bases are not on the
R117 keep list, so they read as junk — which is correct for an accidental
pickup and catastrophic for a charm the user has been carrying for weeks.
The audit surfaces that distinction while it is still only a printout.

**2. The isolated drop.** Everything currently carried is added to the
protected baseline, so the cleanse may not touch ANY of it. The user then
adds one expendable item, which is by construction outside the baseline,
and that single item is dropped and verified — gone from the inventory,
present on the ground.

That is the whole of stage A. No combat, no travel, no Cold Plains.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.behavior.town import PreambleReport, TownConfig, TownLayer  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.perception.units import scan_units  # noqa: E402
from pd2bot.pickit import cleanse_keep, load_pickit  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


T43 = Drill(
    test_id="T43",
    title="Ctrl+right-click drop, and a whitelist audit",
    kind="bot control",
    sends_input=True,
    instructions=(
        "P6 STAGE A - town only. No combat, no travel.",
        "First I AUDIT: I print what the cleanse would think of everything "
        "you carry. Nothing is sent for this part.",
        "Then I protect ALL of it - the cleanse may not touch a single "
        "item you are holding right now.",
        "Then you add ONE item you do not mind losing to the inventory, "
        "and I drop that one item to prove the gesture works.",
        "Hands off once I say TEST LIVE, except for adding that item.",
    ),
)


def build_town(run: DrillRun, keep_item, protected_ids) -> TownLayer:
    session = run.session
    return TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        # Stage A never travels; a walk would be a defect, so make it loud.
        walk_to=lambda target: (_ for _ in ()).throw(
            DrillAborted(f"stage A tried to WALK to {target} — it must not")
        ),
        snapshot=Perception(session).snapshot,
        config=TownConfig(),
        keep_item=keep_item,
        protected_ids=protected_ids,
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def t43_body(run: DrillRun) -> str:
    session = run.session
    pickit = load_pickit(REPO / "config" / "pickit.toml")
    keep_item = cleanse_keep(pickit)
    if keep_item is None:
        raise DrillAborted(
            "the cleanse is disabled — the pickit still has pending names, "
            f"so there is nothing to test: {sorted(pickit.pending_names)}"
        )

    # -- half 1: the audit, entirely read-only --------------------------------
    carried = read_carried_items(session)
    would_drop, would_keep = [], []
    for item in carried.main_inventory:
        if not item.is_movable:
            would_keep.append((item, "unmovable (cube/quest)"))
        elif item.potion_name is not None:
            would_keep.append((item, "potion — the town loop's business"))
        elif keep_item(item):
            action, rule = pickit.decide(item, carried, mode="permissive")
            would_keep.append((item, f"whitelist: {rule}"))
        else:
            would_drop.append(item)

    print("== whitelist audit of what you are carrying ==", flush=True)
    for item, why in would_keep:
        print(f"  KEEP  kind {item.kind:5} q{item.quality} at {item.position} — {why}",
              flush=True)
    for item in would_drop:
        print(f"  DROP  kind {item.kind:5} q{item.quality} at {item.position} "
              "— no rule matches", flush=True)
    print(
        f"\nverdict: {len(would_keep)} kept, {len(would_drop)} would be "
        "dropped IF they were not protected.",
        flush=True,
    )
    run.say(
        f"Audit: of {len(carried.main_inventory)} carried items, the "
        f"whitelist would keep {len(would_keep)} and drop {len(would_drop)}."
    )

    # -- the protection baseline ----------------------------------------------
    baseline = {i.unit_id for i in carried.main_inventory}
    run.say(
        f"All {len(baseline)} are now PROTECTED - I cannot drop any of them. "
        "Add ONE item you do not mind losing to your inventory."
    )
    town = build_town(run, keep_item, lambda: baseline)

    def newcomers():
        return [
            i for i in read_carried_items(session).main_inventory
            if i.unit_id not in baseline
        ]

    if not run.wait_until(lambda: bool(newcomers()), timeout_s=300):
        raise DrillAborted("no expendable item was added — nothing to drop")
    target = newcomers()[0]
    print(f"\ntarget: kind {target.kind} q{target.quality} at {target.position}",
          flush=True)

    if keep_item(target):
        _, rule = pickit.decide(target, None, mode="permissive")
        run.say(
            f"Careful - kind {target.kind} is on the KEEP list ({rule}). I "
            "will still drop it because you nominated it, but be aware."
        )

    # -- half 2: the drop, through the production path -------------------------
    ground_before = {
        g.unit_id for g in scan_units(session).ground_items
    }
    run.say(f"Dropping kind {target.kind} now.")
    town.close_panels()
    town.press_inventory_open()
    dropped = town.drop_item(target)
    town.close_panels()

    if not dropped:
        raise DrillAborted(
            f"the drop gesture had NO effect on kind {target.kind} — "
            "ctrl+right-click did not move it; do not enable the cleanse"
        )

    # Verified twice: gone from the inventory AND lying on the floor. Gone
    # from the inventory alone would also be true if the click had USED the
    # item, which is precisely the R113 hazard this drill exists to rule out.
    still_held = any(
        i.unit_id == target.unit_id
        for i in read_carried_items(session).main_inventory
    )
    # POLLED, not read once. Reading the ground a single time immediately
    # after the drop is what made run 1 of this drill report a false
    # negative: the item had landed, but had not yet entered the unit
    # table, and the drill accused the modifier of a fault that was its
    # own (T44, and the antidote later found lying where it fell).
    def landed() -> bool:
        return any(
            g.kind == target.kind and g.unit_id not in ground_before
            for g in scan_units(session).ground_items
        )

    run.wait_until(landed, timeout_s=4.0)
    on_ground = [
        g for g in scan_units(session).ground_items
        if g.unit_id not in ground_before
    ]
    matching = [g for g in on_ground if g.kind == target.kind]
    print(f"still held: {still_held}; new ground items: "
          f"{[(g.unit_id, g.kind) for g in on_ground]}", flush=True)

    if still_held:
        raise DrillAborted("the item is still in the inventory after a 'successful' drop")
    if not matching:
        raise DrillAborted(
            f"kind {target.kind} left the inventory but did NOT appear on the "
            "ground — the click may have USED the item rather than dropping "
            "it (the R113 unmodified-click hazard). Do not enable the cleanse."
        )

    # And prove the protection held: nothing else moved.
    after = {i.unit_id for i in read_carried_items(session).main_inventory}
    lost = baseline - after
    if lost:
        raise DrillAborted(
            f"PROTECTED items left the inventory: {sorted(lost)} — the "
            "baseline guard did not hold"
        )

    run.say(f"Dropped and verified on the ground. You can pick kind {target.kind} back up.")
    report = PreambleReport()
    report.log.append("T43: drop verified")
    return (
        f"ctrl+right-click DROP verified by effect: kind {target.kind} left "
        f"the inventory and appeared on the ground; all {len(baseline)} "
        f"protected items untouched; audit said {len(would_drop)} of "
        f"{len(carried.main_inventory)} carried items would read as junk"
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T43, t43_body, session=GameSession()) == "PASS" else 1)
