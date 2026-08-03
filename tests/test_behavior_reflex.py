"""The reflex ladder: every rung's trigger and guard, against scripted worlds.

The ladder is pure decision-making, so these tests hand it snapshots and
belts and assert on the emitted decisions — no fake input paths needed. What
is under test is the R49 ladder itself: priority order, escalation, cooldown
bookkeeping, the warp position-verify, and town suppression.
"""

import pytest

from pd2bot import offsets
from pd2bot.behavior.actions import (
    CastAtPoint,
    CastSelf,
    DrinkPotion,
    GiveMercPotion,
    MoveTo,
)
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


def snap(pl=None, area=FIELD, monsters=(), allies=()):
    return GameSnapshot(
        in_game=True, taken_at=0.0,
        player=pl if pl is not None else player(),
        area=Area(level_no=area, position=(0, 0), size=(500, 500)),
        monsters=tuple(monsters),
        allies=tuple(allies),
    )


def merc(hp=128, max_hp=1620):
    """The rogue hireling (kind 271), friendly, at the player's side.

    `hp` is on the client's 0-128 scale (full = 128) while `max_hp` is
    the REAL maximum — exactly what the 2026-08-02 probe read from the
    live full-health rogue (128/1620). Building the fixture any other
    way is how the phantom "merc hp 8%" trigger stayed invisible to a
    green suite (T54 run 3).
    """
    return Monster(
        unit_id=900, kind=271, position=(1005, 1000), hp=hp, max_hp=max_hp,
        is_champion=False, is_boss=False, is_minion=False,
        alignment=offsets.ALIGNMENT_FRIENDLY,
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


def fire(ladder, snapshot):
    """Evaluate AND commit — what the engine does when the send lands.

    The ladder now decides and the engine commits (review 002), so a test
    about a COOLDOWN has to say which of the two it means. Most do mean
    "the rung fired and the action went out", and this is that; the tests
    that care about a refused send call `evaluate` and skip the commit on
    purpose.
    """
    decision = ladder.evaluate(snapshot)
    if decision is not None:
        decision.commit_attempted()  # pacing: recorded either way
        decision.commit_sent()  # cooldowns: only because this one landed
    return decision


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
    first = fire(ladder, snap(player(hp=550), monsters=pack(4)))
    assert first.rung == "blood_warp"
    # Same spot half a second later: the attempt is pending its verify —
    # no second cast, the ladder falls through.
    clock.advance(0.5)
    again = fire(ladder, snap(player(hp=550), monsters=pack(4)))
    assert again.rung == "heal"
    # Past the retry window the attempt is written off and warp re-arms.
    clock.advance(2.0)
    third = fire(ladder, snap(player(hp=550), monsters=pack(4)))
    assert third.rung == "blood_warp"


def test_warp_refused_leaves_the_escape_armed():
    """A warp that was never sent must not block the next one (review 002).

    The worst case of the old commit-at-decision bug: the character is in
    the pack that triggered the escape, and a refusal would have recorded
    an attempt that never happened — blocking re-casts for `warp_retry_s`
    while it stood there.
    """
    ladder, clock = make_ladder(carried=no_rejuv_belt)
    first = ladder.evaluate(snap(player(hp=550), monsters=pack(4)))
    assert first.rung == "blood_warp"  # decided, but NOT committed
    clock.advance(0.5)
    again = ladder.evaluate(snap(player(hp=550), monsters=pack(4)))
    assert again.rung == "blood_warp"


def test_warp_verified_by_movement_rearms_immediately():
    ladder, clock = make_ladder(carried=no_rejuv_belt)
    assert fire(
        ladder, snap(player(hp=550), monsters=pack(4))
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
    first = fire(ladder, snap(player(hp=900)))
    assert first.rung == "heal"
    assert first.action == DrinkPotion(2, "healing")  # R53: key 3 primary
    clock.advance(1.0)
    assert fire(ladder, snap(player(hp=900))) is None  # cooling down
    clock.advance(9.5)
    assert fire(ladder, snap(player(hp=900))).rung == "heal"


def test_refused_heal_does_not_start_its_cooldown():
    """Review 002's probe, as a test: decide, do not send, decide again.

    The character is below the threshold that asked for the heal, so the
    ladder must offer it again on the very next tick rather than sit out a
    10 s cooldown for a potion nobody drank.
    """
    ladder, clock = make_ladder()
    assert ladder.evaluate(snap(player(hp=900))).rung == "heal"
    clock.advance(1.0)
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


# -- type search: column order must never matter (R179) --------------------------


def test_rejuv_in_the_wrong_column_is_still_drunk():
    # The R179 rule: a rejuv is a rejuv wherever it sits. Column 3 is a
    # healing column by layout; the press follows the potion.
    wrong = belt(belt_potion(9, REJUV, 3))
    ladder, _ = make_ladder(carried=lambda: wrong)
    decision = ladder.evaluate(snap(player(hp=490)))
    assert decision.rung == "rejuv"
    assert decision.action == DrinkPotion(3, "rejuv")


def test_configured_column_is_preferred_when_both_hold_the_type():
    both = belt(belt_potion(1, REJUV, 0), belt_potion(2, REJUV, 1))
    ladder, _ = make_ladder(carried=lambda: both)
    decision = ladder.evaluate(snap(player(hp=490)))
    assert decision.action == DrinkPotion(1, "rejuv")  # the R53 home wins


def test_heal_found_outside_its_configured_columns():
    wrong = belt(belt_potion(9, HEAL, 0))  # the mana column
    ladder, _ = make_ladder(carried=lambda: wrong)
    decision = ladder.evaluate(snap(player(hp=900)))
    assert decision.rung == "heal"
    assert decision.action == DrinkPotion(0, "healing")


def test_mana_found_outside_its_configured_column():
    wrong = belt(belt_potion(9, MANA, 2))
    ladder, _ = make_ladder(carried=lambda: wrong)
    decision = ladder.evaluate(snap(player(mana=90)))
    assert decision.rung == "mana"
    assert decision.action == DrinkPotion(2, "mana")


# -- rung 7.5: merc first aid (R179) ---------------------------------------------


def test_merc_heal_fires_below_half():
    ladder, _ = make_ladder()
    decision = ladder.evaluate(snap(allies=[merc(hp=63)]))  # 63/128 = 49%
    assert decision is not None and decision.rung == "merc_heal"
    assert decision.action == GiveMercPotion(2)  # the R53 primary heal column
    assert "merc hp 49%" in decision.reason


def test_merc_heal_holds_at_half_and_above():
    ladder, _ = make_ladder()
    assert ladder.evaluate(snap(allies=[merc(hp=65)])) is None  # 51%
    assert ladder.evaluate(snap(allies=[merc(hp=64)])) is None  # 50%, strict <


def test_a_full_merc_with_a_real_max_hp_is_never_fed():
    """T54 run 3's phantom trigger, pinned: the FULL rogue reads hp 128
    with max_hp 1620 — hp/max_hp says 8%, the client scale says 100%.
    The rung fed her every 3 s for a whole game on the wrong fraction."""
    ladder, _ = make_ladder()
    assert ladder.evaluate(snap(allies=[merc(hp=128, max_hp=1620)])) is None


def test_dead_merc_is_not_fed():
    # A dead merc leaves snapshot.merc (hp 0 fails is_alive); no rung.
    ladder, _ = make_ladder()
    assert ladder.evaluate(snap(allies=[merc(hp=0)])) is None


def test_merc_heal_never_fires_in_town():
    ladder, _ = make_ladder()
    assert ladder.evaluate(snap(area=TOWN, allies=[merc(hp=38)])) is None


def test_merc_heal_is_paced_across_failed_sends():
    # The stage B run 9 rule: a send that keeps failing must not refire at
    # tick rate. Pacing records on ATTEMPT, so even a refused chord waits
    # out merc_heal_retry_s.
    ladder, clock = make_ladder()
    first = ladder.evaluate(snap(allies=[merc(hp=38)]))
    assert first.rung == "merc_heal"
    first.commit_attempted()  # the send FAILED; pacing still recorded
    clock.advance(0.5)
    assert ladder.evaluate(snap(allies=[merc(hp=38)])) is None
    clock.advance(3.0)
    assert ladder.evaluate(snap(allies=[merc(hp=38)])).rung == "merc_heal"


def test_merc_heal_needs_a_healing_potion_somewhere():
    ladder, _ = make_ladder(carried=lambda: belt(belt_potion(1, MANA, 0)))
    assert ladder.evaluate(snap(allies=[merc(hp=38)])) is None


def test_merc_served_from_the_wrong_column():
    # P1 integration: healing only in the rejuv column still serves the merc.
    wrong = belt(belt_potion(9, HEAL, 1))
    ladder, _ = make_ladder(carried=lambda: wrong)
    decision = ladder.evaluate(snap(allies=[merc(hp=38)]))
    assert decision is not None and decision.action == GiveMercPotion(1)


def test_player_survival_outranks_the_merc():
    # Both trigger on the same tick: the player's rejuv wins, the merc waits.
    ladder, _ = make_ladder()
    decision = ladder.evaluate(snap(player(hp=490), allies=[merc(hp=38)]))
    assert decision.rung == "rejuv"


# -- the bottom of the column is what the key sends (T54 run 3) ------------------
#
# Pressing key N consumes the LOWEST row of column N. Mixed columns and
# foreign potions (antidotes) are NORMAL belt states (user, 2026-08-02),
# so every type check reads the bottom occupant — "any of the type in the
# column" fed a mana potion to the merc and would drink the wrong potion.

ANTIDOTE = 999  # any kind outside the healing/mana/rejuv sets


def test_a_squatter_under_the_healing_blocks_that_column():
    # Column 2: mana at the bottom (slot 2), healing above (slot 6). The
    # key would send the mana, so the heal rung must not press it.
    mixed = belt(belt_potion(1, MANA, 2), belt_potion(2, HEAL, 6))
    ladder, _ = make_ladder(carried=lambda: mixed)
    assert ladder.evaluate(snap(player(hp=900))) is None


def test_the_search_moves_on_to_a_column_with_a_healing_bottom():
    mixed = belt(
        belt_potion(1, MANA, 2), belt_potion(2, HEAL, 6),  # col 2: blocked
        belt_potion(3, HEAL, 3),  # col 3: healing at the bottom
    )
    ladder, _ = make_ladder(carried=lambda: mixed)
    decision = ladder.evaluate(snap(player(hp=900)))
    assert decision is not None and decision.action == DrinkPotion(3, "healing")


def test_an_antidote_at_the_bottom_is_never_pressed_as_a_heal():
    # An accidental antidote in the belt matches no type: the heal search
    # skips its column — and the hygiene rung (7.6) then drinks it CLEAR,
    # which is the fix rather than the mistake: the healing above becomes
    # the new bottom.
    foreign = belt(
        belt_potion(1, ANTIDOTE, 2), belt_potion(2, HEAL, 6),
    )
    ladder, _ = make_ladder(carried=lambda: foreign)
    decision = ladder.evaluate(snap(player(hp=900)))
    assert decision is not None and decision.rung == "belt_hygiene"
    assert decision.action == DrinkPotion(2, "hygiene")


def test_the_merc_is_never_fed_a_squatting_mana():
    # Run 3 live: Shift+key on a healing column with mana at the bottom —
    # "I can't use that", nothing consumed, refire every 3 s.
    mixed = belt(belt_potion(1, MANA, 2), belt_potion(2, HEAL, 6))
    ladder, _ = make_ladder(carried=lambda: mixed)
    assert ladder.evaluate(snap(allies=[merc(hp=38)])) is None


# -- rung 7.6: belt-bottom hygiene (user rules, 2026-08-02) ----------------------
#
# The keys only reach the BOTTOM row, so the contract is: one of each
# type at column bottoms when the contents allow, foreign potions drunk
# clear, and never a mana glut. Rejuv bottoms are never spent.


def test_two_bottom_manas_drink_the_squatter_first():
    # Mana at the bottom of its own column AND squatting in a healing
    # column: drink the squatter, keep the home column's bottom.
    glut = belt(
        belt_potion(1, MANA, 0),  # the configured mana column — keep
        belt_potion(2, MANA, 2), belt_potion(3, HEAL, 6),  # the squatter
        belt_potion(4, HEAL, 3), belt_potion(5, REJUV, 1),
    )
    ladder, _ = make_ladder(carried=lambda: glut)
    decision = ladder.evaluate(snap())
    assert decision is not None and decision.rung == "belt_hygiene"
    assert decision.action == DrinkPotion(2, "hygiene")
    assert "glut" in decision.reason


def test_one_bottom_mana_is_no_glut():
    ladder, _ = make_ladder()  # full_belt: one of each type at bottoms
    assert ladder.evaluate(snap()) is None


def test_a_foreign_bottom_is_drunk_clear():
    # An antidote picked into an empty column blocks it for every rung:
    # drinking it is harmless and frees the slot.
    foreign = belt(
        belt_potion(1, MANA, 0), belt_potion(2, REJUV, 1),
        belt_potion(3, ANTIDOTE, 2), belt_potion(4, HEAL, 6),
        belt_potion(5, HEAL, 3),
    )
    ladder, _ = make_ladder(carried=lambda: foreign)
    decision = ladder.evaluate(snap())
    assert decision is not None and decision.rung == "belt_hygiene"
    assert decision.action == DrinkPotion(2, "hygiene")
    assert "foreign" in decision.reason


def test_a_missing_type_is_worked_down_through_a_duplicate_bottom():
    # No rejuv on the bottom row, but one buried above a DUPLICATE
    # healing bottom: drink that healing, the rejuv falls a row closer.
    buried = belt(
        belt_potion(1, MANA, 0),
        belt_potion(2, HEAL, 2), belt_potion(3, REJUV, 6),  # rejuv buried
        belt_potion(4, HEAL, 3),  # the duplicate that makes col 2 spendable
    )
    ladder, _ = make_ladder(carried=lambda: buried)
    decision = ladder.evaluate(snap())
    assert decision is not None and decision.rung == "belt_hygiene"
    assert decision.action == DrinkPotion(2, "hygiene")
    assert "rejuv" in decision.reason


def test_the_last_bottom_of_a_type_is_never_spent():
    # Rejuv missing and buried — but above the ONLY healing bottom.
    # Diversity already achieved outranks diversity sought: stay quiet.
    buried = belt(
        belt_potion(1, MANA, 0),
        belt_potion(2, HEAL, 2), belt_potion(3, REJUV, 6),
    )
    ladder, _ = make_ladder(carried=lambda: buried)
    assert ladder.evaluate(snap()) is None


def test_rejuv_bottoms_are_never_drunk_for_tidiness():
    # Two rejuv bottoms with healing buried: rejuvs are unbuyable
    # emergency stock, and a hygiene drink would waste one entirely.
    rejuvs = belt(
        belt_potion(1, REJUV, 1), belt_potion(2, REJUV, 2),
        belt_potion(3, HEAL, 6), belt_potion(4, MANA, 0),
    )
    ladder, _ = make_ladder(carried=lambda: rejuvs)
    assert ladder.evaluate(snap()) is None


def test_mana_above_a_healing_bottom_does_not_count():
    # The rules read BOTTOMS: a mana stacked above healing is not
    # clogging anything the keys can reach yet.
    stacked = belt(
        belt_potion(1, MANA, 0), belt_potion(2, REJUV, 1),
        belt_potion(3, HEAL, 2), belt_potion(4, MANA, 6),
    )
    ladder, _ = make_ladder(carried=lambda: stacked)
    assert ladder.evaluate(snap()) is None


def test_hygiene_is_paced_across_failed_sends():
    glut = belt(belt_potion(1, MANA, 0), belt_potion(2, MANA, 2))
    ladder, clock = make_ladder(carried=lambda: glut)
    first = ladder.evaluate(snap())
    assert first.rung == "belt_hygiene"
    first.commit_attempted()  # the send FAILED; pacing still recorded
    clock.advance(0.5)
    assert ladder.evaluate(snap()) is None
    clock.advance(2.0)
    assert ladder.evaluate(snap()).rung == "belt_hygiene"


def test_hygiene_never_fires_in_town():
    glut = belt(belt_potion(1, MANA, 0), belt_potion(2, MANA, 2))
    ladder, _ = make_ladder(carried=lambda: glut)
    assert ladder.evaluate(snap(area=TOWN)) is None


def test_survival_outranks_hygiene():
    glut = belt(
        belt_potion(1, MANA, 0), belt_potion(2, MANA, 2),
        belt_potion(3, REJUV, 1),
    )
    ladder, _ = make_ladder(carried=lambda: glut)
    assert ladder.evaluate(snap(player(hp=490))).rung == "rejuv"


# -- rung 6: mana --------------------------------------------------------------


def test_mana_fires_below_quarter_with_long_cooldown():
    ladder, clock = make_ladder()
    first = fire(ladder, snap(player(mana=90)))  # 22.5%
    assert first.rung == "mana"
    assert first.action == DrinkPotion(0, "mana")  # R53: key 1
    clock.advance(10.0)
    assert fire(ladder, snap(player(mana=90))) is None  # 15 s, R49
    clock.advance(5.5)
    assert fire(ladder, snap(player(mana=90))).rung == "mana"


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
    assert fire(ladder, snap(player(hp=650))).rung == "upkeep"
    # The recast did not take: absorb reads zero, attempt still cooling.
    armor[0] = 0.0
    clock.advance(0.5)
    decision = fire(ladder, snap(player(hp=650), monsters=pack(3)))
    assert decision.rung == "disengage"
    assert isinstance(decision.action, MoveTo)


def test_no_disengage_without_hostiles():
    armor = [0.5]
    ladder, clock = make_ladder(
        carried=lambda: belt(belt_potion(2, REJUV, 1)), armor=lambda: armor[0]
    )
    assert fire(ladder, snap(player(hp=650))).rung == "upkeep"
    armor[0] = 0.0
    clock.advance(0.5)
    # Nothing to run from, recast still cooling: this tick has nothing.
    assert fire(ladder, snap(player(hp=650))) is None


# -- rung 8: upkeep ------------------------------------------------------------


def test_armor_recast_below_threshold():
    ladder, _ = make_ladder(armor=0.5)
    decision = ladder.evaluate(snap())
    assert decision.rung == "upkeep"
    assert decision.action == CastSelf(offsets.SKILL_BONE_ARMOR)


def test_armor_recast_attempts_are_paced():
    ladder, clock = make_ladder(armor=0.5)
    assert fire(ladder, snap()).rung == "upkeep"
    clock.advance(0.5)
    assert fire(ladder, snap()) is None  # attempt pending; do not spam
    clock.advance(2.0)
    assert fire(ladder, snap()).rung == "upkeep"


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


def test_a_pending_armor_recast_starves_the_combat_upkeep():
    """T55 run 1: absorb slid 67% -> 54% -> 5% while desecrate/revive
    casts occupied every recast window (CastInFlight ate the retries).
    While an armor recast is NEEDED but waiting out its pacing, rung 8's
    combat half must not start another animation — draining the cast
    pipeline is the fastest way to get the armor up."""
    calls = []

    def upkeep(s):
        calls.append(s)
        return CastAtPoint(offsets.SKILL_DESECRATE, POS)

    armor = [0.0]
    ladder, clock = make_ladder(armor=lambda: armor[0], upkeep=upkeep)
    first = ladder.evaluate(snap())
    assert first.rung == "upkeep" and first.action == CastSelf(
        offsets.SKILL_BONE_ARMOR
    )
    first.commit_attempted()  # the send collided: pacing recorded
    clock.advance(0.5)
    assert ladder.evaluate(snap()) is None, "combat cast during armor pacing"
    assert calls == []
    armor[0] = 1.0  # the recast finally landed
    clock.advance(0.1)
    decision = ladder.evaluate(snap())
    assert decision is not None and decision.action.skill_id == offsets.SKILL_DESECRATE
    assert len(calls) == 1


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


# -- armor down is a trigger, not an unknown (T46 / user report) -------------------


def test_armor_down_casts_immediately_without_waiting_to_be_hit():
    """The user's report from watching stage B: the bot never cast bone
    armor at all.

    With no armor up, stats 132/133 are ABSENT — T46 read 70 other stats
    alongside them, so the list was plainly healthy. That used to return
    None, the ladder read None as "unreadable" and fell back to R47's
    recast-after-being-hit, and in town nothing hits us. Armor down is the
    strongest reason to cast, and it was arriving as ignorance.
    """
    ladder, _ = make_ladder(armor=0.0)
    decision = ladder.evaluate(snap(player(hp=1000), area=TOWN))
    assert decision is not None, "armor down must fire the upkeep rung"
    assert decision.rung == "upkeep"
    assert decision.action == CastSelf(offsets.SKILL_BONE_ARMOR)


def test_armor_down_fires_on_the_very_first_tick_of_a_game():
    """The user's requirement: armor up as the first action on entering a
    game, and after a waypoint. Nothing special is needed to arrange that —
    the ladder is evaluated before any run step, so a down reading fires
    ahead of the town preamble and ahead of any travel."""
    ladder, _ = make_ladder(armor=0.0)
    assert ladder.evaluate(snap(player(hp=1000), area=TOWN)).rung == "upkeep"


def test_a_genuinely_unreadable_stat_still_uses_the_hit_fallback():
    """The guard that makes the change safe. Absence means "down" only
    because T46 saw a healthy list omit the entries; an EMPTY read means we
    learned nothing, and must not be treated as an empty armor pool."""
    ladder, clock = make_ladder(armor=lambda: None)
    assert ladder.evaluate(snap(player(hp=1000), area=TOWN)) is None
    clock.advance(0.5)
    assert ladder.evaluate(snap(player(hp=950), area=TOWN)).rung == "upkeep"


def test_full_armor_is_left_alone():
    """The other half: a healthy pool must not be recast every tick, or a
    firing rung would consume every tick and the bot would never attack."""
    ladder, _ = make_ladder(armor=1.0)
    assert ladder.evaluate(snap(player(hp=1000), area=TOWN)) is None


def test_armor_above_the_threshold_is_left_alone():
    # 80% > the 75% recast threshold, and comfortably above the user's
    # stated "keep it above 50%" floor.
    ladder, _ = make_ladder(armor=0.8)
    assert ladder.evaluate(snap(player(hp=1000), area=TOWN)) is None


def test_a_failing_recast_is_still_paced():
    """Stage B run 9: the bone-armor switch would not take, so the rung
    fired, the send failed, nothing was recorded, and it fired again on the
    very next tick — fifteen times running, every tick consumed, the run
    unable to take a single step. Absorbing the failure had turned a crash
    into a livelock.

    Pacing must survive a failed send. A COOLDOWN must not (review 002):
    that is why they are now two different callables.
    """
    ladder, clock = make_ladder(armor=0.0)
    first = ladder.evaluate(snap(player(hp=1000), area=TOWN))
    assert first.rung == "upkeep"
    first.commit_attempted()  # the send FAILED: pacing only, no commit
    assert ladder.evaluate(snap(player(hp=1000), area=TOWN)) is None
    clock.advance(2.5)
    assert ladder.evaluate(snap(player(hp=1000), area=TOWN)).rung == "upkeep"


def test_a_refused_heal_cooldown_is_still_not_started():
    """The other side of the split, and review 002's actual point: a
    cooldown says the resource is spent, so a heal that never happened must
    be offered again immediately."""
    ladder, _ = make_ladder()
    first = ladder.evaluate(snap(player(hp=900)))
    assert first.rung == "heal"
    first.commit_attempted()  # failed send: pacing runs, cooldown does not
    assert ladder.evaluate(snap(player(hp=900))).rung == "heal"


# -- rung 6.5: reposition (R176 Q3) ---------------------------------------------
#
# The R173 run stood in ground fire — invisible to perception, no unit to
# see — until chicken fired at 49%. The rung's trigger is therefore
# damage-source-agnostic: losing health while the feet are not moving IS
# the signal, whatever is doing the damage.


def empty_belt():
    return belt()


def bleed(ladder, clock, *, hp_steps, pos=POS, step_s=1.0):
    """Feed a sequence of hp readings from a stationary character; return
    the last decision."""
    decision = None
    for hp in hp_steps:
        decision = ladder.evaluate(snap(player(hp=hp, pos=pos)))
        clock.advance(step_s)
    return decision


def test_bleeding_while_still_fires_reposition():
    ladder, clock = make_ladder(carried=empty_belt)
    decision = bleed(ladder, clock, hp_steps=[1000, 990, 975])
    assert decision is not None and decision.rung == "reposition"
    assert isinstance(decision.action, MoveTo)
    assert max(
        abs(decision.action.target[0] - POS[0]),
        abs(decision.action.target[1] - POS[1]),
    ) >= ReflexConfig().reposition_step - 1
    assert "standing still" in decision.reason


def test_moving_through_the_damage_does_not_fire():
    ladder, clock = make_ladder(carried=empty_belt)
    positions = [(1000, 1000), (1006, 1000), (1012, 1000)]
    decision = None
    for hp, pos in zip([1000, 990, 975], positions, strict=True):
        decision = ladder.evaluate(snap(player(hp=hp, pos=pos)))
        clock.advance(1.0)
    assert decision is None, "travelling through chip damage is not standing in it"


def test_reposition_is_paced_not_refired_every_tick():
    ladder, clock = make_ladder(carried=empty_belt)
    decision = bleed(ladder, clock, hp_steps=[1000, 990, 975])
    assert decision.rung == "reposition"
    decision.commit_attempted()  # pacing records even on a failed send
    clock.advance(0.3)
    assert ladder.evaluate(snap(player(hp=970))) is None
    clock.advance(ReflexConfig().reposition_cooldown_s)
    again = ladder.evaluate(snap(player(hp=950)))
    assert again is not None and again.rung == "reposition"


def test_emergencies_outrank_reposition():
    # Same shape of history, but the drop crosses rung 3's threshold with a
    # full belt: the rejuv wins the tick, not the sidestep.
    ladder, clock = make_ladder()
    decision = bleed(ladder, clock, hp_steps=[1000, 700, 450])
    assert decision.rung == "rejuv"


def test_reposition_never_fires_in_town():
    ladder, clock = make_ladder(carried=empty_belt)
    decision = None
    for hp in [1000, 990, 975]:
        decision = ladder.evaluate(snap(player(hp=hp), area=TOWN))
        clock.advance(1.0)
    assert decision is None


def test_reposition_steps_away_from_visible_hostiles():
    ladder, clock = make_ladder(carried=empty_belt)
    decision = None
    for hp in [1000, 990, 975]:
        decision = ladder.evaluate(
            snap(player(hp=hp), monsters=[hostile((1005, 1000))])
        )
        clock.advance(1.0)
    assert decision is not None and decision.rung == "reposition"
    # Away from the hostile at +x: the step lands on the -x side.
    assert decision.action.target[0] < POS[0]
