"""The necro module: the skirmish pattern and revive maintenance.

Pure decision-making again, so the tests hand it scripted snapshots and
assert on the actions it returns. What is under test is the USER'S pattern
(R47.2) — contact, wait for tanks, dash, strike, retreat, repeat — plus the
target-selection rules that keep poison doing the killing.
"""

from pd2bot import offsets
from pd2bot.behavior.actions import AttackUnit, CastAtPoint, MoveTo
from pd2bot.behavior.necro import CombatConfig, NecroCombat
from pd2bot.player import Player
from pd2bot.snapshot import GameSnapshot
from pd2bot.units import Monster
from pd2bot.world import Area

TOWN, FIELD = 1, 3
HOME = (1000, 1000)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


def player(pos=HOME, hp=1000):
    return Player(
        name="N", level=91, act=1, position=pos, mode=1,
        hp=hp, max_hp=1000, mana=200, max_mana=400,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


def monster(uid, pos, hp=100, mode=1, alignment=0):
    return Monster(
        unit_id=uid, kind=50, position=pos, hp=hp, max_hp=100,
        is_champion=False, is_boss=False, is_minion=False,
        alignment=alignment, mode=mode,
    )


def corpse(uid, pos):
    return monster(uid, pos, hp=0, mode=offsets.MONSTER_MODE_DEAD)


def ally(uid, pos):
    return monster(uid, pos, alignment=offsets.ALIGNMENT_FRIENDLY)


def wall(count=3, pos=(1004, 1000)):
    """A standing revive wall.

    The skirmish tests need one because approaching is GATED on it (the
    user's protocol: three revives before walking into a pack, and
    desecrate makes its own corpses so there is never a reason to go in
    short-handed). A test that dashed without a wall would be asserting
    behaviour the bot is no longer allowed to have.
    Placed CLOSE to where the tests put hostiles, so the wall reads as
    already engaged and phase 2's wait-for-the-tanks ends immediately.
    """
    return [ally(900 + i, pos) for i in range(count)]


def skirmishing(**kw):
    """A config with the wait-for-the-tanks phase switched off.

    Phases 3-5 (dash, strike, retreat) are a different subject from
    phase 2, and leaving the wait in forces every skirmish test to also
    arrange revives that are already engaged with whichever hostile it
    happens to use. Saying so here beats staging it in each test.
    """
    return CombatConfig(wait_for_revives_s=0.0, **kw)


def snap(pos=HOME, monsters=(), allies=(), corpses=(), area=FIELD):
    return GameSnapshot(
        in_game=True, taken_at=0.0, player=player(pos),
        area=Area(level_no=area, position=(0, 0), size=(500, 500)),
        monsters=tuple(monsters), allies=tuple(allies), corpses=tuple(corpses),
    )


def make(config=None, walkable=None):
    clock = Clock()
    return (
        NecroCombat(
            config=config or CombatConfig(),
            is_walkable=walkable or (lambda p: True),
            clock=clock,
        ),
        clock,
    )


# -- engagement: the skirmish pattern ------------------------------------------


def test_no_hostiles_means_no_decision():
    necro, _ = make()
    assert necro.engage(snap()) is None


def test_never_engages_in_town():
    # Town guards read as monsters to perception (P1 drill D), so this is a
    # correctness rule, not tidiness.
    necro, _ = make()
    assert necro.engage(snap(monsters=[monster(1, (1002, 1000))], area=TOWN)) is None


def test_distant_hostiles_are_not_contact():
    necro, _ = make()
    far = monster(1, (1000 + 60, 1000))  # beyond engage_radius 40
    assert necro.engage(snap(allies=wall(), monsters=[far])) is None


def test_dash_then_strike_then_retreat():
    necro, clock = make(skirmishing())
    target = monster(1, (1020, 1000))  # inside engage radius, out of melee

    # Phase 3 — dash, in a short hop rather than one long walk.
    first = necro.engage(snap(allies=wall(), monsters=[target]))
    assert isinstance(first, MoveTo)
    assert first.target == (1008, 1000)  # dash_step 8, not the full 20

    # Arrive in melee range: phase 4 — strike.
    clock.advance(1.0)
    close = monster(1, (1002, 1000))
    strike = necro.engage(snap(allies=wall(), monsters=[close]))
    assert strike == AttackUnit(1, (1002, 1000))

    # Phase 5 — back out of the pack immediately afterwards.
    clock.advance(0.2)
    retreat = necro.engage(snap(allies=wall(), monsters=[close]))
    assert isinstance(retreat, MoveTo)
    assert retreat.target != (1002, 1000)


def test_dash_goes_straight_there_when_already_close():
    necro, _ = make(skirmishing())
    target = monster(1, (1006, 1000))  # 6 away, under dash_step 8
    assert necro.engage(snap(allies=wall(), monsters=[target])) == MoveTo((1006, 1000))


def test_a_struck_monster_is_not_restruck_immediately():
    """Poison keeps working, so a freshly-struck monster is not re-stabbed.

    What changed (user, after watching a live run) is what happens INSTEAD.
    This used to return None and the character stood perfectly still until
    the restrike timer expired; the user judged that the riskier option —
    "better to move often, even small movements" — so the wait is now spent
    drifting away from the pack.
    """
    necro, clock = make(skirmishing())
    target = monster(1, (1002, 1000))
    assert isinstance(necro.engage(snap(allies=wall(), monsters=[target])), AttackUnit)
    clock.advance(0.2)
    necro.engage(snap(allies=wall(), monsters=[target]))  # the retreat
    clock.advance(0.2)
    drift = necro.engage(snap(allies=wall(), monsters=[target]))
    assert isinstance(drift, MoveTo), "waiting must not mean standing still"
    assert drift.target != (1002, 1000)  # away from it, not into it


def test_a_survivor_is_restruck_after_the_cooldown():
    necro, clock = make()
    target = monster(1, (1002, 1000))
    necro.engage(snap(allies=wall(), monsters=[target]))
    clock.advance(0.2)
    necro.engage(snap(allies=wall(), monsters=[target]))  # retreat
    clock.advance(6.5)  # past restrike_s
    assert necro.engage(snap(allies=wall(), monsters=[target])) == AttackUnit(1, (1002, 1000))


def test_unstruck_targets_are_preferred_over_survivors():
    necro, clock = make()
    first = monster(1, (1002, 1000))
    necro.engage(snap(allies=wall(), monsters=[first]))  # strike #1
    clock.advance(0.2)
    necro.engage(snap(allies=wall(), monsters=[first]))  # retreat
    clock.advance(0.2)
    # A fresh monster arrives, further away than the poisoned one.
    fresh = monster(2, (1005, 1002))
    action = necro.engage(snap(allies=wall(), monsters=[first, fresh]))
    assert isinstance(action, MoveTo | AttackUnit)
    if isinstance(action, AttackUnit):
        assert action.unit_id == 2
    else:
        assert action.target == (1005, 1002)


def test_adjacent_monsters_come_first():
    # Stun-lock risk: whatever is already on top of us gets hit first, even
    # if something else is untouched further away.
    necro, _ = make()
    adjacent = monster(1, (1001, 1000))
    distant = monster(2, (1030, 1000))
    assert necro.engage(snap(allies=wall(), monsters=[adjacent, distant])) == AttackUnit(
        1, (1001, 1000)
    )


def test_corpses_are_never_targets():
    necro, _ = make()
    world = snap(allies=wall(), monsters=[monster(1, (1002, 1000), hp=0,
                                   mode=offsets.MONSTER_MODE_DEAD)])
    assert necro.engage(world) is None


def test_retreat_falls_through_to_fighting_when_cornered():
    # Nowhere walkable to retreat to: keep fighting rather than stand still.
    necro, clock = make(walkable=lambda p: p == HOME)
    target = monster(1, (1002, 1000))
    assert isinstance(necro.engage(snap(allies=wall(), monsters=[target])), AttackUnit)
    clock.advance(6.5)
    assert isinstance(necro.engage(snap(allies=wall(), monsters=[target])), AttackUnit)


# -- waiting for the revives ---------------------------------------------------


def test_waits_briefly_for_revives_to_engage():
    necro, clock = make()
    target = monster(1, (1020, 1000))
    revive = ally(9, (1000, 1001))  # right beside us, not yet at the enemy
    world = snap(monsters=[target], allies=[revive])
    assert necro.engage(world) is None  # holding at range
    clock.advance(2.0)  # past wait_for_revives_s
    assert isinstance(necro.engage(world), MoveTo)


def test_the_wait_ends_early_once_a_revive_is_in_contact():
    # It is a wait for them to TANK, not a timer to run out.
    necro, _ = make()
    target = monster(1, (1020, 1000))
    engaged = ally(9, (1018, 1000))  # within revive_engaged_range of the target
    action = necro.engage(snap(monsters=[target], allies=[engaged]))
    assert isinstance(action, MoveTo)


def test_no_wall_means_no_approach():
    """The user's protocol: three revives BEFORE walking into a pack.

    Desecrate makes its own corpses, so there is never a reason to go in
    short-handed. This test used to assert the opposite — that no revives
    meant no wait, so dash straight in — which is exactly the behaviour
    being removed.
    """
    necro, _ = make()
    far = monster(1, (1020, 1000))
    action = necro.engage(snap(monsters=[far]))  # no allies: no wall
    assert isinstance(action, MoveTo)
    assert action.target != (1008, 1000), "that is the dash; it must not happen"


def test_the_wall_gate_releases_when_the_wall_cannot_be_built():
    """A protocol, not a deadlock. `upkeep` gives up after
    `desecrate_rounds` fruitless casts, and offense must not hold back
    forever on ground where no corpse can be raised."""
    necro, _ = make(CombatConfig(wait_for_revives_s=0.0, desecrate_rounds=0))
    far = monster(1, (1020, 1000))
    assert necro.engage(snap(monsters=[far])) == MoveTo((1008, 1000))


def test_a_new_pack_restarts_the_wait():
    necro, clock = make()
    revive = ally(9, (1000, 1001))
    world = snap(monsters=[monster(1, (1020, 1000))], allies=[revive])
    necro.engage(world)
    clock.advance(2.0)
    assert isinstance(necro.engage(world), MoveTo)
    # Pack dies; a new one shows up later.
    necro.engage(snap(allies=[revive]))
    clock.advance(5.0)
    fresh = snap(monsters=[monster(2, (1020, 1000))], allies=[revive])
    assert necro.engage(fresh) is None  # waiting again


# -- desecrate -> revive maintenance -------------------------------------------


def test_upkeep_quiet_when_the_wall_is_up():
    necro, _ = make()
    allies = [ally(i, (1001, 1000)) for i in range(3)]
    assert necro.upkeep(snap(allies=allies)) is None


def test_upkeep_never_runs_in_town():
    necro, _ = make()
    assert necro.upkeep(snap(area=TOWN)) is None


def test_upkeep_revives_an_available_corpse():
    necro, _ = make()
    action = necro.upkeep(snap(corpses=[corpse(5, (1004, 1000))]))
    assert action == CastAtPoint(offsets.SKILL_REVIVE, (1004, 1000))


def test_upkeep_desecrates_when_there_are_no_corpses():
    necro, _ = make()
    action = necro.upkeep(snap())
    assert isinstance(action, CastAtPoint)
    assert action.skill_id == offsets.SKILL_DESECRATE


def test_desecrate_avoids_ground_occupied_by_units():
    necro, _ = make()
    # Ring the player with units at the first search radius so the cast has
    # to move outward: a right-click on a unit targets it instead of casting.
    crowd = [monster(i, (1000 + dx * 4, 1000 + dy * 4))
             for i, (dx, dy) in enumerate(
                 ((1, 0), (0, 1), (-1, 0), (0, -1),
                  (1, 1), (-1, 1), (1, -1), (-1, -1)))]
    action = necro.upkeep(snap(monsters=crowd))
    assert isinstance(action, CastAtPoint)
    for unit in crowd:
        assert max(abs(action.target[0] - unit.position[0]),
                   abs(action.target[1] - unit.position[1])) > 2


def test_desecrate_is_bounded_when_it_produces_nothing():
    necro, clock = make()
    empty = snap()
    casts = 0
    for _ in range(10):
        if necro.upkeep(empty) is not None:
            casts += 1
        clock.advance(1.5)  # past desecrate_settle_s each time
    assert casts == 2  # desecrate_rounds, then it stops trying


def test_the_round_budget_resets_once_the_wall_is_back_up():
    necro, clock = make()
    for _ in range(3):
        necro.upkeep(snap())
        clock.advance(1.5)
    assert necro.upkeep(snap()) is None  # budget spent
    # Revives come up, then expire later: the next shortfall gets a fresh
    # budget rather than inheriting the spent one.
    necro.upkeep(snap(allies=[ally(i, (1001, 1000)) for i in range(3)]))
    clock.advance(1.5)
    assert necro.upkeep(snap()) is not None


def test_settle_delays_stop_double_casting():
    necro, clock = make()
    assert necro.upkeep(snap()) is not None
    clock.advance(0.2)  # inside desecrate_settle_s
    assert necro.upkeep(snap()) is None

    necro2, clock2 = make()
    bodies = [corpse(5, (1004, 1000)), corpse(6, (1005, 1001))]
    assert necro2.upkeep(snap(corpses=bodies)) is not None
    clock2.advance(0.2)  # inside revive_settle_s
    assert necro2.upkeep(snap(corpses=bodies)) is None


def test_revives_move_to_the_next_corpse():
    necro, clock = make()
    bodies = [corpse(5, (1004, 1000)), corpse(6, (1005, 1001))]
    first = necro.upkeep(snap(corpses=bodies))
    clock.advance(1.0)
    second = necro.upkeep(snap(corpses=bodies))
    assert first.target != second.target


def test_distant_corpses_are_not_revive_fuel():
    necro, _ = make()
    far = corpse(5, (1000 + 40, 1000))  # beyond revive_search_radius 15
    action = necro.upkeep(snap(corpses=[far]))
    assert action.skill_id == offsets.SKILL_DESECRATE  # desecrates instead


def test_every_number_is_config():
    necro, _ = make(
        skirmishing(engage_radius=5, melee_range=1, dash_step=2)
    )
    # Outside engage_radius: not our business at all, so nothing happens —
    # not even the drift, which only applies when there IS a fight on.
    assert necro.engage(snap(allies=wall(), monsters=[monster(1, (1010, 1000))])) is None
    assert necro.engage(
        snap(allies=wall(), monsters=[monster(1, (1004, 1000))])
    ) == MoveTo((1002, 1000))
