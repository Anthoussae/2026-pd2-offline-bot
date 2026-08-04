"""The class config loader (strict by design) and the fake combat module."""

from pathlib import Path

import pytest

from pd2bot import offsets
from pd2bot.behavior.actions import AttackUnit, CastSelf
from pd2bot.behavior.combat import (
    ConfigError,
    FakeCombatModule,
    load_class_config,
)
from pd2bot.input import VK_F1, VK_F2, VK_F5
from pd2bot.snapshot import GameSnapshot

REPO = Path(__file__).resolve().parent.parent
NECRO = REPO / "config" / "necro.toml"


def necro_text():
    return NECRO.read_text(encoding="utf-8")


def write(tmp_path, text):
    path = tmp_path / "class.toml"
    path.write_text(text, encoding="utf-8")
    return path


# -- the shipped necro config --------------------------------------------------


def test_the_shipped_necro_config_loads():
    config = load_class_config(NECRO)
    assert config.name == "necromancer"
    # Skill ids are the live-captured constants (P1 drill A).
    assert config.skills["bone_armor"] == offsets.SKILL_BONE_ARMOR
    assert config.skills["blood_warp"] == offsets.SKILL_BLOOD_WARP
    # Hotkeys come out in the skills.py table shape: skill id -> VK.
    assert config.hotkeys[offsets.SKILL_BONE_ARMOR] == VK_F1
    assert config.hotkeys[offsets.SKILL_BLOOD_WARP] == VK_F2
    assert config.hotkeys[offsets.SKILL_DESECRATE] == VK_F5
    # The R53 permanent belt layout.
    assert config.belt.columns == ("mana", "rejuv", "healing", "healing")
    assert config.belt.min_healing == 4
    # Ladder columns are DERIVED from the layout — one source of truth.
    assert config.reflex.mana_column == 0
    assert config.reflex.rejuv_column == 1
    assert config.reflex.heal_columns == (2, 3)
    # Casting rungs resolve their skills by name.
    assert config.reflex.warp_skill_id == offsets.SKILL_BLOOD_WARP
    assert config.reflex.armor_skill_id == offsets.SKILL_BONE_ARMOR
    # Spot-check R49 numbers, including the 15 s amendment.
    assert config.reflex.mana_cooldown_s == 15.0
    assert config.reflex.rejuv_below_pct == 50.0
    assert config.chicken_life_pct == 35.0
    assert config.revive_target == 3


# -- strictness ----------------------------------------------------------------


def test_unknown_reflex_key_fails_loudly(tmp_path):
    text = necro_text().replace(
        "heal_cooldown_s = 10.0", "heal_cooldown_s = 10.0\nheal_cooldwn_s = 5.0"
    )
    with pytest.raises(ConfigError, match="heal_cooldwn_s"):
        load_class_config(write(tmp_path, text))


def test_unknown_top_level_key_fails(tmp_path):
    with pytest.raises(ConfigError, match="mercenary"):
        load_class_config(
            write(tmp_path, necro_text() + "\n[mercenary]\naura = 1\n")
        )


def test_missing_required_key_fails(tmp_path):
    text = necro_text().replace("mana_cooldown_s = 15.0\n", "")
    with pytest.raises(ConfigError, match="mana_cooldown_s"):
        load_class_config(write(tmp_path, text))


def test_unknown_belt_key_fails(tmp_path):
    text = necro_text().replace(
        "min_rejuv = 0", "min_rejuv = 0\nmin_stamina = 1"
    )
    with pytest.raises(ConfigError, match="min_stamina"):
        load_class_config(write(tmp_path, text))


def test_hotkey_for_unknown_skill_fails(tmp_path):
    text = necro_text().replace('revive = "F6"', 'revive = "F6"\nteeth = "F6"')
    with pytest.raises(ConfigError, match="teeth"):
        load_class_config(write(tmp_path, text))


def test_unknown_function_key_fails(tmp_path):
    text = necro_text().replace('bone_armor = "F1"', 'bone_armor = "F13"')
    with pytest.raises(ConfigError, match="F13"):
        load_class_config(write(tmp_path, text))


def test_belt_needs_exactly_four_known_columns(tmp_path):
    text = necro_text().replace(
        'columns = ["mana", "rejuv", "healing", "healing"]',
        'columns = ["mana", "rejuv", "healing"]',
    )
    with pytest.raises(ConfigError, match="exactly 4"):
        load_class_config(write(tmp_path, text))


def test_belt_needs_every_potion_type(tmp_path):
    text = necro_text().replace(
        'columns = ["mana", "rejuv", "healing", "healing"]',
        'columns = ["mana", "mana", "healing", "healing"]',
    )
    with pytest.raises(ConfigError, match="rejuv"):
        load_class_config(write(tmp_path, text))


def test_escape_skill_must_name_a_skill(tmp_path):
    text = necro_text().replace(
        'escape_skill = "blood_warp"', 'escape_skill = "town_portal"'
    )
    with pytest.raises(ConfigError, match="town_portal"):
        load_class_config(write(tmp_path, text))


def test_bool_is_not_a_number(tmp_path):
    text = necro_text().replace(
        "chicken_life_pct = 35.0", "chicken_life_pct = true"
    )
    with pytest.raises(ConfigError, match="bool"):
        load_class_config(write(tmp_path, text))


def test_skill_ids_must_be_integers(tmp_path):
    text = necro_text().replace("bone_armor = 68", 'bone_armor = "68"')
    with pytest.raises(ConfigError, match="integer skill id"):
        load_class_config(write(tmp_path, text))


def test_unknown_combat_key_fails(tmp_path):
    text = necro_text().replace(
        "revive_target = 3", "revive_target = 3\nrampage = true"
    )
    with pytest.raises(ConfigError, match="rampage"):
        load_class_config(write(tmp_path, text))


# -- the fake combat module ----------------------------------------------------


def test_fake_combat_module_scripts_pop_in_order():
    snap = GameSnapshot(in_game=True, taken_at=0.0)
    module = FakeCombatModule(
        engage_script=[AttackUnit(7, (1, 2)), None],
        upkeep_script=[CastSelf(83)],
    )
    assert module.engage(snap) == AttackUnit(7, (1, 2))
    assert module.engage(snap) is None
    assert module.engage(snap) is None  # exhausted script keeps answering
    assert module.upkeep(snap) == CastSelf(83)
    assert module.upkeep(snap) is None
    assert module.engage_calls == 3
    assert module.upkeep_calls == 2


# -- postures (M6 P3) ----------------------------------------------------------


def test_the_shipped_postures_load():
    config = load_class_config(NECRO)
    assert set(config.postures) == {"cautious", "brisk", "aggressive"}
    # Cautious IS the base numbers, by identity not by copy.
    assert config.postures["cautious"] is config.combat
    # Brisk: the corridor bubble and no lingering; everything it does not
    # name is inherited from the base.
    brisk = config.postures["brisk"]
    assert brisk.engage_radius == 12 and brisk.linger is False
    assert brisk.revive_target == config.combat.revive_target
    # Aggressive: group-conditioned retreat, faster restrike.
    aggressive = config.postures["aggressive"]
    assert aggressive.retreat_group_size == 3
    assert aggressive.restrike_s == 0.5
    assert aggressive.linger is True  # inherited


def test_redefining_cautious_is_refused(tmp_path):
    text = necro_text() + "\n[combat.postures.cautious]\nrestrike_s = 0.1\n"
    with pytest.raises(ConfigError, match="cautious"):
        load_class_config(write(tmp_path, text))


def test_a_posture_cannot_override_unknown_or_forbidden_keys(tmp_path):
    text = necro_text() + "\n[combat.postures.swift]\nrestrike_x = 0.1\n"
    with pytest.raises(ConfigError, match="unknown key"):
        load_class_config(write(tmp_path, text))
    # park_grace_s is executor wiring, read once at startup — a
    # per-posture value would look tunable and silently not be.
    text = necro_text() + "\n[combat.postures.swift]\npark_grace_s = 9.0\n"
    with pytest.raises(ConfigError, match="unknown key"):
        load_class_config(write(tmp_path, text))
