"""The reflex ladder: every rung's trigger and guard, against scripted worlds.

The ladder is pure decision-making, so these tests hand it snapshots and
belts and assert on the emitted decisions — no fake input paths needed. What
is under test is the R49 ladder itself: priority order, escalation, cooldown
bookkeeping, the warp position-verify, and town suppression.
"""

import pytest

from pd2bot import offsets
from pd2bot.behavior.actions import CastAtPoint, CastSelf, DrinkPotion, MoveTo
from pd2bot.behavior.reflex import (
    ReflexConfig,
    ReflexLadder,
    retreat_point,
)
from pd2bot.items import CarriedItem, CarriedItems
from pd2bot.player import Player
from pd2bot.snapshot import GameSnapshot
from pd2bot.units import Monster
from pd2bot.world import Area

TOWN, FIELD = 1, 3  # Rogue Encampment, Cold Plains
POS = (1000, 1000)

# Live-verified PD2 potion kinds (P1 drill C / R54).
HEAL, MANA, REJUV = 606, 611, 530


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def player(hp=1000, max_hp=1000, mana=200, max_mana=400, pos=POS):
    return Player(
        name="N", level=91, act=1, position=pos, mode=1,
        hp=hp, max_hp=max_hp, mana=mana, max_mana=max_mana,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


def hostile(pos, uid=1):
    return Monster(
        unit_id=uid, kind=50, position=pos, hp=100, max_hp=100,
        is_champion=False, is_boss=False, is_minion=False,
    )


def pack(count, center=POS, spread=2):
    """`count` hostiles clustered within `spread` of `center`."""
    return [
        hostile((center[0] + (i % spread), center[1]), uid=100 + i)
        for i in range(count)
    ]


def snap(pl=None, area=FIELD, monsters=()):
    return GameSnapshot(
        in_game=True, taken_at=0.0,
        player=pl if pl is not None else player(),
        area=Area(level_no=area, position=(0, 0), size=(500, 500)),
        monsters=tuple(monsters),
    )


def belt_potion(uid, kind, slot):
    return CarriedItem(uid, kind, 2, offsets.ITEM_MODE_IN_BELT, 0,
                       offsets.NODE_BELT, (slot, 0), 1)


def belt(*potions):
    return CarriedItems(items=tuple(potions), skipped=0)


def full_belt():
    """One of everything, in the R53 columns: mana/rejuv/heal/heal."""
    return belt(
        belt_potion(1, MANA, 0), belt_potion(2, REJUV, 1),
        belt_potion(3, HEAL, 2), belt_potion(4, HEAL, 3),
    )


def no_rejuv_belt():
    return belt(
        belt_potion(1, MANA, 0),
        belt_potion(3, HEAL, 2), belt_potion(4, HEAL, 3),
    )


def make_ladder(config=None, *, carried=full_belt, armor=1.0,
                walkable=None, upkeep=None):
    """A ladder over scripted inputs. `armor` may be a constant or a
    callable; `walkable` defaults to everything-walkable."""
    clock = Clock()
    armor_fn = armor if callable(armor) else (lambda: armor)
    ladder = ReflexLadder(
        config if config is not None else ReflexConfig(),
        carried=carried,
        armor_ratio=armor_fn,
        is_walkable=walkable if walkable is not None else (lambda p: True),
        combat_upkeep=upkeep,
        clock=clock,
    )
    return ladder, clock


# -- quiet paths ---------------------------------------------------------------


def test_quiet_when_healthy():
    ladder, _ = make_ladder()
    assert ladder.evaluate(snap()) is None


def test_no_player_no_decision():
    ladder, _ = make_ladder()
    quiet = GameSnapshot(in_game=True, taken_at=0.0)
    assert ladder.evaluate(quiet) is None


# -- rung 3: rejuv -------------------------------------------------------------


def test_rejuv_fires_below_half():
    ladder, _ = make_ladder()
    decision = ladder.evaluate(snap(player(hp=490)))
    assert decision.rung == "rejuv"
    assert decision.action == DrinkPotion(1, "rejuv")  # R53: key 2


def test_rejuv_has_no_cooldown():
    ladder, clock = make_ladder()
    assert ladder.evaluate(snap(player(hp=490))).rung == "rejuv"
    clock.advance(0.2)
    assert ladder.evaluate(snap(player(hp=490))).rung == "rejuv"


def test_rejuv_beats_warp_when_available():
    # Rung order: a rejuv in the belt wins even with warp's trigger met.
    ladder, _ = make_ladder()
    decision = ladder.evaluate(snap(player(hp=450), monsters=pack(5)))
    assert decision.rung == "rejuv"


def test_rejuv_empty_and_surrounded_escalates_to_warp():
    ladder, _ = make_ladder(carried=no_rejuv_belt)
    decision = ladder.evaluate(snap(player(hp=450), monsters=pack(2)))
    assert decision.rung == "blood_warp"
    assert isinstance(decision.action, CastAtPoint)
    assert decision.action.skill_id == offsets.SKILL_BLOOD_WARP
    assert "escalated" in decision.reason


def test_rejuv_empty_but_alone_falls_through_to_heal():
    ladder, _ = make_ladder(carried=no_rejuv_belt)
    decision = ladder.evaluate(snap(player(hp=450), monsters=pack(1)))
    assert decision.rung == "heal"


def test_escalated_warp_still_respects_mana_guard():
    ladder, _ = make_ladder(carried=no_rejuv_belt)
    decision = ladder.evaluate(
        snap(player(hp=450, mana=5), monsters=pack(2))
    )
    assert decision.rung == "heal"  # warp refused, ladder falls through


# -- rung 4: blood warp --------------------------------------------------------


def test_warp_fires_when_packed_and_hurt():
    ladder, _ = make_ladder(carried=no_rejuv_belt)
    decision = ladder.evaluate(snap(player(hp=550), monsters=pack(4)))
    assert decision.rung == "blood_warp"
    assert "packed" in decision.reason


def test_warp_needs_low_hp_not_just_a_pack():
    ladder, _ = make_ladder()
    decision = ladder.evaluate(snap(player(hp=800), monsters=pack(6)))
    assert decision.rung == "heal"  # hp 80% >= warp's 60% — no warp


def test_warp_fires_on_burst_damage():
    ladder, clock = make_ladder()
    assert ladder.evaluate(snap(player(hp=1000))) is None
    clock.advance(0.5)
    decision = ladder.evaluate(snap(player(hp=700)))  # 30% inside 2 s
    assert decision.rung == "blood_warp"
    assert "lost 300 hp" in decision.reason


def test_burst_window_expires():
    ladder, clock = make_ladder()
    assert ladder.evaluate(snap(player(hp=1000))) is None
    clock.advance(3.0)  # beyond the 2 s window
    decision = ladder.evaluate(snap(player(hp=700)))
    assert decision.rung == "heal"  # the old sample aged out; no burst


def test_warp_hp_cost_guard():
    # Cost = max(12% of 1000, 12) = 120; hp must exceed 240 to warp.
    ladder, clock = make_ladder(carried=no_rejuv_belt)
    assert ladder.evaluate(snap(player(hp=1000))) is None
    clock.advance(0.5)
    decision = ladder.evaluate(snap(player(hp=230)))
    assert decision.rung == "heal"


def test_warp_position_verify_blocks_recast_until_retry():
    ladder, clock = make_ladder(carried=no_rejuv_belt)
    first = ladder.evaluate(snap(player(hp=550), monsters=pack(4)))
    assert first.rung == "blood_warp"
    # Same spot half a second later: the attempt is pending its verify —
    # no second cast, the ladder falls through.
    clock.advance(0.5)
    again = ladder.evaluate(snap(player(hp=550), monsters=pack(4)))
    assert again.rung == "heal"
    # Past the retry window the attempt is written off and warp re-arms.
    clock.advance(2.0)
    third = ladder.evaluate(snap(player(hp=550), monsters=pack(4)))
    assert third.rung == "blood_warp"


def test_warp_verified_by_movement_rearms_immediately():
    ladder, clock = make_ladder(carried=no_rejuv_belt)
    assert ladder.evaluate(
        snap(player(hp=550), monsters=pack(4))
    ).rung == "blood_warp"
    clock.advance(0.5)
    # The player materialized 20 subtiles away: the cast landed.
    moved = (POS[0] + 20, POS[1])
    decision = ladder.evaluate(
        snap(player(hp=550, pos=moved), monsters=pack(4, center=moved))
    )
    assert decision.rung == "blood_warp"


def test_warp_refuses_without_walkable_ground():
    ladder, _ = make_ladder(carried=no_rejuv_belt, walkable=lambda p: False)
    decision = ladder.evaluate(snap(player(hp=550), monsters=pack(4)))
    assert decision.rung == "heal"  # nowhere to land — not available


# -- rung 5: heal --------------------------------------------------------------


def test_heal_fires_below_full_with_cooldown():
    ladder, clock = make_ladder()
    first = ladder.evaluate(snap(player(hp=900)))
    assert first.rung == "heal"
    assert first.action == DrinkPotion(2, "healing")  # R53: key 3 primary
    clock.advance(1.0)
    assert ladder.evaluate(snap(player(hp=900))) is None  # cooling down
    clock.advance(9.5)
    assert ladder.evaluate(snap(player(hp=900))).rung == "heal"


def test_heal_uses_backup_column():
    only_backup = belt(belt_potion(4, HEAL, 3))
    ladder, _ = make_ladder(carried=lambda: only_backup)
    decision = ladder.evaluate(snap(player(hp=900)))
    assert decision.action == DrinkPotion(3, "healing")  # R53: key 4 backup


def test_heal_checks_column_contents_not_layout():
    # A mana potion sitting in a healing column must not be drunk as a heal.
    wrong = belt(belt_potion(9, MANA, 2))
    ladder, _ = make_ladder(carried=lambda: wrong)
    assert ladder.evaluate(snap(player(hp=900))) is None


# -- rung 6: mana --------------------------------------------------------------


def test_mana_fires_below_quarter_with_long_cooldown():
    ladder, clock = make_ladder()
    first = ladder.evaluate(snap(player(mana=90)))  # 22.5%
    assert first.rung == "mana"
    assert first.action == DrinkPotion(0, "mana")  # R53: key 1
    clock.advance(10.0)
    assert ladder.evaluate(snap(player(mana=90))) is None  # 15 s, R49
    clock.advance(5.5)
    assert ladder.evaluate(snap(player(mana=90))).rung == "mana"


def test_mana_needs_a_potion_in_its_column():
    ladder, _ = make_ladder(carried=lambda: belt(belt_potion(3, HEAL, 2)))
    assert ladder.evaluate(snap(player(mana=90))) is None


# -- rung 7: disengage ---------------------------------------------------------


def test_disengage_when_armor_down_and_cooling():
    # Only rejuv in the belt so the heal rung cannot mask rung 7, and hp
    # above 50 so rejuv itself stays quiet.
    armor = [0.5]
    ladder, clock = make_ladder(
        carried=lambda: belt(belt_potion(2, REJUV, 1)), armor=lambda: armor[0]
    )
    # First: absorb below 75% -> the upkeep rung recasts (and records it).
    assert ladder.evaluate(snap(player(hp=650))).rung == "upkeep"
    # The recast did not take: absorb reads zero, attempt still cooling.
    armor[0] = 0.0
    clock.advance(0.5)
    decision = ladder.evaluate(snap(player(hp=650), monsters=pack(3)))
    assert decision.rung == "disengage"
    assert isinstance(decision.action, MoveTo)


def test_no_disengage_without_hostiles():
    armor = [0.5]
    ladder, clock = make_ladder(
        carried=lambda: belt(belt_potion(2, REJUV, 1)), armor=lambda: armor[0]
    )
    assert ladder.evaluate(snap(player(hp=650))).rung == "upkeep"
    armor[0] = 0.0
    clock.advance(0.5)
    # Nothing to run from, recast still cooling: this tick has nothing.
    assert ladder.evaluate(snap(player(hp=650))) is None


# -- rung 8: upkeep ------------------------------------------------------------


def test_armor_recast_below_threshold():
    ladder, _ = make_ladder(armor=0.5)
    decision = ladder.evaluate(snap())
    assert decision.rung == "upkeep"
    assert decision.action == CastSelf(offsets.SKILL_BONE_ARMOR)


def test_armor_recast_attempts_are_paced():
    ladder, clock = make_ladder(armor=0.5)
    assert ladder.evaluate(snap()).rung == "upkeep"
    clock.advance(0.5)
    assert ladder.evaluate(snap()) is None  # attempt pending; do not spam
    clock.advance(2.0)
    assert ladder.evaluate(snap()).rung == "upkeep"


def test_armor_recast_allowed_in_town():
    ladder, _ = make_ladder(armor=0.5)
    assert ladder.evaluate(snap(area=TOWN)).rung == "upkeep"


def test_armor_in_town_can_be_disabled():
    ladder, _ = make_ladder(
        ReflexConfig(armor_in_town=False), armor=0.5
    )
    assert ladder.evaluate(snap(area=TOWN)) is None


def test_armor_fallback_recasts_after_a_hit():
    # Stat unreadable (None): the R47 fallback is recast-after-being-hit.
    # Exercised in town so the drink rungs cannot fire first.
    ladder, clock = make_ladder(armor=lambda: None)
    assert ladder.evaluate(snap(player(hp=1000), area=TOWN)) is None
    clock.advance(0.5)
    decision = ladder.evaluate(snap(player(hp=950), area=TOWN))
    assert decision.rung == "upkeep"
    assert decision.action == CastSelf(offsets.SKILL_BONE_ARMOR)


def test_combat_upkeep_delegation_out_of_town_only():
    calls = []

    def upkeep(s):
        calls.append(s)
        return CastAtPoint(offsets.SKILL_DESECRATE, POS)

    ladder, _ = make_ladder(upkeep=upkeep)
    decision = ladder.evaluate(snap())
    assert decision.rung == "upkeep"
    assert decision.action.skill_id == offsets.SKILL_DESECRATE
    assert len(calls) == 1

    ladder2, _ = make_ladder(upkeep=upkeep)
    assert ladder2.evaluate(snap(area=TOWN)) is None
    assert len(calls) == 1  # never consulted in town (R47.4)


# -- town suppression ----------------------------------------------------------


def test_town_suppresses_every_drink_and_escape():
    # Dying of thirst in town with "hostiles" (town guards read as monsters
    # to perception, P1 drill D): rungs 3-7 must all stay silent.
    ladder, _ = make_ladder()
    decision = ladder.evaluate(
        snap(player(hp=300, mana=10), area=TOWN, monsters=pack(5))
    )
    assert decision is None


# -- retreat_point -------------------------------------------------------------


def test_retreat_point_runs_away_from_the_pack():
    hostiles = [(1010, 1000), (1012, 1000)]
    point = retreat_point((1000, 1000), hostiles, 20, lambda p: True)
    assert point == (980, 1000)  # dead away, full distance


def test_retreat_point_rotates_around_unwalkable_ground():
    hostiles = [(1010, 1000)]
    point = retreat_point(
        (1000, 1000), hostiles, 20, lambda p: p != (980, 1000)
    )
    assert point is not None and point != (980, 1000)


def test_retreat_point_gives_up_when_nothing_is_walkable():
    assert retreat_point((0, 0), [(5, 5)], 20, lambda p: False) is None


def test_retreat_point_without_hostiles_still_finds_ground():
    assert retreat_point((0, 0), [], 20, lambda p: True) is not None


# -- config plumbing -----------------------------------------------------------


def test_every_number_is_config():
    # A ladder with moved thresholds obeys the moved numbers.
    config = ReflexConfig(rejuv_below_pct=80.0, heal_below_pct=0.0)
    ladder, _ = make_ladder(config)
    decision = ladder.evaluate(snap(player(hp=700)))
    assert decision.rung == "rejuv"  # 70% < the tuned 80%


@pytest.mark.parametrize("area,expected", [(TOWN, True), (FIELD, False)])
def test_snapshot_in_town_drives_suppression(area, expected):
    assert snap(area=area).in_town is expected
