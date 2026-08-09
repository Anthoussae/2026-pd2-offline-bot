"""Tests for reading the player, the current area and the map seed."""

import pytest

from pd2bot import offsets
from pd2bot.perception.player import read_active_skills, read_player
from pd2bot.perception.world import Area, read_area, read_map_seed
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession, stat_array, u16, u32

UNIT = 0x0AF00000
PLAYER_DATA = 0x0AF01000
PATH = 0x0AF02000
STAT_LIST = 0x0AF03000
STAT_ARRAY = 0x0AF04000
ACT = 0x0AF05000
ROOM1 = 0x0AF06000
ROOM2 = 0x0AF07000
LEVEL = 0x0AF08000
INFO = 0x0AF09000
LEFT_SKILL = 0x0AF0A000
RIGHT_SKILL = 0x0AF0B000
LEFT_TXT = 0x0AF0C000
RIGHT_TXT = 0x0AF0D000

# The real character read during M1/M2, including the stats that exposed the
# base-vs-full array trap: max_hp 1141 (full) rather than 920 (base).
STATS = {
    offsets.STAT_STRENGTH: 122,
    offsets.STAT_ENERGY: 31,
    offsets.STAT_DEXTERITY: 70,
    offsets.STAT_VITALITY: 357,
    offsets.STAT_HP: 961 << 8,
    offsets.STAT_MAX_HP: 1141 << 8,
    offsets.STAT_MANA: 378 << 8,
    offsets.STAT_MAX_MANA: 378 << 8,
    offsets.STAT_STAMINA: 586 << 8,
    offsets.STAT_MAX_STAMINA: 586 << 8,
    offsets.STAT_LEVEL: 91,
    offsets.STAT_EXPERIENCE: 1815585662,
    offsets.STAT_GOLD: 46565,
    offsets.STAT_GOLD_BANK: 70129,
}


def build(in_game: bool = True) -> FakeSession:
    mem = FakeMemory()
    mem.write(CLIENT_BASE + offsets.PLAYER_UNIT_PTR, u32(UNIT if in_game else 0))

    mem.write_fields(
        UNIT,
        {
            offsets.UNIT_TYPE: u32(offsets.UNIT_TYPE_PLAYER),
            offsets.UNIT_ID: u32(1),
            offsets.UNIT_DATA: u32(PLAYER_DATA),
            offsets.UNIT_ACT_NO: u32(0),  # act 1, stored 0-based
            offsets.UNIT_ACT: u32(ACT),
            offsets.UNIT_PATH: u32(PATH),
            offsets.UNIT_STATS: u32(STAT_LIST),
            offsets.UNIT_INFO: u32(0),  # no skill chain until add_skills()
        },
    )
    mem.write(PLAYER_DATA, b"MaqiuDoubing\x00\x00\x00\x00")
    mem.write_fields(
        PATH,
        {
            offsets.PATH_X: u32(5862)[:2],
            offsets.PATH_Y: u32(5757)[:2],
            offsets.PATH_ROOM1: u32(ROOM1),
        },
    )
    mem.write_fields(
        STAT_LIST,
        {
            offsets.STATLIST_BASE_ARRAY: u32(0),
            offsets.STATLIST_BASE_COUNT: u32(0)[:2],
            offsets.STATLIST_FULL_ARRAY: u32(STAT_ARRAY),
            offsets.STATLIST_FULL_COUNT: u32(len(STATS))[:2],
        },
    )
    mem.write(STAT_ARRAY, stat_array(STATS))
    mem.write_fields(ACT, {offsets.ACT_MAP_SEED: u32(0x1A2B3C4D)})
    mem.write_fields(ROOM1, {offsets.ROOM1_ROOM2: u32(ROOM2)})
    mem.write_fields(ROOM2, {offsets.ROOM2_LEVEL: u32(LEVEL)})
    # Level bounds are in TILES; the player position above is in subtiles, five
    # to a tile. These values put the player inside the level once converted:
    # tiles (1100, 1100)+(200, 200) -> subtiles (5500, 5500)..(6500, 6500).
    mem.write_fields(
        LEVEL,
        {
            offsets.LEVEL_NO: u32(1),  # Rogue Encampment
            offsets.LEVEL_POS_X: u32(1100),
            offsets.LEVEL_POS_Y: u32(1100),
            offsets.LEVEL_SIZE_X: u32(200),
            offsets.LEVEL_SIZE_Y: u32(200),
        },
    )
    return FakeSession(mem)


def test_reads_the_player():
    player = read_player(build())
    assert player is not None
    assert player.name == "MaqiuDoubing"
    assert player.level == 91
    assert player.act == 1
    assert player.position == (5862, 5757)


def test_uses_the_full_stat_list_so_current_never_exceeds_maximum():
    """The M1 bug: the base array reported hp 961 with max_hp 920."""
    player = read_player(build())
    assert (player.hp, player.max_hp) == (961, 1141)
    assert player.hp <= player.max_hp
    assert player.mana <= player.max_mana


def test_decodes_only_the_fixed_point_stats():
    """Attributes, level, gold and experience are plain integers."""
    player = read_player(build())
    assert player.strength == 122
    assert player.vitality == 357
    assert player.gold == 46565
    assert player.gold_stash == 70129
    assert player.experience == 1815585662


def test_fractions():
    player = read_player(build())
    assert player.hp_fraction == pytest.approx(961 / 1141)
    assert player.mana_fraction == 1.0


def test_not_in_a_game_reads_as_none():
    assert read_player(build(in_game=False)) is None
    assert read_area(build(in_game=False)) is None
    assert read_map_seed(build(in_game=False)) is None


def test_transition_with_a_broken_chain_reads_as_none_not_an_error():
    """Pointers go null during loading screens; that is normal, not a failure."""
    session = build()
    session.memory.write_fields(UNIT, {offsets.UNIT_PATH: u32(0), offsets.UNIT_DATA: u32(0)})
    assert read_player(session) is None
    assert read_area(session) is None


def test_reads_the_area():
    area = read_area(build())
    assert area == Area(level_no=1, position=(1100, 1100), size=(200, 200))


def test_area_bounds_convert_tiles_to_subtiles():
    """Levels are stored in tiles, units positioned in subtiles, five per tile.

    Comparing them directly looks plausible and is wrong by 5x — the live dump
    caught it.
    """
    area = read_area(build())
    assert area.bounds_subtiles == (5500, 5500, 6500, 6500)
    assert area.contains((5862, 5757))  # where the player actually is
    assert not area.contains((1150, 1150))  # the tile coords, unconverted
    assert not area.contains((100, 100))


def test_area_containment_against_real_observed_values():
    """Numbers taken from a live dump: act 5, player inside a level."""
    area = Area(level_no=124, position=(2500, 1000), size=(84, 84))
    assert area.bounds_subtiles == (12500, 5000, 12920, 5420)
    assert area.contains((12610, 5203))


def test_reads_the_map_seed():
    assert read_map_seed(build()) == 0x1A2B3C4D


def add_skills(session, left_id=74, right_id=68):
    """Wire the Info chain onto the built player: pInfo -> left/right
    Skill -> SkillsTxt -> wSkillId."""
    session.memory.regions[UNIT][offsets.UNIT_INFO : offsets.UNIT_INFO + 4] = u32(INFO)
    session.memory.write_fields(
        INFO,
        {
            offsets.INFO_LEFT_SKILL: u32(LEFT_SKILL),
            offsets.INFO_RIGHT_SKILL: u32(RIGHT_SKILL),
        },
    )
    session.memory.write_fields(LEFT_SKILL, {offsets.SKILL_TXT: u32(LEFT_TXT)})
    session.memory.write_fields(RIGHT_SKILL, {offsets.SKILL_TXT: u32(RIGHT_TXT)})
    session.memory.write(LEFT_TXT, u16(left_id))
    session.memory.write(RIGHT_TXT, u16(right_id))


def test_reads_the_active_skill_ids():
    session = build()
    add_skills(session, left_id=74, right_id=68)
    skills = read_active_skills(session)
    assert skills is not None
    assert (skills.left_id, skills.right_id) == (74, 68)


def test_active_skills_none_outside_a_game():
    assert read_active_skills(build(in_game=False)) is None


def test_a_null_skill_slot_reads_as_none_not_a_guess():
    """Mid-switch the slot pointer can be null; the caller must see 'unknown'
    — a wrong id here would let an unverified cast through (M5's verified-
    switch pattern depends on this being honest)."""
    session = build()
    add_skills(session)
    session.memory.write_fields(
        INFO,
        {
            offsets.INFO_LEFT_SKILL: u32(LEFT_SKILL),
            offsets.INFO_RIGHT_SKILL: u32(0),
        },
    )
    skills = read_active_skills(session)
    assert skills is not None
    assert skills.left_id == 74
    assert skills.right_id is None


def test_no_info_chain_reads_as_none():
    """The player unit exists during loading before pInfo does."""
    assert read_active_skills(build()) is None
