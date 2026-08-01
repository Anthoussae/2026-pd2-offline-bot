"""The step handlers: clearance termination, the sweep, the full-inventory guard."""

from pathlib import Path

from pd2bot import offsets
from pd2bot.behavior.actions import AttackUnit, MoveTo, PickUpItem
from pd2bot.behavior.engine import EngineContext
from pd2bot.behavior.execute import RecordingExecutor
from pd2bot.behavior.necro import CombatConfig, NecroCombat
from pd2bot.behavior.run import build_states, load_run
from pd2bot.behavior.steps import RunServices, _chebyshev, build_registry
from pd2bot.items import CarriedItems
from pd2bot.pickit import Pickit, Rule
from pd2bot.player import Player
from pd2bot.snapshot import GameSnapshot
from pd2bot.uistate import UIState
from pd2bot.units import GameObject, GroundItem, Monster
from pd2bot.world import Area

REPO = Path(__file__).resolve().parent.parent
FIELD = 3
HOME = (1000, 1000)
HEAL, RARE = 606, 6


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


def player(pos=HOME):
    return Player(
        name="N", level=91, act=1, position=pos, mode=1,
        hp=1000, max_hp=1000, mana=200, max_mana=400,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


def monster(uid, pos):
    return Monster(
        unit_id=uid, kind=50, position=pos, hp=100, max_hp=100,
        is_champion=False, is_boss=False, is_minion=False,
    )


def snap(pos=HOME, monsters=(), items=(), allies=(), objects=(), ui=None, area=FIELD):
    return GameSnapshot(
        in_game=True, taken_at=0.0, player=player(pos),
        area=Area(level_no=area, position=(0, 0), size=(500, 500)),
        monsters=tuple(monsters), ground_items=tuple(items),
        allies=tuple(allies), objects=tuple(objects), ui=ui,
    )


def waypoint(pos):
    return GameObject(
        unit_id=11, kind=offsets.OBJ_WAYPOINT_A1, position=pos, mode=0
    )


def panels(*ids):
    return UIState(open_panels=frozenset(ids))


def revive(uid, pos):
    return Monster(
        unit_id=uid, kind=50, position=pos, hp=100, max_hp=100,
        is_champion=False, is_boss=False, is_minion=False,
        alignment=offsets.ALIGNMENT_FRIENDLY,
    )


class StubCombat:
    """Returns a scripted action per engage call."""

    def __init__(self, script=(), approach_script=()):
        self.script = list(script)
        self.approach_script = list(approach_script)
        self.calls = 0
        self.approach_calls = 0

    def engage(self, snap, ctx=None):
        self.calls += 1
        return self.script.pop(0) if self.script else None

    def upkeep(self, snap, ctx=None):
        return None

    def approach(self, snap, position):
        self.approach_calls += 1
        return self.approach_script.pop(0) if self.approach_script else None


# A fully-resolved pickit: the shipped file's ids await the T39 drill (its
# rules correctly match nothing until then), so the step tests use their own
# — same evaluator, no pending vocabulary.
TEST_PICKIT = Pickit(
    rules=(
        Rule(name="healing", action="belt",
             kinds=frozenset(offsets.HEALING_POTION_KINDS),
             potion_reserve=2, potion_type="healing"),
        Rule(name="mana", action="belt",
             kinds=frozenset(offsets.MANA_POTION_KINDS),
             potion_reserve=2, potion_type="mana"),
        Rule(name="rejuv", action="belt",
             kinds=frozenset(offsets.REJUV_POTION_KINDS),
             potion_reserve=2, potion_type="rejuv"),
        Rule(name="quality loot", action="keep",
             qualities=frozenset({5, 6, 7, 8})),  # set/rare/unique/crafted
    )
)


def services(clock, *, combat=None, alerts=None, **kw):
    return RunServices(
        run_preamble=lambda: None,
        travel_to=lambda dest: None,
        combat=combat if combat is not None else StubCombat(),
        pickit=TEST_PICKIT,
        carried=lambda: CarriedItems(items=(), skipped=0),
        clock=clock,
        alert=(alerts.append if alerts is not None else lambda r: None),
        **kw,
    )


def context(executor=None):
    return EngineContext(executor=executor or RecordingExecutor(clock=lambda: 0.0))


def make_step(name, svc, params=None):
    registry = build_registry(svc)
    return registry.spec(name).factory(params or {})


# -- clear_radius ---------------------------------------------------------------


def test_clearance_engages_while_hostiles_remain():
    clock = Clock()
    combat = StubCombat([AttackUnit(1, (1002, 1000))])
    step = make_step("clear_radius", services(clock, combat=combat),
                     {"radius": 150, "center": "arrival"})
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    outcome = step.step(snap(monsters=[monster(1, (1002, 1000))]), ctx)
    assert not outcome.done and outcome.acted
    assert executor.actions == [AttackUnit(1, (1002, 1000))]


def test_clearance_waits_out_the_settle_before_finishing():
    # A radius that reads empty for one tick is not cleared: a poisoned
    # monster is still alive for a few seconds and packs arrive late.
    clock = Clock()
    step = make_step("clear_radius", services(clock), {"radius": 150, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    assert not step.step(snap(), ctx).done  # first empty tick starts the timer
    clock.advance(2.0)
    assert not step.step(snap(), ctx).done
    clock.advance(4.0)  # past clear_settle_s 5.0
    assert step.step(snap(), ctx).done


def test_a_late_monster_resets_the_settle_timer():
    clock = Clock()
    combat = StubCombat([AttackUnit(1, (1002, 1000))])
    step = make_step("clear_radius", services(clock, combat=combat),
                     {"radius": 150, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    step.step(snap(), ctx)
    clock.advance(4.0)
    step.step(snap(monsters=[monster(1, (1002, 1000))]), ctx)  # timer resets
    clock.advance(4.0)
    assert not step.step(snap(), ctx).done


def test_monsters_outside_the_radius_do_not_hold_the_step_open():
    clock = Clock()
    step = make_step("clear_radius", services(clock), {"radius": 20, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    far = monster(1, (1000 + 90, 1000))
    assert not step.step(snap(monsters=[far]), ctx).done
    clock.advance(6.0)
    assert step.step(snap(monsters=[far]), ctx).done


def test_clearance_picks_up_loot_when_there_is_nothing_to_hit():
    clock = Clock()
    step = make_step("clear_radius", services(clock), {"radius": 150, "center": "arrival"})
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    potion = GroundItem(unit_id=50, kind=HEAL, position=(1002, 1000), quality=2)
    # A hostile in range keeps the step open; combat has nothing to do.
    step.step(snap(monsters=[monster(1, (1030, 1000))], items=[potion]), ctx)
    assert executor.actions == [PickUpItem(50, (1002, 1000))]


def test_clearance_uses_the_player_position_when_there_is_no_arrival_note():
    clock = Clock()
    step = make_step("clear_radius", services(clock), {"radius": 150, "center": "arrival"})
    ctx = context()  # no note at all
    assert not step.step(snap(monsters=[monster(1, (1002, 1000))]), ctx).done


# -- the waypoint lock-out (stage B attempt 10) ---------------------------------


def test_the_waypoint_step_walks_off_the_waypoint_it_landed_on():
    """The user's request, from watching the run lock itself out.

    Travelling puts the character ON the waypoint with the cursor still
    over it, which makes the arrival square the one place an ordinary
    click is likeliest to open a menu instead of doing what it meant.
    """
    clock = Clock()
    svc = services(clock)
    step = make_step("waypoint", svc, {"dest": 3})
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.snapshot = lambda: snap(objects=[waypoint(HOME)])
    outcome = step.step(snap(), ctx)
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert moves, "it stayed standing on the waypoint"
    assert _chebyshev(moves[0].target, HOME) >= svc.waypoint_step_off
    # The arrival note is the WAYPOINT, not where we stepped to: the run's
    # landmark does not move just because the character does.
    assert ctx.notes["arrival"] == HOME
    assert outcome.done


def test_nothing_to_step_off_means_no_step():
    # Conditioned on the hazard actually being there — an arrival with
    # nothing clickable nearby behaves exactly as it always did.
    clock = Clock()
    step = make_step("waypoint", services(clock), {"dest": 3})
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.snapshot = lambda: snap()  # no objects at all
    step.step(snap(), ctx)
    assert not [a for a in executor.actions if isinstance(a, MoveTo)]


def test_a_stray_panel_outside_town_is_closed_not_waited_out():
    """What actually ended attempt 10.

    A mis-placed cast opened the waypoint menu. `GatedInput` refuses every
    send while a blocking panel is open, so the bot kept deciding correctly
    and kept reaching the game with none of it — for 10 s, until the
    navigator gave up and the run chickened out with the area untouched.
    """
    clock = Clock()
    closed = []
    svc = services(clock, clear_panels=lambda: closed.append(1))
    step = make_step("clear_radius", svc, {"radius": 50, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    outcome = step.step(snap(ui=panels(offsets.UI_WPMENU)), ctx)
    assert closed, "the panel was left open"
    assert outcome.acted and not outcome.done


def test_panels_are_left_alone_in_town():
    # Town opens panels on purpose all through the preamble; this recovery
    # is for the field, where nothing does.
    clock = Clock()
    closed = []
    svc = services(clock, clear_panels=lambda: closed.append(1))
    step = make_step("clear_radius", svc, {"radius": 50, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    step.step(snap(ui=panels(offsets.UI_STASH), area=1), ctx)
    assert not closed


# -- review 001: the gap between the two radii ----------------------------------


def test_clearance_asks_the_module_to_close_on_what_it_cannot_reach():
    # The step measures from the arrival point, the module from the player,
    # so a monster can be inside the clearance and outside the fight. The
    # step used to call that patience and declare a wait.
    clock = Clock()
    hop = MoveTo((1008, 1000))
    combat = StubCombat(approach_script=[hop])
    step = make_step("clear_radius", services(clock, combat=combat),
                     {"radius": 50, "center": "arrival"})
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    outcome = step.step(snap(monsters=[monster(1, (1045, 1000))]), ctx)
    assert executor.actions == [hop]
    assert outcome.acted and not outcome.waiting


def test_clearance_still_declares_a_wait_when_the_module_says_no():
    # The module refuses to close while a fight is genuinely in progress —
    # its pauses (restrike cooldowns, waiting for the revives to take the
    # front) are deliberate, and this must not have turned them into a
    # charge. Patience is still patience.
    clock = Clock()
    combat = StubCombat()  # engage: None, approach: None
    step = make_step("clear_radius", services(clock, combat=combat),
                     {"radius": 50, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    outcome = step.step(snap(monsters=[monster(1, (1010, 1000))]), ctx)
    assert combat.approach_calls == 1
    assert outcome.waiting and not outcome.acted


def test_the_clearance_reaches_a_hostile_that_started_out_of_reach():
    """Review 001's validation, against the REAL combat module.

    A hostile just inside `radius` (50) and just outside `engage_radius`
    (40) is the exact shape that hung: `engage` returned None forever, the
    step reported `waiting=True` forever, and `waiting` suppresses the idle
    watchdog. Before the fix this loop reached its last tick having sent
    nothing at all; now it closes the distance and strikes.
    """
    clock = Clock()
    combat = NecroCombat(
        config=CombatConfig(), is_walkable=lambda p: True, clock=clock
    )
    step = make_step("clear_radius", services(clock, combat=combat),
                     {"radius": 50, "center": "arrival"})
    here = {"pos": HOME}

    def react(action):
        if isinstance(action, MoveTo):
            here["pos"] = action.target

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    hostile = monster(1, (1045, 1000))
    # A standing wall next to the hostile: approaching is gated on one, and
    # placing it there means the wait-for-the-tanks phase ends immediately.
    wall = [revive(900 + i, (1040, 1000)) for i in range(3)]
    for _ in range(12):
        step.step(snap(pos=here["pos"], monsters=[hostile], allies=wall), ctx)
        clock.advance(0.5)
        if any(isinstance(a, AttackUnit) for a in executor.actions):
            break
    assert any(isinstance(a, AttackUnit) for a in executor.actions), (
        f"never reached the hostile: {executor.actions}"
    )


# -- pickup ---------------------------------------------------------------------


def test_pickup_walks_to_a_distant_item_then_clicks_it():
    clock = Clock()
    step = make_step("pickup", services(clock))
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    loot = GroundItem(unit_id=60, kind=999, position=(1020, 1000), quality=RARE)
    step.step(snap(items=[loot]), ctx)
    assert executor.actions == [MoveTo((1020, 1000))]
    # Now standing on it: the click goes out.
    step.step(snap(pos=(1019, 1000), items=[loot]), ctx)
    assert executor.actions[-1] == PickUpItem(60, (1020, 1000))


def test_pickup_finishes_when_nothing_is_wanted():
    clock = Clock()
    step = make_step("pickup", services(clock))
    ctx = context()
    ctx.notes["arrival"] = HOME
    junk = GroundItem(unit_id=61, kind=999, position=(1002, 1000), quality=4)
    assert step.step(snap(items=[junk]), ctx).done  # magic: no rule matches


def test_pickup_verifies_by_the_item_leaving_the_ground():
    clock = Clock()
    step = make_step("pickup", services(clock))
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    loot = GroundItem(unit_id=60, kind=999, position=(1001, 1000), quality=RARE)
    step.step(snap(items=[loot]), ctx)
    assert len(executor.actions) == 1
    # Gone from the next snapshot: the step is satisfied and moves on.
    assert step.step(snap(), ctx).done


def test_a_stuck_item_trips_the_inventory_full_guard():
    clock = Clock()
    alerts = []
    svc = services(clock, alerts=alerts)
    step = make_step("pickup", svc)
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    loot = GroundItem(unit_id=60, kind=999, position=(1001, 1000), quality=RARE)
    world = snap(items=[loot])
    for _ in range(6):  # more ticks than pickup_attempts
        step.step(world, ctx)
        clock.advance(2.0)
    assert len(executor.actions) == svc.pickup_attempts  # bounded, not a loop
    assert svc.inventory_full
    assert alerts and "INVENTORY FULL" in alerts[0]


def test_a_full_inventory_still_allows_belt_potions():
    clock = Clock()
    svc = services(clock)
    svc.inventory_full = True
    step = make_step("pickup", svc)
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    potion = GroundItem(unit_id=70, kind=HEAL, position=(1001, 1000), quality=2)
    loot = GroundItem(unit_id=71, kind=999, position=(1001, 1000), quality=RARE)
    step.step(snap(items=[potion, loot]), ctx)
    assert executor.actions == [PickUpItem(70, (1001, 1000))]  # the potion only


def test_the_full_inventory_flag_is_shared_across_steps():
    # Clearance discovering a full inventory must stop the sweep that
    # follows it: both steps share one services object per game.
    clock = Clock()
    svc = services(clock)
    clearance = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    sweep = make_step("pickup", svc)
    assert clearance.services is sweep.services


# -- blocking steps and the registry ---------------------------------------------


def test_town_preamble_runs_the_preamble_once():
    clock = Clock()
    calls = []
    svc = services(clock)
    svc.run_preamble = lambda: calls.append(1)
    step = make_step("town_preamble", svc)
    assert step.step(snap(), context()).done
    assert calls == [1]


def test_waypoint_travels_and_records_the_arrival():
    clock = Clock()
    travelled = []
    svc = services(clock)
    svc.travel_to = travelled.append
    step = make_step("waypoint", svc, {"dest": 3})
    ctx = context()
    # The step re-reads position after the trip: the tick's snapshot was
    # taken in town, before the character moved areas.
    ctx.snapshot = lambda: snap(pos=(5000, 5000))
    outcome = step.step(snap(pos=HOME), ctx)
    assert outcome.done and travelled == [3]
    assert ctx.notes["arrival"] == (5000, 5000)


def test_done_completes_immediately():
    step = make_step("done", services(Clock()))
    assert step.step(snap(), context()).done


def test_the_shipped_run_builds_end_to_end():
    # P4 could only validate the run; with handlers registered it builds.
    svc = services(Clock())
    registry = build_registry(svc)
    run = load_run(REPO / "runs" / "cold-plains.toml", registry)
    states = build_states(run, registry)
    assert [s.name for s in states] == [
        "town_preamble", "waypoint", "clear_radius", "pickup", "done",
    ]
    assert states[2].radius == 150  # the run file's parameter reached the step
    assert states[1].dest == offsets.AREA_COLD_PLAINS
