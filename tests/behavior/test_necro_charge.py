"""The charge style (R241 berserk): nearest target, no dash-out, no
waiting for the wall — with the guardrails that make it rage rather
than a livelock: restrike pacing, write-offs, and the reflex ladder's
precedence all still standing.
"""

import pytest

from pd2bot.behavior.actions import AttackUnit, MoveTo
from pd2bot.behavior.combat import ConfigError, load_class_config
from pd2bot.behavior.necro import CombatConfig
from tests.behavior.test_behavior_necro import make, monster, snap

CHARGE = CombatConfig(style="charge", wait_for_revives_s=5.0)


def charge_combat():
    return make(config=CHARGE)


def test_charge_strikes_the_nearest_not_the_freshest():
    combat, clock = charge_combat()
    near, far = monster(1, (1002, 1000)), monster(2, (1006, 1000))
    # Strike the near one once; skirmish would now prefer the never-struck
    # far one. Charge goes straight back to the nearest off cooldown.
    first = combat.engage(snap(monsters=[near, far]))
    assert isinstance(first, AttackUnit) and first.unit_id == 1
    clock.advance(CHARGE.restrike_s + 0.1)
    second = combat.engage(snap(monsters=[near, far]))
    assert isinstance(second, AttackUnit) and second.unit_id == 1


def test_charge_takes_no_dash_out_after_the_strike():
    combat, clock = charge_combat()
    pack = [monster(i, (1002 + i, 1000)) for i in range(1, 5)]
    action = combat.engage(snap(monsters=pack))
    assert isinstance(action, AttackUnit)
    clock.advance(0.1)
    # Skirmish's next decision after a strike is the retreat MoveTo; the
    # charge's next decision is more violence (or a dash toward it) —
    # never the post-strike back-out.
    following = combat.engage(snap(monsters=pack))
    assert not (
        isinstance(following, MoveTo) and getattr(following, "toward", None) is None
    ), f"charge took a retreat: {following}"


def test_charge_does_not_wait_for_revives():
    combat, clock = charge_combat()
    tank = monster(9, (1020, 1020), alignment=2)
    hostile = monster(1, (1010, 1000))
    # Fresh contact, revives up but NOT engaged, well inside the 5 s
    # skirmish wait: skirmish returns None here; charge acts at once.
    action = combat.engage(snap(monsters=[hostile], allies=[tank]))
    assert action is not None


def test_charge_still_respects_the_write_off():
    combat, clock = charge_combat()
    bat = monster(1, (1002, 1000))  # its hp will never move
    for _ in range(CHARGE.futile_strikes + 2):
        combat.engage(snap(monsters=[bat]))
        clock.advance(CHARGE.restrike_s + 0.1)
    # Written off: the nearest-target rule must not resurrect it.
    assert combat.engage(snap(monsters=[bat])) is None or not isinstance(
        combat.engage(snap(monsters=[bat])), AttackUnit
    )


def test_the_loader_rejects_an_unknown_style(tmp_path):
    source = (
        tmp_path / "bad.toml"
    )
    base = open("config/necro.toml", encoding="utf-8").read()
    source.write_text(
        base.replace('style = "charge"', 'style = "flail"'), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="flail"):
        load_class_config(source)


def test_the_shipped_berserk_posture_is_the_charge_package():
    config = load_class_config("config/necro.toml")
    berserk = config.postures["berserk"]
    assert berserk.style == "charge"
    assert berserk.armor_recast_below_pct == 60.0
    # The base posture stays skirmish with NO armor override.
    assert config.combat.style == "skirmish"
    assert config.combat.armor_recast_below_pct is None


# -- attack at range (R259) ----------------------------------------------------


def test_charge_attacks_at_range_with_a_walk_in_click():
    """Beyond melee but inside charge_attack_range: the strike IS the
    approach — a bare (no-SHIFT) click the client paths in around unit
    collision, instead of the manual dash that run 1 measured being
    body-blocked 88 times for 183 s."""
    combat, clock = charge_combat()
    target = monster(1, (1010, 1000))  # 10 away: past melee (3), inside 16
    action = combat.engage(snap(monsters=[target]))
    assert isinstance(action, AttackUnit)
    assert action.walk_in is True


def test_charge_within_melee_strikes_in_place():
    combat, clock = charge_combat()
    action = combat.engage(snap(monsters=[monster(1, (1002, 1000))]))
    assert isinstance(action, AttackUnit)
    assert action.walk_in is False


def test_charge_beyond_click_range_still_dashes():
    combat, clock = charge_combat()
    target = monster(1, (1030, 1000))  # 30 away: beyond charge_attack_range
    action = combat.engage(snap(monsters=[target]))
    assert isinstance(action, MoveTo)
    assert action.toward == 1


def test_skirmish_never_walk_in_attacks():
    from tests.behavior.test_behavior_necro import make as make_skirmish

    combat, clock = make_skirmish()
    target = monster(1, (1010, 1000))  # 10 away: skirmish dashes, never clicks
    action = combat.engage(snap(monsters=[target]))
    assert not isinstance(action, AttackUnit)


# -- the seam gate (R260) ------------------------------------------------------


def test_a_hostile_across_the_area_border_is_not_engaged():
    """Battery run 3: the walk-in attack chased a border pack into Blood
    Moor for 202 s. A monster standing in another area is not a target,
    whatever the posture."""
    from pd2bot.perception.world import Area

    combat, clock = charge_combat()
    # A tight area whose right edge is at x=1005; the monster stands past it.
    tight = Area(level_no=3, position=(190, 190), size=(11, 20))
    outside = monster(1, (1010, 1000))  # inside engage_radius, outside area
    inside = monster(2, (1002, 1000))
    scene = snap(monsters=[outside])
    scene = type(scene)(**{**scene.__dict__, "area": tight})
    assert combat.engage(scene) is None
    # The moment one crosses to us, it is a target again.
    both = type(scene)(**{**scene.__dict__, "monsters": (inside, outside)})
    action = combat.engage(both)
    assert isinstance(action, AttackUnit) and action.unit_id == 2
