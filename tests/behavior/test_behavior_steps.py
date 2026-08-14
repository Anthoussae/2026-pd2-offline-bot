"""The step handlers: clearance termination, the sweep, the full-inventory guard."""

from pathlib import Path

import pytest

from pd2bot import offsets
from pd2bot.behavior.actions import AttackUnit, MoveTo, PickUpItem
from pd2bot.behavior.engine import EngineContext
from pd2bot.behavior.execute import RecordingExecutor
from pd2bot.behavior.necro import CombatConfig, NecroCombat
from pd2bot.behavior.run import RunError, build_states, load_run
from pd2bot.behavior.steps import RunServices, _chebyshev, build_registry
from pd2bot.nav.navigate import NavigationError
from pd2bot.perception.items import CarriedItems
from pd2bot.perception.player import Player
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.perception.uistate import UIState
from pd2bot.perception.units import GameObject, GroundItem, Monster
from pd2bot.perception.world import Area
from pd2bot.pickit import Pickit, Rule

REPO = Path(__file__).resolve().parents[2]
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


def snap(pos=HOME, monsters=(), items=(), allies=(), objects=(), ui=None,
         area=FIELD, corpses=()):
    return GameSnapshot(
        in_game=True, taken_at=0.0, player=player(pos),
        area=Area(level_no=area, position=(0, 0), size=(500, 500)),
        monsters=tuple(monsters), ground_items=tuple(items),
        allies=tuple(allies), objects=tuple(objects), ui=ui,
        corpses=tuple(corpses),
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

    def approach(self, snap, position, via=None):
        self.approach_calls += 1
        self.approach_targets = getattr(self, "approach_targets", [])
        self.approach_targets.append((position, via))
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
    for point in step.patrol_points(HOME, snap().area):
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


# -- the border livelock's three fixes (R189, T55 run 2) ---------------------------


def test_a_collect_walk_that_lands_short_is_written_off():
    """T55 run 2: the walk to the seam item ARRIVED 5 subtiles short of
    pickup reach (4) every time, clicked nothing, and cost nothing —
    collect's only budget counted clicks. Walks that get no closer now
    pay the same budget as every other mover."""
    clock = Clock()
    svc = services(clock)
    step = make_step("pickup", svc)
    item = GroundItem(unit_id=88, kind=999, position=(1040, 1000), quality=RARE)
    here = {"pos": HOME}

    def react(action):
        if isinstance(action, MoveTo):
            here["pos"] = (1035, 1000)  # honest arrival, 5 short, forever

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    for _ in range(12):
        step.step(snap(pos=here["pos"], items=[item]), ctx)
        clock.advance(2.0)
    assert 88 in svc.stuck, "the short-arriving walk never spent a budget"
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert len(moves) <= 1 + svc.pickup_attempts


def test_subtile_wobble_does_not_reset_the_patrol_budget():
    """R189 b: the run-2 ping-pong landed a subtile closer now and then,
    and that hair kept the no-progress budget resetting forever. Progress
    now needs to beat the best by `patrol_progress_margin`."""
    clock = Clock()
    svc = services(clock)
    step = make_step(
        "clear_radius", svc, {"radius": 96, "center": "arrival", "patrol": True}
    )
    here = {"pos": HOME}
    target_point = step.patrol_points(HOME, snap().area)[0]
    legs = {"n": 0}

    def react(action):
        if isinstance(action, MoveTo):
            # Land alternately 7 and 6 subtiles short of the ring point:
            # a 1-subtile "improvement" every other leg, never arriving.
            legs["n"] += 1
            offset = 6 if legs["n"] % 2 else 7
            here["pos"] = (target_point[0] - offset, target_point[1])

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    gave_up = None
    for _ in range(30):
        outcome = step.step(snap(pos=here["pos"]), ctx)
        clock.advance(0.5)
        if outcome.note and "gave up" in outcome.note:
            gave_up = outcome.note
            break
    assert gave_up is not None, (
        "the wobble kept the budget resetting — the T55 run 2 loop"
    )


def test_ring_points_outside_the_area_are_dropped_at_birth():
    """R189 c: 'clear Cold Plains' must never chase ground that belongs
    to Blood Moor — a seam point stops existing as a target."""
    clock = Clock()
    svc = services(clock)
    step = make_step(
        "clear_radius", svc, {"radius": 96, "center": "arrival", "patrol": True}
    )
    # An area whose right edge sits at x = 1050 (210 tiles x 5): the east
    # ring point (~1063) is beyond it; most of the ring is inside.
    narrow = Area(level_no=FIELD, position=(0, 0), size=(210, 500))
    points = step.patrol_points(HOME, narrow)
    assert points, "the filter emptied a mostly-inside ring"
    left, top, right, bottom = narrow.bounds_subtiles
    for x, y in points:
        assert left + 4 <= x < right - 4, f"seam point {x, y} survived"
    assert len(points) < svc.patrol_points  # the east point is gone


# -- the chat console belongs to the operator (T54 run 4) --------------------------


def test_a_lone_chat_console_is_left_for_the_operator():
    """The field panel-recovery ESC'd the chat console over and over
    while the user typed `abort`, wiping the half-typed line each time —
    the abort never reached chat. Nothing in the field opens the console
    but a human, so a lone console is theirs, not a stray."""
    clock = Clock()
    cleared = []
    svc = services(clock, clear_panels=lambda: cleared.append(1))
    step = make_step("clear_radius", svc, {"radius": 96, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    step.step(snap(ui=panels(offsets.UI_CHAT_CONSOLE)), ctx)
    assert cleared == [], "the operator's chat console was closed"


def test_a_stray_esc_menu_is_still_cleared():
    clock = Clock()
    cleared = []
    svc = services(clock, clear_panels=lambda: cleared.append(1))
    step = make_step("clear_radius", svc, {"radius": 96, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    outcome = step.step(snap(ui=panels(offsets.UI_ESCMENU_MAIN)), ctx)
    assert cleared == [1] and outcome.note == "closed a stray panel"


def test_console_alongside_another_blocking_panel_is_fair_game():
    # A console AND an ESC menu: something is genuinely stuck; recovery
    # proceeds (ESC closes one panel per press, whichever it is).
    clock = Clock()
    cleared = []
    svc = services(clock, clear_panels=lambda: cleared.append(1))
    step = make_step("clear_radius", svc, {"radius": 96, "center": "arrival"})
    ctx = context()
    ctx.notes["arrival"] = HOME
    step.step(
        snap(ui=panels(offsets.UI_CHAT_CONSOLE, offsets.UI_ESCMENU_MAIN)), ctx
    )
    assert cleared == [1]


# -- route-aware legs (R181) ------------------------------------------------------
#
# The atlas answered every NAVIGATOR question and no STEP ever asked it:
# legs were straight-line bearings, so far-corner targets clamped at fences
# and burned no-progress budgets, and a bearing hop happily crossed a zone
# exit (T53 run 2 wandered into Stony Field). These pin the new contract:
# legs follow the route's answer, and "no route" is an instant write-off.


def test_route_leg_walks_around_the_wall_not_into_the_pocket():
    from pd2bot.behavior.steps import _route_leg

    clock = Clock()
    # A U-shaped pocket between us and the target: the bearing is +x,
    # straight into the pocket; the route goes up (+y), across, and down.
    target = (1040, 1000)
    route = [(1000, 1020), (1040, 1020), target]
    svc = services(clock, route_to=lambda t: route)
    leg = _route_leg(svc, HOME, target)
    assert leg == (1000, 1020)  # toward the first corner, capped at patrol_step
    # The old bearing hop is what we must NOT get:
    assert leg != (1020, 1000)


def test_route_leg_without_a_service_is_the_bearing_hop():
    from pd2bot.behavior.steps import _route_leg

    svc = services(Clock())
    assert svc.route_to is None
    assert _route_leg(svc, HOME, (1040, 1000)) == (1020, 1000)


def test_route_leg_skips_waypoints_already_underfoot():
    from pd2bot.behavior.steps import _route_leg

    route = [(1001, 1000), (1040, 1000)]
    svc = services(Clock(), route_to=lambda t: route)
    assert _route_leg(svc, HOME, (1040, 1000)) == (1020, 1000)


def test_patrol_walks_the_routes_answer_not_the_bearing():
    clock = Clock()
    corner = (1000, 1060)
    step, svc, here, executor, ctx = patrolling(
        clock, route_to=lambda t: [corner, t]
    )
    step.step(snap(pos=here["pos"]), ctx)
    first_move = next(a for a in executor.actions if isinstance(a, MoveTo))
    assert first_move.target == (1000, 1020)  # toward the corner, not the ring


def test_patrol_writes_off_a_routeless_point_after_two_asks():
    """No-path targets still fail FAST — two ticks, zero legs — but never
    on a single answer: T55 run 1's torn grid read produced five spurious
    no-routes in one second, writing off points the clearance had just
    walked. One answer is a reading; two over fresh grids is a fact."""
    clock = Clock()
    step, svc, here, executor, ctx = patrolling(clock, route_to=lambda t: None)
    outcome = drive(step, here, ctx, clock, ticks=40)
    assert outcome is not None, "routeless points must not hold the step open"
    assert not [a for a in executor.actions if isinstance(a, MoveTo)], (
        "a routeless point earned walking legs"
    )
    assert len(step._visited) == svc.patrol_points


def test_one_no_route_answer_is_not_believed():
    clock = Clock()
    answers = [None, [(1000, 1060)], [(1000, 1060)]]  # a torn read, then honest
    step, svc, here, executor, ctx = patrolling(
        clock, route_to=lambda t: answers.pop(0) if answers else [(1000, 1060)]
    )
    first = step.step(snap(pos=here["pos"]), ctx)
    assert "asking again" in first.note
    second = step.step(snap(pos=here["pos"]), ctx)
    assert "asking again" not in second.note  # the fresh grid answered
    assert [a for a in executor.actions if isinstance(a, MoveTo)], (
        "the recovered route was not walked"
    )
    assert not step._visited, "a point was written off on one torn answer"


def test_survey_writes_off_a_routeless_frontier_on_the_first_tick():
    clock = Clock()
    svc = services(
        clock,
        route_to=lambda t: None,
        survey_targets=lambda: [(1200, 1200)],
        survey_coverage=lambda: "1 room",
    )
    step = make_step("survey", svc)
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    first = step.step(snap(), ctx)
    assert "asking again" in first.note  # one answer is a reading
    outcome = step.step(snap(), ctx)
    assert "wrote off" in outcome.note  # two is a fact
    assert executor.actions == []


def test_clearance_writes_off_a_routeless_monster_and_steers_by_route():
    clock = Clock()
    combat = StubCombat()
    svc = services(clock, combat=combat, route_to=lambda t: None)
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    ctx = context(RecordingExecutor(clock=clock))
    ctx.notes["arrival"] = HOME
    far = monster(1, (1100, 1000))  # inside the clearance, outside the fight
    first = step.step(snap(monsters=[far]), ctx)
    assert "asking again" in first.note  # one torn answer is not believed
    outcome = step.step(snap(monsters=[far]), ctx)
    assert outcome.acted and "no route" in outcome.note
    assert 1 in step._unreachable, "the routeless monster was not written off"
    assert combat.approach_calls == 0, "approach was asked despite no route"


def test_clearance_hands_the_route_waypoint_to_the_approach():
    clock = Clock()
    corner = (1050, 1040)
    combat = StubCombat(approach_script=[MoveTo(corner)])
    svc = services(
        clock, combat=combat, route_to=lambda t: [corner, t]
    )
    step = make_step("clear_radius", svc, {"radius": 150, "center": "arrival"})
    ctx = context(RecordingExecutor(clock=clock))
    ctx.notes["arrival"] = HOME
    far = monster(1, (1100, 1000))
    step.step(snap(monsters=[far]), ctx)
    assert combat.approach_targets == [((1100, 1000), corner)], (
        "the module must gate on the monster and steer by the route"
    )


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


def test_the_sweep_walks_the_circle_while_a_sighting_is_pending():
    """T3 (R186): the re-walk now needs EVIDENCE. With a wanted sighting
    on the books — recorded by the clearance, never collected — the
    sweep must still walk its circle the way it always did."""
    clock = Clock()
    step, svc, here, executor, ctx = sweeping(clock)
    # The clearance saw a rune on the far side and never got it. The
    # memo entry is exactly what it would have recorded.
    rune = GroundItem(unit_id=77, kind=999, position=(1070, 1000), quality=RARE)
    svc.wanted_seen[77] = (rune.position, rune.kind, None)

    def visible(pos):
        # Stand in for the client's horizon, which is what actually hides
        # it — and the pickup itself: a clicked rune leaves the ground.
        if any(isinstance(a, PickUpItem) and a.unit_id == 77
               for a in executor.actions):
            return []
        return [rune] if _chebyshev(rune.position, pos) <= 50 else []

    outcome = None
    for _ in range(400):
        outcome = step.step(snap(pos=here["pos"], items=visible(here["pos"])), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done
    assert [a for a in executor.actions if isinstance(a, MoveTo)], "it never moved"
    assert [a for a in executor.actions if isinstance(a, PickUpItem)
            and a.unit_id == 77], "the far-side item was never even attempted"
    assert 77 not in svc.wanted_seen, "the sighting was never reaped"


def test_the_sweep_skips_the_ring_when_every_sighting_is_accounted_for():
    """The other half of T3: the clearance patrolled the same circle and
    its memo is empty — the old unconditional re-walk spent 60-120 s
    confirming emptiness the memo already proves."""
    clock = Clock()
    step, svc, here, executor, ctx = sweeping(clock)
    outcome = step.step(snap(pos=here["pos"]), ctx)
    assert outcome.done
    assert "ring walk skipped" in outcome.note
    assert not [a for a in executor.actions if isinstance(a, MoveTo)]


def test_a_stuck_sighting_does_not_hold_the_sweep_open():
    # Written off as unpickable = not pending: the sweep must not re-walk
    # the ring for an item three clicks already failed to lift.
    clock = Clock()
    step, svc, here, executor, ctx = sweeping(clock)
    svc.wanted_seen[77] = ((1070, 1000), 999, None)
    svc.stuck.add(77)
    outcome = step.step(snap(pos=here["pos"]), ctx)
    assert outcome.done and "ring walk skipped" in outcome.note


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
    for _ in range(9):  # more ticks than pickup_click_attempts
        step.step(world, ctx)
        clock.advance(2.0)
    assert len(executor.actions) == svc.pickup_click_attempts  # bounded, not a loop
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
    svc.attempts[601] = svc.pickup_click_attempts
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
    svc.attempts[602] = svc.pickup_click_attempts
    assert not step.collect(snap(items=[other]), ctx, other)
    assert svc.cleanse_queued, "601's exhaustion must not block 602's cleanse"


def test_a_walk_away_that_gains_nothing_spends_its_patience():
    """Review issue 001: a clamped walk ARRIVES without gaining ground,
    so 'send succeeded' must not be the loop condition. A wanted item the
    bot cannot get clear of (boxed in) costs patrol_attempts ticks, then
    the cleanse drops anyway — one risky drop beats a pinned character
    that every watchdog is blind to (each tick sends real input)."""
    step, svc, executor, ctx, calls = hygiene_setup()
    svc.cleanse_queued = True
    rune = GroundItem(unit_id=601, kind=999, position=(1003, 1000), quality=RARE)
    world = snap(items=[rune])  # the player never moves: walks are clamped
    for _ in range(svc.patrol_attempts + 2):
        if calls:
            break
        assert step.maybe_cleanse(world, ctx)
    assert calls == [1], "patience spent: the cleanse must proceed, not loop"


def test_a_step_off_that_gains_nothing_spends_its_patience():
    step, svc, executor, ctx, calls = hygiene_setup()
    svc.cleanse_dropped_at = HOME
    svc.stuck.add(601)
    svc.inventory_full = True
    for _ in range(svc.patrol_attempts + 2):
        if svc.cleanse_dropped_at is None:
            break
        step.maybe_cleanse(snap(), ctx)  # the player never leaves the pile
    assert svc.cleanse_dropped_at is None, "patience spent: marker must clear"
    assert not svc.inventory_full and 601 in svc.cleanse_retried


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


# -- potion pickup: tiers, the belt-full diagnosis, arrival telemetry ------------
#
# T56 (2026-08-02): game 2 chickened at 47% with healing potions on the
# ground all game. Three causes, each pinned here: only ONE healing tier
# (hp5/606) was in the kind table, a click miss was diagnosed as "belt
# full for the type", and the type write-off never expired when drinking
# made room.


def belt_potion(uid, kind, slot):
    from pd2bot.perception.items import CarriedItem
    return CarriedItem(
        unit_id=uid, kind=kind, quality=2, mode=offsets.ITEM_MODE_IN_BELT,
        game_location=0, node_page=0, position=(slot, 0), item_level=1,
    )


def carried_with_belt(*potions):
    return CarriedItems(items=tuple(potions), skipped=0)


def test_every_potion_tier_is_recognized():
    # The game's own code table (config/item_codes.toml, T42): hp1-hp5 are
    # kinds 602-606, mp1-mp5 are 607-611. A tier missing from the sets is
    # invisible to the pickit, the town refill AND the belt hygiene — the
    # T56 starvation had hp4s in the inventory reported as "no stock".
    from pd2bot.pickit import potion_type_of
    for kind in (602, 603, 604, 605, 606):
        item = GroundItem(unit_id=1, kind=kind, position=HOME, quality=2)
        assert potion_type_of(item) == "healing", kind
    for kind in (607, 608, 609, 610, 611):
        item = GroundItem(unit_id=1, kind=kind, position=HOME, quality=2)
        assert potion_type_of(item) == "mana", kind
    for kind in (530, 531):
        item = GroundItem(unit_id=1, kind=kind, position=HOME, quality=2)
        assert potion_type_of(item) == "rejuv", kind


def test_a_click_miss_with_belt_room_blames_the_item_not_the_type():
    clock = Clock()
    alerts = []
    svc = services(clock, alerts=alerts)
    svc.carried = lambda: carried_with_belt(belt_potion(1, HEAL, 2))  # 1/8: room
    step = make_step("pickup", svc)
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    potion = GroundItem(unit_id=70, kind=HEAL, position=(1001, 1000), quality=2)
    world = snap(items=[potion])
    for _ in range(10):  # past pickup_click_attempts
        step.step(world, ctx)
        clock.advance(2.0)
    assert 70 in svc.stuck  # the ITEM is written off
    assert "healing" not in svc.belt_full  # the TYPE stays wanted
    assert alerts and "click misses suspected" in alerts[0]
    # A different healing potion is still collected.
    other = GroundItem(unit_id=71, kind=605, position=(1001, 1000), quality=2)
    step.step(snap(items=[other]), ctx)
    assert executor.actions[-1] == PickUpItem(71, (1001, 1000))


def test_a_refused_potion_marks_the_type_only_when_the_belt_is_full():
    clock = Clock()
    alerts = []
    svc = services(clock, alerts=alerts)
    svc.carried = lambda: carried_with_belt(
        *(belt_potion(i, HEAL, i) for i in range(8))  # 8/8: genuinely full
    )
    step = make_step("pickup", svc)
    ctx = context(RecordingExecutor(clock=clock))
    ctx.notes["arrival"] = HOME
    potion = GroundItem(unit_id=70, kind=HEAL, position=(1001, 1000), quality=2)
    world = snap(items=[potion])
    for _ in range(10):
        step.step(world, ctx)
        clock.advance(2.0)
    assert "healing" in svc.belt_full
    assert alerts and "belt full for healing" in alerts[0]


def test_the_belt_full_mark_expires_when_drinking_makes_room():
    clock = Clock()
    svc = services(clock)
    svc.belt_full.add("healing")
    svc.carried = lambda: carried_with_belt(belt_potion(1, HEAL, 2))  # room again
    step = make_step("pickup", svc)
    executor = RecordingExecutor(clock=clock)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    potion = GroundItem(unit_id=70, kind=602, position=(1001, 1000), quality=2)
    step.step(snap(items=[potion]), ctx)
    assert "healing" not in svc.belt_full  # re-derived from the live count
    assert executor.actions == [PickUpItem(70, (1001, 1000))]


def test_a_confirmed_pickup_narrates_with_the_belt_census():
    clock = Clock()
    lines = []
    svc = services(clock)
    svc.narrate = lines.append
    svc.carried = lambda: carried_with_belt(belt_potion(1, HEAL, 2))
    step = make_step("pickup", svc)
    ctx = context(RecordingExecutor(clock=clock))
    ctx.notes["arrival"] = HOME
    potion = GroundItem(unit_id=70, kind=605, position=(1001, 1000), quality=2)
    step.step(snap(items=[potion]), ctx)  # the click
    clock.advance(2.0)
    step.step(snap(), ctx)  # gone from the ground: confirmed
    confirmed = [line for line in lines if "came up" in line]
    assert confirmed and "belt healing 1/8, mana 0/4, rejuv 0/4" in confirmed[0]


# -- postures on steps (M6 P3) -------------------------------------------------


class PosturedCombat(StubCombat):
    def __init__(self):
        super().__init__()
        self.postures_set = []

    def set_posture(self, name):
        self.postures_set.append(name)


def test_the_clearance_applies_its_posture_once():
    clock = Clock()
    combat = PosturedCombat()
    svc = services(clock, combat=combat, postures=frozenset({"brisk"}))
    step = make_step("clear_radius", svc, {"radius": 96, "posture": "brisk"})
    ctx = context()
    step.step(snap(), ctx)
    step.step(snap(), ctx)
    assert combat.postures_set == ["brisk"], "once, on the first tick"


def test_a_step_without_a_posture_leaves_the_module_alone():
    clock = Clock()
    combat = PosturedCombat()
    svc = services(clock, combat=combat, postures=frozenset({"brisk"}))
    step = make_step("clear_radius", svc, {"radius": 96})
    step.step(snap(), context())
    assert combat.postures_set == []


def test_an_unknown_posture_fails_at_build_time():
    """The same place every other run-file mistake fails: before the bot
    has moved, not mid-run in Hell."""
    clock = Clock()
    svc = services(clock, postures=frozenset({"brisk"}))
    with pytest.raises(RunError, match="unknown posture"):
        make_step("clear_radius", svc, {"radius": 96, "posture": "reckless"})
    # No postures loaded at all (sims, drills): naming one is refused too.
    bare = services(clock)
    with pytest.raises(RunError, match="no postures"):
        make_step("clear_radius", bare, {"radius": 96, "posture": "brisk"})


# -- pending sightings re-ask wantedness (M6 P3, review 002) -------------------


def test_a_sighting_that_stopped_being_wanted_skips_the_ring():
    """The review's validation verbatim: a mana potion is sighted,
    `belt_full` gains "mana" (and the belt really has no room), and the
    sweep must skip its ring instead of walking for a bottle nobody
    would pick up on arrival."""
    clock = Clock()
    step, svc, here, executor, ctx = sweeping(clock)
    svc.wanted_seen[88] = ((1070, 1000), 530, "mana")
    svc.belt_full.add("mana")
    # carried() reports an empty belt but TEST_PICKIT's capacity for mana
    # is what _belt_has_room checks against; force "no room" the simple
    # way: capacity 0 via a full-looking belt is fiddly, so assert via
    # the outcome — with capacity > 0 the mark would expire instead.
    svc.pickit.belt_capacity["mana"] = 0
    try:
        outcome = step.step(snap(pos=here["pos"]), ctx)
    finally:
        del svc.pickit.belt_capacity["mana"]
    assert outcome.done and "ring walk skipped" in outcome.note
    assert not [a for a in executor.actions if isinstance(a, MoveTo)]


# -- the seam filter and the missing first-tick area (M6 P3, review 003) -------


def test_no_ring_is_cached_until_an_area_was_available_to_filter():
    clock = Clock()
    svc = services(clock)
    step = make_step(
        "clear_radius", svc, {"radius": 96, "center": "arrival", "patrol": True}
    )
    # First tick: mid-transition, no area readable. Nothing may be cached.
    assert step.patrol_points(HOME, None) == []
    assert step._points is None, "an unfiltered ring was cached"
    # Second tick: a narrow area arrives; the ring is filtered against it.
    narrow = Area(level_no=FIELD, position=(0, 0), size=(220, 500))
    points = step.patrol_points(HOME, narrow)
    assert points, "the ring never got planned"
    left, top, right, bottom = narrow.bounds_subtiles
    assert all(
        left + 4 <= x < right - 4 and top + 4 <= y < bottom - 4
        for x, y in points
    ), "a seam point survived the late filter"


# -- the traverse step (M6 P2) -------------------------------------------------


def _exit_scan(area, exits, rooms=()):
    from pd2bot.perception.exits import ExitScan, LevelExit

    return ExitScan(
        exits=tuple(LevelExit(position=p, dest_area=d) for p, d in exits),
        area=area,
        rooms=tuple(rooms),
        rooms_walked=len(rooms),
    )


def traversing(clock, *, here=20, dest=21, exit_pos=(1060, 1000),
               recall=None, combat=None, runlog=None):
    """A traverse step over a scripted world: clicking the staircase
    flips the area after a beat, like the client's walk + load."""
    world = {"area": here, "pos": HOME, "flip_at": None}
    remembered = []
    extra = {"runlog": runlog} if runlog is not None else {}
    svc = services(
        clock,
        combat=combat if combat is not None else StubCombat(),
        level_exits=lambda: _exit_scan(
            world["area"], [(exit_pos, dest)] if world["area"] == here else []
        ),
        exit_recall=(lambda a, d: recall) if recall is not None else None,
        exit_remember=lambda a, d, p: remembered.append((a, d, p)),
        **extra,
    )
    step = make_step("traverse", svc, {"dest": dest})

    def react(action):
        from pd2bot.behavior.actions import InteractObject

        if isinstance(action, MoveTo):
            world["pos"] = action.target
        if isinstance(action, InteractObject):
            world["flip_at"] = clock() + 1.0  # the walk + load beat

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)

    def tick():
        if world["flip_at"] is not None and clock() >= world["flip_at"]:
            world["area"] = dest
            world["flip_at"] = None
        return step.step(snap(pos=world["pos"], area=world["area"]), ctx)

    return step, world, remembered, executor, ctx, tick


def test_traverse_walks_clicks_and_proves_arrival_by_area_id():
    from pd2bot.behavior.actions import InteractObject

    clock = Clock()
    step, world, remembered, executor, ctx, tick = traversing(clock)
    outcome = None
    for _ in range(60):
        outcome = tick()
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done
    assert "arrived in Tower Cellar Level 1" in outcome.note
    assert ctx.notes["arrival"] == world["pos"]
    moves = [a for a in executor.actions if isinstance(a, MoveTo)]
    assert moves, "it never walked toward the exit"
    clicks = [a for a in executor.actions if isinstance(a, InteractObject)]
    assert len(clicks) == 1 and clicks[0].position == (1060, 1000)
    # First discovery is written back to the memory.
    assert remembered == [(20, 21, (1060, 1000))]


def test_traverse_starts_from_memory_and_reclicks_are_paced():
    from pd2bot.behavior.actions import InteractObject

    clock = Clock()
    # Memory already knows the exit; put the player right beside it so
    # the first tick clicks. The scripted flip is DISABLED (flip_at
    # cleared each react) by recreating the world without a flip: here
    # we just never advance past flip because the click sets flip 1.0s
    # out and we tick faster than that at first.
    step, world, remembered, executor, ctx, tick = traversing(
        clock, exit_pos=(1004, 1000), recall=(1004, 1000)
    )
    tick()  # click 1 (from memory, no walking needed)
    clicks = lambda: [  # noqa: E731
        a for a in executor.actions
        if isinstance(a, InteractObject)
    ]
    assert len(clicks()) == 1
    clock.advance(1.0)  # still inside exit_retry_s
    world["flip_at"] = None  # the transition never resolves this time
    tick()
    assert len(clicks()) == 1, "re-clicked inside the retry window"
    clock.advance(5.0)
    tick()
    assert len(clicks()) == 2, "the paced re-click never came"


def test_traverse_raises_loudly_when_no_exit_leads_there():
    clock = Clock()
    step, world, remembered, executor, ctx, tick = traversing(clock, dest=99)
    # The scan answers for area 20 but its only exit leads to 21, not 99:
    # the run file asked for a transition this map does not have.
    step.services.level_exits = lambda: _exit_scan(20, [((1060, 1000), 21)])
    with pytest.raises(NavigationError, match="no exit"):
        tick()


def test_traverse_lets_the_fight_own_the_tick():
    clock = Clock()
    fighting = StubCombat(script=[MoveTo((1002, 1002))])  # one combat decision
    step, world, remembered, executor, ctx, tick = traversing(
        clock, combat=fighting
    )
    outcome = tick()
    assert outcome.acted and not outcome.done
    # The one action sent was the COMBAT's, not a traverse leg (the
    # combat move and a route leg differ: the leg aims at the exit).
    assert executor.actions == [MoveTo((1002, 1002))]


def test_traverse_seeks_unvisited_rooms_until_the_exit_loads():
    """The T70 descent fix: preset data only loads around the player, so
    a scan that lacks the exit means 'not visible from here', never
    'does not exist'. The step must walk toward unvisited room centres
    (static data, atlas-routable) and re-scan until the staircase
    appears — then use it exactly as if it had always been known."""
    from pd2bot.behavior.actions import InteractObject

    clock = Clock()
    world = {"pos": HOME, "area": 20, "flip_at": None}
    far_room = (1200, 1000)  # ~200 subtiles east; its data is not loaded
    dest = 21
    exit_pos = (1195, 1000)
    remembered = []

    def scan():
        # The exit's room only reveals its presets once the character
        # has been NEAR it — the live discoverability limit, scripted.
        near = _chebyshev(world["pos"], far_room) <= 25
        return _exit_scan(
            world["area"],
            [(exit_pos, dest)] if near else [],
            rooms=((1005, 1000), far_room),
        )

    svc = services(
        clock,
        level_exits=scan,
        exit_remember=lambda a, d, p: remembered.append((a, d, p)),
    )
    step = make_step("traverse", svc, {"dest": dest})

    def react(action):
        if isinstance(action, MoveTo):
            world["pos"] = action.target
        if isinstance(action, InteractObject):
            world["flip_at"] = clock() + 1.0

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)

    outcome = None
    for _ in range(80):
        if world["flip_at"] is not None and clock() >= world["flip_at"]:
            world["area"] = dest
            world["flip_at"] = None
        outcome = step.step(snap(pos=world["pos"], area=world["area"]), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done, "the seek never found the exit"
    # It walked east toward the unloaded room, clicked, and arrived.
    assert any(
        isinstance(a, MoveTo) and a.target[0] > 1100 for a in executor.actions
    ), "no seek leg ever approached the far room"
    assert any(isinstance(a, InteractObject) for a in executor.actions)
    # The discovery was written back: next run skips the whole search.
    assert (20, dest, exit_pos) in remembered


def test_traverse_reclicks_only_when_the_walk_stalls():
    """Progress-aware pacing (the T70 'pause before clicking the
    stairs'): the first click is a WALK ORDER the client honours over
    several seconds, and while the character keeps closing on the
    staircase no re-click may fire — the old time-based pacing burned
    ~10s per transition re-issuing orders mid-walk."""
    from pd2bot.behavior.actions import InteractObject

    clock = Clock()
    # Exit at the edge of click range; the walk closes 2 subtiles per
    # tick, slower than the old timer would tolerate.
    step, world, remembered, executor, ctx, tick = traversing(
        clock, exit_pos=(1016, 1000), recall=(1016, 1000)
    )

    def clicks():
        return [a for a in executor.actions if isinstance(a, InteractObject)]

    def tick_unflipped():
        # This test drives the WALK, not the transition: the scripted
        # flip a click schedules must never fire, or the step just
        # arrives and nothing about pacing gets tested.
        world["flip_at"] = None
        return tick()

    tick_unflipped()  # in range: click 1 (the walk order)
    assert len(clicks()) == 1
    # The character closes steadily for 8 ticks x 1s — far past the old
    # 5s timer — and no re-click fires, because progress keeps the
    # clock reset.
    for i in range(8):
        clock.advance(1.0)
        world["pos"] = (world["pos"][0] + 2, 1000)
        if world["pos"][0] >= 1016:
            break
        tick_unflipped()
        assert len(clicks()) == 1, f"re-clicked mid-walk on tick {i}"
    # Now the walk STALLS short of the stairs: the re-click is earned.
    world["pos"] = (1013, 1000)
    tick_unflipped()
    clock.advance(4.0)
    tick_unflipped()
    assert len(clicks()) == 2, "a stalled walk never earned its re-click"


def _runlog(tmp_path, clock):
    from pd2bot.runlog import RunLog

    return RunLog("t", root=tmp_path, clock=clock, wall=lambda: 1786000000.0)


def _events(log, kind):
    from pd2bot.runlog import load

    return [e for e in load(log.directory) if e["kind"] == kind]


def test_a_spent_click_budget_says_why_and_what_it_tried(tmp_path):
    """T71 run 4 wrote eleven items off this way in silence, a Nef rune
    and a flawless emerald among them. The budget being spent is the
    single most informative moment in the pickup path and it emitted
    nothing at all."""
    from pd2bot.behavior.actions import PICKUP_AIM_POINTS

    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    potion = GroundItem(unit_id=910, kind=HEAL, position=(1001, 1000), quality=2)
    svc.attempts[910] = svc.pickup_click_attempts  # the budget is spent

    step.collect(snap(pos=HOME, items=[potion]), ctx, potion)

    gave = _events(log, "item.abandoned")
    assert len(gave) == 1, gave
    assert gave[0]["unit_id"] == 910
    assert gave[0]["clicks"] == svc.pickup_click_attempts
    # The belt is empty, so this is NOT a belt-full case: the honest
    # diagnosis is that the clicks missed.
    assert gave[0]["reason"] == "clicks did not land (belt has room)"
    assert len(gave[0]["aim_points"]) == svc.pickup_click_attempts
    assert gave[0]["aim_points"][0] == list(PICKUP_AIM_POINTS[0])
    assert gave[0]["position"]["world"] == [1001, 1000]


def test_a_write_off_counts_the_neighbours_that_could_have_stolen_the_click(
    tmp_path,
):
    # The density correlation is the leading hypothesis (misses averaged
    # 1.6 neighbours within 2 subtiles against 0.9 for successes), so the
    # number rides on the event rather than being re-derived later.
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    target = GroundItem(unit_id=911, kind=HEAL, position=(1001, 1000), quality=2)
    crowd = [
        target,
        GroundItem(unit_id=912, kind=HEAL, position=(1002, 1000), quality=2),
        GroundItem(unit_id=913, kind=HEAL, position=(1001, 1001), quality=2),
        GroundItem(unit_id=914, kind=HEAL, position=(1040, 1040), quality=2),
    ]
    svc.attempts[911] = svc.pickup_click_attempts

    step.collect(snap(pos=HOME, items=crowd), ctx, target)

    gave = _events(log, "item.abandoned")
    assert gave[0]["neighbours"] == 2, "only the two within 2 subtiles count"


def test_a_belt_full_write_off_is_still_reported_as_belt_full(tmp_path):
    # The belt-full vs click-missed distinction is load-bearing (T56's
    # starvation loop). P1 reports it; it must not re-decide it.
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    full = svc.pickit.belt_capacity.get("healing", 8)
    svc.carried = lambda: carried_with_belt(
        *(belt_potion(800 + i, HEAL, i) for i in range(full))
    )
    potion = GroundItem(unit_id=915, kind=HEAL, position=(1001, 1000), quality=2)
    svc.attempts[915] = svc.pickup_click_attempts

    step.collect(snap(pos=HOME, items=[potion]), ctx, potion)

    gave = _events(log, "item.abandoned")
    assert gave[0]["reason"] == "belt full for healing"


def test_draw_order_collects_the_front_sprite_first(tmp_path):
    """P3 (Direction C): the item drawn ON TOP (largest screen depth,
    wx+wy) is what a click hits, so lift it first to uncover the next —
    instead of the old nearest-to-player order, unrelated to occlusion."""
    clock = Clock()
    step, svc, here, executor, ctx = sweeping(clock)
    a = GroundItem(unit_id=1, kind=702, position=(1000, 1000), quality=RARE)  # depth 2000
    b = GroundItem(unit_id=2, kind=702, position=(1003, 1003), quality=RARE)  # depth 2006, front
    c = GroundItem(unit_id=3, kind=702, position=(1001, 1000), quality=RARE)  # depth 2001
    ordered = step._draw_order([a, b, c])
    assert [i.unit_id for i in ordered] == [2, 3, 1], "front (largest wx+wy) first"


def test_draw_order_is_stable_for_a_single_item():
    from tests.behavior.test_behavior_steps import sweeping  # noqa: F401

    clock = Clock()
    step, *_ = sweeping(clock)
    lone = GroundItem(unit_id=9, kind=606, position=(5, 7), quality=2)
    assert step._draw_order([lone]) == [lone]
    assert step._draw_order([]) == []


def test_a_non_potion_miss_in_a_pile_is_ambiguity_not_a_full_inventory(tmp_path):
    """P4's correctness fix: a rune that will not come up with items packed
    around it is a pile-ambiguity miss (the clicks hit a neighbour), NOT
    proof the inventory is full — it must NOT suppress every OTHER
    non-potion pickup this game, which is what marking inventory-full did.
    But it DOES queue a cleanse now (2026-08-10 live): a genuinely full
    inventory manifests as pile ambiguity whenever drops cluster — 88 of
    that pilot's 89 write-offs took this branch, so the cleanse the full
    grid needed never queued and the operator watched the bot click
    forever with no room. A cleanse costs nothing when the grid is clean."""
    clock = Clock()
    log = _runlog(tmp_path, clock)
    alerts = []
    step, svc, here, executor, ctx = sweeping(clock, alerts=alerts)
    svc.runlog = log
    rune = GroundItem(unit_id=930, kind=702, position=(1001, 1000), quality=RARE)
    crowd = [
        rune,
        GroundItem(unit_id=931, kind=702, position=(1002, 1000), quality=RARE),
        GroundItem(unit_id=932, kind=702, position=(1001, 1001), quality=RARE),
    ]
    svc.attempts[930] = svc.pickup_click_attempts

    step.collect(snap(pos=HOME, items=crowd), ctx, rune)

    assert not svc.inventory_full, "a pile miss must not blame the inventory"
    assert svc.cleanse_queued, "a full grid can hide behind a pile — cleanse"
    assert 930 in svc.stuck, "this item is still written off"
    reason = _events(log, "item.abandoned")[0]["reason"]
    assert "pile ambiguity" in reason
    assert any("pile ambiguity" in a for a in alerts)
    queued = _events(log, "inventory.cleanse_queued")
    assert queued and queued[0]["reason"] == "pile-ambiguity write-off"


def test_a_pile_miss_that_already_had_its_cleanse_retry_queues_nothing(tmp_path):
    # The R173 guard extends to the pile path: a retry that cannot differ
    # is not a retry, so an item that failed AFTER a cleanse-and-step-off
    # must not queue another one.
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock)
    svc.runlog = log
    rune = GroundItem(unit_id=933, kind=702, position=(1001, 1000), quality=RARE)
    crowd = [
        rune,
        GroundItem(unit_id=934, kind=702, position=(1002, 1000), quality=RARE),
    ]
    svc.attempts[933] = svc.pickup_click_attempts
    svc.cleanse_retried.add(933)

    step.collect(snap(pos=HOME, items=crowd), ctx, rune)

    assert not svc.cleanse_queued
    assert _events(log, "inventory.cleanse_queued") == []


def test_a_written_off_item_is_not_re_logged_every_tick(tmp_path):
    """The 2026-08-10 pilot wrote 88 `item.abandoned` events for a handful
    of items: `service_orders` targets the order's unit directly (no
    stuck filter, unlike `wanted_items`), so every serviced tick
    re-entered the spent-budget branch and re-logged the same write-off."""
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    solo = GroundItem(unit_id=950, kind=702, position=(1001, 1000), quality=RARE)
    svc.attempts[950] = svc.pickup_click_attempts

    step.collect(snap(pos=HOME, items=[solo]), ctx, solo)  # the write-off
    clock.advance(1.0)
    acted = step.collect(snap(pos=HOME, items=[solo]), ctx, solo)  # stuck now

    assert acted is False
    assert len(_events(log, "item.abandoned")) == 1


def test_the_full_inventory_mark_is_on_the_record(tmp_path):
    # The 2026-08-10 diagnosis had to be made from the log's SILENCE;
    # the suppression that costs a game's loot now says so in the stream.
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    solo = GroundItem(unit_id=941, kind=702, position=(1001, 1000), quality=RARE)
    svc.attempts[941] = svc.pickup_click_attempts

    step.collect(snap(pos=HOME, items=[solo]), ctx, solo)

    full = _events(log, "inventory.full")
    assert len(full) == 1 and full[0]["unit_id"] == 941


def test_service_orders_runs_a_queued_cleanse_without_inventory_full(tmp_path):
    """The second half of the 2026-08-10 cleanse starvation: while orders
    are being serviced the step's own maybe_cleanse call sits AFTER the
    service_orders return, so the call inside service_orders is the only
    one that can run — and it was gated on `inventory_full`, which the
    pile-ambiguity path (the one that actually queues under a full grid)
    never sets. The gate is gone; maybe_cleanse declines by itself when
    nothing is queued."""
    from pd2bot.behavior.steps.orders import OrderBook

    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    svc.order_book = OrderBook(budget_s=75.0)
    # An order far away (no reap, and the return walk is not this tick's
    # business), a queued cleanse, and the inventory NOT marked full.
    svc.order_book.sight(50, 999, (1200, 1200), now=clock())
    svc.cleanse_queued = True
    svc.cleanse = lambda: 1
    assert not svc.inventory_full

    outcome = step.service_orders(snap(pos=HOME), ctx)

    assert outcome is not None and "cleansing" in outcome.note
    assert _events(log, "inventory.cleanse")
    assert not svc.cleanse_queued


def test_a_terminally_stuck_order_closes_instead_of_waiting_out_the_budget(
    tmp_path,
):
    """An order whose unit is written off AND already had its one
    post-cleanse retry is known futile — everything a cleanse can change
    has been tried. The 2026-08-10 pilots stood in 'pickup pacing' for
    the full 75 s budget per such item."""
    from pd2bot.behavior.steps.orders import OrderBook

    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    svc.order_book = OrderBook(budget_s=75.0)
    svc.order_book.sight(60, 999, (1010, 1000), now=clock())
    svc.stuck.add(60)
    svc.cleanse_retried.add(60)
    lying = GroundItem(unit_id=60, kind=999, position=(1010, 1000), quality=RARE)

    outcome = step.service_orders(snap(pos=HOME, items=[lying]), ctx)

    assert outcome is None, "the closed order must not claim the tick"
    assert svc.order_book.pending() == []
    gave = _events(log, "pickup.order_abandoned")
    assert gave and "post-cleanse retry" in gave[0]["reason"]


def test_a_non_potion_miss_alone_still_marks_the_inventory_full(tmp_path):
    """The no-neighbour case is unchanged: aim-failure-or-full-inventory is
    indistinguishable from persistence, so the conservative suppression
    stays (a real full grid must not be ignored)."""
    clock = Clock()
    log = _runlog(tmp_path, clock)
    alerts = []
    step, svc, here, executor, ctx = sweeping(clock, alerts=alerts)
    svc.runlog = log
    solo = GroundItem(unit_id=940, kind=702, position=(1001, 1000), quality=RARE)
    svc.attempts[940] = svc.pickup_click_attempts

    step.collect(snap(pos=HOME, items=[solo]), ctx, solo)

    assert svc.inventory_full, "no neighbour: keep the conservative full-grid behaviour"
    assert svc.cleanse_queued
    reason = _events(log, "item.abandoned")[0]["reason"]
    assert "aim failure" in reason and "full inventory" in reason


def test_a_pickup_that_lands_on_the_neighbour_says_so(tmp_path):
    """The sharpest signal in T71 run 4 and the bot learned nothing from
    it: a Nef rune missed at (12544, 11084) while a Hel rune ONE subtile
    away came up. Nine of thirteen misses had that shape."""
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    target = GroundItem(unit_id=920, kind=HEAL, position=(1001, 1000), quality=2)
    neighbour = GroundItem(unit_id=921, kind=HEAL, position=(1002, 1000), quality=2)

    # We clicked the TARGET...
    step.collect(snap(pos=HOME, items=[target, neighbour]), ctx, target)
    # ...and had also clicked the neighbour a moment before, so both are
    # pending. The neighbour is what leaves the ground.
    svc.pending_pickup[921] = (HEAL, "healing", (1002, 1000), clock())
    clock.advance(0.5)
    step.confirm_pickups(snap(pos=HOME, items=[target]))

    got = _events(log, "item.collected")
    assert len(got) == 1 and got[0]["unit_id"] == 921
    assert got[0]["attributed_to"] == 920, "the click was aimed at 920"
    assert got[0]["attributed_aim"] == [1001, 1000]


def test_attribution_stays_quiet_when_the_item_was_its_own_target(tmp_path):
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    item = GroundItem(unit_id=922, kind=HEAL, position=(1001, 1000), quality=2)
    step.collect(snap(pos=HOME, items=[item]), ctx, item)
    clock.advance(0.5)
    step.confirm_pickups(snap(pos=HOME))

    got = _events(log, "item.collected")
    assert "attributed_to" not in got[0], "an ordinary pickup needs no blame"


def test_attribution_refuses_to_guess_across_distance_or_time(tmp_path):
    # A loose attribution would poison the measurement it exists to make.
    clock = Clock()
    log = _runlog(tmp_path, clock)
    step, svc, here, executor, ctx = sweeping(clock, runlog=log)
    far = GroundItem(unit_id=923, kind=HEAL, position=(1001, 1000), quality=2)
    step.collect(snap(pos=HOME, items=[far]), ctx, far)

    # Same moment, but 30 subtiles away: one click cannot have hit both.
    svc.pending_pickup[924] = (HEAL, "healing", (1030, 1030), clock())
    clock.advance(0.2)
    step.confirm_pickups(snap(pos=HOME))
    got = [e for e in _events(log, "item.collected") if e["unit_id"] == 924]
    assert "attributed_to" not in got[0]

    # Close enough, but long after the click stopped resolving.
    svc.pending_pickup[925] = (HEAL, "healing", (1002, 1000), clock())
    clock.advance(svc.pickup_retry_s * 2 + 1)
    step.confirm_pickups(snap(pos=HOME))
    got = [e for e in _events(log, "item.collected") if e["unit_id"] == 925]
    assert "attributed_to" not in got[0]


def test_a_swallowed_navigation_error_is_recorded(tmp_path):
    """`send` absorbs NavigationError so one unreachable target cannot end
    a run — correct, and until now completely invisible. T71 run 4 spent
    four ticks of 25-35 s each here with nothing in the log but the tick
    durations."""
    clock = Clock()
    log = _runlog(tmp_path, clock)
    svc = services(clock, runlog=log)
    step = make_step("pickup", svc)

    def refuse(action):
        if isinstance(action, MoveTo):
            raise NavigationError("gave up after 5 plan cycles without progress")

    ctx = context(RecordingExecutor(clock=clock, on_execute=refuse))
    assert step.send(ctx, MoveTo((1050, 1050), toward=42)) is False

    failed = _events(log, "nav.failed")
    assert len(failed) == 1, failed
    assert failed[0]["action"] == "MoveTo"
    assert failed[0]["target"]["world"] == [1050, 1050]
    assert failed[0]["toward"] == 42
    assert "5 plan cycles" in failed[0]["detail"]
    assert failed[0]["elapsed_s"] >= 0


def test_a_wanted_item_on_a_traversal_floor_is_logged(tmp_path):
    """T71 run 4's hole, and the operator's fix request (2026-08-06).

    `item.dropped` used to fire only from `note_wanted_sightings`, which
    the clearance, the sweep and the endgame call and `TraverseStep` does
    not — yet traverse is what collects during a descent. The run logged
    four drops on the one floor that ran a clearance and NONE on the four
    it descended through, while being the artifact meant to answer "what
    did we leave behind".

    The item here sits far outside `pickup_radius`, so it is never a
    collection candidate: the drop is on the record irrespective of
    whether anything could be done about it, which is the whole ask.
    """
    from pd2bot.runlog import RunLog, load

    clock = Clock()
    log = RunLog("t", root=tmp_path, clock=clock, wall=lambda: 1786000000.0)
    step, world, remembered, executor, ctx, tick = traversing(clock, runlog=log)
    far = GroundItem(unit_id=901, kind=999, position=(1400, 1400), quality=RARE)
    step.step(snap(pos=world["pos"], area=20, items=[far]), ctx)

    dropped = [e for e in load(log.directory) if e["kind"] == "item.dropped"]
    assert len(dropped) == 1, f"the drop was not logged: {dropped}"
    assert dropped[0]["unit_id"] == 901
    assert dropped[0]["position"]["world"] == [1400, 1400]
    assert dropped[0]["rule"], "the matching pickit rule must be named"
    assert dropped[0]["at"], "a wanted drop needs its timestamp"
    assert not [a for a in executor.actions if isinstance(a, PickUpItem)], (
        "the far item must be logged, not collected"
    )


def test_a_wanted_drop_is_logged_once_not_once_per_tick(tmp_path):
    # The dedupe that makes always-on logging affordable: a rune lying
    # there for thirty ticks is one event, not thirty.
    from pd2bot.runlog import RunLog, load

    clock = Clock()
    log = RunLog("t", root=tmp_path, clock=clock, wall=lambda: 1786000000.0)
    step, world, remembered, executor, ctx, tick = traversing(clock, runlog=log)
    far = GroundItem(unit_id=902, kind=999, position=(1400, 1400), quality=RARE)
    for _ in range(6):
        step.step(snap(pos=world["pos"], area=20, items=[far]), ctx)
        clock.advance(0.5)

    dropped = [e for e in load(log.directory) if e["kind"] == "item.dropped"]
    assert len(dropped) == 1, f"one event per item, got {len(dropped)}"


def test_junk_on_the_floor_is_never_logged_as_a_wanted_drop(tmp_path):
    # "Whitelisted" is the pickit's verdict, not "an item exists". A log
    # that recorded every dropped item would answer a different question
    # from the one asked and bury the answer to this one.
    from pd2bot.runlog import RunLog, load

    clock = Clock()
    log = RunLog("t", root=tmp_path, clock=clock, wall=lambda: 1786000000.0)
    step, world, remembered, executor, ctx, tick = traversing(clock, runlog=log)
    junk = GroundItem(unit_id=903, kind=999, position=(1005, 1000), quality=2)
    step.step(snap(pos=world["pos"], area=20, items=[junk]), ctx)

    assert not [e for e in load(log.directory) if e["kind"] == "item.dropped"]


def test_traverse_collects_a_wanted_item_en_route():
    """The T70 run 5 Thul, at unit scale: a wanted item on a traversal
    floor wins the tick (combat declined it), and the walk resumes once
    the ground is clean."""
    from pd2bot.behavior.actions import InteractObject

    clock = Clock()
    step, world, remembered, executor, ctx, tick = traversing(
        clock, exit_pos=(1060, 1000), recall=(1060, 1000)
    )
    rune = GroundItem(unit_id=880, kind=606, position=(1002, 1000), quality=2)
    outcome = step.step(snap(pos=world["pos"], area=20, items=[rune]), ctx)
    assert outcome.acted and not outcome.done
    picks = [a for a in executor.actions if isinstance(a, PickUpItem)]
    assert len(picks) == 1 and picks[0].unit_id == 880
    assert not [a for a in executor.actions if isinstance(a, InteractObject)]
    # The click resolving holds the walk (a march away from a click in
    # flight would orphan it) ...
    outcome = step.step(snap(pos=world["pos"], area=20, items=[rune]), ctx)
    assert outcome.waiting
    # ... and a clean floor hands the tick straight back to the traversal.
    clock.advance(2.0)
    step.step(snap(pos=world["pos"], area=20), ctx)
    assert [a for a in executor.actions if isinstance(a, MoveTo)], (
        "the walk never resumed after the pickup"
    )


# -- the countess endgame (M6 P4) ------------------------------------------------


COUNTESS_KIND, COUNTESS_NO = 734, 6
CHAMBER = (1100, 1100)


def countess_monster(pos=CHAMBER, mode=1):
    return Monster(
        unit_id=66, kind=COUNTESS_KIND, position=pos, hp=100, max_hp=100,
        is_champion=False, is_boss=True, is_minion=False,
        unique_no=COUNTESS_NO, mode=mode,
    )


def countess_corpse(pos=CHAMBER):
    return Monster(
        unit_id=66, kind=COUNTESS_KIND, position=pos, hp=0, max_hp=100,
        is_champion=False, is_boss=True, is_minion=False,
        unique_no=COUNTESS_NO, mode=offsets.MONSTER_MODE_DEAD,
    )


def countess_step(clock, *, combat=None, alerts=None, **svc_kw):
    svc = services(clock, combat=combat, alerts=alerts, **svc_kw)
    step = make_step(
        "clear_countess", svc,
        {"chamber_x": CHAMBER[0], "chamber_y": CHAMBER[1],
         "neighborhood_radius": 30, "chamber_radius": 20},
    )
    return step, svc


def settle_neighborhood(step, clock, ctx, make_snap):
    """Drive the composed clearance to done on an empty arrival pocket."""
    step.step(make_snap(), ctx)  # settle timer starts
    clock.advance(6.0)  # past clear_settle_s
    outcome = step.step(make_snap(), ctx)
    assert "neighborhood clear" in (outcome.note or ""), outcome
    return outcome


def test_countess_corpse_confirms_and_publishes_the_chamber_region():
    # The primary kill condition: her pinned identity with a dead mode.
    # The sweep still runs (the sanity pass doubles as drop recon), then
    # the chamber circle goes on the blackboard for pickup to adopt.
    clock = Clock()
    step, svc = countess_step(clock)
    ctx = context()
    ctx.notes["arrival"] = HOME
    dead = countess_corpse((1102, 1101))
    make_snap = lambda: snap(corpses=[dead])  # noqa: E731
    settle_neighborhood(step, clock, ctx, make_snap)
    outcome = None
    for _ in range(40):
        outcome = step.step(make_snap(), ctx)
        clock.advance(0.5)
        if outcome.done:
            break
    assert outcome is not None and outcome.done, "the kill never confirmed"
    assert "down" in outcome.note
    cleared = ctx.notes["cleared"]
    assert cleared["centre"] == (1102, 1101)  # her corpse, not the anchor
    assert cleared["radius"] == 20 and cleared["patrol"] is True


def test_countess_provably_absent_after_the_sweep():
    # The fallback: never seen, never dead — the sweep WALKS its pass and
    # concludes absence rather than waiting on a read that cannot answer.
    # The player must actually move: a static run of the same script is
    # the unproven-absence loud stop below, not this conclusion.
    clock = Clock()
    step, svc = countess_step(clock)
    here = {"pos": HOME}

    def react(action):
        if isinstance(action, MoveTo):
            here["pos"] = action.target

    executor = RecordingExecutor(clock=clock, on_execute=react)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    make_snap = lambda: snap(pos=here["pos"])  # noqa: E731
    settle_neighborhood(step, clock, ctx, make_snap)
    outcome = None
    for _ in range(60):
        outcome = step.step(make_snap(), ctx)
        clock.advance(0.4)
        if outcome.done:
            break
    assert outcome is not None and outcome.done, "absence never concluded"
    assert "provably absent" in outcome.note
    assert ctx.notes["cleared"]["centre"] == CHAMBER


def test_countess_unwalked_sweep_cannot_prove_absence():
    # Review 001's shape, one layer down: with the player pinned in
    # place, every sweep point is skipped as unreachable — the pass saw
    # nothing. Concluding "provably absent" from it would let the
    # flagship drill PASS on a partial run; the step must stop loudly.
    clock = Clock()
    alerts = []
    step, svc = countess_step(clock, alerts=alerts)
    ctx = context()  # the default executor moves nothing
    ctx.notes["arrival"] = HOME
    make_snap = lambda: snap()  # noqa: E731
    settle_neighborhood(step, clock, ctx, make_snap)
    with pytest.raises(NavigationError, match="absence is unproven"):
        for _ in range(60):
            step.step(make_snap(), ctx)
            clock.advance(0.3)
    assert any("COUNTESS UNRESOLVED" in a for a in alerts)


def test_countess_alive_and_unreachable_is_a_loud_stop():
    # The run's whole objective: alive, in sight, and every walk to her
    # failing must END the run loudly — never a silent write-off.
    clock = Clock()
    alerts = []
    combat = StubCombat(approach_script=[
        MoveTo((1010, 1010), toward=66), MoveTo((1010, 1010), toward=66),
    ])
    step, svc = countess_step(clock, combat=combat, alerts=alerts)

    def refuse_walks(action):
        if isinstance(action, MoveTo):
            raise NavigationError("no way through")

    executor = RecordingExecutor(clock=clock, on_execute=refuse_walks)
    ctx = context(executor)
    ctx.notes["arrival"] = HOME
    her = countess_monster()
    make_snap = lambda: snap(monsters=[her])  # noqa: E731
    settle_neighborhood(step, clock, ctx, make_snap)
    with pytest.raises(NavigationError, match="alive and unreachable"):
        for _ in range(30):
            step.step(make_snap(), ctx)
            clock.advance(0.5)
    assert any("COUNTESS UNRESOLVED" in a for a in alerts)


def test_countess_advance_holds_for_the_revive_wall_then_releases():
    # The user's tactic as a brake, with the bound that keeps it a tactic:
    # a cellar with nothing to raise can never grow a wall, and the hold
    # must release loudly rather than hang the run.
    import types

    clock = Clock()
    combat = StubCombat(approach_script=[MoveTo((1010, 1010))])
    combat.config = types.SimpleNamespace(approach_with_revives=2)
    step, svc = countess_step(clock, combat=combat, advance_revive_patience=3)
    ctx = context()
    ctx.notes["arrival"] = HOME
    make_snap = lambda: snap()  # noqa: E731
    settle_neighborhood(step, clock, ctx, make_snap)
    # Walk the staging phase out (static position: the progress budget
    # writes it off and the advance begins).
    outcomes = []
    for _ in range(20):
        outcomes.append(step.step(make_snap(), ctx))
        clock.advance(0.5)
        if combat.approach_calls:
            # The advance resumed — this test's whole claim. Ticking on
            # from a pinned position now ends in the unwalked-sweep loud
            # stop, which is the next test's subject, not this one's.
            break
    braked = [o for o in outcomes if (o.note or "") == "revive brake"]
    assert len(braked) == 3, f"the brake held {len(braked)} ticks, not 3"
    assert combat.approach_calls > 0, "the advance never resumed after the brake"


def test_countess_sweep_budget_spent_unproven_is_a_loud_stop():
    # The <15s budget is a promise: spent with the kill unproven, the
    # step reports and stops — silence is the one forbidden outcome.
    clock = Clock()
    alerts = []
    step, svc = countess_step(clock, alerts=alerts)
    ctx = context()
    ctx.notes["arrival"] = HOME
    make_snap = lambda: snap()  # noqa: E731
    settle_neighborhood(step, clock, ctx, make_snap)
    # Stage writes itself off (static position), the empty advance drops
    # straight into the sweep, and then the budget runs dry mid-pass.
    entered_sweep = False
    with pytest.raises(NavigationError, match="sweep"):
        for _ in range(30):
            outcome = step.step(make_snap(), ctx)
            if "chamber" in (outcome.note or "") or "sweep" in (outcome.note or ""):
                entered_sweep = True
            clock.advance(4.0 if entered_sweep else 0.5)
    assert any("COUNTESS UNRESOLVED" in a for a in alerts)


def test_a_traverse_runs_a_queued_cleanse():
    """The descent's blind spot, found live 2026-08-08.

    `collect` queues a cleanse when a non-potion will not come up, and
    `_mark_inventory_full` then suppresses every non-potion pickup for
    the REST OF THE GAME. A descent run is `town_preamble, waypoint,
    traverse x6` — and `TraverseStep` was the one collecting step that
    never called `maybe_cleanse`. So the queue was set on the first
    cellar floor and served on none of them, and the Countess's drops
    were skipped by a flag raised twenty minutes before she was reached.
    """
    clock = Clock()
    step, world, remembered, executor, ctx, tick = traversing(clock)
    cleansed = []
    step.services.cleanse = lambda: cleansed.append(True) or 1
    step.services.cleanse_queued = True
    step.services.inventory_full = True

    step.step(snap(pos=world["pos"], area=20), ctx)

    assert cleansed, "the traverse never ran the queued cleanse"


def test_a_traverse_does_not_cleanse_with_nothing_queued():
    """It must stay a traversal, not become a step that stops to tidy."""
    clock = Clock()
    step, world, remembered, executor, ctx, tick = traversing(clock)
    cleansed = []
    step.services.cleanse = lambda: cleansed.append(True) or 1
    step.services.cleanse_queued = False

    step.step(snap(pos=world["pos"], area=20), ctx)

    assert not cleansed
