"""Sanity checks on the offset table.

These cannot prove an offset is *right* — only the live game can do that — but
they catch the mistakes that are easy to make while editing a table of numbers.
"""

from pd2bot import offsets


def test_stat_indices_are_distinct():
    stats = [
        offsets.STAT_STRENGTH,
        offsets.STAT_ENERGY,
        offsets.STAT_DEXTERITY,
        offsets.STAT_VITALITY,
        offsets.STAT_HP,
        offsets.STAT_MAX_HP,
        offsets.STAT_MANA,
        offsets.STAT_MAX_MANA,
        offsets.STAT_STAMINA,
        offsets.STAT_MAX_STAMINA,
        offsets.STAT_LEVEL,
        offsets.STAT_EXPERIENCE,
        offsets.STAT_GOLD,
        offsets.STAT_GOLD_BANK,
    ]
    assert len(stats) == len(set(stats))


def test_only_pools_are_fixed_point():
    """Level, attributes, gold and experience are plain integers.

    M1 shifted them by 8 and silently read zeros.
    """
    assert offsets.STAT_HP in offsets.FIXED_POINT_STATS
    assert offsets.STAT_MAX_MANA in offsets.FIXED_POINT_STATS
    for plain in (
        offsets.STAT_LEVEL,
        offsets.STAT_STRENGTH,
        offsets.STAT_GOLD,
        offsets.STAT_EXPERIENCE,
    ):
        assert plain not in offsets.FIXED_POINT_STATS


def test_base_and_full_stat_arrays_are_different():
    """The trap that produced hp=961/920: reading base stats instead of totals."""
    assert offsets.STATLIST_BASE_ARRAY != offsets.STATLIST_FULL_ARRAY
    assert offsets.STATLIST_BASE_COUNT != offsets.STATLIST_FULL_COUNT


def test_unit_types_are_distinct():
    types = {
        offsets.UNIT_TYPE_PLAYER,
        offsets.UNIT_TYPE_MONSTER,
        offsets.UNIT_TYPE_OBJECT,
        offsets.UNIT_TYPE_MISSILE,
        offsets.UNIT_TYPE_ITEM,
        offsets.UNIT_TYPE_TILE,
    }
    assert len(types) == 6


def test_monster_class_flags_are_single_distinct_bits():
    flags = [
        offsets.MONSTER_FLAG_NORMAL,
        offsets.MONSTER_FLAG_CHAMPION,
        offsets.MONSTER_FLAG_BOSS,
        offsets.MONSTER_FLAG_MINION,
    ]
    for flag in flags:
        assert flag & (flag - 1) == 0, "each class flag must be a single bit"
    assert len(set(flags)) == len(flags)


def test_every_named_ui_constant_has_a_name():
    for value in (offsets.UI_GAME, offsets.UI_ESCMENU_MAIN, offsets.UI_NPCSHOP):
        assert value in offsets.UI_NAMES
