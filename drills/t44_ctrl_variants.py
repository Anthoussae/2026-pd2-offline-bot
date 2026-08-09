"""T44 — which spelling of CTRL does the client actually honour?

T43 sent a ctrl+right-click at an antidote potion. The potion left the
inventory and never reached the ground: the game read the click as
UNMODIFIED and drank it. That is the R113 hazard again, one modifier
along — and it is why T43 refused to bless the cleanse.

**A potion cannot tell us why.** "Ctrl was ignored" and "the gesture does
not exist" both end with the potion gone, so the test has no diagnostic
power. This drill therefore insists on an item whose UNMODIFIED
right-click does nothing at all — a rune or a gem — which turns the two
hypotheses into two different observable outcomes:

    the item drops to the ground   -> that spelling of ctrl WORKS
    the item just sits there       -> that spelling was ignored, and
                                      nothing was consumed finding out

Then it tries the spellings in turn on that same item, cheapest first,
stopping at whichever works:

    1. VK_CONTROL (0x11) with the standard one-frame settle   [T43's]
    2. VK_CONTROL with a long settle    — a timing problem, not a key one
    3. VK_LCONTROL (0xA2), standard settle — Windows treats 0x11 as an
       aggregate of both physical keys, and a client reading state
       per-side can miss it
    4. VK_LCONTROL with a long settle

Every attempt goes through the real `PanelInput` gate; nothing here
hand-rolls a raw send. A run that exhausts all four without moving the
item is a clean, non-destructive NO, and the cleanse stays disabled.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.behavior.town import TownConfig, TownLayer  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import VK_CONTROL, VK_LCONTROL, GatedInput  # noqa: E402
from pd2bot.input.menu import MenuInput  # noqa: E402
from pd2bot.input.panel import PanelInput  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.perception.units import scan_units  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# Kinds whose unmodified right-click is a NO-OP with only the inventory
# open, so a failed attempt costs nothing and is visibly a failure. Runes
# and gems, from the live-read code table.
SAFE_LOW, SAFE_HIGH = 625, 731  # the rune and PD2 gem/rune blocks
VARIANTS = [
    ("VK_CONTROL 0x11, 1-frame settle", VK_CONTROL, 0.06),
    ("VK_CONTROL 0x11, long settle", VK_CONTROL, 0.25),
    ("VK_LCONTROL 0xA2, 1-frame settle", VK_LCONTROL, 0.06),
    ("VK_LCONTROL 0xA2, long settle", VK_LCONTROL, 0.25),
]


T44 = Drill(
    test_id="T44",
    title="Which CTRL spelling the client honours for drop",
    kind="bot control",
    sends_input=True,
    instructions=(
        "Town only. I try up to four ways of holding CTRL, on ONE item.",
        "Put a RUNE or a GEM you do not mind dropping in your inventory - "
        "NOT a potion. A plain right-click does nothing to a rune, so if "
        "CTRL fails to register the item simply stays put and nothing is "
        "consumed. That is the whole point: a potion would be drunk and "
        "tell us nothing.",
        "Then hands off. I stop at the first spelling that works.",
    ),
)


def build_town(run: DrillRun, panel: PanelInput) -> TownLayer:
    session = run.session
    return TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=panel,
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=lambda target: (_ for _ in ()).throw(
            DrillAborted(f"T44 tried to WALK to {target} — it must not")
        ),
        snapshot=Perception(session).snapshot,
        config=TownConfig(),
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def t44_body(run: DrillRun) -> str:
    session = run.session

    def safe_items():
        return [
            i for i in read_carried_items(session).main_inventory
            if SAFE_LOW <= i.kind <= SAFE_HIGH
        ]

    if not run.announce_until(
        "T44: put a RUNE or GEM (not a potion) in your inventory - a plain "
        "right-click does nothing to those, so a failed CTRL costs nothing.",
        lambda: bool(safe_items()),
        timeout_s=300,
    ):
        raise DrillAborted("no rune or gem was offered — nothing safe to test on")

    target = safe_items()[0]
    print(f"target: kind {target.kind} at cell {target.position}", flush=True)
    run.say(f"Using kind {target.kind}. Hands off now - trying up to 4 variants.")

    for label, ctrl_vk, settle in VARIANTS:
        run.check_cancel()
        print(f"\n-- attempt: {label}", flush=True)
        panel = PanelInput(
            session, ui_array=run.ui_array,
            ctrl_vk=ctrl_vk, modifier_settle_s=settle,
        )
        town = build_town(run, panel)
        town.close_panels()
        town.press_inventory_open()

        ground_before = {g.unit_id for g in scan_units(session).ground_items}
        moved = town.drop_item(target)
        # The ground read is POLLED: a just-dropped item takes a moment to
        # enter the unit table, and T43 read it once, immediately. That
        # single read is not enough to conclude "it never landed".
        def on_floor(seen=ground_before) -> bool:
            return any(
                g.kind == target.kind and g.unit_id not in seen
                for g in scan_units(session).ground_items
            )

        landed = run.wait_until(on_floor, timeout_s=4.0)
        still_held = any(
            i.unit_id == target.unit_id
            for i in read_carried_items(session).main_inventory
        )
        print(f"   moved={moved} landed={landed} still_held={still_held}", flush=True)
        town.close_panels()

        if landed and not still_held:
            run.say(f"WORKS: {label}. Stopping here - you can pick it up.")
            return (
                f"CTRL DROP VERIFIED with {label}: kind {target.kind} left "
                "the inventory AND appeared on the ground"
            )
        if not still_held:
            raise DrillAborted(
                f"{label}: the item left the inventory but never reached the "
                "ground — something CONSUMED it, which should be impossible "
                f"for kind {target.kind}. Stopping before anything else is lost."
            )
        run.say(f"No effect from {label}; trying the next spelling.")

    return (
        "NONE of the four CTRL spellings moved the item, and nothing was "
        "consumed proving it. Either the client does not accept a synthetic "
        "ctrl+right-click, or the drop gesture is not what we think. The "
        "cleanse stays disabled."
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T44, t44_body, session=GameSession()) == "PASS" else 1)
