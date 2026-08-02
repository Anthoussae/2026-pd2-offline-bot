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
from pd2bot.navigate import NavigationError
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
    """Build a step the way `build_states` does — defaults included.

    The factory's contract is that it receives VALIDATED parameters, so
    a helper that hands it a bare dict is testing a path production
    never takes. It also breaks the moment a step gains an optional
    parameter, which is how this was found.
    """
    registry = build_registry(svc)
    spec = registry.spec(name)
    merged = {p.name: p.default for p in spec.params if not p.required}
    merged.update(params or {})
    return spec.factory(merged)


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


# -- the patrol ------------------------------------------------------------------


def patrolling(clock, radius=96, **kw):
    """A patrolling clearance plus an executor that actually moves.

    The patrol only means anything if walking changes where the character
    is, so the executor reacts the way the game would.
    """
    svc = services(clock, **kw)
    step = make_step(
        "clear_radius", svc, {"radius": radius, "center": "arrival", "patrol": True}
    )
    here = {"pos": HOME}

    def react(action):
        if isinstance(action, MoveTo):
            here["pos"] = action.target

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    return step, svc, here, executor, ctx


def drive(step, here, ctx, clock, ticks=400, monsters=()):
    for _ in range(ticks):
        outcome = step.step(snap(pos=here["pos"], monsters=monsters), ctx)
        clock.advance(0.5)
        if outcome.done:
            return outcome
    return None


def test_the_patrol_visits_every_sample_point():
    """The circle has to be walked before it can be believed.

    Perception is 80 subtiles (`units.PERCEPTION_RADIUS`) and `scan_units`
    drops everything past it, so a standstill clearance of radius 96 is a
    claim about ground it never looked at.
    """
    clock = Clock()
    step, svc, here, _, ctx = patrolling(clock)
    assert drive(step, here, ctx, clock) is not None, "the patrol never finished"
    assert len(step._visited) == svc.patrol_points
    for point in step.patrol_points(HOME):
        assert _chebyshev(point, HOME) <= 96


def test_the_clearance_does_not_finish_while_circle_remains():
    # The bug in one assertion: the radius reads clear from tick one, and
    # that is not the same as the radius BEING clear.
    clock = Clock()
    step, _, here, _, ctx = patrolling(clock)
    first = step.step(snap(pos=here["pos"]), ctx)
    assert not first.done
    clock.advance(60.0)  # far past clear_settle_s
    assert not step.step(snap(pos=here["pos"]), ctx).done


def test_a_point_on_unread_ground_is_skipped_not_fatal():
    """Unknown ground is impassable by design (navigate.py), and a ring
    several screens out will often name ground nobody has read. Uncaught,
    `NavigationError` fails the whole cycle."""
    clock = Clock()
    svc = services(clock)
    step = make_step(
        "clear_radius", svc, {"radius": 96, "center": "arrival", "patrol": True}
    )

    def refuse(action):
        raise NavigationError("that ground has never been seen")

    executor = RecordingExecutor(clock=clock, on_execute=refuse)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    here = {"pos": HOME}
    assert drive(step, here, ctx, clock) is not None, "a skip became fatal"
    assert len(step._visited) == svc.patrol_points


def test_an_unwalkable_fight_target_costs_the_target_not_the_game():
    """2026-08-01, the first run that fought since the review fixes.

    Four kills, a full revive wall, the circle walked — and it ended on
    `NavigationError: gave up after 5 plan cycles without progress; last
    position (5226, 5658), target (5219, 5658)`. Seven subtiles. The
    patrol already gives up on a point it cannot reach and takes the
    next one; the fight had no equivalent, so one unreachable monster
    ended the game.
    """
    clock = Clock()
    combat = StubCombat([MoveTo((1200, 1200))])
    step = make_step("clear_radius", services(clock, combat=combat),
                     {"radius": 150, "center": "arrival"})

    def refuse(action):
        raise NavigationError("gave up after 5 plan cycles without progress")

    executor = RecordingExecutor(clock=clock, on_execute=refuse)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    outcome = step.step(snap(monsters=[monster(1, (1002, 1000))]), ctx)
    assert not outcome.done  # survived; the engine gets another tick


# -- writing off a monster we cannot get to -------------------------------------
#
# Surviving the unreachable target was only half of it, and shipping the
# half was a regression: absorbing `NavigationError` stopped one monster
# ending the run, and then nothing wrote that monster off, so the clearance
# re-decided the identical approach every tick and could never finish. The
# user watched it "hesitate at great length when an enemy was behind a
# wall". These are the other half.


def test_an_unreachable_monster_stops_holding_the_clearance_open():
    clock = Clock()
    combat = StubCombat([MoveTo((1100, 1000), toward=1)] * 10)
    svc = services(clock, combat=combat)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})

    def refuse(action):
        raise NavigationError("gave up after 5 plan cycles without progress")

    executor = RecordingExecutor(clock=clock, on_execute=refuse)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    walled = monster(1, (1100, 1000))

    step.step(snap(monsters=[walled]), ctx)
    assert 1 in step._unreachable, "a monster we cannot walk to must be written off"

    # And now the step can actually finish, with the monster still standing.
    outcome = drive(step, {"pos": HOME}, ctx, clock, monsters=[walled])
    assert outcome is not None and outcome.done
    assert "written off" in outcome.note, "finishing that way must be said out loud"


def test_a_dash_blames_only_the_monster_it_named():
    """A retreat and a lateral drift aim at open ground, not at anything.

    They carry no `toward`, and a failed one must write nothing off — the
    monster the fight is about is not the reason a step sideways failed.
    """
    clock = Clock()
    combat = StubCombat([MoveTo((1002, 1000))])  # no `toward`: a drift
    svc = services(clock, combat=combat)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})

    def refuse(action):
        raise NavigationError("nowhere to drift to")

    ctx = context(RecordingExecutor(clock=clock, on_execute=refuse))
    ctx.notes["arrival"] = HOME
    step.step(snap(monsters=[monster(1, (1100, 1000))]), ctx)
    assert not step._unreachable, "an unaimed walk must not cost a monster"


def test_closing_that_gets_closer_is_never_written_off():
    """Progress, not effort — the same correction the patrol needed.

    A monster we are slowly walking toward earns as many ticks as it
    takes; only ticks that achieve nothing count against it.
    """
    clock = Clock()
    combat = StubCombat(approach_script=[MoveTo((1010, 1000))] * 20)
    svc = services(clock, combat=combat)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    here = {"pos": HOME}

    def react(action):
        if isinstance(action, MoveTo):
            here["pos"] = (here["pos"][0] + 10, here["pos"][1])  # 10 closer

    ctx = context(RecordingExecutor(clock=clock, on_execute=react))
    ctx.notes["arrival"] = HOME
    target = monster(1, (1100, 1000))
    for _ in range(6):
        step.step(snap(pos=here["pos"], monsters=[target]), ctx)
    assert not step._unreachable, "closing steadily must not be a write-off"


def test_closing_that_never_gets_closer_is_written_off():
    """The silent version of the hang: every walk succeeds, none arrives.

    No `NavigationError` is ever raised here — the navigator is perfectly
    happy — so the failed-walk path would never fire, and without this the
    step closes on the same monster from the same distance forever.
    """
    clock = Clock()
    combat = StubCombat(approach_script=[MoveTo((1010, 1000))] * 20)
    svc = services(clock, combat=combat)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    ctx = context(RecordingExecutor(clock=clock))  # walks "succeed", nothing moves
    ctx.notes["arrival"] = HOME
    target = monster(1, (1100, 1000))
    for _ in range(svc.monster_attempts + 1):
        step.step(snap(monsters=[target]), ctx)
    assert 1 in step._unreachable


def test_a_written_off_monster_that_moves_gets_another_try():
    """Monsters walk, which is how they differ from ring points and items.

    The write-off says "unreachable from where it was standing", so a
    monster that has left that spot has invalidated the only evidence
    behind it. This repo's own rule: a retry that cannot differ from the
    attempt it retries is not a retry — and one that CAN differ is owed.
    """
    clock = Clock()
    combat = StubCombat(approach_script=[MoveTo((1010, 1000))] * 20)
    svc = services(clock, combat=combat)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    ctx = context(RecordingExecutor(clock=clock))
    ctx.notes["arrival"] = HOME
    for _ in range(svc.monster_attempts + 1):
        step.step(snap(monsters=[monster(1, (1100, 1000))]), ctx)
    assert 1 in step._unreachable

    # It gives up on its wall and walks toward us.
    moved = monster(1, (1100 - svc.unreachable_forget - 1, 1000))
    step.step(snap(monsters=[moved]), ctx)
    assert 1 not in step._unreachable, "it moved; the write-off's evidence is gone"


def test_an_unreachable_item_is_written_off_not_retried_forever():
    clock = Clock()
    svc = services(clock)
    step = make_step("pickup", svc)

    def refuse(action):
        raise NavigationError("that ground has never been seen")

    executor = RecordingExecutor(clock=clock, on_execute=refuse)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    potion = GroundItem(unit_id=50, kind=HEAL, position=(1100, 1000), quality=2)
    step.step(snap(items=[potion]), ctx)
    assert 50 in svc.stuck, "an unwalkable item must not be attempted forever"


def test_a_point_that_cannot_be_reached_is_abandoned():
    # Walkable in principle, unreachable in practice: the walk "succeeds"
    # and the character never arrives. One awkward corner must not hold
    # the whole clearance open.
    clock = Clock()
    svc = services(clock)
    step = make_step(
        "clear_radius", svc, {"radius": 96, "center": "arrival", "patrol": True}
    )
    executor = RecordingExecutor(clock=clock)  # nothing moves
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    here = {"pos": HOME}
    assert drive(step, here, ctx, clock) is not None
    legs = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert len(legs) == svc.patrol_points * svc.patrol_attempts


def test_a_fight_does_not_count_against_the_patrol_point():
    """Live, 2026-08-01: 5 of 8 points reached, and the misses were wrong.

    Two were abandoned from 20 subtiles — walking distance, not a wall.
    During a fight the character moves toward the monster, which is away
    from wherever the patrol was heading, so every leg after the fight
    measured worse than a `_closest` recorded before it and three ticks
    threw the point away. The budget is for one attempt; an interruption
    ends the attempt rather than counting against it.
    """
    clock = Clock()
    step, svc, here, _, ctx = patrolling(clock)
    step.step(snap(pos=here["pos"]), ctx)  # a leg, recording _closest
    step._attempts = svc.patrol_attempts - 1  # one tick from giving up
    step.step(snap(pos=here["pos"], monsters=[monster(1, (1002, 1000))]), ctx)
    assert step._attempts == 0 and step._closest is None


def test_patrol_legs_are_capped_so_the_ladder_keeps_its_look():
    # `walk_to` blocks until arrival, so a leg is time the reflex ladder
    # is not consulted — the same reason a combat dash is capped.
    clock = Clock()
    step, svc, here, executor, ctx = patrolling(clock)
    drive(step, here, ctx, clock)
    previous = HOME
    for action in executor.actions:
        if isinstance(action, MoveTo):
            assert _chebyshev(action.target, previous) <= svc.patrol_step
            previous = action.target


def test_without_patrol_the_clearance_stands_exactly_as_before():
    clock = Clock()
    svc = services(clock)
    step = make_step("clear_radius", svc, {"radius": 96, "center": "arrival"})
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    assert not step.step(snap(), ctx).done
    clock.advance(6.0)
    assert step.step(snap(), ctx).done
    assert executor.actions == [], "a non-patrolling clearance must not walk"


def test_fighting_suspends_the_patrol():
    # Clearing is the job; walking is only what happens when there is
    # nothing to clear.
    clock = Clock()
    combat = StubCombat([AttackUnit(1, (1002, 1000))])
    step, _, here, executor, ctx = patrolling(clock, combat=combat)
    outcome = step.step(snap(pos=here["pos"], monsters=[monster(1, (1002, 1000))]), ctx)
    assert outcome.acted and not outcome.done
    assert executor.actions == [AttackUnit(1, (1002, 1000))]
    assert not step._visited, "it walked while something was alive in the radius"


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


# -- the sweep walks the circle too ---------------------------------------------
#
# The user watched a whitelisted Tir rune left behind on the far side of a
# 96-radius circle. The pickit rules were right; nothing ever asked them
# about that rune, because the sweep stood where the clearance finished and
# collected what it could see — and T51 measured what that is: 46-67
# subtiles, room-quantised, not the 80 the constant claims.


def cleared_circle(ctx, centre=HOME, radius=96, patrol=True):
    """What `clear_radius` leaves on the blackboard for the sweep."""
    ctx.notes["arrival"] = centre
    ctx.notes["cleared"] = {"centre": centre, "radius": radius, "patrol": patrol}


def sweeping(clock, **kw):
    """A patrolling sweep plus an executor that actually moves the player."""
    svc = services(clock, **kw)
    step = make_step("pickup", svc)
    here = {"pos": HOME}

    def react(action):
        if isinstance(action, MoveTo):
            here["pos"] = action.target

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)
    cleared_circle(ctx)
    return step, svc, here, executor, ctx


def test_the_sweep_walks_the_circle_before_calling_it_empty():
    clock = Clock()
    step, svc, here, executor, ctx = sweeping(clock)
    outcome = None
    for _ in range(400):
        outcome = step.step(snap(pos=here["pos"]), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done
    assert len(step._visited) == svc.patrol_points, (
        "the sweep finished without walking its circle — the exact bug that "
        "left a whitelisted rune on the far side"
    )
    assert [a for a in executor.actions if isinstance(a, MoveTo)], "it never moved"


def test_the_sweep_collects_something_only_reachable_by_patrolling():
    """The rune on the far side. Visible only once the sweep gets there."""
    clock = Clock()
    step, svc, here, executor, ctx = sweeping(clock)
    # 70 subtiles out: inside the 96 circle, outside anything the sweep can
    # see from the arrival point.
    rune = GroundItem(unit_id=77, kind=999, position=(1070, 1000), quality=RARE)

    def visible(pos):
        # Stand in for the client's horizon, which is what actually hides it.
        return [rune] if _chebyshev(rune.position, pos) <= 50 else []

    for _ in range(400):
        outcome = step.step(snap(pos=here["pos"], items=visible(here["pos"])), ctx)
        clock.advance(0.5)
        if any(isinstance(a, PickUpItem) and a.unit_id == 77
               for a in executor.actions):
            break
        if outcome.done:
            break
    assert [a for a in executor.actions if isinstance(a, PickUpItem)
            and a.unit_id == 77], "the far-side item was never even attempted"


def test_the_sweep_follows_the_clearance_rather_than_its_own_number():
    """One radius, not two. The `--radius` override only rewrites
    `clear_radius`, so a sweep with its own copy would silently ignore it."""
    clock = Clock()
    svc = services(clock)
    step = make_step("pickup", svc)
    ctx = context()
    cleared_circle(ctx, centre=(2000, 2000), radius=120, patrol=True)
    step.step(snap(pos=(2000, 2000)), ctx)
    assert (step.radius, step.patrol, step._centre) == (120, True, (2000, 2000))


def test_a_sweep_with_no_clearance_does_not_patrol():
    """Nothing published a circle, so there is no circle to walk."""
    clock = Clock()
    svc = services(clock)
    step = make_step("pickup", svc)
    ctx = context()
    ctx.notes["arrival"] = HOME  # a waypoint ran; no clearance did
    assert step.step(snap(), ctx).done
    assert not step.patrol


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


# -- cleanse drop hygiene (R175, after the R173 loop) ----------------------------
#
# The loop, watched live by the user: the cleanse drops junk at the feet —
# right at the pointer — and the retried pickup click scoops it straight
# back. Then `maybe_cleanse` re-armed the same doomed retry, forever, until
# the character (standing in fire the whole time) chickened at 49%.


def hygiene_setup(cleanse_result=3):
    clock = Clock()
    calls = []
    svc = services(clock, cleanse=lambda: (calls.append(1), cleanse_result)[1])
    step = make_step("pickup", svc)
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    return step, svc, executor, ctx, calls


def test_the_cleanse_walks_clear_of_a_wanted_item_before_dropping():
    step, svc, executor, ctx, calls = hygiene_setup()
    svc.cleanse_queued = True
    svc.stuck.add(601)  # the failed pickup that queued the cleanse
    rune = GroundItem(unit_id=601, kind=999, position=(1003, 1000), quality=RARE)

    assert step.maybe_cleanse(snap(items=[rune]), ctx)
    assert not calls, "junk must not be dropped beside the item we will click"
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert moves, "the tick should be spent walking clear"
    assert _chebyshev(moves[-1].target, rune.position) >= svc.cleanse_standoff

    # Standing clear now: the drop happens, and the pile is remembered.
    away = moves[-1].target
    assert step.maybe_cleanse(snap(pos=away, items=[rune]), ctx)
    assert calls == [1]
    assert svc.cleanse_dropped_at == away


def test_the_rearm_waits_for_the_step_off_and_happens_once():
    step, svc, executor, ctx, calls = hygiene_setup()
    svc.cleanse_dropped_at = HOME
    svc.stuck.add(601)
    svc.inventory_full = True

    # Still on the pile: the tick is spent leaving, nothing is re-armed.
    assert step.maybe_cleanse(snap(), ctx)
    assert 601 in svc.stuck and svc.inventory_full
    assert isinstance(executor.actions[-1], MoveTo)

    # Clear of the pile: the one differing retry is granted.
    far = (HOME[0] + svc.cleanse_standoff + 4, HOME[1])
    assert not step.maybe_cleanse(snap(pos=far), ctx)
    assert 601 not in svc.stuck
    assert not svc.inventory_full
    assert 601 in svc.cleanse_retried

    # The retry fails again: written off for the game, NO new cleanse —
    # a second cleanse cannot differ from the first for this item.
    rune = GroundItem(unit_id=601, kind=999, position=(1001, 1000), quality=RARE)
    svc.attempts[601] = svc.pickup_attempts
    assert not step.collect(snap(items=[rune]), ctx, rune)
    assert 601 in svc.stuck and svc.inventory_full
    assert not svc.cleanse_queued


def test_a_cleanse_with_nothing_wanted_nearby_drops_immediately():
    step, svc, executor, ctx, calls = hygiene_setup()
    svc.cleanse_queued = True
    assert step.maybe_cleanse(snap(), ctx)
    assert calls == [1], "no wanted item near = no reason to walk first"
    assert svc.cleanse_dropped_at == HOME


def test_a_different_item_still_earns_its_own_cleanse():
    step, svc, executor, ctx, calls = hygiene_setup()
    svc.cleanse_retried.add(601)  # 601 spent its retry; 602 has not
    other = GroundItem(unit_id=602, kind=998, position=(1001, 1000), quality=RARE)
    svc.attempts[602] = svc.pickup_attempts
    assert not step.collect(snap(items=[other]), ctx, other)
    assert svc.cleanse_queued, "601's exhaustion must not block 602's cleanse"


def test_a_dry_cleanse_leaves_no_pile_to_avoid():
    step, svc, executor, ctx, calls = hygiene_setup(cleanse_result=0)
    svc.cleanse_queued = True
    assert step.maybe_cleanse(snap(), ctx)
    assert calls == [1]
    assert svc.cleanse_dropped_at is None, "nothing dropped, nothing to flee"


# -- the survey step (R175/R176) --------------------------------------------------


class FrontierWorld:
    """A scripted survey service: frontiers close when the player nears them.

    Stands in for the wiring's closure over the atlas — the step's contract
    is only "call me for the current list", and this answers it the way the
    real one does: reaching a frontier removes it (the rooms beyond got
    recorded), and nothing else changes the list.
    """

    def __init__(self, points):
        self.points = list(points)
        self.player = HOME

    def targets(self):
        self.points = [
            p for p in self.points if _chebyshev(p, self.player) > 5
        ]
        return list(self.points)

    def coverage(self):
        return f"{len(self.points)} frontier point(s) open"


def surveying(clock, points, *, monsters_react=None, **kw):
    world = FrontierWorld(points)
    svc = services(
        clock,
        survey_targets=world.targets,
        survey_coverage=world.coverage,
        **kw,
    )
    step = make_step("survey", svc)
    here = {"pos": HOME}

    def react(action):
        if isinstance(action, MoveTo):
            here["pos"] = action.target
            world.player = action.target

    executor = RecordingExecutor(clock=clock, on_execute=react)
    return step, svc, world, here, executor, context(executor)


def test_the_survey_walks_frontiers_until_none_remain():
    clock = Clock()
    step, svc, world, here, executor, ctx = surveying(
        clock, [(1060, 1000), (1000, 1060)]
    )
    outcome = None
    for _ in range(200):
        outcome = step.step(snap(pos=here["pos"]), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done
    assert "survey complete" in outcome.note
    assert world.points == [], "every frontier must be visited"
    assert [a for a in executor.actions if isinstance(a, MoveTo)]


def test_an_unreachable_frontier_is_written_off_not_looped_on():
    clock = Clock()
    step, svc, world, here, executor, ctx = surveying(clock, [(1060, 1000)])
    # Walks "succeed" but nobody moves: the far bank of a river.
    executor_still = RecordingExecutor(clock=clock)
    ctx = context(executor_still)
    outcome = None
    for _ in range(50):
        outcome = step.step(snap(), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done
    assert "written off" in outcome.note
    legs = [a for a in executor_still.actions if isinstance(a, MoveTo)]
    assert len(legs) <= svc.patrol_attempts + 1, "give up, do not orbit"


def test_hostiles_close_by_divert_the_survey_tick_to_combat():
    clock = Clock()
    combat = StubCombat([AttackUnit(9, (1010, 1000))])
    step, svc, world, here, executor, ctx = surveying(
        clock, [(1060, 1000)], combat=combat
    )
    near = monster(9, (1010, 1000))  # inside survey_engage_radius (30)
    outcome = step.step(snap(monsters=[near]), ctx)
    assert combat.calls == 1
    assert outcome.note == "fighting"
    # A distant one is walked around, not hunted (R176 Q1).
    far = monster(10, (1200, 1000))
    step.step(snap(monsters=[far]), ctx)
    assert combat.calls == 1, "beyond the radius, surveying continues"


def test_the_leg_budget_ends_a_survey_that_cannot_converge():
    clock = Clock()
    alerts = []
    step, svc, world, here, executor, ctx = surveying(
        clock, [(9000, 9000)], alerts=alerts, survey_max_legs=5,
    )
    # The frontier is absurdly far and the walker teleports each leg but
    # the service never closes it (FrontierWorld only closes within 5):
    # the budget, not patience, must end this.
    outcome = None
    for _ in range(200):
        outcome = step.step(snap(pos=here["pos"]), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done
    assert any("leg budget" in a for a in alerts)


def test_a_fight_going_nowhere_stops_gating_the_survey():
    """The first Cold Plains survey's 14-minute stall, as a regression.

    Every dash toward the monster SUCCEEDS (walkable ground) and none
    arrives — so the failed-walk write-off never fires. Neither distance
    nor the monster's hp moves; after `survey_fight_patience` such ticks
    the monster is written off and the survey resumes.
    """
    clock = Clock()
    combat = StubCombat([MoveTo((1015, 1000), toward=7)] * 100)
    step, svc, world, here, executor, ctx = surveying(
        clock, [(1060, 1000)], combat=combat
    )
    walled = monster(7, (1020, 1000))  # inside the engage radius, forever
    fighting = 0
    outcome = None
    for _ in range(svc.survey_fight_patience + 60):
        # The executor "moves" the player only for survey legs; combat
        # dashes go nowhere, like a fence the path skirts endlessly.
        outcome = step.step(snap(pos=here["pos"], monsters=[walled]), ctx)
        if outcome.note == "fighting":
            fighting += 1
            here["pos"] = HOME  # dashes never actually move us
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done, "the survey must escape the fight"
    assert fighting <= svc.survey_fight_patience + 1
    assert 7 in step._unreachable


def test_a_fight_that_is_working_keeps_the_tick():
    """Distance closing or hp falling is progress; patience never fires."""
    clock = Clock()
    combat = StubCombat([MoveTo((1015, 1000), toward=7)] * 100)
    step, svc, world, here, executor, ctx = surveying(
        clock, [(1060, 1000)], combat=combat
    )
    hp = 100
    for _ in range(svc.survey_fight_patience * 2):
        dying = monster(7, (1010, 1000))
        dying = type(dying)(**{**dying.__dict__, "hp": hp})
        outcome = step.step(snap(monsters=[dying]), ctx)
        assert outcome.note == "fighting", "a dying monster keeps the tick"
        hp = max(1, hp - 1)  # the poison is working
        clock.advance(0.5)
    assert 7 not in step._unreachable


def test_the_survey_target_is_sticky_between_ticks():
    """Two near-equidistant frontiers must not trade 'nearest' forever."""
    clock = Clock()
    step, svc, world, here, executor, ctx = surveying(
        clock, [(1060, 1000), (940, 1000)]  # opposite sides, equal-ish
    )
    outcome = None
    for _ in range(200):
        outcome = step.step(snap(pos=here["pos"]), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done
    assert world.points == [], "both sides must eventually be visited"
    # The walk must not alternate directions: once a target is chosen the
    # legs run monotonically toward it until it is dealt with.
    moves = [a.target[0] for a in executor.actions if isinstance(a, MoveTo)]
    switches = sum(
        1 for a, b, c in zip(moves, moves[1:], moves[2:], strict=False)
        if (b - a) * (c - b) < 0
    )
    assert switches <= 1, f"direction flapped {switches} times: {moves}"


def test_a_survey_with_no_service_finishes_honestly():
    clock = Clock()
    svc = services(clock)  # survey_targets stays None
    step = make_step("survey", svc)
    outcome = step.step(snap(), context())
    assert outcome.done and "no survey service" in outcome.note


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
