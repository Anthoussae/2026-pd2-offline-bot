"""The tag-mode battery (R248/R250): refusals, protection, recovery,
and a full block sequence.

The battery is TEST KIT, and test kit gets the same discipline as the
bot: the things it must never do (drop the Cube or a tome, advance past
an unreconciled floor, measure mode A through an executor that
re-lights the labels, fight the operator for items it asked them to
lift) each get a test, and one end-to-end run proves the phase machine
converges through all three blocks.
"""

from collections import Counter

from pd2bot import offsets
from pd2bot.behavior.actions import MoveTo, PickUpItem
from pd2bot.behavior.engine import EngineContext
from pd2bot.behavior.steps import RunServices, build_registry
from pd2bot.perception.items import CarriedItem, CarriedItems
from pd2bot.perception.player import Player
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.perception.uistate import UIState
from pd2bot.perception.units import GroundItem
from pd2bot.perception.world import Area
from pd2bot.pickit import Pickit, Rule
from pd2bot.runlog import NullRunLog

TOWN = 1  # the Rogue Encampment
HOME = (1000, 1000)
RARE, JUNK_QUALITY = 6, 2
LOOT_KIND, JUNK_KIND = 999, 555
POTION_KIND = next(iter(offsets.HEALING_POTION_KINDS))


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


class EventLog(NullRunLog):
    def __init__(self):
        self.events = []

    def event(self, kind, /, **fields):
        # The envelope tripwire (2026-08-10): the real log's record merge
        # would let a field named after an envelope key clobber the event
        # kind on disk. Fail here the way the real log cannot.
        assert not {"seq", "at", "t", "kind"} & fields.keys(), (
            f"event field collides with the envelope: {sorted(fields)}"
        )
        self.events.append((kind, fields))

    def of(self, kind, **match):
        return [
            f for k, f in self.events
            if k == kind and all(f.get(mk) == mv for mk, mv in match.items())
        ]


TEST_PICKIT = Pickit(
    rules=(
        Rule(name="quality loot", action="keep",
             qualities=frozenset({5, 6, 7, 8})),
    )
)


def inv_item(uid, kind, quality=RARE):
    return CarriedItem(uid, kind, quality, offsets.ITEM_MODE_IN_STORAGE,
                       offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE,
                       (uid % 10, 0), 1)


def belt_item(uid, kind):
    return CarriedItem(uid, kind, 2, offsets.ITEM_MODE_IN_BELT, 0,
                       offsets.NODE_BELT, (0, 0), 1)


def player_at(pos):
    return Player(
        name="N", level=91, act=1, position=pos, mode=1,
        hp=1000, max_hp=1000, mana=200, max_mana=400,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


class World:
    """Scripted town: carried items, the floor, panels, and the toggles."""

    def __init__(self, items):
        self.items = list(items)
        self.ground: list[GroundItem] = []
        self.pos = HOME
        self.next_uid = 500
        self.labels = False  # the client's label flag (BH.dll's byte)
        self.label_presses = 0
        self.filter_presses = 0
        self.enforcement = []
        self.panels: set[int] = set()
        self.said = []

    # -- the wired services -------------------------------------------------
    def carried(self):
        return CarriedItems(items=tuple(self.items), skipped=0)

    def drop_item(self, item):
        self.items = [i for i in self.items if i.unit_id != item.unit_id]
        self.next_uid += 1
        self.ground.append(GroundItem(
            unit_id=self.next_uid, kind=item.kind,
            position=self.pos, quality=item.quality,
        ))
        return True

    def open_inventory(self):
        self.panels.add(offsets.UI_INVENTORY)

    def clear_panels(self):
        self.panels.clear()

    def press_show_items(self):
        self.label_presses += 1
        self.labels = not self.labels

    def press_filter_toggle(self):
        self.filter_presses += 1

    # -- test plumbing ------------------------------------------------------
    def pick(self, ground_item):
        """A pickup lands: potions route to the BELT, like the client."""
        self.ground = [g for g in self.ground
                       if g.unit_id != ground_item.unit_id]
        self.next_uid += 1
        if ground_item.kind in offsets.POTION_KINDS:
            self.items.append(belt_item(self.next_uid, ground_item.kind))
        else:
            self.items.append(
                inv_item(self.next_uid, ground_item.kind, ground_item.quality)
            )

    def snapshot(self):
        return GameSnapshot(
            in_game=True, taken_at=0.0, player=player_at(self.pos),
            area=Area(level_no=TOWN, position=(0, 0), size=(500, 500)),
            monsters=(), ground_items=tuple(self.ground), allies=(),
            objects=(),
            ui=UIState(open_panels=frozenset(self.panels)),
            corpses=(),
        )


class Reactor:
    """An executor whose sends actually happen in the World."""

    def __init__(self, world):
        self.world = world
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        if isinstance(action, MoveTo):
            self.world.pos = action.target
        elif isinstance(action, PickUpItem):
            hit = next(
                (g for g in self.world.ground
                 if g.unit_id == action.unit_id), None,
            )
            if hit is not None:
                self.world.pick(hit)


class DeafReactor(Reactor):
    """Walks land; pickup clicks never do. The stubborn-floor case."""

    def execute(self, action):
        self.actions.append(action)
        if isinstance(action, MoveTo):
            self.world.pos = action.target


def battery_services(world, clock, *, alerts=None, wire=True):
    svc = RunServices(
        run_preamble=lambda: None,
        travel_to=lambda dest: None,
        combat=object(),
        pickit=TEST_PICKIT,
        carried=world.carried,
        clock=clock,
        alert=(alerts.append if alerts is not None else lambda r: None),
        runlog=EventLog(),
        clear_panels=world.clear_panels,
    )
    if wire:
        svc.drop_item = world.drop_item
        svc.open_inventory = world.open_inventory
        svc.carried_with_sockets = world.carried
        svc.label_state = lambda: world.labels
        svc.press_show_items = world.press_show_items
        svc.press_filter_toggle = world.press_filter_toggle
        svc.set_label_enforcement = world.enforcement.append
        svc.say = world.said.append
    return svc


def make_battery(svc, params=None):
    registry = build_registry(svc)
    spec = registry.spec("tagmode_battery")
    merged = {p.name: p.default for p in spec.params if not p.required}
    merged.update(params or {})
    return spec.factory(merged)


def drive(step, world, clock, ctx, *, ticks=600):
    """Tick until the step reports done, with a scripted OPERATOR who
    clears the floor during gather holds (the R251 design makes the
    between-round pickup a human job). The tick budget is a tripwire,
    not a tuning knob — a battery that needs more is looping."""
    outcome = None
    for _ in range(ticks):
        outcome = step.step(world.snapshot(), ctx)
        clock.advance(2.0)  # past pickup_retry_s, so budgets keep moving
        if step._phase == "gather" and step._gather_started is not None:
            for g in list(world.ground)[:2]:  # the operator hoovers
                world.pick(g)
        if outcome.done:
            return outcome
    raise AssertionError(f"battery never finished; last: {outcome}")


def loaded_world():
    """Two whitelisted droppables, junk, a potion, a map and a scroll —
    ALL of which drop under the R250 rule — plus the cube and the two
    tomes, which never do."""
    return World([
        inv_item(1, LOOT_KIND), inv_item(2, LOOT_KIND),
        inv_item(3, JUNK_KIND, JUNK_QUALITY),
        inv_item(4, POTION_KIND, JUNK_QUALITY),
        inv_item(5, offsets.MAP_KIND_UNCODED, JUNK_QUALITY),
        inv_item(6, offsets.SCROLL_OF_IDENTIFY_KIND, JUNK_QUALITY),
        inv_item(7, offsets.CUBE_KIND),
        inv_item(8, offsets.TOME_OF_TOWN_PORTAL_KIND),
        inv_item(9, offsets.TOME_OF_IDENTIFY_KIND),
    ])


# -- refusals: a battery that cannot run says so and stops ---------------------


def test_refuses_unwired_environment():
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock, wire=False)
    step = make_battery(svc)
    outcome = step.step(world.snapshot(), EngineContext(executor=Reactor(world)))
    assert outcome.done
    assert "not wired" in outcome.note
    assert svc.runlog.of("battery.end", completed=False)


def test_refuses_thin_whitelist():
    world = World([inv_item(1, LOOT_KIND), inv_item(3, JUNK_KIND, JUNK_QUALITY)])
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc)
    outcome = step.step(world.snapshot(), EngineContext(executor=Reactor(world)))
    assert outcome.done
    assert "restock" in outcome.note
    assert world.ground == [], "a refused battery must not have dropped anything"


def test_refuses_outside_town():
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc)
    snap = world.snapshot()
    field_snap = GameSnapshot(
        in_game=True, taken_at=0.0, player=snap.player,
        area=Area(level_no=3, position=(0, 0), size=(500, 500)),
        monsters=(), ground_items=(), allies=(), objects=(), ui=snap.ui,
        corpses=(),
    )
    outcome = step.step(field_snap, EngineContext(executor=Reactor(world)))
    assert outcome.done
    assert "town" in outcome.note


# -- the full battery, one round per block ---------------------------------------


def test_full_block_sequence_reconciles_and_restores():
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1, "confirm_seconds": 2})
    ctx = EngineContext(executor=Reactor(world))
    before = Counter(i.kind for i in world.items)

    outcome = drive(step, world, clock, ctx)

    assert outcome.done and "complete" in outcome.note
    log = svc.runlog
    # Three rounds ran (1A, 1B, 1C), every one reconciled.
    starts = log.of("battery.round", stage="test_start")
    assert [(f["round_no"], f["block"], f["mode"]) for f in starts] == [
        (1, "A", 1), (1, "B", 2), (1, "C", 3),
    ]
    ends = log.of("battery.round", stage="gather_end")
    assert len(ends) == 3 and all(f["reconciled"] for f in ends)
    assert log.of("battery.end", completed=True)
    assert not log.of("battery.loss")
    # The R250 drop rule: cube + tomes NEVER dropped, everything else
    # was — potion, map and scroll included. Round 1A drops six; the
    # gather then routes the potion to the BELT (client behavior), so
    # later rounds drop five. Composition drift, not loss: the census
    # counts inventory + belt, and potions are not whitelisted, so the
    # scores are untouched.
    drops = log.of("battery.round", stage="drop_end")
    assert [f["dropped"] for f in drops] == [6, 5, 5]
    protected_left = {
        i.kind for i in world.items
        if i.kind in {offsets.CUBE_KIND, offsets.TOME_OF_TOWN_PORTAL_KIND,
                      offsets.TOME_OF_IDENTIFY_KIND}
    }
    assert protected_left == {offsets.CUBE_KIND,
                              offsets.TOME_OF_TOWN_PORTAL_KIND,
                              offsets.TOME_OF_IDENTIFY_KIND}
    # NOTHING lost: the census (inventory + belt) matches the start.
    after = Counter(i.kind for i in world.items)
    assert after == before
    assert world.ground == []
    # Blocks set their modes once, flag-verified: labels off for A
    # (initial state), one ALT press into B, none into C, one back at
    # the restore; F pressed once into C and once back. Enforcement is
    # suspended for EVERY round — the battery owns the display (R254).
    modes = log.of("battery.mode")
    assert [(f["block"], f["mode"], f["enforcement"]) for f in modes] == [
        ("A", 1, False), ("B", 2, False), ("C", 3, False),
    ]
    assert world.labels is False
    assert world.label_presses == 2
    assert world.filter_presses == 2
    assert world.enforcement[-1] is True, (
        "the battery must not leave the executor's label policy suspended"
    )
    # The operator's announcements, verbatim shapes (R250).
    assert any("round 1A - mode NO NAME TAGS" in t for t in world.said)
    assert any("round 1B - mode LOOT FILTER TAGS" in t for t in world.said)
    assert any("round 1C - mode DEFAULT TAGS" in t for t in world.said)
    assert any("score:" in t for t in world.said)


# -- misclick recovery (R250 item 1) ---------------------------------------------


def test_stray_panel_is_closed_and_the_round_continues():
    """A misclicked stash (the 2026-08-13 wedge) costs one ESC now."""
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1})
    ctx = EngineContext(executor=Reactor(world))
    step._phase = "test"
    step._anchor = HOME
    step._manifest_kinds = {LOOT_KIND}
    world.panels.add(offsets.UI_STASH)  # the misclick
    outcome = step.step(world.snapshot(), ctx)
    assert outcome.acted and "stray panel" in outcome.note
    assert world.panels == set(), "the stash must be closed"
    assert step._phase == "test", "and the round must carry on"


def test_the_chat_console_is_never_closed():
    """The human opening chat is most likely typing `abort` (T54 run 4)."""
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1})
    ctx = EngineContext(executor=Reactor(world))
    step._phase = "test"
    step._anchor = HOME
    step._manifest_kinds = {LOOT_KIND}
    step._test_started = clock()  # mid-round
    step._wanted_start = 0
    world.panels.add(offsets.UI_CHAT_CONSOLE)
    step.step(world.snapshot(), ctx)
    assert offsets.UI_CHAT_CONSOLE in world.panels


# -- the operator gather (R251: theirs immediately) --------------------------------


def test_gather_asks_the_operator_immediately_and_never_clicks():
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1})
    reactor = DeafReactor(world)
    ctx = EngineContext(executor=reactor)
    step._phase = "gather"
    step._anchor = HOME
    step._manifest_kinds = {LOOT_KIND}
    step._pre_drop_counts = Counter(i.kind for i in world.items)
    stubborn = GroundItem(unit_id=999, kind=LOOT_KIND,
                          position=HOME, quality=RARE)
    world.ground.append(stubborn)
    step._pre_drop_counts[LOOT_KIND] += 1  # it belongs in the census

    # The ask comes on the FIRST gather tick, and the bot never clicks.
    step.step(world.snapshot(), ctx)
    assert svc.runlog.of("battery.assist")
    assert any("please pick up all" in t for t in world.said)
    for _ in range(30):
        step.step(world.snapshot(), ctx)
        clock.advance(2.0)
    assert not any(isinstance(a, PickUpItem) for a in reactor.actions), (
        "the gather is the operator's job — the bot must not fight them"
    )
    assert any("waiting on 1 item" in t for t in world.said), (
        "the hold must stay audible"
    )

    # The operator lifts it -> reconcile -> "resuming."
    world.pick(stubborn)
    outcome = step.step(world.snapshot(), ctx)
    assert not outcome.done
    assert any(t == "resuming." for t in world.said)
    ends = svc.runlog.of("battery.round", stage="gather_end")
    assert len(ends) == 1 and ends[0]["reconciled"] is True


def test_census_mismatch_is_announced_and_recorded_never_fatal():
    """Launch 3 ended a healthy battery over one drunk potion, and
    stackables merge on pickup — a count census reads both as loss.
    R251: announce, record, continue."""
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1})
    ctx = EngineContext(executor=Reactor(world))
    step._phase = "gather"
    step._anchor = HOME
    step._manifest_kinds = {LOOT_KIND}
    step._pre_drop_counts = Counter(i.kind for i in world.items)
    step._pre_drop_counts[LOOT_KIND] += 1  # one more than exists anywhere
    step.step(world.snapshot(), ctx)  # tick 1: the ask (floor is empty)
    outcome = step.step(world.snapshot(), ctx)  # tick 2: reconcile
    assert not outcome.done, "a census note must not end the battery"
    assert svc.runlog.of("battery.loss")
    ends = svc.runlog.of("battery.round", stage="gather_end")
    assert len(ends) == 1 and ends[0]["reconciled"] is False
    assert any("census note" in t for t in world.said)
    assert any(t == "resuming." for t in world.said)


def test_a_consumed_drop_is_excluded_from_the_census():
    """Launch 3's root cause: a slipped ctrl DRANK a healing potion
    during the drop — gone from the inventory, never on the floor. The
    floor-landing confirmation catches it at cause and the battery
    completes with the census adjusted."""

    class SlippingWorld(World):
        def drop_item(self, item):
            if item.kind == POTION_KIND:  # the slip: drunk, not dropped
                self.items = [
                    i for i in self.items if i.unit_id != item.unit_id
                ]
                return True
            return super().drop_item(item)

    world = SlippingWorld(loaded_world().items)
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1, "confirm_seconds": 2})
    ctx = EngineContext(executor=Reactor(world))

    outcome = drive(step, world, clock, ctx)

    assert outcome.done and "complete" in outcome.note
    consumed = svc.runlog.of("battery.consumed")
    assert len(consumed) == 1 and consumed[0]["item_kind"] == POTION_KIND
    assert any("never hit the floor" in t for t in world.said)
    assert not svc.runlog.of("battery.loss"), (
        "a caught consumption reconciles cleanly — no loss records"
    )
    ends = svc.runlog.of("battery.round", stage="gather_end")
    assert all(f["reconciled"] for f in ends)


def test_timed_out_round_reports_a_click_in_flight_as_resolving():
    """Tagmode review issue 002: a click sent before the cap whose item
    is still on the ground at the boundary is not a miss — it is
    RESOLVING, and the old scoring biased every timed-out round (only
    they can end with clicks in flight)."""
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1, "round_seconds": 4})
    ctx = EngineContext(executor=DeafReactor(world))
    step._phase = "test"
    step._anchor = HOME
    step._manifest_kinds = {LOOT_KIND}
    world.ground.append(
        GroundItem(unit_id=901, kind=LOOT_KIND, position=HOME, quality=RARE)
    )
    for _ in range(10):
        step.step(world.snapshot(), ctx)
        clock.advance(2.0)
        if step._phase != "test":
            break
    ends = svc.runlog.of("battery.round", stage="test_end")
    assert len(ends) == 1
    assert ends[0]["timed_out"] is True
    assert ends[0]["collected"] == 0
    assert ends[0]["resolving"] == 1, "the in-flight click must be named"
    assert ends[0]["wanted_left"] == 0, "a resolving click is not a miss"


def test_wired_filter_reader_is_settled_not_double_pressed():
    """A toggle press gets _TOGGLE_SETTLE_S to land before the flag is
    re-read — the engine ticks faster than the flags settle."""
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    filter_flag = {"on": False}
    svc.filter_state = lambda: filter_flag["on"]

    def press_f():
        world.filter_presses += 1
        filter_flag["on"] = not filter_flag["on"]

    svc.press_filter_toggle = press_f
    step = make_battery(svc, {"rounds": 1})
    ctx = EngineContext(executor=Reactor(world))
    world.labels = True  # block C's label target, already satisfied
    step._phase = "set_mode"
    step._block_i = 2  # block C: default tags ON
    step._labels_initial = True
    step._filter_on = False
    for _ in range(6):
        step.step(world.snapshot(), ctx)
        clock.advance(0.2)  # the real tick rate — FASTER than the settle
        if step._phase != "set_mode":
            break
    assert world.filter_presses == 1, "one press, verified after the settle"
    assert step._phase == "drop"


# -- the shipped run file ---------------------------------------------------------


def test_the_shipped_battery_run_validates():
    from pathlib import Path

    from pd2bot.behavior.run import default_registry, load_run

    repo = Path(__file__).resolve().parents[2]
    run = load_run(repo / "runs" / "t90-tagmode-battery.toml",
                   default_registry())
    assert run.name == "t90-tagmode-battery"
    assert [s.name for s in run.steps] == ["tagmode_battery", "done"]
    # No town_preamble ON PURPOSE: chores are suspended by construction.
    assert run.steps[0].params["rounds"] == 5
    assert run.steps[0].params["round_seconds"] == 30


def test_blocks_param_runs_a_single_block():
    """blocks="C" reruns one mode without re-paying for finished blocks
    (the 07:40 launch banked A and B; the watchdog stall ate C)."""
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"rounds": 1, "blocks": "C",
                              "confirm_seconds": 2})
    ctx = EngineContext(executor=Reactor(world))
    outcome = drive(step, world, clock, ctx)
    assert outcome.done and "complete" in outcome.note
    starts = svc.runlog.of("battery.round", stage="test_start")
    assert [(f["round_no"], f["block"], f["mode"]) for f in starts] == [
        (1, "C", 3),
    ]
    # C needs labels ON and F pressed; both restored afterwards.
    assert world.labels is False
    assert world.label_presses == 2
    assert world.filter_presses == 2


def test_unknown_blocks_refuse():
    world = loaded_world()
    clock = Clock()
    svc = battery_services(world, clock)
    step = make_battery(svc, {"blocks": "XYZ"})
    outcome = step.step(world.snapshot(), EngineContext(executor=Reactor(world)))
    assert outcome.done
    assert "blocks" in outcome.note
